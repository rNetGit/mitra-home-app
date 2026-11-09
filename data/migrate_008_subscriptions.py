"""Apply migration 008 to data/family.db (idempotent): richer subscription tracking.

Adds to `subscriptions`: match_pattern (SQL LIKE on UPPER(description), several joined by '|'),
match_payee (payee name when the description is cryptic), category, price_type (fixed|variable),
decision (unreviewed|keep|cancel|cancelled), reviewed_on, used_by, notes. Charges, last-charge date,
price changes and 'stopped?' status are computed live from `transactions` (data/subscriptions.py tracked()),
so nothing here goes stale when new statements are loaded.
Decisions start as 'unreviewed': set them with  python data/subscriptions.py decide "<name>" keep|cancel|cancelled
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(subscriptions)")}
for col, ddl in [("match_pattern", "TEXT"), ("match_payee", "TEXT"), ("category", "TEXT"), ("price_type", "TEXT"),
                 ("decision", "TEXT DEFAULT 'unreviewed'"), ("reviewed_on", "TEXT"), ("used_by", "TEXT"), ("notes", "TEXT")]:
    if col not in cols:
        c.execute(f"ALTER TABLE subscriptions ADD COLUMN {col} {ddl}")
c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_subscriptions_name ON subscriptions(name)")

# No seed rows: run `python data/subscriptions.py detect` after statements are loaded.
S = []
for name, pat, payee, cat, freq, amt, ptype, active, notes in S:
    if c.execute("SELECT 1 FROM subscriptions WHERE name=?", (name,)).fetchone():
        continue
    c.execute("INSERT INTO subscriptions(name,amount,frequency,active,match_pattern,match_payee,category,price_type,decision,notes)"
              " VALUES(?,?,?,?,?,?,?,?, 'unreviewed', ?)", (name, amt, freq, active, pat, payee, cat, ptype, notes))
c.commit()
print("migration 008 ok;", c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0], "subscriptions")
