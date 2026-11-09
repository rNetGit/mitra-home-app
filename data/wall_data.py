"""What the Mitra Wall shows, with no web code (webapp/routes_wall.py draws it).

  week(con, start, today, who)   seven days from `start`: timed events on a 15-minute grid (with lanes for overlaps),
                                 all-day items, and a money lane (bills, renewals, pay days) WITHOUT amounts
  day(con, d, today)             one day: the week's grid split into a lane per person (then House), and the same day
                                 as one list for small screens
  month(con, first, today)       the month around `first` as whole weeks (Monday first): each day's first items and the
                                 full list for the day's popup, bills named without amounts
  today(con, now)                today's line, what needs doing (no amounts), the children's progress, dinner, and
                                 what is coming up in the next COMING_DAYS days (bills named, no amounts)
  lists(con, today)              the family's shared lists (never adults-only ones)
  meals(con, start)              the week by meal, and tonight's recipe
  money(con, today)              the month for adults: spent against the plan, bills with amounts, allowance from stars

Privacy: the wall is in the kitchen, so everything but `money` is what a child or a visitor may see: no amounts, no
account numbers, no papers, no critical info (member_info is never read here), no adults-only lists. `money` is drawn
only after an adult typed their PIN on the wall, for a minute.
"""
import datetime as dt
import re
import sqlite3

import activities
import calendar_days
import calendar_themes
import db
import wall as W
from money import fmt as money_fmt

START_HOUR, END_HOUR = 8, 20       # the grid's default hours; widened to fit what is on (GRID_FROM..GRID_TO at most)
GRID_FROM, GRID_TO = 6, 22         # anything wholly outside these hours is an all-day line with its time
SLOT_MIN = 15
DEFAULT_MINUTES = 60               # an appointment with only a start time
MAX_LANES = 3                      # side by side in one day; more overlaps share the last lane
HOUSE = "House"
COUNTDOWN_DAYS = 90
TIMED_KINDS = ("Appointment", "Class", "Event")
COMING_DAYS, COMING_SHOWN = 3, 6    # Today's "Coming up": the next days, at most this many lines
WEEK_BANDS = 3                     # all-day lines under a day's name on the week; the rest behind "+N more"
MONTH_SHOWN = 3                    # lines in a month cell; the rest is "+N more" (all of them in the day's popup)
MONEY_LABEL = {"late": "late", "bill": "due", "renews": "renews", "pay": ""}
# The PC's Today list (action_items + seasonal jobs) adds what the wall's own sources above do not hold. Left out: rows
# the wall already draws (bills, appointments, events, birthdays, classes; reminders and subscriptions unless overdue)
# and money-only kinds; amounts never come along and a policy's last four digits are dropped from its title.
TODO_SKIP_REFS = {"bills", "appointments", "events", "members", "activity_schedules"}
TODO_LATE_ONLY_REFS = {"life_items", "subscriptions"}
TODO_SKIP_KINDS = {"Bill", "Appointment", "Event", "Birthday", "Class", "Benefit", "Investment", "Cancel", "Spending"}
LAST4 = re.compile(r"\s+x\d{4}\b")


