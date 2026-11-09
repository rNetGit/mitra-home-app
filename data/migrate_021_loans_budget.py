"""Apply migration 021 to data/family.db (idempotent): loans and monthly budget.

loans  : mortgage / auto / student / personal / HELOC. Account number as last4 only.
budget : one row per category with a monthly limit; compared with `transactions.category` by data/budget.py.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS loans (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  lender TEXT,
  kind TEXT,                     -- mortgage|auto|student|personal|heloc|other
  last4 TEXT,
  balance REAL,                  -- latest known principal
  balance_date TEXT,
  rate_pct REAL,
  payment REAL,                  -- regular payment
  payment_day INTEGER,           -- day of month
  start_date TEXT,
  payoff_date TEXT,              -- scheduled payoff / maturity
  status TEXT DEFAULT 'active',  -- active|paid_off
  notes TEXT
);
CREATE TABLE IF NOT EXISTS budget (
  category TEXT PRIMARY KEY,
  monthly_limit REAL NOT NULL,
  notes TEXT
);
""")
c.commit()
print("migration 021 ok")
