"""Apply migration 020 to data/family.db (idempotent): life_items, one table for the rest of family life.

domain: school | activity | medical | prescription | vaccine | pet | legal | travel | gift | chore | other
An item with a due_date raises alerts `lead_days` ahead; with recur_months it rolls forward when marked done.
No due_date = "needs a date" (shown in the family digest). Manage with data/life.py.
Medical/legal notes: keep identifiers last4 only; do not store diagnoses or full policy numbers.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS life_items (
  id INTEGER PRIMARY KEY,
  domain TEXT NOT NULL,
  member TEXT,                   -- canonical member name or NULL = whole household
  title TEXT NOT NULL,
  due_date TEXT,                 -- ISO date
  recur_months INTEGER,          -- NULL = one-off
  lead_days INTEGER DEFAULT 14,
  amount REAL,                   -- fee / cost if any
  status TEXT DEFAULT 'open',    -- open|done|dropped
  last_done TEXT,
  provider TEXT,                 -- school, clinic, vet, camp...
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_life_status ON life_items(status, due_date);
""")
c.commit()
print("migration 020 ok;", c.execute("SELECT COUNT(*) FROM life_items").fetchone()[0], "items")
