"""Apply migration 006 to data/family.db (idempotent): seasonal / recurring home & health tasks (tables only).

seasonal_tasks: one row per recurring yearly task with a date window (MM-DD .. MM-DD; the window may
  cross New Year, e.g. 11-01 .. 03-31). lead_days = how early the dashboard starts warning.
seasonal_log:   one row each time a task is done (done_date, where/who, notes). A task counts as
  done for a season when a log row falls inside [window_start - 45d, window_end + 21d].
Tasks come from a region pack: `python data/seasonal_packs.py apply KEY` (the wizard picks one from the
family's country and climate). Until 0.14 this migration also seeded the US cold-climate pack into every
database; migration 023 tags those rows as pack `us_cold`. Manage tasks with data/seasonal.py (list / done / add).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS seasonal_tasks (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  category TEXT,              -- Health|Lawn|Winter|Home|Car|Safety
  start_md TEXT NOT NULL,     -- window opens, 'MM-DD'
  end_md TEXT NOT NULL,       -- window closes, 'MM-DD' (may be earlier in the year than start = crosses New Year)
  lead_days INTEGER DEFAULT 21,
  who TEXT,                   -- family / person
  place TEXT,                 -- where (e.g. the pharmacy or shop you use)
  notes TEXT,
  active INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS seasonal_log (
  id INTEGER PRIMARY KEY,
  task_id INTEGER NOT NULL REFERENCES seasonal_tasks(id),
  done_date TEXT NOT NULL,
  place TEXT,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_seasonal_log_task ON seasonal_log(task_id, done_date);
""")
c.commit()
print("migration 006 ok;", c.execute("SELECT COUNT(*) FROM seasonal_tasks").fetchone()[0], "tasks")
