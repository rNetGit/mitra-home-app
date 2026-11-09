"""Apply migration 050 to data/family.db (idempotent): critical information about each family member.

member_info: one row per fact (a label and a short value) under a category.
  category  emergency (who to call) | medical (allergies, medicines, doctor) | school (school, teacher, pickup) | other
  member    a family member's name (a pet's too); the sheet is for adults only
  label     what it is ("Allergies", "Paediatrician", "Mum: mobile"); a short phrase
  value     the fact itself, at most 200 characters. Never a password, PIN or full account / ID number; a diagnosis only as an adult typed it (PC only).
  verified_on  ISO date an adult last confirmed it is still right (the Records "Still correct" button); NULL = never
Stays on this PC: no sync trigger, never sent to the phone app, chat bots or an AI (see member_info.py).
Changes are logged in logs/edits.log by row id and field name, never the value.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS member_info (
  id INTEGER PRIMARY KEY,
  member TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'other' CHECK (category IN ('emergency', 'medical', 'school', 'other')),
  label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 60),
  value TEXT NOT NULL CHECK (length(value) BETWEEN 1 AND 200),
  verified_on TEXT CHECK (verified_on IS NULL OR verified_on GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dropped')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_member_info ON member_info(member, category, label) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_member_info_member ON member_info(member, status);
""")
c.commit()
print("migration 050 ok")
