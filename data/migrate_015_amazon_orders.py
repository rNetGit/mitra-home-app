"""Apply migration 015 to data/family.db (idempotent): Amazon order history.

`amazon_orders`: one row per order from the archived Amazon 'Your Orders' PDFs
(data/import_amazon_orders.py). order_no is an Amazon order number (not an account number).
ship_to holds a first name only. transaction_id/match_* are filled by data/amazon_match.py.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.execute("""CREATE TABLE IF NOT EXISTS amazon_orders (
  id INTEGER PRIMARY KEY,
  order_no TEXT NOT NULL,
  order_date TEXT NOT NULL,           -- ISO
  total REAL NOT NULL,                -- USD, positive
  ship_to TEXT,                       -- first name only
  status TEXT CHECK (status IN ('delivered','returned','refunded','cancelled','digital','gift_card','other')),
  items TEXT,                         -- item titles joined by ' | ', each shortened to ~80 chars
  document_id INTEGER REFERENCES documents(id),
  transaction_id INTEGER REFERENCES transactions(id),
  match_confidence TEXT,              -- high|medium|low|none
  match_note TEXT,
  UNIQUE(order_no)
)""")
c.execute("CREATE INDEX IF NOT EXISTS idx_amazon_orders_date ON amazon_orders(order_date)")
c.commit()
print("migration 015 ok;", c.execute("SELECT COUNT(*) FROM amazon_orders").fetchone()[0], "amazon_orders")
