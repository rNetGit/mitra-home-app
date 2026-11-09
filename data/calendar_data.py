"""What the Calendar shows, with no web code: every dated record as {date: [(kind, title)]}, the week /
month / year layouts as plain lists, moving between them, and the read-only Google Calendar copy. Used by the web app
(webapp/app.py).
"""
import calendar as cal
import datetime as dt
import sqlite3
import threading
import time

import activities
import calendar_days
import dates
import db
import calendar_themes
import paths
from money import fmt as money

VIEWS = ("week", "month", "year")
DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
GOOGLE_DAYS = (7, 14, 30)
GOOGLE_TTL = 300  # seconds: the Google copy is fetched at most every five minutes per look-ahead
KIND_COLOR = {"Bill": "#c0392b", "Appointment": "#3b6fd4", "Event": "#8e44ad",
              "Insurance": "#d68910", "Vehicle": "#16a085", "Subscription": "#7f8c8d",
              "Investment": "#2e86c1", "Festival": "#e67e22",
              "Contract": "#5d6d7e", "Shopping": "#1abc9c", "Birthday": "#e84393", "School": "#2980b9",
              "Activity": "#27ae60", "Medical": "#c0392b", "Pet": "#a0522d", "Legal": "#34495e", "Travel": "#16a2b8",
              "Gift": "#d35400", "Chore": "#7f8c8d", "Loan": "#6c3483", "Tax": "#b7950b", "Class": "#1e8449",
              "Holiday": "#ca6f1e", "No school": "#2471a3", "Early dismissal": "#5dade2",
              "Clocks change": "#7d6608", "Remote": "#2a9d8f", "Office": "#5d6d7e", "Pay day": "#1e8449"}


def _rows(con, sql):
    """Rows of one query; none when the table does not exist yet (an older or brand-new database)."""
    try:
        return con.execute(sql).fetchall()
    except sqlite3.Error:
        return []


def load_events(y0, y1, refs=None):
    """All dated items between years y0..y1 inclusive -> {date: [(kind, title)]}. refs (a dict, optional) is filled with
    {(date, kind, title): "table:id"} for every chip that comes from one record, so the page can link it to that record."""
    ev = {}

    def add(d, kind, title, ref=None):
        try:
            d = dt.date.fromisoformat(str(d)[:10])
        except ValueError:
            return
        if y0 <= d.year <= y1:
            ev.setdefault(d, []).append((kind, title))
            if refs is not None and ref:
                refs.setdefault((d, kind, title), ref)

    try:
        con = db.connect(paths.DB, readonly=True)
    except sqlite3.Error:
        return ev
    try:
        for i, n, v, a, d, s in _rows(con, "SELECT id, name, vendor, amount, due_date, status FROM bills"):
            add(d, "Bill", f"{v or n} {money(a)}" + (" ✓" if s == "paid" else ""), f"bills:{i}")
        for i, _p, pr, pu, d in _rows(con, "SELECT id, person, provider, purpose, appt_datetime FROM appointments"):
            add(d, "Appointment", f"{pu or 'Appt'} – {pr or ''} {str(d)[11:16]}".strip(), f"appointments:{i}")
        for i, n, d, rec, t0, t1 in _rows(con, "SELECT id, name, event_date, recurs_yearly, start_time, end_time FROM events"):
            try:
                base = dt.date.fromisoformat(str(d)[:10])
            except ValueError:
                continue
            n = f"{n} {dates.time_span(t0, t1)}" if t0 else n  # a family event at a time: 'Family dinner 8:00–8:30 PM'
            for y in range(y0, y1 + 1):
                if rec or y == base.year:
                    try:
                        add(base.replace(year=y), "Event", n, f"events:{i}")
                    except ValueError:  # Feb 29
                        add(dt.date(y, 2, 28), "Event", n, f"events:{i}")
        for i, k, c, last4, d in _rows(con, "SELECT id, kind, carrier, policy_last4, term_end FROM policies"):
            add(d, "Insurance", f"{c} {k} x{last4} term ends", f"policies:{i}")
        for i, md, rg, ins in _rows(con, "SELECT id, model, registration_expires, inspection_expires "
                                         "FROM vehicles WHERE status='active'"):
            add(rg, "Vehicle", f"{md} registration expires", f"vehicles:{i}")
            add(ins, "Vehicle", f"{md} inspection expires", f"vehicles:{i}")
        for i, n, a, d in _rows(con, "SELECT id, name, amount, next_renewal FROM subscriptions WHERE active=1"):
            add(d, "Subscription", f"{n} {money(a)}", f"subscriptions:{i}")
        for i, n, d in _rows(con, "SELECT id, name, maturity_date FROM investments"):
            add(d, "Investment", f"{n} matures", f"investments:{i}")
        for i, n, md, by in _rows(con, "SELECT id, name, birth_month_day, birth_year FROM members "
                                    "WHERE birth_month_day IS NOT NULL AND birth_month_day != ''"):
            for y in range(y0, y1 + 1):
                try:
                    turns = f" (turns {y - int(by)})" if by else ""
                except (TypeError, ValueError):
                    turns = ""
                add(f"{y}-{md}", "Birthday", f"{n}'s birthday{turns}", f"members:{i}")
        for i, dom, mem, ti, d in _rows(con, "SELECT id, domain, member, title, due_date FROM life_items "
                                             "WHERE status='open' AND due_date IS NOT NULL"):
            kind = str(dom or "").capitalize()
            add(d, kind if kind in KIND_COLOR else "Chore", f"{ti}" + (f" ({mem})" if mem else ""), f"life_items:{i}")
        for i, no, cl, d in _rows(con, "SELECT id, contract_no, client, end_date FROM contracts WHERE status='active'"):
            add(d, "Contract", f"{cl} contract {no} ends", f"contracts:{i}")
        for i, ln, it, d in _rows(con, "SELECT id, list_name, item, target_date FROM shopping_items WHERE status='todo'"):
            add(d, "Shopping", f"{ln}: {it}", f"shopping_items:{i}")
        first, last = dt.date(y0, 1, 1), dt.date(y1, 12, 31)
        for d, kind, t in work_items(con, first, last):
            add(d, kind, t)
        try:
            for o in activities.occurrences(con, first, last):
                add(o["date"], "Class", o["label"], f"activity_schedules:{o['id']}" if o.get("id") else None)
        except sqlite3.Error:
            pass
        try:
            for r in calendar_days.between(first, last, con):  # spans spread over each day, as by_day does
                d = r["start"]
                while d <= r["end"]:
                    add(d, r["kind"], calendar_days.title(r), f"calendar_days:{r['id']}" if r["id"] else None)
                    d += dt.timedelta(days=1)
        except sqlite3.Error:
            pass
    finally:
        con.close()
    return ev


