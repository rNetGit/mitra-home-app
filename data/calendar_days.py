"""Special days in one list: public holidays (computed, data/holidays.py), the festival pack (config/festivals.json)
and the household's own calendar days (table calendar_days, migration 049: holidays, festivals, school closures and
early dismissals, added by hand, confirmed from the yearly traditions look-up or read from a school calendar).

  python data/calendar_days.py list [YEAR]                        everything for the year (default this year)
  python data/calendar_days.py add YYYY-MM-DD "<name>" [--kind holiday|festival|closure|early] [--end YYYY-MM-DD]
                                   [--who NAME]
  python data/calendar_days.py drop ID
  python data/calendar_days.py proposed                           what waits for an adult in the Inbox

Library: between(start, end, con=None, who=None) -> [{start, end, kind, name, member, source, id}] sorted by date;
kind is what a person reads (Holiday, Festival, No school, Early dismissal). Only 'active' rows are shown; rows from
the AI look-up and school calendars wait as 'proposed' until an adult accepts them in the Inbox (proposals.py).
"""
import argparse
import datetime as dt
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402

KINDS = ("holiday", "festival", "closure", "early")
SHOWN = {"holiday": "Holiday", "festival": "Festival", "closure": "No school", "early": "Early dismissal",
         "clock": "Clocks change"}  # clock: daylight saving dates from the holiday rules (holidays.observances)
MAX_SPAN = 800


def _rows(con, sql, params):
    try:
        con.row_factory = sqlite3.Row
        return [dict(r) for r in con.execute(sql, params)]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def stored(con, start, end, status="active", who=None):
    """calendar_days rows overlapping start..end with this status (who: only the household's and that person's)."""
    sql = ("SELECT * FROM calendar_days WHERE status=? AND day <= ? AND COALESCE(end_day, day) >= ?")
    p = [status, end.isoformat(), start.isoformat()]
    if who:
        sql += " AND (member IS NULL OR member=?)"
        p.append(who)
    return _rows(con, sql + " ORDER BY day, kind, name", p)


def between(start, end, con=None, who=None, shared=False):
    """Every special day overlapping start..end (inclusive, at most MAX_SPAN days): public holidays, the festival
    pack and active calendar_days rows; the same day and name only once. shared=True: for a file that leaves the PC
    (the Drive copies of the digest and this-week page): the days from the family's traditions are left out."""
    end = min(end, start + dt.timedelta(days=MAX_SPAN))
    out = []
    try:
        import holidays
        out += [{"start": d, "end": d, "kind": SHOWN["holiday"], "name": n, "member": None, "source": "rules", "id": None}
                for d, n in holidays.between(start, end)]
        out += [{"start": d, "end": d, "kind": SHOWN["clock"], "name": n, "member": None, "source": "rules", "id": None}
                for d, n in holidays.observances_between(start, end)]
    except Exception:  # noqa: BLE001 (a broken rules file must not break a page)
        pass
    try:
        import festivals
        out += [{"start": a, "end": b, "kind": SHOWN["festival"], "name": n, "member": None, "source": "pack", "id": None}
                for a, b, n in festivals.FESTIVALS if b >= start and a <= end]
    except ImportError:
        pass
    own = con is None
    try:
        con = con or db.connect(paths.DB, readonly=True)
    except sqlite3.Error:
        con = None
    if con is not None:
        try:
            for r in stored(con, start, end, who=who):
                if shared and r["source"] == "tradition":
                    continue
                try:
                    a = dt.date.fromisoformat(r["day"])
                    b = dt.date.fromisoformat(r["end_day"]) if r["end_day"] else a
                except ValueError:
                    continue
                out.append({"start": a, "end": b, "kind": SHOWN.get(r["kind"], "Holiday"), "name": r["name"],
                            "member": r["member"], "source": r["source"], "id": r["id"]})
        finally:
            if own:
                con.close()
    seen, keep = set(), []
    for r in sorted(out, key=lambda r: (r["start"], r["id"] is None, r["kind"], r["name"])):
        k = (r["start"], r["name"].lower(), r["member"])
        if k not in seen:
            seen.add(k)
            keep.append(r)
    return keep


def title(r):
    """'Diwali', 'No school (Sam)', 'Thanksgiving break': the name as a list shows it."""
    return r["name"] + (f" ({r['member']})" if r.get("member") else "")


def span(r):
    return f"{r['start']:%b} {r['start'].day}" + (f" to {r['end']:%b} {r['end'].day}" if r["end"] != r["start"] else "")


def by_day(start, end, con=None, who=None):
    """{date: [(kind, title)]} with spans spread over each day they cover."""
    ev = {}
    for r in between(start, end, con, who):
        d = max(r["start"], start)
        while d <= min(r["end"], end):
            ev.setdefault(d, []).append((r["kind"], title(r)))
            d += dt.timedelta(days=1)
    return ev


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["list", "add", "drop", "proposed"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--kind", default="holiday", choices=KINDS)
    ap.add_argument("--end")
    ap.add_argument("--who")
    a = ap.parse_args(argv)
    actor = {"name": "terminal", "role": "adult"}
    if a.cmd in ("add", "drop"):
        import edit_actions as ea
        if a.cmd == "add":
            if len(a.args) != 2:
                raise SystemExit('usage: add YYYY-MM-DD "<name>" [--kind ...] [--end ...] [--who ...]')
            ok, msg = ea.calendar_day_add(actor, a.args[0], a.args[1], a.kind, a.end, a.who)
        else:
            if len(a.args) != 1:
                raise SystemExit("usage: drop ID")
            ok, msg = ea.calendar_day_drop(actor, a.args[0])
        print(msg)
        return 0 if ok else 1
    con = db.connect(paths.DB, readonly=True)
    try:
        if a.cmd == "proposed":
            got = stored(con, dt.date(1900, 1, 1), dt.date(2200, 1, 1), status="proposed")
            for r in got:
                print(f"{r['id']:>4}  {r['day']}{' to ' + r['end_day'] if r['end_day'] else '':<14} "
                      f"{SHOWN.get(r['kind'], r['kind']):<16} {r['name']}  [{r['source']}: {r['label'] or ''}]")
            if not got:
                print("Nothing waits for review.")
            return 0
        year = int(a.args[0]) if a.args else dates.today().year
        got = between(dt.date(year, 1, 1), dt.date(year, 12, 31), con)
        for r in got:
            print(f"  {span(r):<16} {r['kind']:<16} {title(r)}" + (f"  (id {r['id']})" if r["id"] else ""))
        if not got:
            print(f"No holidays, festivals or school days off recorded for {year}.")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    sys.exit(main())
