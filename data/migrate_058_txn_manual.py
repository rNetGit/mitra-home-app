"""Apply migration 058 to data/family.db (idempotent): a line a person changed by hand is kept that way.

transactions.manual  1 = its category or type was set by a person (Money > Ledger); the category rules, the transfer pairing
                     and the data check's category fill never overwrite it. 0 for every line until then.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(transactions)")}
if cols and "manual" not in cols:
    c.execute("ALTER TABLE transactions ADD COLUMN manual INTEGER NOT NULL DEFAULT 0")
c.commit()
print("migration 058 ok")
