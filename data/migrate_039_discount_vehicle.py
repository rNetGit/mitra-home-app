"""Apply migration 039 to data/family.db (idempotent): which car a policy discount belongs to.

policy_discounts.vehicle_id -> policy_vehicles(id), NULL = a discount on the whole policy. policy_coverages already
has the same column (migration 003). Filled by data/doc_extract.py when a declarations page prints its coverages and
discounts per car, so a three-car policy shows each line once per car instead of an unexplained repeat.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = [r[1] for r in c.execute("PRAGMA table_info(policy_discounts)")]
if cols and "vehicle_id" not in cols:
    c.execute("ALTER TABLE policy_discounts ADD COLUMN vehicle_id INTEGER REFERENCES policy_vehicles(id)")
c.execute("CREATE INDEX IF NOT EXISTS ix_policy_coverages_vehicle ON policy_coverages(vehicle_id)")
c.commit()
print("migration 039 ok")
