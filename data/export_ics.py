"""Every due date as one calendar file (.ics) for any phone or desktop calendar. No Google account, no OAuth.

  python data/export_ics.py                       -> brief/mitrahome.ics (next 365 days)
  python data/export_ics.py --horizon 90 --kinds Bill,Renewal,Birthday --no-amounts --alarm 2
  python data/export_ics.py --out PATH | --stdout

Events are the same items as the Action tab and the weekly digest (bills, renewals, appointments, birthdays,
subscriptions, warranties, ID documents...), minus anything marked done, snoozed or ignored. Each is an all-day event
with a reminder the day before (--alarm N days, 0 = none), except a family event at a time of day (events.start_time):
that one is at its time (local floating, an hour long without an end) with a reminder an hour before. The UID is
derived from the item's stable key, so importing the file again updates events instead of duplicating them, and a bill
that is paid or snoozed simply disappears from the next export. The description carries the 8-character Id people use with `action_state.py done/snooze`.

What leaves the PC in this file: vendor names, titles, amounts (unless --no-amounts) and last4 identifiers exactly as
the Action tab shows them. Nothing else. `python data/sync_drive.py push` copies it to the Drive Brief/ folder when
"ics" is in config/family.json drive.push (the default); the weekly task refreshes it.

Library: build(items, today, alarm_days=1, amounts=True) -> str;  export(...) -> (path, count)
"""
import brand
import argparse
import datetime as dt
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = HERE.parent
DEFAULT_OUT = paths.BRIEF / "mitrahome.ics"
PRODID = "-//Mitra Home//due dates//EN"


