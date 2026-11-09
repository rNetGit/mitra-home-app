"""Apply migration 063 to data/family.db (idempotent): the Mitra Wall as an app on the tablet, working from its own copy.

walls.kind         'browser' (the wall page in the tablet's browser, signed in by a cookie) or 'app' (the Mitra Home app
                   in wall mode, signed in by a bearer token over pinned HTTPS); a token works only for its own kind.
walls.app_version  the app's version at its last contact (app walls only).
walls.last_sync    when the app wall last took a copy from this PC (Settings > Phones > Mitra Wall shows the age).
wall_ops           the taps an app wall made while the PC was off (a job ticked, a list item ticked or added, a reward
                   asked for), applied when it next reaches the PC: one row per tap the wall sent, keyed by the wall's
                   own id for it, so a tap sent twice is answered from here and never done twice. No content: the op name,
                   the result and the sentence shown back on the wall.
"""
import sqlite3

TS = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]*'"
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(walls)")}
if cols:
    if "kind" not in cols:
        c.execute("ALTER TABLE walls ADD COLUMN kind TEXT NOT NULL DEFAULT 'browser' CHECK (kind IN ('browser','app'))")
    if "app_version" not in cols:
        c.execute("ALTER TABLE walls ADD COLUMN app_version TEXT CHECK (app_version IS NULL OR length(app_version) <= 20)")
    if "last_sync" not in cols:
        c.execute(f"ALTER TABLE walls ADD COLUMN last_sync TEXT CHECK (last_sync IS NULL OR last_sync {TS})")
c.executescript(f"""
CREATE TABLE IF NOT EXISTS wall_ops (
  id INTEGER PRIMARY KEY,
  wall_id INTEGER NOT NULL REFERENCES walls(id),
  client_id TEXT NOT NULL CHECK (length(client_id) BETWEEN 8 AND 64),
  op TEXT NOT NULL CHECK (length(op) BETWEEN 1 AND 30),
  status TEXT NOT NULL CHECK (status IN ('ok','rejected')),
  message TEXT CHECK (message IS NULL OR length(message) <= 300),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  UNIQUE (wall_id, client_id)
);
""")
c.commit()
print("migration 063 ok")
