"""Apply migration 009 to data/family.db (idempotent): recurring card benefits (statement credits).

card_benefits: one row per periodic credit on a card (e.g. a $10 monthly dining credit).
  qualify_pattern : SQL LIKE (on UPPER(description)) for purchases that trigger it, joined by '|'
  credit_pattern  : SQL LIKE for the statement-credit line that proves it was received
  reset_basis     : 'calendar_month' (default; many issuers reset monthly credits on the 1st) | 'statement'
Status per month is computed live from transactions (data/benefits.py). Nothing is cancelled or enrolled by the agent.
Only benefits visible in statements can be tracked: in-app credits (e.g. Uber Cash) never appear as statement lines.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS card_benefits (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  name TEXT NOT NULL,
  amount REAL NOT NULL,
  period TEXT DEFAULT 'monthly',            -- monthly | quarterly | semiannual | annual
  reset_basis TEXT DEFAULT 'calendar_month',
  qualify_pattern TEXT,
  credit_pattern TEXT,
  active INTEGER DEFAULT 1,
  notes TEXT,
  UNIQUE(account_id, name)
);
""")
# No seed rows: add a benefit per card with data/benefits.py once the card's statements are loaded.
c.commit()
print("migration 009 ok;", c.execute("SELECT COUNT(*) FROM card_benefits").fetchone()[0], "benefit(s)")
