"""Apply migration 052 to data/family.db (idempotent): the people and businesses the household has had work done by.

home_contacts: one row per plumber, furnace company, garage, electrician, handyman ...
  name       the business or the person ("Acme Plumbing", "Joe the handyman"), 1-80 characters
  trade      plumbing | electrical | heating_cooling | garage_door | auto | appliance | roofing | handyman | landscaping |
             pest | cleaning | painting | locksmith | pool | other
  phone, email, website  how to reach them (a business line; website http(s) only)
  notes      what they did, prices, who to ask for; at most 300 characters
  last_used  ISO date of the last job (the upkeep log also counts: recurring_log.provider = name)
  rating     1-5 or NULL;  again: 1 = would use again, 0 = would not, NULL = not said
Stays on this PC: no sync trigger, not readable through ask_sql. Changes are logged by row id and field name only.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS home_contacts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 80),
  trade TEXT NOT NULL DEFAULT 'other' CHECK (trade IN ('plumbing', 'electrical', 'heating_cooling', 'garage_door', 'auto',
    'appliance', 'roofing', 'handyman', 'landscaping', 'pest', 'cleaning', 'painting', 'locksmith', 'pool', 'other')),
  phone TEXT CHECK (phone IS NULL OR length(phone) <= 30),
  email TEXT CHECK (email IS NULL OR length(email) <= 120),
  website TEXT CHECK (website IS NULL OR (length(website) <= 200 AND (website LIKE 'http://%' OR website LIKE 'https://%'))),
  notes TEXT CHECK (notes IS NULL OR length(notes) <= 300),
  last_used TEXT CHECK (last_used IS NULL OR last_used GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
  rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
  again INTEGER CHECK (again IS NULL OR again IN (0, 1)),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dropped')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_home_contacts ON home_contacts(name, trade) WHERE status = 'active';
CREATE INDEX IF NOT EXISTS ix_home_contacts_trade ON home_contacts(trade, status);
""")
c.commit()
print("migration 052 ok")
