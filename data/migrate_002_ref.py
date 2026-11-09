"""Apply migration 002 to data/family.db (idempotent): transactions.ref.

Why: statement/activity exports can legitimately contain two rows with the same
(date, description, amount) -- e.g. two identical AMEX charges on the same day with
different reference numbers. Dedupe on those three fields alone is therefore unsafe.
`ref` holds the source system's reference/transaction id so re-imports can dedupe exactly.
"""
import sqlite3
import pathlib

import paths  # noqa: E402
db = paths.DB
c = sqlite3.connect(db)
cols = {r[1] for r in c.execute("PRAGMA table_info(transactions)")}
if "ref" not in cols:
    c.execute("ALTER TABLE transactions ADD COLUMN ref TEXT")
    print("added transactions.ref")
else:
    print("transactions.ref already present")
# Not UNIQUE: legacy rows have no ref, and not every source provides one.
c.execute("CREATE INDEX IF NOT EXISTS idx_transactions_ref ON transactions(ref)")
# CREATE TABLE/INDEX IF NOT EXISTS is a no-op for existing objects; refreshes views.
c.executescript(pathlib.Path(__file__).with_name("schema.sql").read_text())
c.commit()
print("migration 002 ok")
