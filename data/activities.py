"""Weekly activity schedules: classes, sports, lessons and clubs that repeat every week (table activity_schedules,
migration 048).

  python data/activities.py add "<title>" --days "Mon Wed" [--who NAME] [--time 17:00] [--until 17:45]
                                [--provider "YMCA"] [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--school-days]
  python data/activities.py list [--who NAME] [--all]
  python data/activities.py week [YYYY-MM-DD] [--span N] [--who NAME]  the classes day by day
  python data/activities.py skip ID YYYY-MM-DD          one cancelled lesson
  python data/activities.py end ID                       the season is over (kept, marked ended)

--school-days: the class follows the school calendar and does not run on a school closure day (calendar_days kind
'closure' for the whole household or for that child). Only titles, the provider's name, days and times are stored.
Library: parse_days, parse_time, rows, occurrences, label, alerts (today and tomorrow for the Brief and Today).
"""
import argparse
import datetime as dt
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import validators  # noqa: E402

DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
SHORT = dict(zip(DAYS, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")))
KIND = "Class"
ALERT_DAYS = 1          # alerts: today and tomorrow (the Calendar and What's on expand any range)
MAX_SPAN = 400          # days one occurrences() call expands at most
_WORDS = {"mo": "MO", "mon": "MO", "monday": "MO", "tu": "TU", "tue": "TU", "tues": "TU", "tuesday": "TU",
          "we": "WE", "wed": "WE", "wednesday": "WE", "th": "TH", "thu": "TH", "thur": "TH", "thurs": "TH",
          "thursday": "TH", "fr": "FR", "fri": "FR", "friday": "FR", "sa": "SA", "sat": "SA", "saturday": "SA",
          "su": "SU", "sun": "SU", "sunday": "SU"}
_GROUPS = {"weekdays": DAYS[:5], "weekends": DAYS[5:], "daily": DAYS, "everyday": DAYS}


def parse_days(text):
    """'Mon Wed', 'mo,we', 'Tuesday & Thursday', 'weekdays' -> 'MO,WE' (week order). ValueError when none or unknown."""
    got = set()
    for w in re.split(r"[\s,;/&+]+|\band\b", str(text or "").lower()):
        w = w.strip(". ")
        if not w:
            continue
        if w in _GROUPS:
            got.update(_GROUPS[w])
        elif w.rstrip("s") in _WORDS:
            got.add(_WORDS[w.rstrip("s")])
        elif w in _WORDS:
            got.add(_WORDS[w])
        else:
            raise ValueError(f"'{w}' is not a day of the week")
    if not got:
        raise ValueError("pick at least one day")
    return ",".join(d for d in DAYS if d in got)


def parse_time(text):
    """'17:00', '5pm', '5:30 pm', '9' -> 'HH:MM' (24-hour). ValueError otherwise."""
    return validators.clock_time(text or "")


def day_codes(weekdays):
    return [d for d in str(weekdays or "").split(",") if d in DAYS]


def days_text(weekdays):
    codes = day_codes(weekdays)
    if codes == list(DAYS[:5]):
        return "Weekdays"
    return " ".join(SHORT[d] for d in codes)


def skips(r):
    out = set()
    for s in str(r.get("skip_dates") or "").split(","):
        try:
            out.add(dt.date.fromisoformat(s.strip()))
        except ValueError:
            continue
    return out


def rows(con, who=None, include_ended=False):
    """Schedules as dicts (active only unless include_ended); none when the table does not exist yet."""
    con.row_factory = sqlite3.Row
    sql, p = "SELECT * FROM activity_schedules WHERE 1=1", []
    if not include_ended:
        sql += " AND status='active'"
    if who:
        sql += " AND member=?"
        p.append(who)
    try:
        return [dict(r) for r in con.execute(sql + " ORDER BY member, title", p)]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def closures(con, start, end):
    """{date: {member or None}} of active school closure days between start and end (calendar_days, kind closure)."""
    out = {}
    try:
        got = con.execute("SELECT day, COALESCE(end_day, day), member FROM calendar_days WHERE status='active' "
                          "AND kind='closure' AND day <= ? AND COALESCE(end_day, day) >= ?",
                          (end.isoformat(), start.isoformat())).fetchall()
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return out
    for a, b, who in got:
        try:
            d, last = max(dt.date.fromisoformat(a), start), min(dt.date.fromisoformat(b), end)
        except ValueError:
            continue
        while d <= last:
            out.setdefault(d, set()).add(who)
            d += dt.timedelta(days=1)
    return out


def label(r, with_who=True):
    """'Swimming 17:00-17:45 (Sam)': the title of one occurrence (Brief, Calendar, What's on use the same)."""
    t = r["title"]
    if r.get("start_time"):
        t += f" {r['start_time']}" + (f"-{r['end_time']}" if r.get("end_time") else "")
    if with_who and r.get("member"):
        t += f" ({r['member']})"
    return t


def summary(r):
    """'Swimming, Mon Wed 17:00-17:45 at YMCA (Sam), until Dec 12': one schedule in a list."""
    t = f"{r['title']}, {days_text(r['weekdays'])}"
    if r.get("start_time"):
        t += f" {r['start_time']}" + (f"-{r['end_time']}" if r.get("end_time") else "")
    if r.get("provider"):
        t += f" at {r['provider']}"
    if r.get("member"):
        t += f" ({r['member']})"
    if r.get("term_end"):
        t += f", until {r['term_end']}"
    return t


def occurrences(con, start, end, who=None, sched=None):
    """Every class between start and end (inclusive, at most MAX_SPAN days), sorted by date and time:
    [{date, time, title, label, member, provider, id}]. Skipped dates, days outside the term and (for school_days
    classes) school closure days are left out."""
    end = min(end, start + dt.timedelta(days=MAX_SPAN))
    if end < start:
        return []
    sched = rows(con, who) if sched is None else sched
    if not sched:
        return []
    shut = closures(con, start, end) if any(r.get("school_days") for r in sched) else {}
    out = []
    for r in sched:
        want = {DAYS.index(d) for d in day_codes(r["weekdays"])}
        try:
            lo = max(start, dt.date.fromisoformat(r["term_start"])) if r.get("term_start") else start
            hi = min(end, dt.date.fromisoformat(r["term_end"])) if r.get("term_end") else end
        except ValueError:
            continue
        skip = skips(r)
        d = lo
        while d <= hi:
            off = shut.get(d, set())
            if d.weekday() in want and d not in skip and not (r.get("school_days") and (None in off or r.get("member") in off)):
                out.append({"date": d, "time": r.get("start_time") or "", "title": r["title"], "label": label(r),
                            "member": r.get("member"), "provider": r.get("provider") or "", "id": r["id"]})
            d += dt.timedelta(days=1)
    out.sort(key=lambda o: (o["date"], o["time"] or "99", o["title"]))
    return out


def alerts(con, today):
    """Today's and tomorrow's classes as action items (kind Class; one key per class and day)."""
    return [{"date": o["date"], "kind": KIND, "title": o["label"], "detail": o["provider"], "amount": None,
             "ref": ("activity_schedules", o["id"])}
            for o in occurrences(con, today, today + dt.timedelta(days=ALERT_DAYS))]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["add", "list", "week", "skip", "end"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--who")
    ap.add_argument("--days", dest="weekdays")
    ap.add_argument("--time")
    ap.add_argument("--until")
    ap.add_argument("--provider")
    ap.add_argument("--from", dest="term_start")
    ap.add_argument("--to", dest="term_end")
    ap.add_argument("--school-days", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--span", type=int, default=7)
    a = ap.parse_args(argv)
    actor = {"name": "terminal", "role": "adult"}
    import edit_actions as ea
    if a.cmd == "add":
        if not a.args:
            raise SystemExit("usage: add TITLE --days 'Mon Wed' [--time 17:00] ...")
        ok, msg = ea.activity_add(actor, a.args[0], a.weekdays, who=a.who, start_time=a.time, end_time=a.until,
                                  provider=a.provider, term_start=a.term_start, term_end=a.term_end,
                                  school_days=a.school_days)
    elif a.cmd == "skip":
        if len(a.args) != 2:
            raise SystemExit("usage: skip ID YYYY-MM-DD")
        ok, msg = ea.activity_skip(actor, a.args[0], a.args[1])
    elif a.cmd == "end":
        if len(a.args) != 1:
            raise SystemExit("usage: end ID")
        ok, msg = ea.activity_end(actor, a.args[0])
    else:
        con = db.connect(paths.DB, readonly=True)
        try:
            if a.cmd == "list":
                got = rows(con, a.who, a.all)
                for r in got:
                    print(f"{r['id']:>3}  {r['status']:<6} {summary(r)}")
                if not got:
                    print("No weekly classes recorded.")
                return 0
            start = dt.date.fromisoformat(a.args[0]) if a.args else dates.today()
            got = occurrences(con, start, start + dt.timedelta(days=max(1, min(a.span, 60)) - 1), a.who)
            for o in got:
                print(f"  {o['date']:%a %b} {o['date'].day}: {o['label']}" + (f" at {o['provider']}" if o["provider"] else ""))
            if not got:
                print("No classes on these days.")
            return 0
        finally:
            con.close()
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
