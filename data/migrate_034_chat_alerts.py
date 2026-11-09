"""Apply migration 034 to data/family.db (idempotent): daily chat alerts opt-in.

chat_links.alerts = 1 when that person asked for a daily private message from the bot (`/alerts on` in a private
chat, or `python data/chat_core.py alerts NAME on`). Off by default. What the message holds follows the role:
adults get bills with amounts, children only their own items (see data/chat_alerts.py).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(chat_links)")}
if "alerts" not in cols:
    c.execute("ALTER TABLE chat_links ADD COLUMN alerts INTEGER NOT NULL DEFAULT 0 CHECK (alerts IN (0,1))")
c.commit()
print("migration 034 ok;", c.execute("SELECT COUNT(*) FROM chat_links WHERE alerts=1 AND revoked_at IS NULL").fetchone()[0],
      "people get daily alerts")
