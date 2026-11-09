"""Apply migration 033 to data/family.db (idempotent): chat links for the phone bots (Telegram, Discord).

chat_links: which chat account belongs to which family member, with the role the bot uses (adult = everything,
limited = children and teens: no money, same rules as the limited dashboard). One live link per chat account;
revoking keeps the row (revoked_at) so the log still makes sense.
chat_invites: one-time pairing codes made on this PC by an adult (`python data/chat_core.py invite NAME`). Only the
SHA-256 of the code is stored; a code works once, before it expires.
chat_log: one row per message the bots answered or refused: who, which command, the outcome. Never the text.
"""
import sqlite3

TS = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]*'"
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS chat_links (
  id INTEGER PRIMARY KEY,
  platform TEXT NOT NULL CHECK (platform IN ('telegram','discord')),
  platform_user_id TEXT NOT NULL CHECK (length(platform_user_id) BETWEEN 1 AND 40),
  member TEXT NOT NULL CHECK (length(member) BETWEEN 1 AND 60),
  role TEXT NOT NULL CHECK (role IN ('adult','limited')),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  revoked_at TEXT CHECK (revoked_at IS NULL OR revoked_at {TS})
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_links_live ON chat_links(platform, platform_user_id) WHERE revoked_at IS NULL;
CREATE TABLE IF NOT EXISTS chat_invites (
  id INTEGER PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE CHECK (length(code_hash) = 64),
  member TEXT NOT NULL CHECK (length(member) BETWEEN 1 AND 60),
  role TEXT NOT NULL CHECK (role IN ('adult','limited')),
  platform TEXT CHECK (platform IS NULL OR platform IN ('telegram','discord')),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  expires_at TEXT NOT NULL CHECK (expires_at {TS}),
  used_at TEXT CHECK (used_at IS NULL OR used_at {TS})
);
CREATE TABLE IF NOT EXISTS chat_log (
  id INTEGER PRIMARY KEY,
  at TEXT NOT NULL CHECK (at {TS}),
  platform TEXT NOT NULL CHECK (platform IN ('telegram','discord')),
  platform_user_id TEXT NOT NULL,
  member TEXT,
  command TEXT NOT NULL CHECK (length(command) BETWEEN 1 AND 20),
  outcome TEXT NOT NULL CHECK (outcome IN ('ok','denied','unknown_user','bad_code','linked','throttled','error'))
);
CREATE INDEX IF NOT EXISTS idx_chat_log_user ON chat_log(platform, platform_user_id, at);
""")
c.commit()
print("migration 033 ok;", c.execute("SELECT COUNT(*) FROM chat_links WHERE revoked_at IS NULL").fetchone()[0], "chat links")
