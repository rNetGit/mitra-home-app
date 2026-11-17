"""Apply migration 072 to data/family.db (idempotent): who an event is for and what kind it is.

events.category     'General', 'Family', 'Business', 'Volunteer' ... a short label (the household can add its own,
                    kept in family.json event_categories); NULL = no label
events.member       the person it is for; NULL = the whole family
events.adults_only  1 = only adults see it (not a child's page, the Mitra Wall or a child's phone); default 0
Events made before stay as they were: whole family, no label, everyone sees them.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(events)")}
if cols and "category" not in cols:
    c.execute("ALTER TABLE events ADD COLUMN category TEXT")
if cols and "member" not in cols:
    c.execute("ALTER TABLE events ADD COLUMN member TEXT")
if cols and "adults_only" not in cols:
    c.execute("ALTER TABLE events ADD COLUMN adults_only INTEGER NOT NULL DEFAULT 0 CHECK (adults_only IN (0,1))")
c.commit()
print("migration 072 ok")
