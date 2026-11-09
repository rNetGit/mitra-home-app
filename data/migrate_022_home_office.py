"""Apply migration 022 to data/family.db (idempotent): home-office tax records.

home_office_profile : one row per tax year and person (who works from home): method, square feet, tests.
home_office_expenses: dated expenses that feed the regular-method calculation (and receipts for either method).
Records and arithmetic only; whether the deduction is allowed is for the user's tax preparer. Manage with data/home_office.py.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS home_office_profile (
  tax_year INTEGER NOT NULL,
  who TEXT NOT NULL,
  method TEXT DEFAULT 'simplified',      -- simplified|regular
  office_sqft REAL,
  home_sqft REAL,
  months_used INTEGER DEFAULT 12,        -- months the space qualified in the year
  exclusive_use INTEGER,                 -- 1/0/NULL: used ONLY for business
  regular_use INTEGER,                   -- 1/0/NULL: used on a regular basis
  principal_place INTEGER,               -- 1/0/NULL: principal place of business (or other qualifying use)
  self_employed INTEGER,                 -- 1/0/NULL: self-employed / business owner (not a W-2 employee)
  gross_income REAL,                     -- gross income from the business (limits the deduction)
  notes TEXT,
  PRIMARY KEY (tax_year, who)
);
CREATE TABLE IF NOT EXISTS home_office_expenses (
  id INTEGER PRIMARY KEY,
  tax_year INTEGER NOT NULL,
  who TEXT,
  category TEXT NOT NULL,                -- rent|mortgage_interest|property_tax|insurance|utilities|repairs|hoa|depreciation|internet|phone|supplies|equipment|other
  description TEXT,
  amount REAL NOT NULL,
  expense_date TEXT,
  direct INTEGER DEFAULT 0,              -- 1 = used only for the office (100% business), 0 = whole-home cost (gets the percentage)
  document_id INTEGER,
  notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_hoexp_year ON home_office_expenses(tax_year);
""")
c.commit()
print("migration 022 ok")
