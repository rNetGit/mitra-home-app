"""Apply migration 062 to data/family.db (idempotent): savings goals, and rewards children spend their stars on.

savings_goals: what the family is saving for (a holiday, a new roof, an emergency fund): the target, by when (or no
date), and how much is set aside so far: either typed by an adult (`saved`) or the latest reported balance of one
account kept for it (`account_id`). Done or dropped goals keep their row.
rewards: what a child can ask for with their stars (30 minutes of screen time = 10 stars), for one child or any child
(member NULL). Removing one marks it dropped.
reward_claims: a child asking for a reward (on the Mitra Wall or their own page) and an adult's answer: asked, given
(the stars are spent) or declined (the stars come back). Stars held by a request that waits are not spendable twice.
"""
import sqlite3

TS = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]*'"
DAY = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS savings_goals (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 60),
  target REAL NOT NULL CHECK (target > 0),
  saved REAL NOT NULL DEFAULT 0 CHECK (saved >= 0),
  due_date TEXT CHECK (due_date IS NULL OR due_date {DAY}),
  account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','done','dropped')),
  created_at TEXT NOT NULL CHECK (created_at {TS}),
  updated_at TEXT CHECK (updated_at IS NULL OR updated_at {TS})
);
CREATE TABLE IF NOT EXISTS rewards (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 60),
  stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 500),
  member TEXT CHECK (member IS NULL OR length(member) BETWEEN 1 AND 60),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','dropped')),
  created_at TEXT NOT NULL CHECK (created_at {TS})
);
CREATE TABLE IF NOT EXISTS reward_claims (
  id INTEGER PRIMARY KEY,
  reward_id INTEGER NOT NULL REFERENCES rewards(id),
  member TEXT NOT NULL CHECK (length(member) BETWEEN 1 AND 60),
  stars INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 500),
  status TEXT NOT NULL DEFAULT 'asked' CHECK (status IN ('asked','given','declined')),
  asked_at TEXT NOT NULL CHECK (asked_at {TS}),
  asked_by TEXT,
  decided_at TEXT CHECK (decided_at IS NULL OR decided_at {TS}),
  decided_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_reward_claims_member ON reward_claims(member, status);
""")
c.commit()
print("migration 062 ok")
