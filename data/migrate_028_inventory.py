"""Apply migration 028 to data/family.db (idempotent): household inventory columns on home_assets.

Adds: location (room / where it is), manual_document_id (FK documents: the filed manual), status
(in_use | sold | disposed | lost, default in_use) and disposed_date. Rows that leave the household keep their history
(receipt, warranty, price) but drop out of the lists, the expiry reminders and the inventory value.
Manage with data/assets.py (add / set / attach / dispose / summary) or the dashboard Assets & inventory tab.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
have = {r[1] for r in c.execute("PRAGMA table_info(home_assets)")}
added = []
for col, ddl in [("location", "TEXT"), ("manual_document_id", "INTEGER REFERENCES documents(id)"),
                 ("status", "TEXT DEFAULT 'in_use'"), ("disposed_date", "TEXT")]:
    if col not in have:
        c.execute(f"ALTER TABLE home_assets ADD COLUMN {col} {ddl}")
        added.append(col)
c.execute("UPDATE home_assets SET status='in_use' WHERE status IS NULL")
c.execute("CREATE INDEX IF NOT EXISTS idx_home_assets_status ON home_assets(status)")
c.commit()
print("migration 028 ok;", ("added " + ", ".join(added)) if added else "columns already present", ";",
      c.execute("SELECT COUNT(*) FROM home_assets").fetchone()[0], "assets")
