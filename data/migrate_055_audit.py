"""Apply migration 055 to data/family.db (idempotent): the weekly data check (data/audit.py).

audit_runs      one row per check run: when, why (weekly | now), who asked, how many checks ran and passed, the score.
audit_findings  what each run found: check key, level (money | decide | note), one household line, detail, the row it is
                about (ref_table, ref_id) and `dedupe_key` (check:identity) so a finding can be followed across runs and,
                later, turned into an Inbox decision. Only ids, dates, short names and amounts: no account numbers.
Rows are kept for reporting (the score over time); a run never changes any other table.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS audit_runs (
  id INTEGER PRIMARY KEY,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  trigger TEXT NOT NULL CHECK (trigger IN ('weekly', 'now')),
  actor TEXT,
  checks_total INTEGER NOT NULL DEFAULT 0,
  checks_ok INTEGER NOT NULL DEFAULT 0,
  score INTEGER,                      -- 0..100, checks with nothing found / checks that ran
  errors TEXT                         -- check keys that could not run, comma separated
);
CREATE TABLE IF NOT EXISTS audit_findings (
  id INTEGER PRIMARY KEY,
  run_id INTEGER NOT NULL REFERENCES audit_runs(id) ON DELETE CASCADE,
  check_key TEXT NOT NULL,
  level TEXT NOT NULL CHECK (level IN ('money', 'decide', 'note')),
  dedupe_key TEXT NOT NULL,
  summary TEXT NOT NULL,
  detail TEXT,
  ref_table TEXT,
  ref_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_audit_findings_run ON audit_findings(run_id, level);
CREATE INDEX IF NOT EXISTS ix_audit_findings_key ON audit_findings(dedupe_key);
""")
c.commit()
print("migration 055 ok")
