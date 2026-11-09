"""Everything coming up in one list, read-only: bills, appointments, expiries, checkups, school items, birthdays,
festivals and holidays from Mitra Home's records, plus your Google Calendar when it is connected (and any holiday
calendar your Google account has). The assistant uses it for "what is on next week", "any events", "holidays next month".

  python data/whats_on.py                          next 14 days
  python data/whats_on.py --start 2026-11-01 --days 30
  python data/whats_on.py --no-google

Nothing is changed and nothing is sent anywhere except the normal read-only request to Google for events.
"""
import argparse
import datetime as dt
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402

MAX_LINES = 60


def _days(con, start, end):
    """Holidays, festivals, school days off (calendar_days.py) and weekly classes (activities.py) in the range."""
    out = []
    try:
        import calendar_days
        out += [(max(r["start"], start), r["kind"], calendar_days.title(r), "")
                for r in calendar_days.between(start, end, con)]
    except Exception:  # noqa: BLE001 (optional; the list must still come)
        pass
    try:
        import activities
        out += [(o["date"], activities.KIND, o["label"], "") for o in activities.occurrences(con, start, end)]
    except Exception:  # noqa: BLE001
        pass
    return out


def _records(start, end, today):
    import action_items as ai
    con = db.connect(paths.DB, readonly=True)
    try:
        items = ai.collect_items(con, today, max(1, (end - today).days))
        extra = _days(con, start, end)
    finally:
        con.close()
    out = []
    for it in items:
        if start <= it["date"] <= end:
            amt = f"${abs(float(it['amount'])):,.2f}" if it.get("amount") is not None else ""
            out.append((it["date"], it["kind"], it["title"], amt))
    return out + extra


def _google(start, end):
    """-> (rows, note). Never raises: a broken sign-in becomes a short note."""
    try:
        import google_calendar as gc
        st = gc.status()
        if not (st["enabled"] and st["signed_in"]):
            return [], ""
        cals = list(gc.configured_calendars())
        try:  # a holiday calendar the account is subscribed to counts as "my calendar" too
            cals += [c["id"] for c in gc.calendars() if "#holiday@group.v.calendar.google.com" in c["id"] and c["id"] not in cals]
        except gc.CalendarError:
            pass
        days = (end - start).days + 1
        rows = []
        for e in gc.events(days, start, cals):
            d = dt.date.fromisoformat(e["date"])
            if start <= d <= end:
                when = "" if e["all_day"] else f" at {e['time']}"
                rows.append((d, "Calendar", e["title"] + when, ""))
        return rows, ""
    except Exception as e:  # noqa: BLE001
        return [], f"(Google Calendar was not available: {type(e).__name__})"


def build(start, days, google=True):
    today = dates.today()
    end = start + dt.timedelta(days=days - 1)
    rows = _records(start, end, today)
    note = ""
    if google:
        g, note = _google(start, end)
        rows += g
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r[0], r[1], r[2])):
        k = (r[0], r[2].lower())
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return start, end, out, note


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--start", default=None)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--no-google", action="store_true")
    a = ap.parse_args(argv)
    start = dt.date.fromisoformat(a.start) if a.start else dates.today()
    days = max(1, min(120, a.days))
    start, end, rows, note = build(start, days, not a.no_google)
    print(f"Coming up from {start:%A, %B} {start.day} to {end:%A, %B} {end.day}:")
    if not rows:
        print("  Nothing is on the calendar or in the records for these dates.")
    for d, kind, title, amt in rows[:MAX_LINES]:
        print(f"  {d:%a %b} {d.day}: {kind} - {title}" + (f" ({amt})" if amt else ""))
    if len(rows) > MAX_LINES:
        print(f"  ... and {len(rows) - MAX_LINES} more")
    if note:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main())
