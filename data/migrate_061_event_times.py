"""Apply migration 061 to data/family.db (idempotent): a family event at a time of day.

events.start_time  'HH:MM' (24-hour) when the event happens at a time ("family dinner 8 PM"); NULL = all day, as every
                   event was until now (birthdays, anniversaries, tax day)
events.end_time    'HH:MM' when it ends, later than start_time; NULL = no end given (shown as one hour where a length
                   is needed: the Family Wall's grid, the .ics file)
The event stays the household's, not one person's: a visit for one person is an appointment.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(events)")}
HHMM = "GLOB '[0-2][0-9]:[0-5][0-9]'"
if cols and "start_time" not in cols:
    c.execute(f"ALTER TABLE events ADD COLUMN start_time TEXT CHECK (start_time IS NULL OR start_time {HHMM})")
if cols and "end_time" not in cols:
    c.execute(f"ALTER TABLE events ADD COLUMN end_time TEXT CHECK (end_time IS NULL OR end_time {HHMM})")
c.commit()
print("migration 061 ok")
