"""Apply migration 048 to data/family.db (idempotent): weekly activity schedules.

activity_schedules: one row per class, sport, lesson or club that repeats every week (swimming Mon + Wed 17:00 at the
YMCA, piano Sat 10:00). member NULL = the whole household. weekdays = two-letter codes joined by commas ("MO,WE").
start_time / end_time are HH:MM (local time) or NULL. term_start / term_end bound the season (NULL = open). skip_dates
= ISO dates joined by commas (a cancelled lesson). school_days = 1: the class does not run on a school closure day
(calendar_days, migration 049). Never deleted: ending a schedule sets status 'ended'. Only the title, the provider's
name, days and times are kept: no addresses, phone numbers or notes about the child. Filled by data/activities.py and
the Records form (edit_actions.activity_*).
"""
import sqlite3

DATE = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"
TIME = "GLOB '[0-2][0-9]:[0-5][0-9]'"

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS activity_schedules (
  id INTEGER PRIMARY KEY,
  member TEXT,
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 80),
  provider TEXT CHECK (provider IS NULL OR length(provider) <= 80),
  weekdays TEXT NOT NULL CHECK (length(weekdays) BETWEEN 2 AND 20),
  start_time TEXT CHECK (start_time IS NULL OR start_time {TIME}),
  end_time TEXT CHECK (end_time IS NULL OR end_time {TIME}),
  term_start TEXT CHECK (term_start IS NULL OR term_start {DATE}),
  term_end TEXT CHECK (term_end IS NULL OR term_end {DATE}),
  skip_dates TEXT NOT NULL DEFAULT '',
  school_days INTEGER NOT NULL DEFAULT 0 CHECK (school_days IN (0, 1)),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'ended')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_activity_status ON activity_schedules(status, member);
""")
import sync_data  # noqa: E402
sync_data.ensure_triggers(c)
c.commit()
print("migration 048 ok")