def _rows(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchall()
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return []
        raise


def _d(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _hm(v):
    """'15:30' / '2026-10-18 15:30' / '2026-10-18T15:30:00' -> minutes after midnight, or None."""
    m = re.search(r"(\d{1,2}):(\d{2})", str(v or "")[10:] if len(str(v or "")) > 10 else str(v or ""))
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    return h * 60 + mi if h < 24 and mi < 60 else None


def clock(minutes):
    """810 -> '1:30 PM' (whole hours: '1 PM')."""
    h, m = divmod(int(minutes), 60)
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {ap}" if m else f"{h12} {ap}"


# ---- people ---------------------------------------------------------------------------------------------------------
def people(con):
    """[(name, role)] in family order (pets included: they have vet visits)."""
    try:
        return [(r[0], (r[1] or "").lower()) for r in con.execute("SELECT name, role FROM members ORDER BY id")]
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return []
        raise


def colour(name, names):
    """The person's colour class on the wall: c0..c5 in family order (the app's look.PEOPLE), ch for the house."""
    if not name or name == HOUSE or name not in names:
        return "ch"
    return f"c{names.index(name) % 6}"


def _people(who, names):
    """[name] -> [{'name','initial','cls'}] for avatars and the popups."""
    return [{"name": p, "initial": p[:1].upper(), "cls": colour(p, names)} for p in who]


def long_day(d):
    """2026-10-19 -> 'Monday, October 19'."""
    return f"{d:%A}, {d:%B} {d.day}"


def _who_in(title, names):
    """The member named in a title ('Dentist (Sam)', "Sam's swim") or None."""
    for n in names:
        first = n.split()[0]
        if re.search(rf"\((?:{re.escape(n)}|{re.escape(first)})\)", title) or re.search(rf"\b{re.escape(first)}'s\b", title):
            return n
    return None


def todo_items(con, start, end, today, names):
    """All-day 'to do' lines for start..end from the PC Today's sources (action_items.collect_items + seasonal jobs),
    without what the wall already shows. Overdue ones land on today (late=True) when today is in the range. Hidden,
    done and snoozed rows stay hidden, and the Brief's watch list (Settings > Home Profile) applies, as on the PC."""
    try:
        import action_items as ai
        import agent_profile
        import dashboard_actions as da
    except ImportError:
        return []
    here = start <= today <= end
    try:
        items = ai.collect_items(con, today, max(0, (end - today).days))
        seas = ai.seasonal_rows(con, today)
        hidden = da.hidden_keys(con, today)
        prof = agent_profile.get()
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return []
        raise
    out = []

    def add(d, kind, title, ref=None):
        late = d < today
        if late and not here:
            return
        d = today if late else d
        if not (start <= d <= end) or not agent_profile.watched(kind, prof):
            return
        title = LAST4.sub("", str(title or "")).strip()
        who = _who_in(title, names)
        out.append({"date": d, "title": title, "who": [who] if who else [], "kind": kind, "late": late, "todo": True,
                    "ref": ref})

    for i in items:
        ref = (i.get("ref") or (None,))[0]
        if i["kind"] in TODO_SKIP_KINDS or ref in TODO_SKIP_REFS:
            continue
        if ref in TODO_LATE_ONLY_REFS and i["date"] >= today:
            continue  # the wall's own reminders and money lane hold the ones still ahead
        add(i["date"], i["kind"], i["title"], ref)
    for s in seas:
        if da.alert_key("seasonal", s["name"], today.year) in hidden:
            continue
        if s["state"] in ("now", "missed"):
            add(today - dt.timedelta(days=1) if s["state"] == "missed" else today, "Seasonal", s["name"])
        else:
            add(s["start"], "Seasonal", s["name"])
    return out


# ---- the week -------------------------------------------------------------------------------------------------------
def _collect(con, start, end, names, today=None, todo=False):
    """(timed, allday, money) lists of dicts for start..end. A bill not paid by `today` (default: start) is late: it shows
    on today when today is in the range, else on its own due day."""
    today = today or start
    here = start <= today <= end
    timed, allday, money = [], [], []
    for person, provider, purpose, when in _rows(con, "SELECT person, provider, purpose, appt_datetime FROM appointments "
                                                      "WHERE date(appt_datetime) BETWEEN ? AND ?", (start.isoformat(), end.isoformat())):
        d, t = _d(when), _hm(when)
        who = person if person in names else _who_in(str(purpose or ""), names)
        title = str(purpose or "Appointment")
        if provider and provider.lower() not in title.lower():
            title += f" · {provider}"
        item = {"date": d, "title": title, "who": [who] if who else [], "kind": "Appointment"}
        if t is None:
            allday.append(item)
        else:
            timed.append({**item, "start": t, "end": t + DEFAULT_MINUTES})
    sched = {r["id"]: r for r in activities.rows(con)}
    for o in activities.occurrences(con, start, end, sched=list(sched.values())):
        t = _hm(o.get("time"))
        r = sched.get(o["id"]) or {}
        e = _hm(r.get("end_time")) if r.get("end_time") else None
        item = {"date": o["date"], "title": o["title"], "who": [o["member"]] if o.get("member") in names else [], "kind": "Class"}
        if t is None:
            allday.append(item)
        else:
            timed.append({**item, "start": t, "end": e if e and e > t else t + DEFAULT_MINUTES})
    for name, when, yearly, t0, t1 in _rows(con, "SELECT name, event_date, recurs_yearly, start_time, end_time FROM events"):
        base = _d(when)
        t, e = _hm(t0), _hm(t1)
        if not base:
            continue
        for y in range(start.year, end.year + 1):
            if not yearly and y != base.year:
                continue
            try:
                d = base.replace(year=y)
            except ValueError:
                d = dt.date(y, 2, 28)
            if start <= d <= end:
                who = _who_in(name, names)
                item = {"date": d, "title": name, "who": [who] if who else [], "kind": "Event"}
                if t is None:
                    allday.append(item)
                else:  # a family event at a time sits on the grid, in the house colour unless a name is in its title
                    timed.append({**item, "start": t, "end": e if e and e > t else t + DEFAULT_MINUTES})
    for name, md in _rows(con, "SELECT name, birth_month_day FROM members WHERE birth_month_day IS NOT NULL AND birth_month_day != ''"):
        for y in range(start.year, end.year + 1):
            try:
                d = dt.date.fromisoformat(f"{y}-{md}")
            except ValueError:
                continue
            if start <= d <= end:
                allday.append({"date": d, "title": f"{name.split()[0]}'s birthday", "who": [name], "kind": "Birthday"})
    for member, title, due, domain in _rows(con, "SELECT member, title, due_date, domain FROM life_items WHERE status='open' "
                                                 "AND due_date BETWEEN ? AND ?", (start.isoformat(), end.isoformat())):
        d = _d(due)
        if d:
            who = member if member in names else _who_in(str(title), names)
            allday.append({"date": d, "title": str(title), "who": [who] if who else [], "kind": str(domain or "").capitalize() or "Chore"})
    try:
        for r in calendar_days.between(start, end, con):
            d0, d1 = r["start"], r["end"]
            d = max(d0, start)
            while d <= min(d1, end):
                who = r.get("member") if r.get("member") in names else None
                allday.append({"date": d, "title": calendar_days.title(r), "who": [who] if who else [], "kind": r["kind"]})
                d += dt.timedelta(days=1)
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
    for name, vendor, amount, due, status in _rows(con, "SELECT name, vendor, amount, due_date, status FROM bills WHERE "
                                                        "COALESCE(status,'due') != 'paid' AND due_date <= ?", (end.isoformat(),)):
        d = _d(due)
        if not d:
            continue
        if d < today and (here or start <= d):
            money.append({"date": today if here else d, "title": vendor or name, "kind": "late", "amount": amount, "due": d})
        elif start <= d <= end and d >= today:
            money.append({"date": d, "title": vendor or name, "kind": "bill", "amount": amount, "due": d})
    for name, amount, renews in _rows(con, "SELECT name, amount, next_renewal FROM subscriptions WHERE active=1 AND "
                                           "next_renewal BETWEEN ? AND ?", (start.isoformat(), end.isoformat())):
        d = _d(renews)
        if d:
            money.append({"date": d, "title": name, "kind": "renews", "amount": amount, "due": d})
    for day, in _rows(con, "SELECT DISTINCT day FROM work_calendar WHERE kind='payday' AND day BETWEEN ? AND ?",
                      (start.isoformat(), end.isoformat())):
        d = _d(day)
        if d:
            money.append({"date": d, "title": "Pay day", "kind": "pay", "amount": None, "due": d})
    if todo:
        allday += todo_items(con, start, end, today, names)
    return timed, allday, money


def _lanes(events):
    """Give overlapping events lanes: each gets 'lane' (0-based) and 'lanes' (how many its cluster needs)."""
    events.sort(key=lambda e: (e["start"], -e["end"]))
    cluster, ends, cluster_end = [], [], -1
    out = []

    def close():
        n = min(max(len(ends), 1), MAX_LANES)
        for e in cluster:
            e["lanes"] = n
        out.extend(cluster)

    for e in events:
        if cluster and e["start"] >= cluster_end:
            close()
            cluster, ends = [], []
        lane = next((i for i, t in enumerate(ends) if t <= e["start"]), None)
        if lane is None:
            lane = len(ends)
            ends.append(e["end"])
        else:
            ends[lane] = e["end"]
        e["lane"] = min(lane, MAX_LANES - 1)
        cluster.append(e)
        cluster_end = max(cluster_end, e["end"])
    if cluster:
        close()
    return out


def heat(n):
    """How busy a day is for the heat-map week, 0 (free) to 4 (7 things or more): the tile's shade and width (.h-N)."""
    return 0 if n <= 0 else min(4, (n + 1) // 2)


def week(con, start, today, who=None, days=7):
    """The family week for the wall. who = one person's name (others dimmed) or None."""
    names = [n for n, _ in people(con)]
    who = who if who in names else None
    end = start + dt.timedelta(days=days - 1)
    timed, allday, money = _collect(con, start, end, names, today, todo=True)
    outside = [e for e in timed if e["start"] >= GRID_TO * 60 or e["end"] <= GRID_FROM * 60]  # before 6 AM, after 10 PM
    timed = [e for e in timed if e not in outside]
    allday += [{**e, "title": f"{e['title']} · {clock(e['start'])}"} for e in outside]
    lo = min([START_HOUR * 60] + [e["start"] for e in timed])
    hi = max([END_HOUR * 60] + [e["end"] for e in timed])
    real = dt.datetime.now()
    if start <= today <= end and today == real.date():  # in the evening the grid reaches the time now (the red line)
        hi = max(hi, real.hour * 60 + real.minute + 30)
    lo_h, hi_h = max(GRID_FROM, lo // 60), min(GRID_TO, -(-hi // 60))
    slots = (hi_h - lo_h) * 60 // SLOT_MIN
    counts = {n: 0 for n in names}
    for e in timed + allday:
        for p in e["who"]:
            if p in counts:
                counts[p] += 1
    out_days = []
    for i in range(days):
        d = start + dt.timedelta(days=i)
        evs = _lanes([dict(e) for e in timed if e["date"] == d])
        lanes = max([e["lanes"] for e in evs] + [1])
        rows = []
        for e in evs:
            s = max(e["start"], lo_h * 60)
            f = min(max(e["end"], s + SLOT_MIN), hi_h * 60)
            r0 = (s - lo_h * 60) // SLOT_MIN + 1
            r1 = max(r0 + 1, -(-(f - lo_h * 60) // SLOT_MIN) + 1)
            mine = not who or who in e["who"]
            rows.append({"title": e["title"], "time": f"{clock(e['start'])} – {clock(e['end'])}", "kind": e["kind"],
                         "who": _people(e["who"], names), "day": long_day(d),
                         "cls": colour(e["who"][0] if e["who"] else HOUSE, names), "r0": r0, "r1": min(r1, slots + 1),
                         "col": "all" if e["lanes"] == 1 else f"l{e['lane'] + 1}", "dim": not mine,
                         "short": (f - s) <= 45})
        ad = [{"title": a["title"], "kind": a["kind"], "cls": colour(a["who"][0] if a["who"] else HOUSE, names),
               "dim": bool(who) and who not in a["who"], "who": _people(a["who"], names), "day": long_day(d),
               "late": a.get("late", False), "todo": a.get("todo", False)}
              for a in sorted((a for a in allday if a["date"] == d), key=lambda a: (not a.get("late"), bool(a.get("todo"))))]
        mn = [{"title": m["title"], "kind": m["kind"], "label": MONEY_LABEL[m["kind"]], "day": long_day(d)}
              for m in sorted(money, key=lambda m: (m["kind"] != "late", m["title"])) if m["date"] == d]
        # the heat-map week (one tile per day): late and all-day first, then by time, then money (no amounts)
        items = ([{"time": "", "title": a["title"], "kind": a["kind"] + (" · late" if a["late"] else ""), "cls": a["cls"],
                   "who": a["who"], "dim": a["dim"], "late": a["late"]} for a in ad]
                 + [{"time": e["time"].split(" – ")[0], "title": e["title"], "kind": e["kind"] + " · " + e["time"],
                     "cls": e["cls"], "who": e["who"], "dim": e["dim"], "late": False} for e in rows]
                 + [{"time": "", "title": m["title"] + (f" · {m['label']}" if m["label"] else ""), "kind": "Money",
                     "cls": "ch", "who": [], "dim": False, "late": m["kind"] == "late"} for m in mn])
        if who:  # one person's chip: only their things on the tiles (owner, 2026-10-26: dimming the rest looked busy)
            items = [i for i in items if not i["dim"] and i["cls"] != "ch"]
        # late ones fold into one red "N late" line on the tile (owner, 2026-10-26: they drowned the day's events);
        # the popup still lists every thing
        out_days.append({"date": d, "dow": d.strftime("%a"), "num": d.day, "today": d == today, "lanes": lanes,
                         "events": rows, "allday": ad, "bands": ad[:WEEK_BANDS], "more": ad[WEEK_BANDS:],
                         "money": mn, "label": long_day(d), "things": items, "heat": heat(len(items)),
                         "theme": calendar_themes.day_theme([(a["kind"], a["title"]) for a in ad] + [(e["kind"], e["title"]) for e in rows]),
                         "lines": [i for i in items if not i["late"]], "late_n": sum(1 for i in items if i["late"])})
    hours = [{"label": clock(h * 60), "row": (h - lo_h) * 60 // SLOT_MIN + 1} for h in range(lo_h, hi_h)]
    now_row = None
    if start <= today <= end:
        n = dt.datetime.now()
        mins = n.hour * 60 + n.minute
        if lo_h * 60 <= mins < hi_h * 60:
            now_row = (mins - lo_h * 60) // SLOT_MIN + 1
    chips = [{"name": n, "initial": n[:1].upper(), "cls": colour(n, names), "n": counts.get(n, 0), "on": who == n}
             for n, role in people(con) if counts.get(n) or role != "pet"]
    return {"start": start, "end": end, "days": out_days, "hours": hours, "slots": slots, "now_row": now_row,
            "chips": chips, "who": who, "countdowns": countdowns(con, today, names),
            "title": f"{start:%b} {start.day} – {end:%b} {end.day}" if start.month != end.month else f"{start:%B} {start.day} – {end.day}"}


DAY_LANES = 8                      # person lanes on the Day view at most (.dcols-N in wall.css); the rest share House


def day(con, d, today):
    """One day for the wall's Day view (owner, 2026-10-26: lanes per person, like Hearth): the week's grid for that day
    (`week(days=1)`: rows, hours, the now line) with its events split into one lane per person who has something that
    day, in family order, then House (no one named, money). A lane = {name, initial, cls, events (with their own overlap
    columns), late (overdue things, one band), bands (the first all-day lines), more}. `line` = the same day as one list for small screens: timed
    by time, then all-day, late ones folded into `late_n`."""
    names = [n for n, _ in people(con)]
    v = week(con, d, today, days=1)
    one = v["days"][0]
    lanes = {}

    def lane(name):
        key = name if name in names else HOUSE
        if key not in lanes:
            lanes[key] = {"name": key, "initial": key[:1].upper(), "cls": colour(key, names), "events": [], "bands": []}
        return lanes[key]
    for e in one["events"]:
        lane(e["who"][0]["name"] if e["who"] else HOUSE)["events"].append(dict(e))
    for a in one["allday"]:
        lane(a["who"][0]["name"] if a["who"] else HOUSE)["bands"].append(a)
    for m in one["money"]:
        lane(HOUSE)["bands"].append({"title": m["title"] + (f" · {m['label']}" if m["label"] else ""), "kind": "Money",
                                     "cls": "ch", "who": [], "day": m["day"], "late": m["kind"] == "late", "money": m["kind"]})
    who = [n for n in names if n in lanes]
    room = DAY_LANES - 1 if (HOUSE in lanes or len(who) > DAY_LANES) else DAY_LANES
    for n in who[room:]:  # more people than lanes: their things go to House
        lane(HOUSE)["events"] += lanes[n]["events"]
        lane(HOUSE)["bands"] += lanes[n]["bands"]
    out = [lanes[n] for n in who[:room]] + ([lanes[HOUSE]] if HOUSE in lanes else [])
    for ln in out:  # overlaps inside one person's lane get columns of their own (rows stand in for minutes)
        evs = _lanes([{**e, "start": e["r0"], "end": e["r1"]} for e in ln["events"]])
        ln["events"] = [{**e, "col": "all" if e["lanes"] == 1 else f"l{e['lane'] + 1}"} for e in evs]
        ln["lanes"] = max([e["lanes"] for e in evs] + [1])
        ln["late"] = [a for a in ln["bands"] if a.get("late")]  # one red "N late" band, like the week's tiles
        rest = [a for a in ln["bands"] if not a.get("late")]
        ln["bands"], ln["more"] = rest[:WEEK_BANDS], rest[WEEK_BANDS:]
    timed = sorted(one["events"], key=lambda e: e["r0"])
    line = ([{"time": e["time"].split(" – ")[0], "title": e["title"], "kind": e["kind"] + " · " + e["time"], "cls": e["cls"],
              "who": e["who"]} for e in timed]
            + [{"time": "", "title": i["title"], "kind": i["kind"], "cls": i["cls"], "who": i["who"]}
               for i in one["lines"] if not i["time"]])
    return {"date": d, "today": d == today, "label": long_day(d), "dow": d.strftime("%a"), "num": d.day,
            "hours": v["hours"], "slots": v["slots"], "now_row": v["now_row"], "lanes": out, "cols": max(1, len(out)),
            "line": line, "late_n": one["late_n"], "things": one["things"], "countdowns": v["countdowns"],
            "prev": d - dt.timedelta(days=1), "next": d + dt.timedelta(days=1)}


def month(con, first, today):
    """The month of `first` as whole weeks, Monday first (4 to 6 rows). A day = {date, num, out (another month), today,
    shown (its first MONTH_SHOWN things that are not late), more, late_n, things (all of them, for the popup), label}; an
    item = {title, time, kind, cls, who, money, late}. Bills are named as due / late with no amount, like the week's money lane."""
    first = first.replace(day=1)
    nxt = (first + dt.timedelta(days=32)).replace(day=1)
    start = first - dt.timedelta(days=first.weekday())
    end = nxt - dt.timedelta(days=1)
    end += dt.timedelta(days=6 - end.weekday())
    names = [n for n, _ in people(con)]
    timed, allday, money = _collect(con, start, end, names, today, todo=True)
    by_day = {}
    for e in sorted(timed, key=lambda e: (e["start"], e["title"])):
        by_day.setdefault(e["date"], []).append(
            {"title": e["title"], "time": clock(e["start"]), "until": clock(e["end"]), "kind": e["kind"],
             "cls": colour(e["who"][0] if e["who"] else HOUSE, names), "who": _people(e["who"], names), "money": False,
             "late": False})
    for a in sorted(allday, key=lambda a: (not a.get("late"), bool(a.get("todo")))):
        by_day.setdefault(a["date"], []).append(
            {"title": a["title"], "time": "", "until": "", "kind": a["kind"] + (" · late" if a.get("late") else ""),
             "cls": colour(a["who"][0] if a["who"] else HOUSE, names), "who": _people(a["who"], names), "money": False,
             "late": bool(a.get("late"))})
    for m in sorted(money, key=lambda m: (m["kind"] != "late", m["title"])):
        by_day.setdefault(m["date"], []).append(
            {"title": m["title"], "time": "", "until": "", "kind": MONEY_LABEL[m["kind"]] or "Pay day", "cls": "ch",
             "who": [], "money": m["kind"], "late": m["kind"] == "late"})
    weeks, d = [], start
    while d <= end:
        row = []
        for _ in range(7):
            items = by_day.get(d, [])
            items = [i for i in items if i["time"]] + [i for i in items if not i["time"]]  # timed first, by time
            lines = [i for i in items if not i["late"]]  # late ones = one "N late" pill, like the week's tiles
            row.append({"date": d, "num": d.day, "out": d.month != first.month, "today": d == today,
                        "things": items, "shown": lines[:MONTH_SHOWN], "more": max(0, len(lines) - MONTH_SHOWN),
                        "late_n": len(items) - len(lines), "label": long_day(d),
                        "theme": calendar_themes.day_theme([(i["kind"].split(" · ")[0], i["title"]) for i in items if not i["money"]])})
            d += dt.timedelta(days=1)
        weeks.append(row)
    return {"first": first, "title": f"{first:%B} {first.year}", "weeks": weeks, "rows": len(weeks),
            "dows": [(start + dt.timedelta(days=i)).strftime("%a") for i in range(7)],
            "prev": (first - dt.timedelta(days=1)).replace(day=1), "next": nxt,
            "countdowns": countdowns(con, today, names)}


def countdowns(con, today, names, n=2):
    """The next family days worth counting down to: birthdays, yearly events, holidays and festivals (not today)."""
    end = today + dt.timedelta(days=COUNTDOWN_DAYS)
    _t, allday, _m = _collect(con, today + dt.timedelta(days=1), end, names)
    seen, out = set(), []
    for a in sorted(allday, key=lambda a: a["date"]):
        if a["kind"] not in ("Birthday", "Event", "Holiday", "Festival") or a["title"] in seen:
            continue
        seen.add(a["title"])
        days = (a["date"] - today).days
        out.append({"title": a["title"], "when": "tomorrow" if days == 1 else f"in {days} days"})
        if len(out) >= n:
            break
    return out


# ---- today ----------------------------------------------------------------------------------------------------------
def today(con, now):
    d = now.date()
    w = week(con, d, d, days=1)
    day = w["days"][0]
    names = [n for n, _ in people(con)]
    mins = now.hour * 60 + now.minute
    line = [{"title": e["title"], "time": clock(e["start"]), "end": clock(e["end"]),
             "cls": colour(e["who"][0] if e["who"] else HOUSE, names), "kind": e["kind"], "day": long_day(d),
             "who": [p[:1].upper() for p in e["who"]], "people": _people(e["who"], names),
             "past": e["end"] <= mins, "now": e["start"] <= mins < e["end"], "s": e["start"], "e": e["end"]}
            for e in sorted(_collect(con, d, d, names)[0], key=lambda e: (e["start"], e["end"]))]
    needs = []
    for member, title, due in _rows(con, "SELECT member, title, due_date FROM life_items WHERE status='open' AND due_date <= ? "
                                         "ORDER BY due_date LIMIT 6", (d.isoformat(),)):
        late = (_d(due) or d) < d
        who = member if member in names else _who_in(str(title), names)
        needs.append({"title": str(title), "sub": "late" if late else "today", "late": late,
                      "initial": (who or HOUSE)[:1], "cls": colour(who or HOUSE, names)})
    for t in sorted(todo_items(con, d, d, d, names), key=lambda t: not t["late"]):  # the PC Today's other rows
        if t["ref"] == "life_items":
            continue  # already listed above from life_items itself
        who = t["who"][0] if t["who"] else None
        needs.append({"title": t["title"], "sub": ("late · " if t["late"] else "today · ") + t["kind"].lower(),
                      "late": t["late"], "initial": (who or HOUSE)[:1], "cls": colour(who or HOUSE, names)})
    needs = sorted(needs, key=lambda n: not n["late"])
    bills = [m for m in _collect(con, d, d + dt.timedelta(days=6), names)[2] if m["kind"] in ("bill", "late")]
    kids = [{**k, "cls": colour(k["name"], names)} for k in W.day_view(con, d, W.part_of(now))]
    dinner = next((m["meal"] for m in _meals_rows(con, d, 1) if m["slot"] == "dinner"), None)
    return {"date": d, "line": line, "allday": [a for a in day["allday"] if not a["todo"]], "needs": needs, "kids": kids, "dinner": dinner,
            "coming": coming(con, d, names),
            "bills_n": len(bills), "late_n": sum(1 for b in bills if b["kind"] == "late"), "part": W.PART_LABEL[W.part_of(now)],
            "countdowns": w["countdowns"]}


def coming(con, today_, names, days=COMING_DAYS, n=COMING_SHOWN):
    """The next `days` days after today for the wall's Today: timed things first each day, then all-day ones and the
    PC Today's to-dos, then bills by name (no amounts). -> {'rows': [...first n], 'more': how many left out}."""
    start, end = today_ + dt.timedelta(days=1), today_ + dt.timedelta(days=days)
    timed, allday, money = _collect(con, start, end, names, today_, todo=True)
    rows = []
    for e in timed:
        rows.append((e["date"], 0, e["start"], {"title": e["title"], "time": clock(e["start"]), "kind": e["kind"],
                                                  "who": _people(e["who"], names), "money": ""}))
    for a in allday:
        rows.append((a["date"], 1, 0, {"title": a["title"], "time": "", "kind": a["kind"], "who": _people(a["who"], names),
                                       "money": ""}))
    for m in money:
        rows.append((m["date"], 2, 0, {"title": m["title"], "time": "", "kind": MONEY_LABEL[m["kind"]] or "Pay day",
                                       "who": [], "money": m["kind"]}))
    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]["title"]))
    out = []
    for d, _o, _t, r in rows:
        when = "Tomorrow" if d == start else f"{d:%A}"
        out.append({**r, "when": when, "day": long_day(d),
                    "cls": r["who"][0]["cls"] if r["who"] else "ch"})
    return {"rows": out[:n], "more": max(0, len(out) - n)}


# ---- lists and meals ------------------------------------------------------------------------------------------------
def lists(con, today_):
    import lists as L
    names = [n for n, _ in people(con)]
    out = []
    try:
        for r in L.lists(con, False):  # family lists only, never adults-only ones
            its = L.items(con, r["id"], today_)
            out.append({"id": r["id"], "name": r["name"], "open_n": r["open_n"],
                        "items": [{"id": i["id"], "text": i["text"], "qty": i["qty"] or "", "done": i["status"] == "done",
                                   "by": i.get("added_by") if i.get("added_by") in names else "",
                                   "by_cls": colour(i.get("added_by"), names) if i.get("added_by") in names else ""}
                                  for i in its]})
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
    return out


def _meals_rows(con, start, days):
    import meals as M
    try:
        return M.week(con, start.isoformat(), days)
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return []
        raise


def meals(con, start, today_):
    import meals as M
    rows = _meals_rows(con, start, 7)
    days = [start + dt.timedelta(days=i) for i in range(7)]
    grid = []
    for slot in M.SLOTS:
        cells = []
        for d in days:
            m = next((r for r in rows if r["day"] == d.isoformat() and r["slot"] == slot), None)
            cells.append({"meal": m["meal"] if m else "", "note": (m["note"] or "") if m else "", "today": d == today_})
        grid.append({"slot": slot, "label": slot.capitalize(), "cells": cells})
    tonight = next((r for r in rows if r["day"] == today_.isoformat() and r["slot"] == "dinner"), None)
    recipe = None
    if tonight and tonight.get("recipe_id"):
        try:
            rec = M.get_recipe(con, tonight["recipe_id"])
        except (sqlite3.Error, ValueError):
            rec = None
        if rec:
            recipe = {"name": rec.get("name") or tonight["meal"], "servings": rec.get("servings"),
                      "ingredients": [{"text": " ".join(str(x) for x in (i.get("qty"), i.get("text")) if x),
                                       "pantry": bool(i.get("pantry"))} for i in rec.get("ingredients") or []][:14],
                      "notes": " ".join(str(rec.get("notes") or "").split())[:400]}
    return {"days": [{"dow": d.strftime("%a"), "num": d.day, "today": d == today_} for d in days], "grid": grid,
            "tonight": tonight["meal"] if tonight else None, "recipe": recipe}


# ---- money (only after an adult's PIN) ------------------------------------------------------------------------------
def money(con, today_):
    import budget
    import trends
    names = [n for n, _ in people(con)]
    try:
        summary = trends.month_summary(con, today_.strftime("%Y-%m"), today=today_)
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        summary = None
    try:
        pace = budget.pace(con, today_)
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        pace = {"lines": [], "day": today_.day, "days": 30}
    bills = sorted(_collect(con, today_, today_ + dt.timedelta(days=13), names)[2], key=lambda m: (m["date"], m["title"]))
    strip = []
    for i in range(14):
        d = today_ + dt.timedelta(days=i)
        here = [m for m in bills if m["date"] == d]
        strip.append({"dow": d.strftime("%a"), "num": d.day, "today": i == 0,
                      "items": [{"text": m["title"] + (f" {money_fmt(m['amount'], 2)}" if m["amount"] else ""),
                                 "kind": m["kind"]} for m in here]})
    due = [m for m in bills if m["kind"] in ("bill", "late") and m["amount"]]
    budgeted = [line for line in pace["lines"] if not line["allowance"] and line["limit"]]
    plan = round(sum(line["limit"] for line in budgeted), 2) or None
    plan_spent = round(sum(line["spent"] for line in budgeted), 2) if budgeted else None  # like for like: budgeted lines only
    spent = summary["spent"] if summary else None
    rate = W.star_cents()
    allowance = [{"name": k["name"], "initial": k["name"][:1], "cls": colour(k["name"], names), "stars": k["stars_week"],
                  "amount": money_fmt(k["cents_week"] / 100, 2)} for k in W.manage(con, today_)["children"] if k["n"] or k["stars_week"]]
    return {"spent": spent, "plan": plan, "plan_spent": plan_spent, "income": summary["income"] if summary else None,
            "left": summary["left"] if summary else None,
            "even_pct": max(0, min(100, round(100 * pace["day"] / pace["days"]))) if pace.get("days") else None,
            "plan_pct": max(0, round(100 * plan_spent / plan)) if plan_spent is not None and plan else None,
            "plan_over": bool(plan and plan_spent and plan_spent > plan),
            "lines": [{"label": line["label"], "spent": money_fmt(line["spent"], 0), "limit": money_fmt(line["limit"], 0),
                       "pct": max(0, min(100, round(line["pct"] or 0))), "over": line["status"] == "red"}
                      for line in pace["lines"] if not line["allowance"]][:5],
            "strip": strip, "due_total": money_fmt(sum(m["amount"] for m in due), 2) if due else None, "due_n": len(due),
            "allowance": allowance, "star_cents": rate, "fmt": money_fmt}
