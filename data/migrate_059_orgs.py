"""Apply migration 059 to data/family.db (idempotent): the school, college or employer each person belongs to, and
where its year calendar comes from.

orgs: one row per school, college or employer the family linked (Family > edit a person).
  kind           school | college | employer
  name           public name ("Lincoln Middle School"); district = the school district's name (public schools)
  ext_id         the public directory id (NCES school id, private school id or IPEDS unit id), NULL when typed by hand
  city, state    where it is (public directory facts, never the family's address)
  calendar_url   the public page or file the year calendar was read from (http(s)); calendar_year "2026-27"
  checked_at     when the calendar was last looked up or imported
members.org_id     the person's school, college or employer (members.school keeps the name as shown)
calendar_days.org_id  the org a proposed / accepted day came from, so a new year's import replaces only its own rows
Stays on this PC: no sync trigger, not in the phone API.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS orgs (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('school', 'college', 'employer')),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 100),
  ext_id TEXT CHECK (ext_id IS NULL OR length(ext_id) <= 20),
  district TEXT CHECK (district IS NULL OR length(district) <= 100),
  city TEXT CHECK (city IS NULL OR length(city) <= 60),
  state TEXT CHECK (state IS NULL OR length(state) <= 20),
  calendar_url TEXT CHECK (calendar_url IS NULL OR (length(calendar_url) <= 2000
                           AND (calendar_url LIKE 'http://%' OR calendar_url LIKE 'https://%'))),
  calendar_year TEXT CHECK (calendar_year IS NULL OR length(calendar_year) <= 9),
  checked_at TEXT,
  created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%S', 'now', 'localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_orgs ON orgs(kind, name, IFNULL(city, ''), IFNULL(state, ''));
""")
for table in ("members", "calendar_days"):
    cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}
    if cols and "org_id" not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN org_id INTEGER REFERENCES orgs(id) ON DELETE SET NULL")
c.commit()
print("migration 059 ok")
