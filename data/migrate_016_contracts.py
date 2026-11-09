"""Apply migration 016 to data/family.db (idempotent): contracts (work/engagement contracts with an end date).

One row per contract. Alerts `lead_days` before end_date (default 183 = about 6 months). Manage with data/contracts.py.
Contract numbers are business identifiers, not account numbers.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS contracts (
  id INTEGER PRIMARY KEY,
  person TEXT,                 -- who holds the contract (NULL = not set yet)
  client TEXT NOT NULL,        -- end client / agency
  vendor TEXT,                 -- staffing vendor or employer of record
  contract_no TEXT,
  start_date TEXT,
  end_date TEXT,               -- ISO date
  hourly_rate REAL,
  term_months INTEGER,
  lead_days INTEGER DEFAULT 183,
  status TEXT DEFAULT 'active',  -- active|renewed|ended
  notes TEXT
);
""")
c.commit()
print("migration 016 ok;", c.execute("SELECT COUNT(*) FROM contracts").fetchone()[0], "contracts")