def work_items(con, first, last):
    """[(date, kind, title)] from the jobs that ask to show on the Calendar (Family > Work > Details > "Show the schedule on
    the Calendar"): Remote / Office days from the job's on-site / off-site pattern while the job runs, the work calendar's
    holidays and floating days (which replace those days' chips) and its pay days. Titles end in the person's name in
    brackets, so the glance and the person chips find them. A private job is left out (the Calendar has no signed-in
    person here). Nothing when the database has no such columns yet."""
    out = []
    try:
        import work
        jobs = [c for c in work.contracts(con) if c.get("show_on_calendar") and c.get("visibility") != "private"]
    except (sqlite3.Error, ImportError):
        return out
    for c in jobs:
        who = f" ({c['person']})" if c.get("person") else ""
        lo, hi = work._d(c.get("start_date")) or first, work._d(c.get("end_date")) or last
        lo, hi = max(lo, first), min(hi, last)
        marks = work.calendar_days(con, c.get("work_calendar"), lo, hi)
        d = lo
        while d <= hi:
            off = [(k, t) for k, t in marks.get(d, []) if k in ("holiday", "floating", "closure")]
            for k, t in marks.get(d, []):
                if k == "payday":
                    out.append((d, "Pay day", f"Pay day{who}"))
            if off:
                out.append((d, "Holiday", f"{off[0][1] or 'Day off'}{who}"))
            else:
                plan = work.plan_for(c, d)
                if plan in ("O", "H"):
                    out.append((d, "Office" if plan == "O" else "Remote", f"{'Office' if plan == 'O' else 'Remote'}{who}"))
            d += dt.timedelta(days=1)
    return out


# ---- layouts ---------------------------------------------------------------------------------------------------
def parse_ref(text, today):
    """The day a view is built around, from a query parameter; today when missing or not a date."""
    try:
        d = dt.date.fromisoformat(str(text or "")[:10])
    except ValueError:
        return today
    return d if 1900 <= d.year <= 2200 else today


