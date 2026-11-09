"""Apply migration 019 to data/family.db (idempotent): acknowledge / snooze store for action items.

action_state.key = stable hash of kind|title|date of an item from action_items.collect_items.
state: done (handled, hide it) | snoozed (hide until `until`) | ignored (hide for good).
Manage with data/action_state.py or the Action tab on the dashboard.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS action_state (
  key TEXT PRIMARY KEY,
  state TEXT NOT NULL,           -- done|snoozed|ignored
  until TEXT,                    -- ISO date, for snoozed
  title TEXT,                    -- snapshot for readability
  note TEXT,
  set_at TEXT DEFAULT CURRENT_TIMESTAMP
);
""")
c.commit()
print("migration 019 ok")
