"""Apply migration 044 to data/family.db (idempotent): sync with paired phones.

sync_log: which row of a table a phone may carry changed (table, rowid, I/U/D, time), written by triggers on those
tables (data/sync_data.py ensure_triggers), whoever made the change. No content. AUTOINCREMENT so an id is never used
twice, even after old entries are pruned: a phone's cursor stays meaningful.
sync_ops: one row per edit a phone sent (`POST /api/sync/push`): the phone's own id for it and the status it got, so a
repeat after a dropped connection is answered without doing it twice. No text of the edit. Removing a phone removes
its rows.
"""
import sqlite3

TS = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]*'"
import paths  # noqa: E402
import sync_data  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS sync_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tbl TEXT NOT NULL CHECK (length(tbl) BETWEEN 1 AND 40),
  row_id INTEGER NOT NULL,
  op TEXT NOT NULL CHECK (op IN ('I','U','D')),
  ts TEXT NOT NULL CHECK (ts {TS})
);
CREATE INDEX IF NOT EXISTS idx_sync_log_ts ON sync_log(ts);
CREATE TABLE IF NOT EXISTS sync_ops (
  id INTEGER PRIMARY KEY,
  device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
  client_id TEXT NOT NULL CHECK (length(client_id) BETWEEN 8 AND 64),
  op TEXT NOT NULL CHECK (length(op) BETWEEN 1 AND 20),
  status TEXT NOT NULL CHECK (status IN ('ok','rejected')),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  UNIQUE (device_id, client_id)
);
""")
n = sync_data.ensure_triggers(c)
c.commit()
print(f"migration 044 ok; change-log triggers on {n} tables")
