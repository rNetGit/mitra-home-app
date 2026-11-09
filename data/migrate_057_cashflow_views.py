"""Apply migration 057 to data/family.db (idempotent): cash flow views count a card payment once and income only as money in.

v_card_payments     only the payment as it left a bank account (amount < 0). A card's own statement prints the same money
                    as a "payment received" line (amount > 0); adding both made Card payments small or negative.
v_monthly_cashflow  card_payments the same way; income = income / interest lines that brought money in (amount > 0).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
DROP VIEW IF EXISTS v_card_payments;
CREATE VIEW v_card_payments AS
SELECT substr(txn_date,1,7) AS month, payee, ROUND(SUM(-amount),2) AS paid, COUNT(*) AS n
FROM transactions WHERE txn_type='card_payment' AND amount < 0 GROUP BY 1,2;

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
  ROUND(SUM(CASE WHEN COALESCE(txn_type,'') NOT IN ('investment_transfer','transfer') THEN amount ELSE 0 END),2) AS operating_net,
  ROUND(SUM(amount),2) AS net_change
FROM transactions GROUP BY 1;
""")
c.commit()
print("migration 057 ok")
