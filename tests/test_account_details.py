"""Money books slice 3 (PLAN_money_books): loans, holdings and life policies as details of an account. Migration 071
links loans to their account (or makes one), Edit account links a loan / holdings and keeps life fields, and books_data
shows them on the account page and the Accounts tab."""
import datetime as dt

import pytest

from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}
TODAY = dt.date(2026, 11, 14)


def _ins(root, sql, *params):
    con = db(root)
    rid = con.execute(sql, params).lastrowid
    con.commit()
    con.close()
    return rid


@pytest.fixture(scope="module")
def clean(root):
    con = db(root)
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if t != "accounts" and "account_id" in {r[1] for r in con.execute(f"PRAGMA table_info({t})")}:
            if t in ("bills",):
                con.execute(f"UPDATE {t} SET account_id=NULL")
            else:
                con.execute(f"DELETE FROM {t}")
    con.execute("DELETE FROM accounts")
    con.commit()
    con.close()
    return root


def test_migration_links_loans_or_makes_their_account(clean, modules):
    root = clean
    acct = _ins(root, "INSERT INTO accounts(name, type, subtype, last4) VALUES ('Car loan', 'loan', 'auto', '7781')")
    by_name = _ins(root, "INSERT INTO loans(name, lender, kind, balance, status) VALUES ('Car loan', 'Toyota', 'auto', 14220, 'active')")
    alone = _ins(root, "INSERT INTO loans(name, lender, kind, balance, rate_pct, payment, status) "
                       "VALUES ('Sofa plan', 'Ashley', 'other', 1980, 0, 165, 'active')")
    paid = _ins(root, "INSERT INTO loans(name, kind, status) VALUES ('Old student loan', 'student', 'paid_off')")
    con = db(root)
    con.execute("DELETE FROM schema_migrations WHERE name LIKE 'migrate_071%'")
    con.commit()
    con.close()
    modules("migrate").run()
    assert {"death_benefit", "premium"} <= {r[1] for r in q(root, "PRAGMA table_info(accounts)")}
    assert q(root, "SELECT account_id FROM loans WHERE id=?", by_name)[0][0] == acct
    made = q(root, "SELECT a.name, a.type, a.subtype, a.institution FROM loans l JOIN accounts a ON a.id=l.account_id WHERE l.id=?", alone)
    assert made == [("Sofa plan", "loan", "other_loan", "Ashley")]
    assert q(root, "SELECT account_id FROM loans WHERE id=?", paid)[0][0] is None, "paid-off loans stay history"


def test_new_loan_gets_its_account(clean, modules):
    ea = modules("edit_actions")
    assert ea.loan_add(ADULT, "Home mortgage", "mortgage", "Rocket", "286400", "6.1", "2231", "2052-04-01")[0]
    r = q(clean, "SELECT a.name, a.subtype, a.institution FROM loans l JOIN accounts a ON a.id=l.account_id WHERE l.name='Home mortgage'")
    assert r == [("Home mortgage", "mortgage", "Rocket")]


