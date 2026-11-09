"""Apply migration 069 to data/family.db (idempotent): the pay period of a job, apart from its schedule cycle.

contracts.period_start  first day of one timesheet / pay period (ISO date), e.g. a Thursday
contracts.period_end    last day of that same period; the length (end - start + 1) repeats back and forth in time
Both empty = the periods follow the schedule cycle (timesheet_cycle + cycle_anchor), as before. The schedule pattern
(`schedule`, `cycle_anchor`) is untouched: a job may work a Sun-Sat pattern and be paid Thu-Wed.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
have = {r[1] for r in c.execute("PRAGMA table_info(contracts)")}
if have:
    for col in ("period_start", "period_end"):
        if col not in have:
            c.execute(f"ALTER TABLE contracts ADD COLUMN {col} TEXT")
c.commit()
print("migration 069 ok")
