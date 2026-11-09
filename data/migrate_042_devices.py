"""Apply migration 042 to data/family.db (idempotent): paired phones.

devices: one row per phone paired in Settings > Phones: its name, the family member it belongs to, the role at pairing
(the live role is checked on every request), what it may see (`scopes`, comma-separated keys from data/devices.py)
and the SHA-256 of its access token (the token itself lives only on the phone). Revoking keeps the row (revoked_at), so
a revoked phone can be told to wipe its copy.
device_pairings: one-time pairing codes behind the QR code. Only the SHA-256 of the secret is stored; a code works
once, for a few minutes.
"""
import sqlite3

TS = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]*'"
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS devices (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
  member TEXT NOT NULL CHECK (length(member) BETWEEN 1 AND 60),
  role TEXT NOT NULL CHECK (role IN ('adult','limited')),
  scopes TEXT NOT NULL DEFAULT '' CHECK (length(scopes) <= 200),
  token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  created_by TEXT,
  last_seen TEXT CHECK (last_seen IS NULL OR last_seen {TS}),
  revoked_at TEXT CHECK (revoked_at IS NULL OR revoked_at {TS})
);
CREATE TABLE IF NOT EXISTS device_pairings (
  id INTEGER PRIMARY KEY,
  secret_hash TEXT NOT NULL UNIQUE CHECK (length(secret_hash) = 64),
  member TEXT NOT NULL CHECK (length(member) BETWEEN 1 AND 60),
  role TEXT NOT NULL CHECK (role IN ('adult','limited')),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
  scopes TEXT NOT NULL DEFAULT '' CHECK (length(scopes) <= 200),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  created_by TEXT,
  expires_at TEXT NOT NULL CHECK (expires_at {TS}),
  used_at TEXT CHECK (used_at IS NULL OR used_at {TS}),
  device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL
);
""")
c.commit()
print("migration 042 ok;", c.execute("SELECT COUNT(*) FROM devices WHERE revoked_at IS NULL").fetchone()[0], "paired phone(s)")
