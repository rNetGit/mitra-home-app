"""Apply migration 051 to data/family.db (idempotent): more about each person, edited by adults (Family > edit icon).

members gets: school (school, college or employer, up to 80 characters), grade (grade, year or program),
grad_year (expected graduation, 4 digits) and relation (how the person is related to the household: "mother", "son").
Names, roles and birthdays already exist; the name can now be corrected (edit_actions.member_update renames it
everywhere). Stays on this PC; never in the phone sync (sync_data lists its own columns).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(members)")}
for col, kind in (("school", "TEXT"), ("grade", "TEXT"), ("grad_year", "INTEGER"), ("relation", "TEXT")):
    if cols and col not in cols:
        c.execute(f"ALTER TABLE members ADD COLUMN {col} {kind}")
c.commit()
print("migration 051 ok")
