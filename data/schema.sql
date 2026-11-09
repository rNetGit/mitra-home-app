-- FamilyAgent personal tracker schema (SQLite). Source of truth lives on the PC.
--
-- Fresh databases are created from this file (data/init_db.py); existing ones are changed only by the numbered
-- data/migrate_NNN_*.py scripts (python data/migrate.py). Migration 011 was never shipped: the number is skipped on
-- purpose, nothing is missing. Date columns hold ISO text (YYYY-MM-DD, optionally with a time); status columns are
-- small fixed vocabularies. Both are enforced with CHECK constraints (migration 025 adds them to older databases).
-- Money stays REAL in the family's currency; every Python write rounds to the cent and matching uses the generated
-- integer amount_cents columns (data/money.py, migration 027).
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY,
  filed_path TEXT NOT NULL,          -- path under archive/
  doc_type TEXT,                     -- bill|statement|receipt|policy|medical|tax|other (free text on purpose)
  vendor TEXT,
  doc_date TEXT,                     -- ISO date
  ingested_at TEXT DEFAULT CURRENT_TIMESTAMP,
  notes TEXT,
  CONSTRAINT ck_documents_doc_date CHECK (doc_date IS NULL OR (date(doc_date) IS NOT NULL AND date(doc_date) = substr(doc_date,1,10)))
);
CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(doc_date);

CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,                -- e.g. "HDFC Savings"
  type TEXT,                         -- savings|checking|credit|loan|investment
  last4 TEXT,
  currency TEXT DEFAULT 'USD'
);

CREATE TABLE IF NOT EXISTS transactions (
  id INTEGER PRIMARY KEY,
  account_id INTEGER REFERENCES accounts(id),
  txn_date TEXT NOT NULL,
  description TEXT,
  amount REAL NOT NULL,              -- negative = spend
  category TEXT,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  payee TEXT,                        -- normalized payee, set via category_rules
  txn_type TEXT,                     -- card_payment|loan_payment|insurance|utility|investment_transfer|income|transfer|spend|fee|interest|tax
  ref TEXT,                          -- source reference/txn id (e.g. AMEX Reference); use for exact dedupe on re-import
  amount_cents INTEGER GENERATED ALWAYS AS (CAST(ROUND(COALESCE(amount, 0) * 100) AS INTEGER)) VIRTUAL,  -- exact matching (migration 027)
  manual INTEGER NOT NULL DEFAULT 0, -- 1 = category / type set by a person in the Ledger: rules never overwrite it (migration 058)
  CONSTRAINT ck_transactions_txn_date CHECK ((date(txn_date) IS NOT NULL AND date(txn_date) = substr(txn_date,1,10)))
);
CREATE INDEX IF NOT EXISTS idx_transactions_ref ON transactions(ref);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(txn_date);
CREATE INDEX IF NOT EXISTS idx_transactions_acct_date ON transactions(account_id, txn_date);
-- A source reference is unique per account; legacy rows without one are not constrained.
CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_acct_ref ON transactions(account_id, ref) WHERE ref IS NOT NULL AND ref != '';

CREATE TABLE IF NOT EXISTS bills (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,                -- electricity, home tax, life insurance...
  vendor TEXT,
  frequency TEXT,                    -- monthly|quarterly|yearly|once
  amount REAL,
  due_date TEXT NOT NULL,
  status TEXT DEFAULT 'due',         -- due|paid|overdue
  paid_date TEXT,
  calendar_event_id TEXT,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  amount_cents INTEGER GENERATED ALWAYS AS (CAST(ROUND(COALESCE(amount, 0) * 100) AS INTEGER)) VIRTUAL,  -- exact matching (migration 027)
  CONSTRAINT ck_bills_due_date CHECK ((date(due_date) IS NOT NULL AND date(due_date) = substr(due_date,1,10))),
  CONSTRAINT ck_bills_paid_date CHECK (paid_date IS NULL OR (date(paid_date) IS NOT NULL AND date(paid_date) = substr(paid_date,1,10))),
  CONSTRAINT ck_bills_status CHECK (status IS NULL OR status IN ('due','paid','overdue'))
);
CREATE INDEX IF NOT EXISTS idx_bills_status_due ON bills(status, due_date);

