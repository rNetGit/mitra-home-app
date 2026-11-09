"""Apply migration 037 to data/family.db (idempotent): one queue of things the agent wants a person to decide.

proposals: one row per file to review, recurring payment to decide, statement to drop, price rise, or question
(a checkup with no date). Filled by data/proposals.py sync from the existing detectors (no AI); shown in the Inbox.
`dedupe_key` keeps each item to one row across syncs; status open | snoozed | done | dismissed | expired.
`payload` holds only the arguments a fixed handler in data/proposals.py needs (never an action name or a command).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY,
  dedupe_key TEXT NOT NULL UNIQUE,   -- source:identity, e.g. review:12, recurring:city water, undated:7
  source TEXT NOT NULL,              -- review | recurring | statement | price_rise | undated
  kind TEXT NOT NULL CHECK (kind IN ('file', 'decision', 'question')),
  summary TEXT NOT NULL,             -- one line in household language
  detail TEXT,
  payload TEXT,                      -- JSON arguments for the source's handler
  ref_table TEXT,
  ref_id INTEGER,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'snoozed', 'done', 'dismissed', 'expired')),
  until TEXT,                        -- ISO date, for snoozed
  outcome TEXT,                      -- the option a person chose
  decided_by TEXT,
  decided_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_proposals_status ON proposals(status, kind);
""")
c.commit()
print("migration 037 ok")
