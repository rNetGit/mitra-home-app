"""The work page of the web app (work contracts pack): jobs and businesses of adults, hours per day for a
timesheet period, the repeating schedule, the contract's profile and its work calendar. Every change goes through
edit_actions (adults only, logs/edits.log), the same functions the earlier Work tab used. No web code here.
"""
import datetime as dt
import sqlite3

import config
import dates  # noqa: E402
import db
import edit_actions as ea
import members as mem
import paths

TABS = (("hours", "Timesheets"), ("papers", "Paperwork"), ("schedule", "Schedule"), ("report", "Summary"), ("profile", "Details"), ("calendar", "Work calendar"))
KIND_LABEL = {"employment": "Employment", "contract": "Contract", "business": "Own business (LLC, S-corp, sole prop)",
              "rental": "Rental", "side": "Side business"}  # the same words as work.KIND_LABEL
PLAN_LABEL = {"O": "Office (on site)", "H": "Remote (off site)", "W": "Working", "-": "Off"}
LOC_LABEL = {"onsite": "Office (on site)", "offsite": "Remote (off site)"}
PAY_RULES = (("every14", "every 14 days"), ("every7", "every 7 days"), ("semimonthly", "twice a month (15th, last day)"),
             ("monthly", "monthly on a day"))
OPS = ("contract_add", "hours", "schedule", "profile", "cal_add", "paydays", "paper_attach", "paper_remove")
MAX_DAYS = 31


def _w():
    import work
    return work


def on():
    return config.pack("contracts")


def _ro():
    return db.connect(paths.DB, readonly=True)


def _months(today, n=13):
    out, m = [], today.replace(day=1)
    for _ in range(n):
        out.append(m.strftime("%Y-%m"))
        m = (m - dt.timedelta(days=1)).replace(day=1)
    return out


def _cycle_len(W, c):
    return W.CYCLES.get(c.get("timesheet_cycle") or "", len(W.schedule_of(c)))


def _cycles(W, c, today, n_back=6):
    """The timesheet periods to pick from, newest first: the next one, this one and `n_back` before (pay period when set)."""
    cur = W.pay_period(c, today)
    out = [cur]
    for _ in range(n_back):
        out.append(W.pay_period(c, out[-1][0] - dt.timedelta(days=1)))
    out.insert(0, W.pay_period(c, cur[1] + dt.timedelta(days=1)))
    return out


