"""Apply migration 038 to data/family.db (idempotent): the drivers listed on an auto policy.

policy_drivers: one row per driver printed on a declarations page (name, relation to the policyholder, excluded or
not). Filled by data/doc_extract.py when the inbox reads a policy with any AI provider. No licence numbers, no dates
of birth: the archived PDF keeps those.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS policy_drivers (
  id INTEGER PRIMARY KEY,
  policy_id INTEGER NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
  name TEXT NOT NULL,                -- member name when it matches one, else as printed
  relation TEXT,                     -- named insured | spouse | child | other
  excluded INTEGER DEFAULT 0         -- 1 = listed as an excluded driver
);
CREATE INDEX IF NOT EXISTS ix_policy_drivers_policy ON policy_drivers(policy_id);
""")
c.commit()
print("migration 038 ok")
