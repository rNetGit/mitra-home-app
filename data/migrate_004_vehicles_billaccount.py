"""Migration 004 - vehicles table + bills.account_id.

Two additions:

1. `bills.account_id` - bills could not reference the account they are paid from or
   owed on, so a bill had to name the card inside its text. Real FK instead.
2. `vehicles` - the three insured cars existed only as last4 inside policy_vehicles,
   which is policy-scoped and replaced every renewal term. A vehicle outlives its
   policy terms and carries its own dates (registration, inspection), so it needs its
   own row. policy_vehicles.vehicle_id links a term's rated vehicle to the real one.

Idempotent: safe to re-run.

Run:  python data/migrate_004_vehicles_billaccount.py
"""

import sqlite3
import os

import paths  # noqa: E402
DB = str(paths.DB)


def has_column(con, table, column):
    return any(r[1] == column for r in con.execute("PRAGMA table_info(%s)" % table))


VEHICLES_DDL = """
CREATE TABLE IF NOT EXISTS vehicles (
  id INTEGER PRIMARY KEY,
  year INTEGER,
  make TEXT,
  model TEXT,
  vin_last4 TEXT,                    -- last4 only; full VIN stays in the archived PDF
  plate_last4 TEXT,
  owner TEXT,
  primary_driver TEXT,
  registration_expires TEXT,         -- ISO date
  inspection_expires TEXT,           -- ISO date (annual safety/emissions inspection, where required)
  status TEXT DEFAULT 'active',      -- active|sold|totaled
  notes TEXT
)
"""


def main():
    if not os.path.exists(DB):
        raise SystemExit("family.db not found at %s" % DB)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    did = []
    try:
        con.execute(VEHICLES_DDL)
        con.execute("CREATE INDEX IF NOT EXISTS idx_vehicles_status ON vehicles(status)")
        did.append("vehicles table")

        if not has_column(con, "bills", "account_id"):
            con.execute("ALTER TABLE bills ADD COLUMN account_id INTEGER REFERENCES accounts(id)")
            did.append("bills.account_id")

        if not has_column(con, "policy_vehicles", "vehicle_id"):
            con.execute("ALTER TABLE policy_vehicles ADD COLUMN vehicle_id INTEGER REFERENCES vehicles(id)")
            did.append("policy_vehicles.vehicle_id")

        con.commit()
        print("migration 004 ok ->", ", ".join(did) if did else "nothing to do")
    finally:
        con.close()


if __name__ == "__main__":
    main()