def _report(W, con, c, args, today):
    """Hours summary, read only: one month as a calendar, or one year month by month. Recorded hours only (a timesheet or
    typed hours); planned hours of past days not entered yet are shown apart, never added to the total."""
    import calendar as _cal
    kind = "year" if args.get("view") == "year" else "month"
    months = _months(today, 13)
    ym = args.get("ym") if args.get("ym") in months else months[0]
    first = min((r[0] for r in con.execute("SELECT MIN(work_date) FROM work_hours WHERE contract_id=?", (c["id"],)) if r[0]), default=None)
    y0 = min(int(first[:4]) if first else today.year, today.year)
    years = list(range(today.year, y0 - 1, -1))
    try:
        year = int(args.get("year", today.year))
    except (TypeError, ValueError):
        year = today.year
    year = year if year in years else today.year
    labels = [(k, f"{dt.date(int(k[:4]), int(k[5:]), 1):%B %Y}") for k in months]

    def unrecorded(rows):
        return round(sum(r["expected"] for r in rows if r["hours"] is None and r["date"] <= today), 2)

    if kind == "month":
        y, m = int(ym[:4]), int(ym[5:])
        d0, d1 = dt.date(y, m, 1), dt.date(y, m, _cal.monthrange(y, m)[1])
        rows = {r["date"]: r for r in W.days(con, c, d0, d1)}
        sm = W.summary(con, c, d0, d1, today)
        weeks = []
        for wk in _cal.Calendar(firstweekday=6).monthdatescalendar(y, m):
            cells = []
            for d in wk:
                r = rows.get(d)
                if r is None:
                    cells.append(None)
                    continue
                worked = (r["hours"] or 0) > 0
                where = r["location"] or ({"O": "onsite", "H": "offsite"}.get(r["plan"]) if worked else None)
                cells.append({"n": d.day, "hours": "" if not worked else f"{r['hours']:g}",
                              "where": {"onsite": "Office", "offsite": "Remote"}.get(where, "") if worked else "",
                              "holiday": r["holiday"] or r["floating"] or "", "today": d == today})
            weeks.append(cells)
        return {"view": "month", "ym": ym, "month_label": dict(labels)[ym], "months": labels, "weeks": weeks,
                "hours": f"{sm['hours']:g}", "days": sm["days_worked"], "onsite": sm["onsite"], "offsite": sm["offsite"],
                "planned": unrecorded(list(rows.values())), "years": years, "year": year}
    out, tot, td, to, tr, tp = [], 0.0, 0, 0, 0, 0.0
    for m in range(1, 13):
        d0, d1 = dt.date(year, m, 1), dt.date(year, m, _cal.monthrange(year, m)[1])
        sm = W.summary(con, c, d0, d1, today)
        pl = unrecorded(W.days(con, c, d0, d1))
        out.append({"month": f"{d0:%B}", "ym": f"{year}-{m:02d}", "hours": f"{sm['hours']:g}" if sm["hours"] else "",
                    "days": sm["days_worked"] or "", "onsite": sm["onsite"] or "", "offsite": sm["offsite"] or ""})
        tot, td, to, tr, tp = tot + sm["hours"], td + sm["days_worked"], to + sm["onsite"], tr + sm["offsite"], tp + pl
    return {"view": "year", "year": year, "years": years, "months": labels, "ym": ym, "rows": out,
            "hours": f"{round(tot, 2):g}", "days": td, "onsite": to, "offsite": tr, "planned": round(tp, 2)}


def _can_see(c, user):
    return c.get("visibility") != "private" or bool(user and user.get("name") and user["name"] == c.get("person"))


def _guard(user, cid):
    """None when this adult may use job `cid`, else the sentence to show (no such job, or a private job of someone else)."""
    try:
        con = _ro()
    except sqlite3.Error:
        return "No such job."
    try:
        try:
            c = _w().get_by_id(con, cid)
        except (ValueError, sqlite3.Error):
            return "No such job."
        return None if _can_see(c, user) else "That job is private to its owner."
    finally:
        con.close()