def test_edit_account_links_loan_holdings_and_life(clean, modules):
    root = clean
    ea, re_ = modules("edit_actions"), modules("records_edit")
    brk = _ins(root, "INSERT INTO accounts(name, type, subtype) VALUES ('Brokerage', 'investment', 'brokerage')")
    other = _ins(root, "INSERT INTO accounts(name, type, subtype) VALUES ('Other brokerage', 'investment', 'brokerage')")
    h1 = _ins(root, "INSERT INTO investments(name, kind, invested, current_value, as_of) VALUES ('Index fund', 'mutual_fund', 50000, 60000, '2026-11-10')")
    h2 = _ins(root, "INSERT INTO investments(name, kind, invested, current_value, as_of, maturity_date) "
                    "VALUES ('12-month CD', 'fd', 10000, 10200, '2026-11-01', '2027-06-01')")
    h3 = _ins(root, "INSERT INTO investments(name, kind, current_value) VALUES ('Loose bond', 'other', 500)")
    v = re_.values("accounts", brk)
    assert {i for i, *_ in v["holdings"]} >= {str(h1), str(h2), str(h3)}
    base = {k: "" for k in ("name", "kind", "institution", "ownership", "owners", "closed_on", "credit_limit", "apr",
                            "due_day", "min_payment")}
    ok, msg, _ = re_.edit(ADULT, "accounts", "save", brk, {**base, "name": "Brokerage", "kind": "brokerage",
                                                            "holdings_shown": "1", f"h_{h1}": "1", f"h_{h2}": "1"})
    assert ok, msg
    assert sorted(x for (x,) in q(root, "SELECT id FROM investments WHERE account_id=?", brk)) == sorted([h1, h2])
    assert ea.account_update(ADULT, other, holdings=[h1])[0] is False, "a holding belongs to one account"
    assert ea.account_update(ADULT, brk, holdings=[h2])[0]
    assert [x for (x,) in q(root, "SELECT id FROM investments WHERE account_id=?", brk)] == [h2]
    assert ea.account_update(ADULT, brk, holdings=[h1, h2])[0]
    life = _ins(root, "INSERT INTO accounts(name, type, subtype) VALUES ('Whole life', 'investment', 'life_whole')")
    ok, msg, _ = re_.edit(ADULT, "accounts", "save", life, {**base, "name": "Whole life", "kind": "life_whole",
                                                             "death_benefit": "250000", "premium": "185"})
    assert ok, msg
    assert q(root, "SELECT death_benefit, premium FROM accounts WHERE id=?", life)[0] == (250000, 185)
    loan_acct = q(root, "SELECT account_id FROM loans WHERE name='Home mortgage'")[0][0]
    lid = q(root, "SELECT id FROM loans WHERE name='Home mortgage'")[0][0]
    spare = _ins(root, "INSERT INTO accounts(name, type, subtype) VALUES ('Spare loan', 'loan', 'other_loan')")
    assert ea.account_update(ADULT, spare, loan_id=lid)[0] is False, "that loan belongs to another account"
    assert ea.account_update(ADULT, loan_acct, loan_id="")[0]
    assert q(root, "SELECT account_id FROM loans WHERE id=?", lid)[0][0] is None
    ok, msg, _ = re_.edit(ADULT, "accounts", "save", loan_acct, {**base, "name": "Home mortgage", "kind": "mortgage", "loan": str(lid)})
    assert ok, msg
    assert q(root, "SELECT account_id FROM loans WHERE id=?", lid)[0][0] == loan_acct


def test_account_page_and_tab_use_the_details(clean, modules):
    bd = modules("books_data")
    con = modules("db").connect(modules("paths").DB, readonly=True)
    try:
        o = bd.overview(con, TODAY)
        rows = {r["name"]: r for g in o["groups"] for r in g["rows"]}
        mort = rows["Home mortgage"]
        assert mort["balance"] == 286400 and mort["apr_pct"] == 6.1 and mort["min_payment"] == 2231
        assert mort["match"]["text"].startswith("From your loan record")
        brk = rows["Brokerage"]
        assert brk["balance"] == 70200 and brk["match"]["text"].startswith("From the holdings")
        assert [h["name"] for h in o["loose"]] == ["Loose bond"]
        assert o["have"] == 70200, "loose holdings and term policies are not in the totals"
        page = bd.account(con, mort["id"], TODAY)
        facts = dict(page["facts"])
        assert facts["Rate"] == "6.1%" and facts["Payment"] == "$2,231.00"
        assert facts["Payoff date on record"] == "2052-04-01" and "months)" in facts["At this payment, paid off"]
        bf = dict(bd.account(con, brk["id"], TODAY)["facts"])
        assert bf["Put in"] == "$60,000.00" and bf["Holdings value"] == "$70,200.00" and bf["Gain"] == "$10,200.00"
        assert bf["Next maturity"] == "2027-06-01"
        lf = dict(bd.account(con, rows["Whole life"]["id"], TODAY)["facts"])
        assert lf["Death benefit"] == "$250,000" and lf["Premium a month"] == "$185.00" and lf["Cash value"] == "not recorded"
    finally:
        con.close()
