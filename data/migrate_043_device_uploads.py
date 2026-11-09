"""Apply migration 043 to data/family.db (idempotent): files sent by paired phones.

device_uploads: one row per file a phone sent to `POST /api/upload` that was saved into inbox/ or recognised as an exact
copy of a paper already here. `client_id` is the phone's own id for that send, so a phone that retries after a dropped
connection gets the first answer back instead of a second copy (UNIQUE per phone). `sha256` is the file's hash; the
file name is the one saved in inbox/ (nothing of the content). Removing a phone removes its rows.
"""
import sqlite3

TS = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]*'"
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS device_uploads (
  id INTEGER PRIMARY KEY,
  device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  client_id TEXT NOT NULL CHECK (length(client_id) BETWEEN 8 AND 64),
  sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
  size INTEGER NOT NULL CHECK (size > 0),
  status TEXT NOT NULL CHECK (status IN ('saved','duplicate')),
  saved_as TEXT CHECK (saved_as IS NULL OR length(saved_as) <= 200),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  UNIQUE (device_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_device_uploads_sha ON device_uploads(sha256);
CREATE INDEX IF NOT EXISTS idx_device_uploads_day ON device_uploads(device_id, created_at);
""")
c.commit()
print("migration 043 ok;", c.execute("SELECT COUNT(*) FROM device_uploads").fetchone()[0], "file(s) from phones")
