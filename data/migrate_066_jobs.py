"""Apply migration 066 to data/family.db (idempotent): a contract row is now any job or business of an adult.

contracts.kind              employment | contract | business | rental | side (existing rows = contract)
contracts.rank              primary | secondary (the primary job is the default for timesheets and the calendar)
contracts.needs_timesheets  1 = hours are tracked and timesheets are expected (existing rows with a timesheet cycle = 1)
contracts.show_on_calendar  1 = the telecommute / office schedule shows on the Calendar (used by a later slice)
contracts.visibility        shared (every adult sees it) | private (only its owner)
No rates, salaries or amounts are kept here: money comes from the bank transactions only. The older rate / invoice
columns and tables stay in the database but the web app no longer shows them.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
have = {r[1] for r in c.execute("PRAGMA table_info(contracts)")}
if have:
    for col, decl in (("kind", "TEXT NOT NULL DEFAULT 'contract'"), ("rank", "TEXT NOT NULL DEFAULT 'primary'"),
                      ("needs_timesheets", "INTEGER NOT NULL DEFAULT 0"), ("show_on_calendar", "INTEGER NOT NULL DEFAULT 0"),
                      ("visibility", "TEXT NOT NULL DEFAULT 'shared'")):
        if col not in have:
            c.execute(f"ALTER TABLE contracts ADD COLUMN {col} {decl}")
            if col == "needs_timesheets":
                c.execute("UPDATE contracts SET needs_timesheets=1 WHERE timesheet_cycle IS NOT NULL")
c.commit()
print("migration 066 ok")
