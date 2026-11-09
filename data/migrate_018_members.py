"""Apply migration 018 to data/family.db (idempotent): household members.

members: one row per person, mirrored from config/family.json (`python data/members.py sync`).
`who` columns elsewhere stay free text, but members.resolve() maps any spelling/case to the canonical name.
birth_year is optional (used for "turns N"); birth_month_day is MM-DD.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  role TEXT DEFAULT 'adult',       -- adult|child|pet
  birth_month_day TEXT,            -- MM-DD
  birth_year INTEGER,
  notes TEXT
);
""")
c.commit()
print("migration 018 ok;", c.execute("SELECT COUNT(*) FROM members").fetchone()[0], "members")