CREATE TABLE IF NOT EXISTS subscriptions (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  amount REAL,
  frequency TEXT,
  next_renewal TEXT,
  active INTEGER DEFAULT 1,
  CONSTRAINT ck_subscriptions_next_renewal CHECK (next_renewal IS NULL OR (date(next_renewal) IS NOT NULL AND date(next_renewal) = substr(next_renewal,1,10)))
);
CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(active);

CREATE TABLE IF NOT EXISTS investments (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kind TEXT,                         -- fd|mutual_fund|stock|retirement|other
  invested REAL,
  current_value REAL,
  as_of TEXT,
  maturity_date TEXT,
  CONSTRAINT ck_investments_as_of CHECK (as_of IS NULL OR (date(as_of) IS NOT NULL AND date(as_of) = substr(as_of,1,10))),
  CONSTRAINT ck_investments_maturity_date CHECK (maturity_date IS NULL OR (date(maturity_date) IS NOT NULL AND date(maturity_date) = substr(maturity_date,1,10)))
);
CREATE INDEX IF NOT EXISTS idx_investments_maturity ON investments(maturity_date);

CREATE TABLE IF NOT EXISTS interest_income (
  id INTEGER PRIMARY KEY,
  account_id INTEGER REFERENCES accounts(id),
  period_end TEXT,
  amount REAL,
  CONSTRAINT ck_interest_income_period_end CHECK (period_end IS NULL OR (date(period_end) IS NOT NULL AND date(period_end) = substr(period_end,1,10)))
);

CREATE TABLE IF NOT EXISTS appointments (
  id INTEGER PRIMARY KEY,
  person TEXT,
  provider TEXT,
  purpose TEXT,
  appt_datetime TEXT NOT NULL,
  followup_due TEXT,
  calendar_event_id TEXT,
  CONSTRAINT ck_appointments_appt_datetime CHECK ((date(appt_datetime) IS NOT NULL AND date(appt_datetime) = substr(appt_datetime,1,10))),
  CONSTRAINT ck_appointments_followup_due CHECK (followup_due IS NULL OR (date(followup_due) IS NOT NULL AND date(followup_due) = substr(followup_due,1,10)))
);
CREATE INDEX IF NOT EXISTS idx_appointments_when ON appointments(appt_datetime);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,                -- birthday, passport renewal, tax filing...
  event_date TEXT NOT NULL,
  recurs_yearly INTEGER DEFAULT 1,
  calendar_event_id TEXT,
  CONSTRAINT ck_events_event_date CHECK ((date(event_date) IS NOT NULL AND date(event_date) = substr(event_date,1,10)))
);
CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);

-- ===== Finance extension (migration 001) =====
-- Existing DBs: run data/migrate_001_finance.py (adds transactions.payee / txn_type / ref if missing).
-- Fresh DBs get the columns from CREATE TABLE above.

-- ===== Source reference (migration 002) =====
-- Existing DBs: run data/migrate_002_ref.py (adds transactions.ref if missing).
-- Needed because (txn_date, description, amount) is NOT unique: real statements can repeat an
-- identical charge on the same day. Dedupe re-imports on ref where the source supplies one.

-- ===== Insurance policies (migration 003) =====
-- Existing DBs: run data/migrate_003_policies.py (adds the four policy_* tables and
-- v_policy_premium_history if missing). That script holds the authoritative DDL.
-- One row per policy TERM, not per calendar year: declarations pages renew on their own
-- cycle, and year-over-year comparison needs the renewal chain via policies.prior_policy_id.
-- Privacy: policy_last4 / vin_last4 only; full numbers stay in the archived PDF.

