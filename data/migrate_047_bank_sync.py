"""Apply migration 047 to data/family.db (idempotent): which SimpleFIN account an `accounts` row is synced from.

accounts.simplefin_id (TEXT, NULL = not synced). Set by data/bank_sync.py when the family ticks an account for the
daily pull, cleared by `bank_sync.py forget`. The SimpleFIN id is an opaque string from the bridge, not an account
number; the access URL itself never goes into the database (config/secrets.env only).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = [r[1] for r in c.execute("PRAGMA table_info(accounts)")]
if cols and "simplefin_id" not in cols:
    c.execute("ALTER TABLE accounts ADD COLUMN simplefin_id TEXT")
c.commit()
print("migration 047 ok")