def escape(s):
    """TEXT value escaping per RFC 5545 3.3.11."""
    return (str(s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n").replace("\r", "\\n"))


def fold(line):
    """Content line folding at 75 octets (continuation lines start with one space), never splitting a UTF-8 character."""
    out, cur, size, limit = [], "", 0, 75
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > limit:
            out.append(cur)
            cur, size, limit = " " + ch, 1 + n, 75
        else:
            cur += ch
            size += n
    out.append(cur)
    return out


def uid(key):
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:20] + "@familyagent"


def event(item, stamp, alarm_days=1, amounts=True):
    import action_state as _as
    key = item.get("key") or _as.key(item)
    d = item["date"]
    summary = f"{item['kind']}: {item['title']}"
    desc = [item.get("detail") or ""]
    if amounts and item.get("amount") is not None:
        desc.append(f"Amount: {_fmt(item['amount'])}")
    desc.append(f"Id: {_as.display_id(key)} (mark it done on Today)")
    desc.append(f"{brand.PRODUCT} record, not advice.")
    at = item.get("at")  # a family event at a time of day: local floating time, an hour long when no end is given
    if at:
        t0, t1 = at[0].replace(":", ""), (at[1] or "").replace(":", "")
        when = [f"DTSTART:{d:%Y%m%d}T{t0}00", f"DTEND:{d:%Y%m%d}T{t1}00" if t1 else "DURATION:PT1H"]
    else:
        when = [f"DTSTART;VALUE=DATE:{d:%Y%m%d}", f"DTEND;VALUE=DATE:{d + dt.timedelta(days=1):%Y%m%d}"]
    lines = ["BEGIN:VEVENT", f"UID:{uid(key)}", f"DTSTAMP:{stamp}", *when,
             f"SUMMARY:{escape(summary)}", f"DESCRIPTION:{escape(chr(10).join(x for x in desc if x))}",
             f"CATEGORIES:{escape(item['kind'])}", "TRANSP:OPAQUE" if at else "TRANSP:TRANSPARENT"]
    if alarm_days and alarm_days > 0:
        trigger = "-PT1H" if at else f"-P{int(alarm_days)}D"  # a timed event: an hour before, not a day
        lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:{trigger}", f"DESCRIPTION:{escape(summary)}", "END:VALARM"]
    lines.append("END:VEVENT")
    return lines


def weekly(sched, today, stamp, horizon=365, off=None):
    """One repeating event per weekly class (activities.py): RRULE WEEKLY on its days until the last day of the term
    (or the horizon), skipped lessons and (school_days classes) school closure days as EXDATE. Local floating time;
    all-day when the class has no start time. None when no lesson falls inside the horizon."""
    import activities as A
    first = max(today, dt.date.fromisoformat(sched["term_start"])) if sched.get("term_start") else today
    last = today + dt.timedelta(days=horizon)
    if sched.get("term_end"):
        last = min(last, dt.date.fromisoformat(sched["term_end"]))
    days = A.day_codes(sched["weekdays"])
    want = {A.DAYS.index(d) for d in days}
    start = next((first + dt.timedelta(days=i) for i in range(7) if (first + dt.timedelta(days=i)).weekday() in want), None)
    if not days or start is None or start > last:
        return None
    skip = sorted(d for d in A.skips(sched) | set(off or ()) if start <= d <= last and d.weekday() in want)
    t = (sched.get("start_time") or "").replace(":", "")
    e = (sched.get("end_time") or "").replace(":", "")

    def at(d, hhmm):
        return f"{d:%Y%m%d}T{hhmm}00"
    if t:
        when = [f"DTSTART:{at(start, t)}", f"DTEND:{at(start, e)}" if e else "DURATION:PT1H"]
        ex = [f"EXDATE:{','.join(at(d, t) for d in skip)}"] if skip else []
        until = at(last, "2359")
    else:
        when = [f"DTSTART;VALUE=DATE:{start:%Y%m%d}", f"DTEND;VALUE=DATE:{start + dt.timedelta(days=1):%Y%m%d}"]
        ex = [f"EXDATE;VALUE=DATE:{','.join(f'{d:%Y%m%d}' for d in skip)}"] if skip else []
        until = f"{last:%Y%m%d}"
    summary = f"{A.KIND}: {A.label(sched)}"
    return (["BEGIN:VEVENT", f"UID:{uid('activity_schedules:' + str(sched['id']))}", f"DTSTAMP:{stamp}", *when,
             f"RRULE:FREQ=WEEKLY;BYDAY={','.join(days)};UNTIL={until}", *ex, f"SUMMARY:{escape(summary)}",
             f"DESCRIPTION:{escape(sched.get('provider') or '')}", f"CATEGORIES:{escape(A.KIND)}", "TRANSP:OPAQUE",
             "END:VEVENT"])


def build(items, today, alarm_days=1, amounts=True, name=None, classes=()):
    """items as action_items.collect_items returns them (date, kind, title, detail, amount, ref[, key]); classes =
    (schedule row, closure dates) pairs for weekly() (their single-day copies are left out of items)."""
    name = name or brand.PRODUCT
    stamp = f"{today:%Y%m%d}T000000Z"  # the export date, not the clock: identical input gives an identical file
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{escape(name)}", f"X-WR-CALDESC:Due dates from {brand.PRODUCT} on this household's PC"]
    for sched, off in classes:
        ev = weekly(sched, today, stamp, off=off)
        if ev:
            lines += ev
    for it in sorted(items, key=lambda i: (i["date"], i["kind"], i["title"])):
        if (it.get("ref") or (None,))[0] == "activity_schedules" and classes:
            continue
        lines += event(it, stamp, alarm_days, amounts)
    lines.append("END:VCALENDAR")
    out = []
    for ln in lines:
        out += fold(ln)
    return "\r\n".join(out) + "\r\n"


def collect(con, today, horizon, kinds=None):
    import action_items as ai
    items = ai.collect_items(con, today, horizon)
    if kinds:
        want = {k.strip().lower() for k in kinds if k.strip()}
        items = [i for i in items if i["kind"].lower() in want]
    return items


def _classes(con, today, horizon):
    """[(schedule, school closure dates)] of the active weekly classes."""
    import activities as A
    sched = A.rows(con)
    if not sched:
        return []
    shut = A.closures(con, today, today + dt.timedelta(days=horizon)) if any(s["school_days"] for s in sched) else {}
    return [(s, [d for d, who in shut.items() if s["school_days"] and (None in who or s["member"] in who)]) for s in sched]


def export(out=None, horizon=365, kinds=None, alarm_days=1, amounts=True, today=None, con=None):
    today = today or dates.today()
    own = con is None
    con = con or db.connect(paths.DB, readonly=True)
    try:
        items = collect(con, today, horizon, kinds)
        classes = _classes(con, today, horizon) if not kinds or "class" in {k.strip().lower() for k in kinds} else []
    finally:
        if own:
            con.close()
    text = build(items, today, alarm_days, amounts, classes=classes)
    n = text.count("BEGIN:VEVENT")
    if out == "-":
        return "-", n, text
    p = pathlib.Path(out) if out else DEFAULT_OUT
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="")
    return p, n, text


def main():
    ap = argparse.ArgumentParser(description="Export due dates as an .ics calendar file.")
    ap.add_argument("--out", help=f"file to write (default {paths.rel(DEFAULT_OUT)})")
    ap.add_argument("--stdout", action="store_true", help="print the calendar instead of writing a file")
    ap.add_argument("--horizon", type=int, default=365, help="days ahead (default 365)")
    ap.add_argument("--kinds", help="comma-separated kinds to keep, e.g. Bill,Renewal,Birthday (default all)")
    ap.add_argument("--alarm", type=int, default=1, help="reminder N days before (default 1, 0 = none)")
    ap.add_argument("--no-amounts", action="store_true", help="leave amounts out of the file")
    a = ap.parse_args()
    kinds = a.kinds.split(",") if a.kinds else None
    p, n, text = export("-" if a.stdout else a.out, a.horizon, kinds, a.alarm, not a.no_amounts)
    if a.stdout:
        sys.stdout.write(text)
        return
    try:
        shown = paths.rel(p)
    except ValueError:
        shown = str(p)
    print(f"{n} events -> {shown}  (import it into your phone calendar, or subscribe to the file; re-import updates, never duplicates)")


if __name__ == "__main__":
    main()
