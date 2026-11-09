"""Apply migration 056 to data/family.db (idempotent): fixes from the data check, and what each one needs to be undone.

audit_findings.payload  JSON arguments for the fix a person can accept in the Inbox (proposals source `audit`): which
                        rows are the duplicates, which bill is still open. Ids only.
audit_fixes             one row per fix the data check made (by itself for the safe kinds, or after a person accepted it):
                        action, one household line, `undo` = JSON with the rows as they were (removed rows in full,
                        moved links, old categories) so Settings > Data > Data check can put them back; done_by is
                        'auto' or the person; undone_at / undone_by once undone.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(audit_findings)")}
if cols and "payload" not in cols:
    c.execute("ALTER TABLE audit_findings ADD COLUMN payload TEXT")
c.executescript("""
CREATE TABLE IF NOT EXISTS audit_fixes (
  id INTEGER PRIMARY KEY,
  run_id INTEGER REFERENCES audit_runs(id) ON DELETE SET NULL,
  dedupe_key TEXT,
  action TEXT NOT NULL,               -- remove_txns | remove_bills | categorize
  summary TEXT NOT NULL,
  undo TEXT NOT NULL,                 -- JSON, see audit_fix.py
  done_by TEXT NOT NULL,              -- 'auto' or the person's name
  done_at TEXT NOT NULL,
  undone_at TEXT,
  undone_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_audit_fixes_done ON audit_fixes(done_at);
""")
c.commit()
print("migration 056 ok")
