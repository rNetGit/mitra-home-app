"""Money > All accounts (data/all_accounts.py, /money?part=all): every account as one by day / week / month, own
transfers paired and counted once, loan payments once in Money out, group filter, net worth from balances."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient

from conftest import db

TODAY = dt.date(2026, 11, 14)  # a Saturday: the week is Mon Nov 9 to Sun Nov 15


@pytest.fixture(scope="module")
def ids(root):
    con = db(root)
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        if t != "accounts" and "account_id" in {r[1] for r in con.execute(f"PRAGMA table_info({t})")}:
            con.execute(f"UPDATE {t} SET account_id=NULL" if t == "bills" else f"DELETE FROM {t}")
    con.execute("DELETE FROM accounts")

    def acct(name, typ, sub):
        return con.execute("INSERT INTO accounts(name, type, subtype) VALUES (?,?,?)", (name, typ, sub)).lastrowid
    chk, card = acct("Checking", "checking", "checking"), acct("Gold Card", "credit", "credit_card")
    sav, mort = acct("Savings", "savings", "savings"), acct("Mortgage", "loan", "mortgage")
    con.executemany("INSERT INTO transactions(account_id, txn_date, description, amount, txn_type, category) VALUES (?,?,?,?,?,?)", [
        (chk, "2026-11-08", "Coffee", -5, "spend", "Dining"),
        (chk, "2026-11-10", "Pay", 3000, "income", "Salary"),
        (chk, "2026-11-11", "Card payment", -500, "card_payment", None),
        (chk, "2026-11-12", "To savings", -200, "transfer", None),
        (chk, "2026-11-13", "Mortgage payment", -2231, "loan_payment", None),
        (chk, "2026-11-14", "Grocer", -100, "spend", "Groceries"),
        (chk, "2026-11-14", "Venmo to Sam", -50, "transfer", None),
        (card, "2026-11-10", "Shoes", -80, "spend", "Clothing"),
        (card, "2026-11-12", "Payment thank you", 500, "card_payment", None),
        (card, "2026-11-13", "Refund", 20, "spend", "Clothing"),
        (sav, "2026-11-12", "From checking", 200, "transfer", None),
        (sav, "2026-11-15", "Interest", 3, "interest", "Interest"),
        (mort, "2026-11-13", "Payment received", 2231, "loan_payment", None)])
    con.executemany("INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?,?,?,?)", [
        (chk, "2026-11-08", 1000, "snapshot"), (chk, "2026-11-15", 1500, "snapshot"),
        (card, "2026-11-08", 300, "snapshot"), (sav, "2026-11-08", 5000, "snapshot")])
    con.commit()
    con.close()
    return {"chk": chk, "card": card, "sav": sav, "mort": mort}


def _view(modules, **kw):
    aa = modules("all_accounts")
    con = modules("db").connect(modules("paths").DB, readonly=True)
    try:
        return aa.view(con, TODAY, **kw)
    finally:
        con.close()


def test_periods(modules):
    aa = modules("all_accounts")
    assert aa.bounds("week", TODAY) == (dt.date(2026, 11, 9), dt.date(2026, 11, 15))
    assert aa.bounds("month", TODAY) == (dt.date(2026, 11, 1), dt.date(2026, 11, 30))
    assert aa.bounds("month", dt.date(2026, 12, 31)) == (dt.date(2026, 12, 1), dt.date(2026, 12, 31))
    assert aa.bounds("day", TODAY) == (TODAY, TODAY)


def test_week_pairs_moves_and_counts_each_once(ids, modules):
    v = _view(modules)
    assert (v["start"], v["end"], v["label"]) == ("2026-11-09", "2026-11-15", "Nov 9 – 15, 2026")
    assert v["money_in"] == 3023 and v["money_out"] == 2411 and v["moved"] == 750
    assert v["prev"] == "2026-11-02" and v["next"] == "2026-11-16" and v["future"]
    items = [it for d in v["days"] for it in d["items"]]
    pairs = [(it["from"]["name"], it["to"]["name"], it["amount"], it["kind"]) for it in items if it["kind"] in ("moved", "loan")]
    assert sorted(pairs) == sorted([("Checking", "Gold Card", 500, "moved"), ("Checking", "Savings", 200, "moved"),
                                    ("Checking", "Mortgage", 2231, "loan")])
    assert [it["desc"] for it in items if it["kind"] == "moved1"] == ["Venmo to Sam"]
    assert "Coffee" not in [it["desc"] for it in items], "Nov 8 is last week"
    assert [d["date"] for d in v["days"]] == sorted((d["date"] for d in v["days"]), reverse=True)
    nov13 = [d for d in v["days"] if d["date"] == "2026-11-13"][0]
    assert nov13["net"] == round(20 - 2231, 2)
    assert v["net_start"] == 5700 and v["net_end"] == 6200 and v["net_change"] == 500 and v["spark"]


def test_filters_day_and_month(ids, modules):
    card = _view(modules, group="card")
    assert card["money_in"] == 20 and card["money_out"] == 80 and card["moved"] == 500
    day = _view(modules, period="day", day="2026-11-13")
    assert day["money_out"] == 2231 and day["money_in"] == 20 and day["moved"] == 0 and day["spark"] == ""
    month = _view(modules, period="month")
    assert month["money_out"] == 2416 and month["label"] == "November 2026"
    assert (month["net_since"], month["net_start"], month["net_change"]) == ("2026-11-08", 5700, 500), \
        "no balance before the month: measured from the first day that has one"
    assert _view(modules, period="bogus", day="not-a-date")["period"] == "week"


def test_page(root, modules, ids):
    auth, config = modules("auth"), modules("config")
    app_mod, sessions = modules("webapp.app"), modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")}]
    config.write_json(root / "config" / "family.json", fam)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    assert c.get("/money?part=all").status_code == 303
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    html = c.get("/money?part=all&period=week&d=2026-11-14").text
    assert 'aria-current="true">All accounts</a>' in html and "Moved between your accounts" in html
    assert "Nov 9 – 15, 2026" in html and "Venmo to Sam" in html and "Gold Card" in html
    assert "Nothing happened" in c.get("/money?part=all&period=day&d=2020-01-01").text
    sessions.clear()