def view(user, args, today=None):
    """Everything the page needs: {on, contracts, c, tab, ...the tab's data}."""
    today = today or dates.today()
    out = {"on": on(), "contracts": [], "c": None, "tab": "profile", "tabs": TABS, "kinds": list(KIND_LABEL.items()), "people": [], "today": today.isoformat()}
    if not out["on"]:
        return out
    W = _w()
    try:
        con = _ro()
    except sqlite3.Error:
        return out
    try:
        try:
            me = (user or {}).get("name")
            cs = sorted((c for c in W.contracts(con, False) if _can_see(c, user)),
                        key=lambda c: (c["status"] != "active", c.get("person") != me, c.get("rank") == "secondary", c["client"], c["id"]))
        except sqlite3.Error:
            return out
        try:
            out["people"] = [r[0] for r in con.execute("SELECT name FROM members WHERE role='adult' ORDER BY id")]
        except sqlite3.Error:
            out["people"] = mem.names(con)
        # one adult at a time: the pills pick whose jobs are listed (default: the signed-in adult); a job with no person shows for all
        who = args.get("who") if args.get("who") in out["people"] else None
        if who is None and args.get("c"):  # a link to one job shows that job's person
            who = next((x.get("person") for x in cs if str(x["id"]) == str(args.get("c")) and x.get("person") in out["people"]), None)
        if who is None and me in out["people"]:
            who = me
        out["who"] = who or ""
        if who:
            cs = [x for x in cs if not x.get("person") or x["person"] == who]
        out["contracts"] = [{"id": c["id"], "label": c["client"] + (f" #{c['contract_no']}" if c.get("contract_no") else "")
                             + (" (secondary)" if c.get("rank") == "secondary" else "")
                             + ("" if c["status"] == "active" else f" ({c['status']})")} for c in cs]
        try:
            want = int(args.get("c", ""))
        except (TypeError, ValueError):
            want = None
        active = [c for c in cs if c["status"] == "active"] or cs
        c = next((x for x in cs if x["id"] == want), active[0] if active else None)
        if c is None:
            return out
        out["c"] = {k: ("" if c.get(k) is None else c.get(k)) for k in c.keys()} if hasattr(c, "keys") else dict(c)
        tab = args.get("tab") if args.get("tab") in dict(TABS) else ("hours" if c.get("needs_timesheets") else "profile")
        out["tab"] = tab
        if tab == "hours":
            cyc = _cycles(W, c, today)
            keys = [a.isoformat() for a, _ in cyc]
            pick = cyc[keys.index(args["cycle"])] if args.get("cycle") in keys else cyc[1]
            rows = []
            for r in W.days(con, c, pick[0], pick[1]):
                past = r["date"] <= today
                hours = r["hours"] if r["hours"] is not None else (r["expected"] or None if past else None)
                where = r["location"] or ({"O": "onsite", "H": "offsite"}.get(r["plan"]) if past else None)
                rows.append({"date": r["date"].isoformat(), "day": f"{r['date']:%a}", "plan": PLAN_LABEL[r["plan"]],
                             "holiday": r["holiday"] or r["floating"] or "", "hours": "" if hours is None else f"{hours:g}",
                             "where": where or "", "from": r["source"] or ("planned" if past and r["expected"] else "")})
            out["hours"] = {"cycles": [(a.isoformat(), f"{a:%a %b %d} - {b:%a %b %d, %Y}") for a, b in cyc],
                            "cycle": pick[0].isoformat(), "rows": rows}
        elif tab == "report":
            out["report"] = _report(W, con, c, args, today)
        elif tab == "papers":
            out["papers"] = {"rows": W.papers(con, c["id"]), "kinds": list(W.PAPER_KINDS.items()), "choices": W.paper_choices(con, c["id"])}
        elif tab == "schedule":
            n = _cycle_len(W, c)
            s0, _ = W.cycle_bounds(c, today)
            out["sched"] = {"n": n, "start": f"{s0:%a %b %d}", "anchor": s0.isoformat(),
                            "days": [(i, f"{s0 + dt.timedelta(days=i):%a %m/%d}", W.plan_for(c, s0 + dt.timedelta(days=i)))
                                     for i in range(n)], "labels": list(PLAN_LABEL.items())}
        elif tab == "profile":
            cals = W.calendar_names(con)
            out["prof"] = {"freqs": W.INVOICE_FREQS, "cycles": list(W.CYCLES), "calendars": cals,
                           "statuses": ["active", "renewed", "ended"]}
        else:
            try:
                year = int(args.get("year", today.year))
            except (TypeError, ValueError):
                year = today.year
            year = min(max(year, 2020), 2100)
            name = c.get("work_calendar")
            days = W.calendar_days(con, name, dt.date(year, 1, 1), dt.date(year, 12, 31)) if name else {}
            out["cal"] = {"year": year, "name": name or "", "kinds": W.CAL_KINDS, "rules": PAY_RULES,
                          "days": [{"date": str(d), "day": f"{d:%a}", "kind": k, "name": t or ""}
                                   for d, ks in sorted(days.items()) for k, t in ks]}
    finally:
        con.close()
    return out


def _cid(d):
    try:
        return int(d.get("c", ""))
    except (TypeError, ValueError):
        return None


