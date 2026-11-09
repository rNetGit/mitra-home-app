"""Apply migration 024 to data/family.db (idempotent): review queue for files the Python pipeline would not guess about.

review_queue: one row per file moved to inbox/needs_review/ with the reason (low confidence, scanned PDF, statement,
unsupported type, validation failed). Resolved by a person or by the Claude intake agent. Manage with data/ai_intake.py.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS review_queue (
  id INTEGER PRIMARY KEY,
  path TEXT NOT NULL,            -- current location of the file (never deleted)
  reason TEXT NOT NULL,
  detail TEXT,                   -- what the model guessed, if anything (no document text)
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  resolved INTEGER DEFAULT 0
);
""")
c.commit()
print("migration 024 ok")
