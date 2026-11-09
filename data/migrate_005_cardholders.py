"""Apply migration 005 to data/family.db (idempotent): per-person card tracking.

accounts.owner      -- primary account holder (e.g. 'Raj', 'Spouse')
transactions.cardholder -- who made the charge (supplementary/kid cards share one account;
                       statements list the card member per charge). NULL = unknown/primary.
Views: v_card_spend_monthly (month x card x cardholder), v_card_category_monthly.
Spend = everything on credit accounts except card_payment/transfer rows.
"""
import sqlite3
import pathlib

here = pathlib.Path(__file__).parent
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)


def cols(t):
    return {r[1] for r in c.execute(f"PRAGMA table_info({t})")}


if "owner" not in cols("accounts"):
    c.execute("ALTER TABLE accounts ADD COLUMN owner TEXT")
    print("added accounts.owner")
if "cardholder" not in cols("transactions"):
    c.execute("ALTER TABLE transactions ADD COLUMN cardholder TEXT")
    print("added transactions.cardholder")
c.execute("CREATE INDEX IF NOT EXISTS idx_transactions_acct_date ON transactions(account_id, txn_date)")
c.executescript("""
DROP VIEW IF EXISTS v_card_spend_monthly;
CREATE VIEW v_card_spend_monthly AS
SELECT substr(t.txn_date,1,7) AS month, a.name AS card, a.last4,
       COALESCE(t.cardholder, a.owner, 'Unassigned') AS cardholder,
       ROUND(SUM(CASE WHEN t.amount<0 THEN -t.amount ELSE 0 END),2) AS charges,
       ROUND(SUM(CASE WHEN t.amount>0 THEN t.amount ELSE 0 END),2) AS credits,
       ROUND(SUM(-t.amount),2) AS net_spend, COUNT(*) AS n
FROM transactions t JOIN accounts a ON a.id=t.account_id
WHERE a.type='credit' AND COALESCE(t.txn_type,'spend') NOT IN ('card_payment','transfer')
GROUP BY 1,2,3,4;

DROP VIEW IF EXISTS v_card_category_monthly;
CREATE VIEW v_card_category_monthly AS
SELECT substr(t.txn_date,1,7) AS month, COALESCE(t.category,'Uncategorized') AS category,
       ROUND(SUM(-t.amount),2) AS net_spend, COUNT(*) AS n
FROM transactions t JOIN accounts a ON a.id=t.account_id
WHERE a.type='credit' AND COALESCE(t.txn_type,'spend') NOT IN ('card_payment','transfer')
GROUP BY 1,2;
""")
c.commit()
print("migration 005 ok")
