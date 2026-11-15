"""Money > Accounts as books, slice 2 (data/books_data.py, /money?part=books, /money/account/ID): grouping, totals,
the register's running balance walked back from the bank balance, statement-end lines and the bank-match check."""
import datetime as dt
import re

import pytest
from fastapi.testclient import TestClient

from conftest import db

TODAY = dt.date(2026, 11, 14)


def _add(root, name, typ, subtype, last4, lines=(), balances=(), **extra):
    con = db(root)
    cols = ["name", "type", "subtype", "last4", *extra]
    aid = con.execute(f"INSERT INTO accounts({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                      (name, typ, subtype, last4, *extra.values())).lastrowid
    con.executemany("INSERT INTO transactions(account_id, txn_date, description, amount, txn_type, category) VALUES (?,?,?,?,?,?)",
                    [(aid, d, desc, amt, t, cat) for d, desc, amt, t, cat in lines])
    con.executemany("INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?,?,?,?)",
                    [(aid, d, b, k) for d, b, k in balances])
    con.commit()
    con.close()
    return aid


@pytest.fixture(scope="module")
def books(root, modules):
    con = db(root)  # the demo household's accounts would change the totals: start from none
    for t in ("transactions", "account_balances"):
        con.execute(f"DELETE FROM {t}")
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if t != "accounts" and "account_id" in {r[1] for r in con.execute(f"PRAGMA table_info({t})")}:
            con.execute(f"UPDATE {t} SET account_id=NULL") if t in ("bills", "loans", "investments") else \
                con.execute(f"DELETE FROM {t}")
    con.execute("DELETE FROM accounts")
    con.commit()
    con.close()
    chk = _add(root, "Everyday Checking", "checking", "checking", "4821", lines=[
        ("2026-10-27", "Pay", 2410.00, "income", "Salary"),
        ("2026-10-30", "Internet", -79.99, "utility", "Internet"),
        ("2026-11-01", "Pay", 3120.55, "income", "Salary"),
        ("2026-11-03", "Mortgage", -2231.00, "loan_payment", None),
        ("2026-11-10", "Power", -131.42, "utility", "Utilities"),
        ("2026-11-13", "Card payment", -1200.00, "card_payment", None),
        ("2026-11-14", "Grocer", -142.37, "spend", "Groceries")],
        balances=[("2026-10-26", 290.32, "statement_end"), ("2026-10-31", 2620.33, "statement_end"),
                  ("2026-11-13", 2178.46, "snapshot")],
        ownership="joint", owners="Ann, Bo", institution="Chase")
    card = _add(root, "Gold Card", "credit", "credit_card", "1004", lines=[
        ("2026-10-26", "Grocer", -118.40, "spend", "Groceries"),
        ("2026-11-05", "Airline", -689.40, "spend", "Travel"),
        ("2026-11-13", "Payment", 1200.00, "card_payment", None)],
        balances=[("2026-10-25", 1000.00, "statement_end"), ("2026-10-28", 1100.00, "statement_end"),
                  ("2026-11-13", 707.80, "snapshot")],
        credit_limit=15000, due_day=22, min_payment=40, apr_pct=24.99, institution="American Express")
    sav = _add(root, "Family Savings", "savings", "savings", "9012", balances=[("2026-11-13", 18500.00, "snapshot")])
    mort = _add(root, "Home mortgage", "loan", "mortgage", "5532", balances=[("2026-11-01", 286400.00, "statement_end")],
                apr_pct=6.1, due_day=1)
    term = _add(root, "Term life", "investment", "life_term", None)
    old = _add(root, "Old checking", "checking", "checking", "1111", balances=[("2026-01-31", 50.0, "statement_end")],
               closed_on="2026-02-01")
    none = _add(root, "New brokerage", "investment", "brokerage", "7713")
    return {"chk": chk, "card": card, "sav": sav, "mort": mort, "term": term, "old": old, "none": none}


def _con(modules):
    return modules("db").connect(modules("paths").DB, readonly=True)


def test_groups_totals_and_match_counts(books, modules):
    bd = modules("books_data")
    con = _con(modules)
    try:
        o = bd.overview(con, TODAY)
    finally:
        con.close()
    assert [g["key"] for g in o["groups"]] == ["bank", "card", "investment", "insurance", "loan"]
    bank = o["groups"][0]
    assert [r["name"] for r in bank["rows"]] == ["Everyday Checking", "Family Savings"], "closed accounts left out"
    assert bank["total"] == round(2178.46 + 18500, 2)
    assert o["have"] == round(2178.46 + 18500, 2) and o["owe"] == round(707.80 + 286400, 2)
    assert o["net"] == round(o["have"] - o["owe"], 2) and o["closed"] == 1
    card = o["groups"][1]["rows"][0]
    assert card["used_pct"] == 5 and card["due"] == "2026-11-22"
    st = {r["name"]: r["match"]["status"] for g in o["groups"] for r in g["rows"]}
    assert st["Everyday Checking"] == "ok" and st["Gold Card"] == "off" and st["Family Savings"] == "sync"
    assert st["New brokerage"] == "none" and st["Home mortgage"] == "sync"
    assert any("Gold Card" in n["text"] and "off" in n["text"] for n in o["needs"])
    assert [r["term"] for r in o["groups"][3]["rows"]] == [True]
    con = _con(modules)
    try:
        assert "Old checking" in [r["name"] for r in bd.overview(con, TODAY, closed=True)["groups"][0]["rows"]]
    finally:
        con.close()


def test_register_walks_back_from_the_bank_balance(books, modules):
    bd = modules("books_data")
    con = _con(modules)
    try:
        v = bd.account(con, books["chk"], TODAY)
        c = bd.account(con, books["card"], TODAY)
        assert bd.account(con, 999999, TODAY) is None
    finally:
        con.close()
    reg = v["register"]
    lines = [x for x in reg if "stmt" not in x]
    assert [x["desc"] for x in lines][:2] == ["Grocer", "Card payment"], "newest first"
    # the newest bank balance is 2178.46 on Nov 13; the Nov 14 line comes after it
    assert lines[0]["after"] == round(2178.46 - 142.37, 2) and lines[1]["after"] == 2178.46
    stmts = [x for x in reg if "stmt" in x]
    assert [(s["stmt"], s["ok"]) for s in stmts] == [("2026-10-31", True), ("2026-10-26", True)]
    assert reg.index(stmts[0]) == [i for i, x in enumerate(reg) if x.get("date") == "2026-10-30"][0] - 1, \
        "the statement line sits just above its last day's lines"
    assert v["a"]["match"]["status"] == "ok" and v["running"]
    facts = dict(v["facts"])
    assert facts["Money in · Nov"] == "$3,120.55" and facts["Money out · Nov"] == "$273.79"
    assert facts["Moved to or from your accounts · Nov"] == "$3,431.00"
    # a card shows what is owed: a charge raises it, a payment lowers it
    cl = [x for x in c["register"] if "stmt" not in x]
    assert [x["after"] for x in cl] == [707.80, 1907.80, 1218.40]
    assert c["a"]["match"]["status"] == "off" and "Off by $18.40" in c["a"]["match"]["text"]
    assert dict(c["facts"])["Credit limit"] == "$15,000" and dict(c["facts"])["Payment due"] == "2026-11-22"


@pytest.fixture(scope="module")
def client(root, modules, books):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    sessions = modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    yield lambda: TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    sessions.clear()


def test_pages(client, books):
    kid = client()
    assert kid.get("/money?part=books").status_code == 303, "needs a session"
    kid.post("/login", data={"name": "Kid", "pin": "0000"})
    assert "Everyday Checking" not in kid.get("/money/account/%d" % books["chk"]).text, "adults only"
    c = client()
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    html = c.get("/money?part=books").text
    assert 'aria-current="true">Accounts</a>' in html
    for name in ("Everyday Checking", "Gold Card", "Home mortgage", "Life insurance", "Mortgage and loans", "Joint"):
        assert name in html, name
    assert "Old checking" not in html and "Show 1 closed account" in html
    assert "Old checking" in c.get("/money?part=books&closed=1").text
    page = c.get("/money/account/%d" % books["chk"]).text
    assert "Matches bank" in page and "Statement ended 2026-10-31" in page and "$2,036.09" in page
    assert re.search(r'href="/records\?ref=accounts%3A\d+"', page), "Edit account opens the record's edit form"
    assert "Off by $18.40" in c.get("/money/account/%d" % books["card"]).text
    gone = c.get("/money/account/999999")
    assert gone.status_code == 303 and gone.headers["location"] == "/money?part=books"
    assert "not there any more" in c.get("/money?part=books").text, "the message shows once on Accounts"
