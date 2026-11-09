"""The Manage calendar page's data, with no web code: the family's calendar items for a date range as one list a person
can filter, each row saying where it comes from and whether it can be changed here.

  editable   an `events` row (family event or yearly date) or a `calendar_days` row (holiday, festival, school closure,
             early dismissal added by hand, confirmed from the traditions look-up or read from a school calendar):
             Change and Remove go through edit_actions (adults only), like the Records forms.
  record     bills, appointments, classes, birthdays, renewals ...: the row opens its own record (Records) to change.
  built in   public holidays, clock changes and the festival pack: computed, never stored, so read-only here.
  other      Google / other calendars, work days: read-only copies.

Used by webapp/app.py (/calendar/manage); nothing here writes.
"""
import datetime as dt

import calendar_data
import dates

EDITABLE = ("events", "calendar_days")
MAX_DAYS = 400
DEFAULT_DAYS = 90
BUILT_IN = ("Holiday", "Festival", "Clocks change")  # kinds a computed rule or the pack can make
ALL = "all"


def parse_range(start, end, today):
    """(from, to) dates from query text: today to 90 days on when missing or wrong; at most MAX_DAYS long."""
    a = calendar_data.parse_ref(start, today) if start else today
    try:
        b = dt.date.fromisoformat(str(end or "")[:10])
    except ValueError:
        b = a + dt.timedelta(days=DEFAULT_DAYS)
    if b < a:
        b = a
    return a, min(b, a + dt.timedelta(days=MAX_DAYS))


def rows(start, end, names=None, today=None):
    """Every calendar item between start and end (inclusive), by date: [{date, kind, title, ref, source, editable, who,
    past, repeats}]; source says where it lives (see above). Filter the list with pick()."""
    import db
    import paths
    import today_data
    today = today or dates.today()
    refs = {}
    ev = calendar_data.load_events(start.year, end.year, refs)
    if names is None:
        try:
            names = [n for n, _ in today_data.members_now()]
        except Exception:  # noqa: BLE001 (a missing database leaves the filter on names only)
            names = []
    yearly = set()
    try:
        con = db.connect(paths.DB, readonly=True)
        try:
            yearly = {r[0] for r in con.execute("SELECT id FROM events WHERE recurs_yearly=1")}
        finally:
            con.close()
    except Exception:  # noqa: BLE001
        pass
    out = []
    d = start
    while d <= end:
        for k, t in ev.get(d, []):
            ref = refs.get((d, k, t), "")
            table, _, rid = ref.partition(":")
            source = "editable" if table in EDITABLE else "record" if ref else "built in" if k in BUILT_IN else "other"
            out.append({"date": d, "kind": k, "title": t, "ref": ref, "source": source, "editable": source == "editable",
                        "who": today_data.person_of({"title": t, "kind": k}, names) or "", "past": d < today,
                        "repeats": table == "events" and rid.isdigit() and int(rid) in yearly})
        d += dt.timedelta(days=1)
    return fold_shopping(out)


def fold_shopping(items):
    """One row per shopping list and day instead of one per item ('Thanksgiving 2026: Pillows', ': Sheets', ...):
    'Thanksgiving 2026 (9 items: Pillows, Sheets, iPhone, Griddle, ...)'. The row keeps the first item's record link."""
    out, seen = [], {}
    for r in items:
        name, sep, item = r["title"].partition(": ")
        if r["kind"] != "Shopping" or not sep or not r["ref"].startswith("shopping_items:"):
            out.append(r)
            continue
        key = (r["date"], name)
        if key in seen:
            seen[key]["_items"].append(item)
            continue
        row = dict(r, _name=name, _items=[item])
        seen[key] = row
        out.append(row)
    for row in seen.values():
        n = len(row["_items"])
        if n > 1:
            shown = ", ".join(row["_items"][:4]) + (", ..." if n > 4 else "")
            row["title"] = f"{row['_name']} ({n} items: {shown})"
        del row["_name"], row["_items"]
    return out


def pick(items, who="", kind="", everything=False):
    """The rows a filter keeps: one person ('' = everyone), one kind ('' = all), everything False = only what can be
    changed here."""
    return [r for r in items if (everything or r["editable"]) and (not kind or r["kind"] == kind)
            and (not who or r["who"] == who)]
