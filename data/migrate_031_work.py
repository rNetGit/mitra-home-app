"""Apply migration 031 to data/family.db (idempotent): work profile, hours, work calendar and invoices.

For adults who bill their time (self-employed, consultants, contractors). Builds on `contracts` (migration 016):
  contracts      + invoice_freq (weekly|biweekly|semimonthly|monthly), timesheet_cycle (weekly|biweekly),
                   cycle_anchor (first day of one timesheet cycle), hours_per_day, schedule (one letter per day of the
                   cycle from cycle_anchor: O on site, H home / off site, W working (place not set), - not working),
                   work_calendar (name of the calendar in work_calendar whose holidays apply).
  work_hours     one row per contract and day: hours, on/off site, where the number came from. No names, no IDs.
  work_calendar  holidays, floating holidays, pay days and closures, by calendar name (an employer's or client's year).
  work_invoices  one row per billed period: hours x rate, draft / sent / paid.
Records only; nothing is sent to anyone. Manage with data/work.py or the dashboard Work tab.
"""
import sqlite3

DATE = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
have = {r[1] for r in c.execute("PRAGMA table_info(contracts)")}
if not have:  # migration 016 not applied (should not happen: migrate.py runs them in order)
    raise SystemExit("migration 031 needs the contracts table (migration 016)")
for col, decl in (("invoice_freq", "TEXT"), ("timesheet_cycle", "TEXT"), ("cycle_anchor", "TEXT"),
                  ("hours_per_day", "REAL"), ("schedule", "TEXT"), ("work_calendar", "TEXT")):
    if col not in have:
        c.execute(f"ALTER TABLE contracts ADD COLUMN {col} {decl}")
c.executescript(f"""
CREATE TABLE IF NOT EXISTS work_hours (
  id INTEGER PRIMARY KEY,
  contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  work_date TEXT NOT NULL CHECK (work_date {DATE}),
  hours REAL NOT NULL CHECK (hours >= 0 AND hours <= 24),
  location TEXT CHECK (location IS NULL OR location IN ('onsite','offsite')),
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('timesheet','manual','schedule')),
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  updated_at TEXT,
  UNIQUE (contract_id, work_date)
);
CREATE TABLE IF NOT EXISTS work_calendar (
  id INTEGER PRIMARY KEY,
  calendar TEXT NOT NULL CHECK (length(calendar) BETWEEN 1 AND 60),
  day TEXT NOT NULL CHECK (day {DATE}),
  kind TEXT NOT NULL CHECK (kind IN ('holiday','floating','payday','closure')),
  name TEXT CHECK (name IS NULL OR length(name) <= 80),
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  UNIQUE (calendar, day, kind)
);
CREATE TABLE IF NOT EXISTS work_invoices (
  id INTEGER PRIMARY KEY,
  contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  period_start TEXT NOT NULL CHECK (period_start {DATE}),
  period_end TEXT NOT NULL CHECK (period_end {DATE}),
  hours REAL NOT NULL CHECK (hours >= 0),
  rate REAL,
  amount REAL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','paid')),
  created_at TEXT NOT NULL,
  sent_on TEXT CHECK (sent_on IS NULL OR sent_on {DATE}),
  paid_on TEXT CHECK (paid_on IS NULL OR paid_on {DATE}),
  notes TEXT CHECK (notes IS NULL OR length(notes) <= 300),
  UNIQUE (contract_id, period_start, period_end)
);
CREATE INDEX IF NOT EXISTS idx_work_hours_date ON work_hours(work_date);
CREATE INDEX IF NOT EXISTS idx_work_calendar_day ON work_calendar(day);
""")
c.commit()
print("migration 031 ok;", c.execute("SELECT COUNT(*) FROM work_hours").fetchone()[0], "work hour rows")
