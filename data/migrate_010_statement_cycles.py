"""Apply migration 010 to data/family.db (idempotent): known statement billing cycles per card.

statement_cycles(account_id, period_start, period_end, source): one row per cycle, entered from the card issuer's
"recent statements" list. Cycles after the last known one are ESTIMATED by data/benefits.py (previous close + 1 month).
Add a row whenever a new statement closes. No rows are seeded.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS statement_cycles (
  id INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  period_start TEXT NOT NULL,
  period_end TEXT NOT NULL,
  source TEXT,
  UNIQUE(account_id, period_start)
);
""")
# No seed rows: statement_cycles are recorded per card as the family provides closing dates.
c.commit()
print("migration 010 ok;", c.execute("SELECT COUNT(*) FROM statement_cycles").fetchone()[0], "cycles")
