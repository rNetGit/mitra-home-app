"""Apply migration 067 to data/family.db (idempotent): remembered words that tell which job a timesheet belongs to.

work_match_rules  pattern (3-60 characters, lower case: a company name or other words printed on that job's timesheets)
                  and the job (contracts row) it points to. Set when a person answers "Which job?" in the Inbox.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS work_match_rules (
  id INTEGER PRIMARY KEY,
  pattern TEXT NOT NULL UNIQUE CHECK (length(pattern) BETWEEN 3 AND 60),
  contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  created_at TEXT
);
""")
c.commit()
print("migration 067 ok")
