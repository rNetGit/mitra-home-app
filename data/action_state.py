"""Acknowledge / snooze action items so the digests stop repeating what is handled.

  python data/action_state.py list                       current done / snoozed / ignored items
  python data/action_state.py done ID [--note T]         handled: hide this item (a later occurrence is a new item)
  python data/action_state.py snooze ID DAYS|YYYY-MM-DD  hide until then
  python data/action_state.py ignore ID                  hide for good
  python data/action_state.py reset ID                   show it again
ID = the 8-character code in the Id column of the digests / Action tab (or the full key from `list`).

Identity. An item that comes from a database row is keyed `<table>:<row id>:<date>` (e.g. `bills:12:2026-10-15`),
so renaming the bill or fixing a typo in its vendor keeps it hidden, and two bills from one vendor on one day are two
items. Items with no row of their own (a detected price spike, a subscription estimate) keep the older key, a short
hash of kind|title|date. The 8-character Id shown to people is a hash of the key either way.

Library: key(item), display_id(key), attach(items), filter(con, items, today), resolve(id_or_key), set_state(...).
Bills are marked paid in `bills`, not here (dashboard_actions.mark_bill_paid_by_id).
"""
import argparse
import datetime as dt
import hashlib
import sqlite3
import sys
import db  # noqa: E402
import dates  # noqa: E402
from dates import parse as _d  # noqa: E402

import paths  # noqa: E402
DB = paths.DB


def _h(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def legacy_key(item):
    """Pre-0.16 key: hash of kind|title|date. Still used for items without a database row."""
    return _h(f"{item['kind']}|{item['title']}|{item['date'].isoformat()}")


def key(item):
    ref = item.get("ref")
    if ref and ref[0] and ref[1] is not None:
        return f"{ref[0]}:{ref[1]}:{item['date'].isoformat()}"
    return legacy_key(item)


def display_id(k):
    return k if len(k) == 8 and ":" not in k else _h(k)


def attach(items):
    for it in items:
        it["key"] = key(it)
        it["id"] = display_id(it["key"])
    return items


def item_key(item):  # kept for older callers; returns the stored key
    return key(item)


def filter(con, items, today):
    """Attach item['key'] / item['id'] and drop items marked done/ignored or snoozed past today."""
    try:
        st = {k: (s, u) for k, s, u in con.execute("SELECT key, state, until FROM action_state")}
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        st = {}
    out = []
    for it in attach(items):
        s, until = st.get(it["key"], (None, None))
        if s in ("done", "ignored"):
            continue
        if s == "snoozed" and until and _d(until) and _d(until) >= today:
            continue
        out.append(it)
    return out


def set_state(key, state, until=None, title=None, note=None):
    con = db.connect(DB)
    con.execute("INSERT INTO action_state(key, state, until, title, note) VALUES (?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET state=excluded.state, until=excluded.until, "
                "title=COALESCE(excluded.title, action_state.title), note=excluded.note, set_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime')",
                (key, state, until, title, note))
    con.commit()
    con.close()


def reset(key):
    con = db.connect(DB)
    con.execute("DELETE FROM action_state WHERE key=?", (key,))
    con.commit()
    con.close()


def resolve(id_or_key, horizon=400):
    """(key, title) for an 8-character Id or a full key, from today's items; (None, None) if nothing matches."""
    s = str(id_or_key).strip()
    sys.path.insert(0, str(DB.parent))
    import action_items as ai
    con = db.connect(DB, readonly=True)
    try:
        for it in ai.collect_items(con, dates.today(), horizon, raw=True):
            if s in (it["id"], it["key"]):
                return it["key"], it["title"]
    finally:
        con.close()
    if ":" in s:  # a full key for an item not currently listed (already hidden): still addressable
        return s, None
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "done", "snooze", "ignore", "reset"])
    ap.add_argument("id", nargs="?")
    ap.add_argument("when", nargs="?")
    ap.add_argument("--note")
    a = ap.parse_args()
    if a.cmd == "list":
        con = db.connect(DB)
        for r in con.execute("SELECT key, state, COALESCE(until,''), COALESCE(title,''), COALESCE(note,'') FROM action_state ORDER BY set_at DESC"):
            print(display_id(r[0]), *r, sep="  ")
        return
    if not a.id:
        raise SystemExit("ID required")
    k, title = resolve(a.id)
    if k is None:
        raise SystemExit(f"no current item has Id {a.id} (python data/make_digest.py lists them; `list` shows full keys)")
    if a.cmd == "reset":
        reset(k)
    elif a.cmd == "snooze":
        if not a.when:
            raise SystemExit("snooze needs DAYS or a date")
        if a.when.isdigit():
            until = (dates.today() + dt.timedelta(days=int(a.when))).isoformat()
        elif _d(a.when) and len(a.when) == 10:
            until = a.when
        else:
            raise SystemExit("snooze needs a number of days or a date as YYYY-MM-DD")
        set_state(k, "snoozed", until, title, a.note)
    else:
        set_state(k, "done" if a.cmd == "done" else "ignored", None, title, a.note)
    print("ok")


if __name__ == "__main__":
    main()
