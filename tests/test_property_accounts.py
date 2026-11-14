"""Money books: the Home and property group (account_types home / vehicle / other_property). A value is typed by a
person (account_balances kind estimate), counts in what the family has, and a home's equity subtracts the mortgage."""
import datetime as dt

import pytest

from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}
TODAY = dt.date(2026, 11, 14)


@pytest.fixture(scope="module")
def clean(root):
    con = db(root)
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if t != "accounts" and "account_id" in {r[1] for r in con.execute(f"PRAGMA table_info({t})")}:
            con.execute(f"UPDATE {t} SET account_id=NULL" if t == "bills" else f"DELETE FROM {t}")
    con.execute("DELETE FROM accounts")
    con.commit()
    con.close()
    return root


def test_value_by_hand_counts_and_home_equity(clean, modules):
    root = clean
    ea, re_, bd, AT = (modules(m) for m in ("edit_actions", "records_edit", "books_data", "account_types"))
    assert AT.group_of("home") == "property" and AT.coarse("vehicle") == "property" and not AT.owed("home")
    assert ea.account_add(ADULT, "Our house", "home")[0]
    assert ea.account_add(ADULT, "Highlander", "vehicle")[0]
    assert ea.account_add(ADULT, "Checking", "checking", "4821")[0]
    home, car, chk = (q(root, "SELECT id FROM accounts WHERE name=?", n)[0][0] for n in ("Our house", "Highlander", "Checking"))
    assert re_.values("accounts", home)["group"] == "property"
    base = {k: "" for k in ("institution", "ownership", "owners", "closed_on", "credit_limit", "apr", "due_day", "min_payment")}
    ok, msg, _ = re_.edit(ADULT, "accounts", "save", home, {**base, "name": "Our house", "kind": "home", "value": "450000"})
    assert ok, msg
    assert q(root, "SELECT balance, kind FROM account_balances WHERE account_id=?", home) == [(450000, "estimate")]
    assert re_.values("accounts", home)["value"] == "450000"
    assert ea.account_update(ADULT, home, value="450000")[1] == "Nothing changed.", "the same value twice is not a change"
    assert ea.account_update(ADULT, chk, value="10")[0] is False, "only property takes a value by hand"
    assert ea.account_update(ADULT, car, value="-5")[0] is False
    assert ea.account_update(ADULT, car, value="31000")[0]
    assert ea.loan_add(ADULT, "Home mortgage", "mortgage", "Rocket", "286400", "6.1", "2231")[0]
    assert ea.loan_add(ADULT, "Car loan", "auto", "Toyota", "14220", "4.9", "512")[0]
    con = modules("db").connect(modules("paths").DB, readonly=True)
    try:
        o = bd.overview(con, TODAY)
        prop = [g for g in o["groups"] if g["key"] == "property"][0]
        assert prop["label"] == "Home and property" and prop["total"] == 481000
        assert [g["key"] for g in o["groups"]].index("property") < [g["key"] for g in o["groups"]].index("loan")
        assert o["have"] == 481000 and o["owe"] == round(286400 + 14220, 2) and o["net"] == round(481000 - 300620, 2)
        rows = {r["name"]: r for g in o["groups"] for r in g["rows"]}
        assert rows["Our house"]["match"]["text"].startswith("Your estimate")
        hf = dict(bd.account(con, home, TODAY)["facts"])
        assert hf == {"Value (your estimate)": "$450,000", "Owed against it": "$286,400", "Equity": "$163,600"}
        cf = dict(bd.account(con, car, TODAY)["facts"])
        assert cf["Owed against it"] == "$14,220" and cf["Equity"] == "$16,780"
    finally:
        con.close()
    fd = modules("finance_data")
    cash, invested, owed = fd.keep_split([{"type": "checking", "signed_balance": 100}, {"type": "property", "signed_balance": 450000}])
    assert (cash, invested, owed) == (100, 0, 0), "the old Keep page leaves property out"
