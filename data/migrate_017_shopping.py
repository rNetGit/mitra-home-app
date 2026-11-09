"""Apply migration 017 to data/family.db (idempotent): shopping_items (named shopping lists with a target date).

Manage with data/shopping.py. No seed rows; add items with shopping.py add.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS shopping_items (
  id INTEGER PRIMARY KEY,
  list_name TEXT NOT NULL,
  item TEXT NOT NULL,
  target_date TEXT,            -- ISO date to have bought it by / sale date
  est_price REAL,
  store TEXT,
  status TEXT DEFAULT 'todo',  -- todo|bought|dropped
  bought_date TEXT,
  paid REAL,
  notes TEXT,
  UNIQUE(list_name, item)
);
""")
c.commit()
print("migration 017 ok;", c.execute("SELECT COUNT(*) FROM shopping_items").fetchone()[0], "items")
