"""Apply migration 007 to data/family.db (idempotent): balances, recurring items, home assets.

account_balances : statement-end / snapshot balance per account. `balance` is as REPORTED:
                   credit cards and loans = amount owed (positive); bank/investment = amount held.
                   v_balance_latest signs it for net worth (liabilities negative).
recurring_items  : repeating non-seasonal tasks on an interval (health checkups, home maintenance).
                   next_due = last_done + interval_months (computed in the app); NULL last_done = "needs a date".
recurring_log    : each completion.
home_assets      : appliances/systems with purchase and warranty dates.
Manage recurring items with data/recurring.py (list / done / add / set).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS account_balances (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  as_of TEXT NOT NULL,                 -- ISO date (statement closing date or snapshot date)
  balance REAL NOT NULL,               -- as reported (cards/loans: owed, positive)
  kind TEXT DEFAULT 'statement_end',   -- statement_end | snapshot
  document_id INTEGER REFERENCES documents(id),
  notes TEXT,
  UNIQUE(account_id, as_of, kind)
);
CREATE INDEX IF NOT EXISTS idx_balances_acct ON account_balances(account_id, as_of);

CREATE TABLE IF NOT EXISTS recurring_items (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT,                       -- Health|Home|Car|School|Admin
  who TEXT,                            -- member name|Family|Home
  interval_months INTEGER NOT NULL,
  last_done TEXT,                      -- ISO date, NULL = unknown
  provider TEXT,
  notes TEXT,
  active INTEGER DEFAULT 1,
  UNIQUE(name, who)
);
CREATE TABLE IF NOT EXISTS recurring_log (
  id INTEGER PRIMARY KEY,
  item_id INTEGER NOT NULL REFERENCES recurring_items(id),
  done_date TEXT NOT NULL,
  provider TEXT,
  notes TEXT
);
CREATE TABLE IF NOT EXISTS home_assets (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  category TEXT,                       -- appliance|hvac|roof|plumbing|electrical|vehicle|other
  brand_model TEXT,
  purchase_date TEXT,
  warranty_end TEXT,
  notes TEXT
);

DROP VIEW IF EXISTS v_balance_latest;
CREATE VIEW v_balance_latest AS
SELECT b.account_id, a.name, a.type, a.last4, a.owner, b.as_of, b.balance,
       CASE WHEN a.type IN ('credit','loan') THEN -b.balance ELSE b.balance END AS signed_balance
FROM account_balances b JOIN accounts a ON a.id=b.account_id
WHERE b.as_of=(SELECT MAX(x.as_of) FROM account_balances x WHERE x.account_id=b.account_id);
""")

R = []
for who in ():  # per-member health items are seeded by onboard.py
    R += [("Annual physical", "Health", who, 12), ("Dental cleaning", "Health", who, 6),
          ("Eye exam", "Health", who, 12)]
R += [
 ("Furnace filter change", "Home", "Home", 3, "Or per filter rating; heavy use in winter."),
 ("Fridge water filter", "Home", "Home", 6, ""),
 ("Water heater flush", "Home", "Home", 12, "Drain a few gallons to clear sediment."),
 ("Dryer vent cleaning", "Home", "Home", 12, "Fire safety."),
 ("Test GFCI outlets + garage door safety reverse", "Home", "Home", 12, ""),
 ("Check fire extinguishers", "Home", "Home", 12, "Pressure gauge in green, not expired."),
 ("Replace smoke/CO detectors if 10 years old", "Home", "Home", 12, "Check the date printed on each unit."),
]
for r in R:
    name, cat, who, iv = r[:4]
    notes = r[4] if len(r) > 4 else ""
    c.execute("INSERT OR IGNORE INTO recurring_items(name,category,who,interval_months,notes) VALUES(?,?,?,?,?)",
              (name, cat, who, iv, notes))
c.commit()
print("migration 007 ok;", c.execute("SELECT COUNT(*) FROM recurring_items").fetchone()[0], "recurring items")