-- ===== Vehicles + bill account link (migration 004) =====
-- Existing DBs: run data/migrate_004_vehicles_billaccount.py (adds the vehicles table,
-- bills.account_id and policy_vehicles.vehicle_id if missing). That script holds the DDL.
-- Why vehicles is separate from policy_vehicles: policy_vehicles is scoped to one policy
-- TERM and is re-inserted every renewal, but a car outlives its terms and carries its own
-- dates (registration, inspection). policy_vehicles.vehicle_id links a rated vehicle to the
-- real one. Privacy: vin_last4 / plate_last4 only.

-- ===== Constraints and indexes (migration 025) =====
-- Existing DBs: data/migrate_025_constraints.py rebuilds each table once with the CHECK constraints shown
-- above (and the same for the tables created by migrations 003-024), adds the indexes, repairs non-ISO dates first.

-- Rules matched against UPPER(transactions.description) with SQL LIKE; lowest priority number wins.
CREATE TABLE IF NOT EXISTS category_rules (
  id INTEGER PRIMARY KEY,
  pattern TEXT NOT NULL,             -- SQL LIKE pattern, uppercase, e.g. 'AMEX EPAYMENT%'
  category TEXT,
  payee_type TEXT,                   -- becomes transactions.txn_type
  payee TEXT,                        -- becomes transactions.payee
  priority INTEGER DEFAULT 100,
  UNIQUE(pattern)
);

DROP VIEW IF EXISTS v_card_payments;
CREATE VIEW v_card_payments AS
SELECT substr(txn_date,1,7) AS month, payee, ROUND(SUM(-amount),2) AS paid, COUNT(*) AS n
FROM transactions WHERE txn_type='card_payment' AND amount < 0 GROUP BY 1,2;  -- paid from a bank account (a card's own 'payment received' line is the same money)

DROP VIEW IF EXISTS v_investment_flows;
CREATE VIEW v_investment_flows AS
WITH m AS (
  SELECT substr(txn_date,1,7) AS month, payee, ROUND(SUM(-amount),2) AS invested, COUNT(*) AS n
  FROM transactions WHERE txn_type='investment_transfer' GROUP BY 1,2)
SELECT month, payee, invested, n,
  ROUND(SUM(invested) OVER (PARTITION BY payee ORDER BY month),2) AS cumulative_payee,
  ROUND(SUM(invested) OVER (ORDER BY month),2) AS cumulative_total   -- positive = money moved out to investments
FROM m;

DROP VIEW IF EXISTS v_monthly_cashflow;
CREATE VIEW v_monthly_cashflow AS
SELECT substr(txn_date,1,7) AS month,
  ROUND(SUM(CASE WHEN txn_type IN ('income','interest') AND amount > 0 THEN amount ELSE 0 END),2) AS income,
  ROUND(SUM(CASE WHEN txn_type='card_payment' AND amount < 0 THEN -amount ELSE 0 END),2) AS card_payments,
  ROUND(SUM(CASE WHEN txn_type='loan_payment' THEN -amount ELSE 0 END),2) AS loans,
  ROUND(SUM(CASE WHEN txn_type='insurance' THEN -amount ELSE 0 END),2) AS insurance,
  ROUND(SUM(CASE WHEN txn_type='utility' THEN -amount ELSE 0 END),2) AS utilities,
  ROUND(SUM(CASE WHEN txn_type='tax' THEN -amount ELSE 0 END),2) AS tax_net,
  ROUND(SUM(CASE WHEN txn_type IN ('spend','fee') THEN -amount ELSE 0 END),2) AS other_spend,
  ROUND(SUM(CASE WHEN txn_type IS NULL THEN -amount ELSE 0 END),2) AS uncategorized_net_out,
  ROUND(SUM(CASE WHEN txn_type='investment_transfer' THEN -amount ELSE 0 END),2) AS invested,
  ROUND(SUM(CASE WHEN txn_type='transfer' THEN amount ELSE 0 END),2) AS transfers_in_net,
  -- operating_net excludes investments and internal transfers
  ROUND(SUM(CASE WHEN COALESCE(txn_type,'') NOT IN ('investment_transfer','transfer') THEN amount ELSE 0 END),2) AS operating_net,
  ROUND(SUM(amount),2) AS net_change
FROM transactions GROUP BY 1;
