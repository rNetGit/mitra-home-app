"""Apply migration 026 to data/family.db (idempotent): re-key hidden action items to row identity.

Until 0.15 a hidden item (done / snoozed / ignored) was stored under a hash of kind|title|date, so renaming a bill
brought it back and two same-day bills from one vendor were one item. From 0.16 items that come from a database row
are keyed `<table>:<row id>:<date>` (data/action_state.py). This migration walks today's items, computes both keys
and renames any stored hash to the new key, so nothing the family hid shows up again. Items that no longer appear
(their date passed) keep their old row; it is harmless.
"""
import datetime as dt
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402

c = sqlite3.connect(paths.DB)
have = {r[0] for r in c.execute("SELECT key FROM action_state")}
moved = 0
if have:
    import action_items as ai
    import action_state as st
    for it in ai.collect_items(c, dt.date.today(), 730, raw=True):
        old, new = st.legacy_key(it), st.key(it)
        if old != new and old in have and new not in have:
            c.execute("UPDATE action_state SET key=? WHERE key=?", (new, old))
            have.discard(old)
            have.add(new)
            moved += 1
c.commit()
print(f"migration 026 ok; {moved} hidden item(s) re-keyed")
