"""Apply migration 071 to data/family.db (idempotent): loans, holdings and life policies as details of an account
(PLAN_money_books slice 3).

accounts.death_benefit   life insurance: what the policy pays (not counted in net worth)
accounts.premium         life insurance: premium a month

Every loan becomes the detail of one account (loans.account_id, added by 070): a loan row is linked to the one loan
account with the same name or the same last four digits; an active loan with none gets a new account (type loan,
subtype from its kind, the lender as the bank). A paid-off loan with no account is left alone. Investments are not
linked here: holdings are linked by a person in Edit account.
"""
import sqlite3

import paths  # noqa: E402

KIND = {"mortgage": "mortgage", "auto": "auto", "student": "student", "personal": "personal", "heloc": "heloc"}

c = sqlite3.connect(paths.DB)
have = {r[1] for r in c.execute("PRAGMA table_info(accounts)")}
if have:
    for col in ("death_benefit", "premium"):
        if col not in have:
            c.execute(f"ALTER TABLE accounts ADD COLUMN {col} REAL")
loan_cols = {r[1] for r in c.execute("PRAGMA table_info(loans)")}
if have and "account_id" in loan_cols and "subtype" in have:
    for lid, name, lender, kind, last4, status in c.execute(
            "SELECT id, name, lender, kind, last4, status FROM loans WHERE account_id IS NULL").fetchall():
        taken = {r[0] for r in c.execute("SELECT account_id FROM loans WHERE account_id IS NOT NULL")}
        cands = [r[0] for r in c.execute(
            "SELECT id FROM accounts WHERE type='loan' AND (lower(name)=lower(?) OR (? IS NOT NULL AND last4=?))",
            (name, last4, last4)) if r[0] not in taken]
        if len(cands) == 1:
            c.execute("UPDATE loans SET account_id=? WHERE id=?", (cands[0], lid))
            continue
        if cands or (status or "active") != "active":
            continue  # two candidates: a person picks in Edit account; a paid-off loan stays history
        label = name
        if c.execute("SELECT 1 FROM accounts WHERE name=? COLLATE NOCASE", (label,)).fetchone():
            label = f"{name} (loan)"
        if c.execute("SELECT 1 FROM accounts WHERE name=? COLLATE NOCASE", (label,)).fetchone():
            continue
        aid = c.execute("INSERT INTO accounts(name, type, subtype, subtype_locked, institution, last4) VALUES (?,?,?,1,?,?)",
                        (label, "loan", KIND.get(kind or "", "other_loan"), lender, last4)).lastrowid
        c.execute("UPDATE loans SET account_id=? WHERE id=?", (aid, lid))
c.commit()
print("migration 071 ok")