def act(user, op, d):
    """One change -> (ok, message). `d` holds the form fields (strings)."""
    if op not in OPS:
        return False, "That cannot be done here."
    if not on():
        return False, "The work contracts pack is off (Settings > Household profile > Optional features)."
    g = lambda k: str(d.get(k, "")).strip()  # noqa: E731
    if op == "contract_add":
        return ea.work_contract_add(user, g("client"), g("vendor") or None, g("contract_no") or None, g("person") or None,
                                    g("start") or None, g("end") or None, None, g("kind") or "employment",
                                    g("rank") or "primary", g("needs_timesheets") == "1")
    cid = _cid(d)
    if cid is None:
        return False, "Pick a job first."
    denied = _guard(user, cid)
    if denied:
        return False, denied
    if op == "paper_attach":
        return ea.work_paper_attach(user, cid, g("document"), g("kind"))
    if op == "paper_remove":
        return ea.work_paper_remove(user, cid, g("document"))
    if op == "hours":
        dates = [k[2:] for k in d if k.startswith("h_")][:MAX_DAYS]
        rows = []
        for day in sorted(dates):
            where = g("w_" + day)
            if f"e_{day}" in d and f"{g('h_' + day)}|{where}" == g("e_" + day):
                continue  # still the plan the form was filled with: planned hours are not worked hours
            rows.append((day, g("h_" + day) or None, where if where in LOC_LABEL else None))
        if not rows:
            return False, "No days to save."
        return ea.work_hours_save(user, cid, rows)
    if op == "schedule":
        picks = []
        for i in range(14):
            p = g(f"p_{i}")
            if not p:
                break
            if p not in PLAN_LABEL:
                return False, "Pick each day from the list."
            picks.append(p)
        fields = {"schedule": "".join(picks)}
        if g("anchor") and g("keep_anchor") != "1":
            fields["cycle_anchor"] = g("anchor")
        return ea.work_profile(user, cid, **fields)
    if op == "profile":
        return ea.work_profile(user, cid, client=g("client"), vendor=g("vendor"), contract_no=g("contract_no"),
                               start_date=g("start"), end_date=g("end"), kind=g("kind") or None,
                               rank=g("rank") or None, needs_timesheets=g("needs_timesheets") or None,
                               visibility=g("visibility") or None, person=g("person"), show_on_calendar=g("show_on_calendar") or None,
                               hours_per_day=g("hours_per_day") or None,
                               timesheet_cycle=g("timesheet_cycle") or None, cycle_anchor=g("anchor") or None,
                               period_start=g("period_start"), period_end=g("period_end"),
                               work_calendar=g("calendar"), status=g("status") or None)
    if op == "cal_add":
        return ea.work_calendar_add(user, g("calendar"), g("day"), g("kind"), g("title") or None)
    rule = g("rule")
    kw = {"every14": {"every": 14}, "every7": {"every": 7}, "semimonthly": {"semimonthly": True}}.get(rule)
    if rule == "monthly":
        try:
            kw = {"monthly": int(g("dom"))}
        except ValueError:
            return False, "Day of month: a number from 1 to 31."
    if kw is None:
        return False, "Pick a rule from the list."
    return ea.work_paydays(user, g("calendar"), g("first"), g("last"), **kw)


def import_file(user, kind, name, raw, cid=None, calendar=None):
    """A timesheet or work calendar sent as the raw body: saved to the inbox with the usual checks, then imported."""
    if kind not in ("timesheet", "work_calendar", "paper"):
        return False, "That cannot be done here."
    if not on():
        return False, "The work contracts pack is off."
    if kind == "paper" and cid is None:
        return False, "Pick the job first."
    if cid is not None and kind in ("timesheet", "paper"):
        denied = _guard(user, cid)
        if denied:
            return False, denied
    import inbox_upload
    ok, msg = inbox_upload.save_upload(name, raw)
    if not ok:
        return False, msg
    if kind == "paper":
        return ea.work_paper_upload(user, msg, cid, calendar or "other")
    return ea.work_import(user, msg, kind, contract_id=cid, calendar=calendar or None)