def shift(view, ref, sign):
    """The reference day one week / month / year earlier (sign -1) or later (sign 1)."""
    if view == "week":
        return ref + sign * dt.timedelta(days=7)
    if view == "month":
        mi = ref.year * 12 + ref.month - 1 + sign
        return dt.date(mi // 12, mi % 12 + 1, 1)
    return dt.date(ref.year + sign, 1, 1)


def week_days(ref):
    """Seven days from `ref` (today by default): a rolling week, so on a Sunday the page shows what is coming, not the
    Monday-to-Sunday week that is ending. Prev / Next move by seven days (shift)."""
    return [ref + dt.timedelta(days=i) for i in range(7)]


def month_weeks(year, month):
    return cal.Calendar(firstweekday=0).monthdatescalendar(year, month)


def title(view, ref):
    if view == "week":
        a, b = week_days(ref)[0], week_days(ref)[-1]
        return f"{a:%b} {a.day} to {b.day} {b:%b}, {b.year}" if a.month != b.month else f"{a:%b} {a.day} to {b.day}, {b.year}"
    if view == "month":
        return f"{ref:%B %Y}"
    return str(ref.year)


def layout(view, ref, today):
    """{'title', 'weeks' | 'months', 'upcoming'}: plain dicts per day ({'date', 'things', 'today', 'other'})."""
    view = view if view in VIEWS else "week"
    refs = {}
    if view == "week":
        days = week_days(ref)
        ev = load_events(days[0].year, days[-1].year, refs)
        weeks = [days]
    elif view == "month":
        weeks = month_weeks(ref.year, ref.month)
        ev = load_events(weeks[0][0].year, weeks[-1][-1].year, refs)
    else:
        ev = load_events(ref.year, ref.year, refs)

    def cell(d, month=None):
        things = ev.get(d, [])
        return {"date": d, "things": things, "today": d == today, "other": month is not None and d.month != month,
                "theme": calendar_themes.day_theme(things)}

    out = {"view": view, "title": title(view, ref), "dow": DOW, "refs": refs}
    if view == "year":
        out["months"] = [{"name": cal.month_name[m], "weeks": [[cell(d, m) for d in w] for w in month_weeks(ref.year, m)]}
                         for m in range(1, 13)]
        out["upcoming"] = sorted((d, k, t) for d, items in ev.items() for k, t in items if d >= today)[:15]
    else:
        out["weeks"] = [[cell(d, ref.month if view == "month" else None) for d in w] for w in weeks]
        out["glance"] = glance([c for w in out["weeks"] for c in w if not c["other"]], today)
    return out


BIG = ("Birthday", "Holiday", "No school", "Early dismissal", "Festival", "Insurance", "Vehicle", "Tax", "Travel",
       "Contract", "Investment", "Legal")


def glance(cells, today, names=None, top=4):
    """The story card over the week / month grid: how many things, by kind, by person (the name in the title; House for
    home and car, Everyone for the rest), the busiest day, and the big dates not to miss (birthdays, holidays, school
    closures, renewals), upcoming first."""
    import today_data
    if names is None:
        try:
            names = [n for n, _ in today_data.members_now()]
        except sqlite3.Error:
            names = []
    items = [(c["date"], k, t) for c in cells for k, t in c["things"]]
    kinds, people, days = {}, {}, {}
    for d, k, t in items:
        kinds[k] = kinds.get(k, 0) + 1
        p = today_data.person_of({"title": t, "kind": k}, names) or "Everyone"
        people[p] = people.get(p, 0) + 1
        days[d] = days.get(d, 0) + 1
    by_kind = sorted(kinds.items(), key=lambda kv: (-kv[1], kv[0]))
    order = {n: i for i, n in enumerate(list(names) + [today_data.HOUSE, "Everyone"])}
    by_person = [{"name": n, "n": c, "av": today_data.avatar(n, names) if n != "Everyone" else ("", "avn")}
                 for n, c in sorted(people.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99)))]
    busy = max(days.items(), key=lambda kv: (kv[1], -kv[0].toordinal()), default=None)
    big = sorted((x for x in items if x[1] in BIG), key=lambda x: (x[0] < today, x[0], x[2]))
    return {"total": len(items), "upcoming": sum(1 for x in items if x[0] >= today),
            "kinds": [{"kind": k, "n": n, "cls": kind_class(k)} for k, n in by_kind[:top]], "kinds_more": max(0, len(by_kind) - top),
            "kind_max": by_kind[0][1] if by_kind else 1, "people": by_person[:5], "person_max": by_person[0]["n"] if by_person else 1,
            "busiest": {"date": busy[0], "n": busy[1]} if busy else None, "big": big[:5], "big_more": max(0, len(big) - 5)}


def kind_class(kind):
    """The CSS class of a kind's colour (k-bill, k-appointment, ...)."""
    return "k-" + "".join(ch for ch in kind.lower() if ch.isalnum())


# ---- Google Calendar (read-only) -------------------------------------------------------------------------------
_cache = {}
_lock = threading.Lock()


def google(days, today):
    """('off', None) when not connected, ('error', message), or ('ok', [events]) for the next `days` days."""
    days = days if days in GOOGLE_DAYS else 14
    try:
        import google_calendar as gc
        s = gc.status()
    except Exception:  # noqa: BLE001 (the page must still render)
        return "off", None
    if not (s["enabled"] and s["signed_in"]):
        return "off", None
    key = (days, today.isoformat())
    with _lock:
        hit = _cache.get(key)
        if hit and time.monotonic() - hit[0] < GOOGLE_TTL:
            return "ok", hit[1]
    try:
        ev = gc.events(days, today)
    except gc.CalendarError as e:
        return "error", str(e)
    except Exception:  # noqa: BLE001 (network trouble must not break the page)
        return "error", "Google Calendar could not be reached just now."
    with _lock:
        _cache.clear() if len(_cache) > 16 else None
        _cache[key] = (time.monotonic(), ev)
    return "ok", ev
