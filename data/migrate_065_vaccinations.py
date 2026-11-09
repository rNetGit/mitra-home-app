"""Apply migration 065 to data/family.db (idempotent): vaccination history for people and pets (data/health_records.py).

vaccinations: one row per shot given, so the record of what was given and when outlives the reminder.
  member       whose shot (members.name, a pet too); never NULL
  vaccine      "MMR", "Flu", "Rabies" (1-60 characters); a name only, no lot numbers, no diagnoses
  given_on     ISO date the shot was given
  next_due     ISO date of the next one or NULL; a date here also keeps ONE open life_items row (domain vaccine) so the
               reminder reaches Today, the Calendar and the weekly digest through the code that already reads life_items
  provider     clinic or vet (at most 80)
  notes        short free text (at most 200); no diagnoses
  life_item_id the open reminder row, or NULL
Never deleted: removing a row sets status 'dropped'. Records only, not medical advice.
"""
import sqlite3

DATE = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS vaccinations (
  id INTEGER PRIMARY KEY,
  member TEXT NOT NULL,
  vaccine TEXT NOT NULL CHECK (length(vaccine) BETWEEN 1 AND 60),
  given_on TEXT NOT NULL CHECK (given_on {DATE}),
  next_due TEXT CHECK (next_due IS NULL OR next_due {DATE}),
  provider TEXT CHECK (provider IS NULL OR length(provider) <= 80),
  notes TEXT CHECK (notes IS NULL OR length(notes) <= 200),
  life_item_id INTEGER REFERENCES life_items(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dropped')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_vaccinations_member ON vaccinations(member, status, given_on);
""")
c.commit()
print("migration 065 ok")
