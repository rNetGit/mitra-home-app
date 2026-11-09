"""Apply migration 040 to data/family.db (idempotent): phone bills per line.

mobile_bills: one row per carrier invoice (account last4, period, bill date, due date, printed total, the account-wide
charges and credits). mobile_bill_lines: one row per phone line (name as printed, device, phone last4, the five printed
sections, the line total, the line's equal share of the account-wide amount, and the net = what that person's phone cost).
mobile_bill_items: the printed items under each section (line_id NULL = an account-wide item). Filled by
data/mobile_bill.py, without AI, only when the bill adds up to the cent. Call logs are never stored.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS mobile_bills (
  id INTEGER PRIMARY KEY,
  carrier TEXT NOT NULL,
  account_last4 TEXT,
  invoice TEXT NOT NULL,
  bill_date TEXT NOT NULL,
  period_start TEXT,
  period_end TEXT,
  due_date TEXT,
  total_due REAL,
  bill_total REAL NOT NULL,
  account_wide REAL NOT NULL DEFAULT 0,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  UNIQUE (carrier, invoice)
);
CREATE TABLE IF NOT EXISTS mobile_bill_lines (
  id INTEGER PRIMARY KEY,
  bill_id INTEGER NOT NULL REFERENCES mobile_bills(id) ON DELETE CASCADE,
  person TEXT NOT NULL,              -- the name printed on the bill
  member TEXT,                       -- members.name when it matches one
  device TEXT,
  phone_last4 TEXT,
  plan REAL DEFAULT 0,
  devices REAL DEFAULT 0,
  perks REAL DEFAULT 0,
  surcharges REAL DEFAULT 0,
  taxes REAL DEFAULT 0,
  other REAL DEFAULT 0,
  line_total REAL NOT NULL,
  account_share REAL NOT NULL DEFAULT 0,
  net REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mobile_bill_items (
  id INTEGER PRIMARY KEY,
  bill_id INTEGER NOT NULL REFERENCES mobile_bills(id) ON DELETE CASCADE,
  line_id INTEGER REFERENCES mobile_bill_lines(id) ON DELETE CASCADE,
  section TEXT NOT NULL,             -- plan | devices | perks | surcharges | taxes | other | account
  label TEXT NOT NULL,
  amount REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mobile_lines_bill ON mobile_bill_lines(bill_id);
CREATE INDEX IF NOT EXISTS ix_mobile_items_line ON mobile_bill_items(line_id);
CREATE INDEX IF NOT EXISTS ix_mobile_bills_date ON mobile_bills(bill_date);
""")
c.commit()
print("migration 040 ok")
