"""Apply migration 049 to data/family.db (idempotent): holidays, festivals and school closure days.

calendar_days: one row per day or span (day .. end_day, end_day NULL = one day).
  kind     holiday (a public or religious holiday) | festival | closure (no school) | early (early dismissal)
  member   NULL = the whole household; a name = only that person (a child's school closure)
  source   manual | tradition (the yearly AI look-up, data/traditions.py) | school (a school calendar paper,
           doc_extract) | pack (copied from config/festivals.json)
  label    the tradition or school the row came from ("Hindu (Telugu)", "school calendar"); never shown to phones
  status   proposed (waits for an adult in the Inbox) | active | dropped
Public holidays from the country's rules (data/holidays.py) are computed, not stored. Filled by data/calendar_days.py,
data/traditions.py, the school-calendar reader and the Inbox.
"""
import sqlite3

DATE = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS calendar_days (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL CHECK (day {DATE}),
  end_day TEXT CHECK (end_day IS NULL OR (end_day {DATE} AND end_day >= day)),
  kind TEXT NOT NULL CHECK (kind IN ('holiday', 'festival', 'closure', 'early')),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  member TEXT,
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'tradition', 'school', 'pack')),
  label TEXT CHECK (label IS NULL OR length(label) <= 60),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('proposed', 'active', 'dropped')),
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_calendar_days ON calendar_days(day, kind, name, IFNULL(member, ''));
CREATE INDEX IF NOT EXISTS ix_calendar_days_status ON calendar_days(status, day);
""")
import sync_data  # noqa: E402
sync_data.ensure_triggers(c)
c.commit()
print("migration 049 ok")
