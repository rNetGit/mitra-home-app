"""Migration 003 - insurance policy tracking.

Adds policies, policy_vehicles, policy_coverages, policy_discounts and the
v_policy_premium_history view. Idempotent: safe to re-run.

Why these tables: declarations pages carry a term (not a calendar year), a premium
that changes every renewal, per-vehicle and per-coverage detail, and a discount list.
Tracking year-over-year change needs the renewal chain (policies.prior_policy_id),
so each term is its own row rather than an updated-in-place record.

Run:  python data/migrate_003_policies.py
"""

import sqlite3
import os

import paths  # noqa: E402
DB = str(paths.DB)

DDL = [
    """
    CREATE TABLE IF NOT EXISTS policies (
      id INTEGER PRIMARY KEY,
      kind TEXT,                         -- auto|home|umbrella|renters|other
      carrier TEXT,                      -- carrier name
      policy_last4 TEXT,                 -- last4 only; full number stays in the archived PDF
      term_start TEXT,                   -- ISO date
      term_end TEXT,                     -- ISO date; renewal/expiry driver
      premium_total REAL,                -- full-term premium as printed
      payment_plan TEXT,                 -- annual|semiannual|quarterly|monthly|escrow
      insured_names TEXT,
      property_address TEXT,             -- home/renters only
      status TEXT DEFAULT 'active',      -- active|expired|replaced
      document_id INTEGER REFERENCES documents(id),
      prior_policy_id INTEGER REFERENCES policies(id),   -- renewal chain, for YoY comparison
      notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS policy_vehicles (
      id INTEGER PRIMARY KEY,
      policy_id INTEGER REFERENCES policies(id),
      vin_last4 TEXT,                    -- last4 only (see CLAUDE.md privacy rule)
      year INTEGER,
      make TEXT,
      model TEXT,
      garage_zip TEXT,
      usage TEXT,                        -- commute|pleasure|business
      annual_miles INTEGER,
      assigned_driver TEXT,
      premium REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS policy_coverages (
      id INTEGER PRIMARY KEY,
      policy_id INTEGER REFERENCES policies(id),
      vehicle_id INTEGER REFERENCES policy_vehicles(id),  -- NULL = policy-level coverage
      coverage TEXT,                     -- bodily injury|property damage|comprehensive|dwelling...
      limit_text TEXT,                   -- as printed, e.g. '250/500' or '300000'
      deductible REAL,
      premium REAL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS policy_discounts (
      id INTEGER PRIMARY KEY,
      policy_id INTEGER REFERENCES policies(id),
      name TEXT,                         -- multi-policy, paid-in-full, telematics...
      amount REAL,                       -- NULL when the dec page does not itemize it
      applied INTEGER DEFAULT 1          -- 1 = on the policy, 0 = known-available but not applied
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_policies_term_end ON policies(term_end)",
    "CREATE INDEX IF NOT EXISTS idx_policies_chain ON policies(prior_policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_policy_vehicles_policy ON policy_vehicles(policy_id)",
    "CREATE INDEX IF NOT EXISTS idx_policy_coverages_policy ON policy_coverages(policy_id)",
]

VIEW = """
DROP VIEW IF EXISTS v_policy_premium_history;
CREATE VIEW v_policy_premium_history AS
SELECT
  p.id, p.kind, p.carrier, p.policy_last4, p.term_start, p.term_end,
  p.premium_total,
  pr.premium_total AS prior_premium,
  ROUND(p.premium_total - pr.premium_total, 2) AS change_abs,
  CASE WHEN pr.premium_total > 0
       THEN ROUND(100.0 * (p.premium_total - pr.premium_total) / pr.premium_total, 1)
  END AS change_pct
FROM policies p
LEFT JOIN policies pr ON pr.id = p.prior_policy_id;
"""


def main():
    if not os.path.exists(DB):
        raise SystemExit("family.db not found at %s" % DB)
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    try:
        for stmt in DDL:
            con.execute(stmt)
        con.executescript(VIEW)
        con.commit()
        names = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE name IN "
            "('policies','policy_vehicles','policy_coverages','policy_discounts',"
            "'v_policy_premium_history') ORDER BY name")]
        print("migration 003 ok ->", ", ".join(names))
    finally:
        con.close()


if __name__ == "__main__":
    main()
