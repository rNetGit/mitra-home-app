"""Apply migration 029 to data/family.db (idempotent): shared lists (lists + list_items).

Everyday lists the whole family uses (groceries, a Costco run, packing, Saturday jobs). Anyone signed in to the
dashboard adds and ticks items on family lists; adults also make, archive and drop. `audience='adults'` keeps a list
off the limited (kid / guest) screen. Nothing is deleted: dropped items are marked 'dropped', ticked items stay
'done' and are only hidden (cleared_at). `shopping_items` (the shopping pack: planned purchases with dates and prices)
is untouched. Seeds one empty "Groceries" list on a database that has no lists yet.
Manage with data/lists.py or the dashboard Family > Lists tab.
"""
import datetime as dt
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS lists (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(name) BETWEEN 1 AND 60),
  kind TEXT NOT NULL DEFAULT 'todo' CHECK (kind IN ('shopping','todo','packing')),
  audience TEXT NOT NULL DEFAULT 'family' CHECK (audience IN ('family','adults')),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  created_by TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS list_items (
  id INTEGER PRIMARY KEY,
  list_id INTEGER NOT NULL REFERENCES lists(id),
  text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 120),
  qty TEXT CHECK (qty IS NULL OR length(qty) <= 20),
  assigned_to TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','done','dropped')),
  added_by TEXT,
  added_at TEXT NOT NULL,
  done_by TEXT,
  done_at TEXT,
  cleared_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_list_items_open ON list_items(list_id, status);
""")
seeded = False
if not c.execute("SELECT COUNT(*) FROM lists").fetchone()[0]:
    c.execute("INSERT INTO lists(name, kind, audience, created_at) VALUES ('Groceries', 'shopping', 'family', ?)",
              (dt.datetime.now().isoformat(timespec="seconds"),))
    seeded = True
c.commit()
print("migration 029 ok;", c.execute("SELECT COUNT(*) FROM lists").fetchone()[0], "lists,",
      c.execute("SELECT COUNT(*) FROM list_items").fetchone()[0], "items" + ("; seeded Groceries" if seeded else ""))
