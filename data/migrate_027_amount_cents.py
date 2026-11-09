"""Apply migration 027 to data/family.db (idempotent): integer-cent shadow columns for exact matching in SQL.

transactions.amount_cents and bills.amount_cents are VIRTUAL generated columns (SQLite 3.31+): always equal to
ROUND(amount * 100) as an integer, never stored, never written. They let dedupe and matching compare whole cents
(`WHERE amount_cents = ?`) instead of REAL values. Amounts themselves stay REAL in the family's currency
(see data/money.py for why), and every Python write rounds to the cent first.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
added = []
for table in ("transactions", "bills"):
    cols = {r[1] for r in c.execute(f"PRAGMA table_info({table})")} | {r[1] for r in c.execute(f"PRAGMA table_xinfo({table})")}
    if "amount_cents" not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN amount_cents INTEGER GENERATED ALWAYS AS "
                  f"(CAST(ROUND(COALESCE(amount, 0) * 100) AS INTEGER)) VIRTUAL")
        added.append(table)
c.commit()
print("migration 027 ok;", "added amount_cents to " + ", ".join(added) if added else "amount_cents already present")
