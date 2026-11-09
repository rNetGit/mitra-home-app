"""Apply migration 012 to data/family.db (idempotent): warranty & receipt tracking on home_assets.

Adds: store, price, serial_last4, receipt_document_id (FK documents.id), warranty_years, vehicle_id (FK vehicles).
Manage with data/assets.py (list / add / attach / warranty).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
have = {r[1] for r in c.execute("PRAGMA table_info(home_assets)")}
for col, ddl in [("store", "TEXT"), ("price", "REAL"), ("serial_last4", "TEXT"),
                 ("receipt_document_id", "INTEGER REFERENCES documents(id)"),
                 ("warranty_years", "REAL"), ("vehicle_id", "INTEGER REFERENCES vehicles(id)")]:
    if col not in have:
        c.execute(f"ALTER TABLE home_assets ADD COLUMN {col} {ddl}")
c.commit()
print("migration 012 ok;", c.execute("SELECT COUNT(*) FROM home_assets").fetchone()[0], "assets")
