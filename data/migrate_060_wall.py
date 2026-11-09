"""Apply migration 060 to data/family.db (idempotent): the Family Wall and children's routines.

walls: one row per wall display (a tablet on the kitchen wall) paired in Settings > Phones > Add a wall. A wall is the
household's, not a person's: it acts as a limited member named after the wall (it may tick family lists and children's
routines, never see money without an adult's PIN). Only the SHA-256 of its access token is stored; the token lives in
the wall browser's cookie. Revoking keeps the row (revoked_at).
wall_pairings: one-time codes behind the QR code (and typed by hand): only the SHA-256 of the code is stored; a code
works once, for a few minutes.
routines: a child's repeating jobs by part of the day (morning / after school / evening), each worth some stars, on
chosen weekdays (MO,TU,... or empty = every day). Removing one marks it dropped.
routine_done: one row per routine ticked on a day (who ticked it: the child's wall or an adult). Stars are counted from
these rows; a routine can be done once a day.
"""
import sqlite3

TS = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]*'"
DAY = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS walls (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
  token_hash TEXT NOT NULL UNIQUE CHECK (length(token_hash) = 64),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  created_by TEXT,
  last_seen TEXT CHECK (last_seen IS NULL OR last_seen {TS}),
  revoked_at TEXT CHECK (revoked_at IS NULL OR revoked_at {TS})
);
CREATE TABLE IF NOT EXISTS wall_pairings (
  id INTEGER PRIMARY KEY,
  code_hash TEXT NOT NULL UNIQUE CHECK (length(code_hash) = 64),
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 40),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  created_by TEXT,
  expires_at TEXT NOT NULL CHECK (expires_at {TS}),
  used_at TEXT CHECK (used_at IS NULL OR used_at {TS}),
  wall_id INTEGER REFERENCES walls(id) ON DELETE SET NULL
);
CREATE TABLE IF NOT EXISTS routines (
  id INTEGER PRIMARY KEY,
  member TEXT NOT NULL CHECK (length(member) BETWEEN 1 AND 60),
  part TEXT NOT NULL CHECK (part IN ('morning','afternoon','evening')),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 60),
  icon TEXT NOT NULL DEFAULT 'star' CHECK (length(icon) BETWEEN 1 AND 20),
  stars INTEGER NOT NULL DEFAULT 1 CHECK (stars BETWEEN 1 AND 5),
  weekdays TEXT NOT NULL DEFAULT '' CHECK (length(weekdays) <= 20),
  sort INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','dropped')),
  created_at TEXT NOT NULL CHECK (created_at {TS})
);
CREATE INDEX IF NOT EXISTS idx_routines_member ON routines(member, status, part);
CREATE TABLE IF NOT EXISTS routine_done (
  id INTEGER PRIMARY KEY,
  routine_id INTEGER NOT NULL REFERENCES routines(id) ON DELETE CASCADE,
  day TEXT NOT NULL CHECK (day {DAY}),
  stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5),
  done_by TEXT,
  done_at TEXT NOT NULL CHECK (done_at {TS}),
  UNIQUE (routine_id, day)
);
CREATE INDEX IF NOT EXISTS idx_routine_done_day ON routine_done(day);
""")
c.commit()
print("migration 060 ok;", c.execute("SELECT COUNT(*) FROM walls WHERE revoked_at IS NULL").fetchone()[0], "wall(s),",
      c.execute("SELECT COUNT(*) FROM routines WHERE status='active'").fetchone()[0], "routine(s)")
