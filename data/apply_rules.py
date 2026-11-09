"""Seed category_rules (idempotent) and apply them to transactions with NULL txn_type.

Rules are (SQL LIKE pattern on UPPER(description), category, payee_type, payee). Lower priority number wins.
Order: the family's own rules from config/category_rules.json first, then the neutral starter set below.

config/category_rules.json:  [["PATTERN%", "category", "txn_type", "Payee name"], ...]
Card payments: classify a credit-card payment as "transfer" ONLY for cards whose own statements are ingested
into `transactions` (otherwise the spend is counted twice in v_monthly_cashflow.operating_net). For cards whose
statements are NOT ingested keep "card_payment". Add a family rule for each card as its statements are loaded, e.g.
  ["AMEX EPAYMENT%", "credit card", "transfer", "Amex"]
"""
import config
import country

import audit_fix  # noqa: E402
import db  # noqa: E402
import rule_match  # noqa: E402

c = db.connect()
FAMILY = [tuple(r) for r in (config.data_file("category_rules.json") or []) if len(r) == 4]
# The neutral starter set comes from the country profile (packs/country/<code>.json `starter_rules`); the US list
# below is what every database had before 0.19 and stays as the fallback when a profile has none.
STARTER = [tuple(r) for r in country.profile().get("starter_rules") or []] or [
 ("%PAYROLL%", "salary", "income", "Payroll"),
 ("%DIRECT DEP%", "salary", "income", "Direct deposit"),
 ("INTEREST PAYMENT%", "interest", "interest", "Bank interest"),
 ("%INTEREST PAID%", "interest", "interest", "Bank interest"),
 ("IRS USATAXPYMT%", "tax", "tax", "IRS"),
 ("IRS TREAS 310 TAX REF%", "tax refund", "tax", "IRS refund"),
 ("SCHWAB%", "investing", "investment_transfer", "Schwab"),
 ("FIDELITY%", "investing", "investment_transfer", "Fidelity"),
 ("VANGUARD%", "investing", "investment_transfer", "Vanguard"),
 ("ROBINHOOD%", "investing", "investment_transfer", "Robinhood"),
 ("TREASURY DIRECT%", "investing", "investment_transfer", "TreasuryDirect"),
 ("GEICO%", "insurance", "insurance", "GEICO"),
 ("STATE FARM%", "insurance", "insurance", "State Farm"),
 ("PROGRESSIVE%", "insurance", "insurance", "Progressive"),
 ("ALLSTATE%", "insurance", "insurance", "Allstate"),
 ("NATIONWIDE%", "insurance", "insurance", "Nationwide"),
 ("PRUDENTIAL%", "insurance", "insurance", "Prudential"),
 ("COMCAST%", "utilities", "utility", "Comcast"),
 ("SPECTRUM%", "utilities", "utility", "Spectrum"),
 ("VERIZON%", "utilities", "utility", "Verizon"),
 ("AT&T%", "utilities", "utility", "AT&T"),
 ("T-MOBILE%", "utilities", "utility", "T-Mobile"),
 ("SUNOCO%", "fuel", "spend", "Sunoco"),
 ("SHELL OIL%", "fuel", "spend", "Shell"),
 ("EXXON%", "fuel", "spend", "Exxon"),
 ("MOBIL %", "fuel", "spend", "Mobil"),
 ("COSTCO%", "wholesale stores", "spend", "Costco"),
 ("WALMART%", "general merchandise", "spend", "Walmart"),
 ("TARGET%", "general merchandise", "spend", "Target"),
 ("%E-Z*PASS%", "tolls", "spend", "E-ZPass"),
 ("PLANET FITNESS%", "fitness", "spend", "Planet Fitness"),
 ("ATM WTH%", "cash withdrawal", "spend", "ATM"),
 ("POS PUR%", "debit card purchase", "spend", None),
 ("REC POS%", "debit card recurring", "spend", None),
]
# Family rules (config/category_rules.json) always win: priorities 1-99 in file order, and an edited rule replaces the
# stored one. Starter rules sit at 1000+ and never overwrite a pattern that is already there.
for i, (p, cat, t, payee) in enumerate(FAMILY):
    c.execute("INSERT INTO category_rules(pattern,category,payee_type,payee,priority) VALUES(?,?,?,?,?) "
              "ON CONFLICT(pattern) DO UPDATE SET category=excluded.category, payee_type=excluded.payee_type, "
              "payee=excluded.payee, priority=excluded.priority", (p, cat, t, payee, min(1 + i, 99)))
for i, (p, cat, t, payee) in enumerate(STARTER):
    c.execute("INSERT OR IGNORE INTO category_rules(pattern,category,payee_type,payee,priority) VALUES(?,?,?,?,?)", (p, cat, t, payee, 1000 + i))
    c.execute("UPDATE category_rules SET priority=? WHERE pattern=? AND priority BETWEEN 100 AND 999", (1000 + i, p))
# A starter rule a newer release dropped or narrowed (0.117.3: "MOBIL%" also caught "MOBILE CHECK DEPOSIT") leaves the table,
# and the lines it typed take what the remaining rules say (none = uncategorized again).
keep = {p for p, *_ in STARTER} | {p for p, *_ in FAMILY}
for p, cat, t in c.execute("SELECT pattern, category, payee_type FROM category_rules WHERE priority >= 1000").fetchall():
    if p not in keep:
        c.execute("DELETE FROM category_rules WHERE pattern=?", (p,))
        rule_match.reapply(c, p, only=(cat, t))
for rid, desc in c.execute("SELECT id,description FROM transactions WHERE txn_type IS NULL AND manual=0").fetchall():
    r = rule_match.first_rule(c, desc)
    if r:
        c.execute("UPDATE transactions SET category=?,txn_type=?,payee=? WHERE id=?", (*r, rid))
# Rows that already have a type but no category (older imports) get the category of the first matching rule.
audit_fix.categorize(c)
pairs = rule_match.pair_transfers(c)  # the same money leaving one own account and arriving in another
c.commit()
print(f"rules: {len(FAMILY)} family + {len(STARTER)} starter; {pairs} transfer pair(s) between own accounts")
