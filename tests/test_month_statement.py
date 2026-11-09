"""Month statement (data/month_statement.py, Money > Statement): income, grouped expenses, variance, the page."""
import sqlite3

import pytest


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE accounts(id INTEGER PRIMARY KEY, type TEXT);
        CREATE TABLE budget(category TEXT, monthly_limit REAL);
        CREATE TABLE transactions(id INTEGER PRIMARY KEY, account_id INT, txn_date TEXT, payee TEXT, amount REAL,
                                  category TEXT, txn_type TEXT, description TEXT,
                                  amount_cents INTEGER GENERATED ALWAYS AS (CAST(ROUND(COALESCE(amount, 0) * 100) AS INTEGER)) VIRTUAL);
        INSERT INTO accounts VALUES (1,'checking');
        INSERT INTO budget VALUES ('groceries', 250), ('allowance:Kid', 20), ('fuel', 100);
    """)
    rows = [("2026-08-02", "Employer", 3000, None, "income"), ("2026-08-03", "Landlord", -1000, "housing", "spend"),
            ("2026-08-09", "Grocer", -200, "groceries", "spend"),
            ("2026-09-01", "Employer", 4000, None, "income"), ("2026-09-02", "Landlord", -1200, "housing", "spend"),
            ("2026-09-05", "Costco", -300, "groceries", "spend"), ("2026-09-06", "Power Co", -100, "electric", "spend"),
            ("2026-09-07", "Bistro", -60, "dining", "spend")]
    con.executemany("INSERT INTO transactions(account_id, txn_date, payee, amount, category, txn_type) VALUES (1,?,?,?,?,?)", rows)
    return con


def test_group_of_puts_home_insurance_with_insurance_not_housing(modules):
    ms = modules("month_statement")
    assert ms.group_of("Home insurance") == "Insurance" and ms.group_of("auto loan") == "Loans"
    assert ms.group_of("personal care") == "Other" and ms.group_of("Car insurance") == "Insurance" and ms.group_of("gasoline") == "Transport"
    assert ms.group_of("rental") == "Housing" and ms.group_of("business") == "Other" and ms.group_of("electric") == "Utilities"
    assert ms.group_of("rent") == "Housing" and ms.group_of("groceries") == "Food" and ms.group_of("zzz") == "Other"


def test_statement_figures_groups_and_reasons(modules):
    ms = modules("month_statement")
    s = ms.statement(_con(), "2026-09")
    assert (s["income"]["now"], s["income"]["prev"], s["income"]["ly"]) == (4000, 3000, None)
    assert s["income"]["lines"] == [{"payee": "Employer", "amount": 4000}]
    assert (s["expenses"]["now"], s["expenses"]["prev"]) == (1660, 1200) and s["unitemised"] == 0
    assert s["net"] == 2340 and s["left"] == 2340 and s["have"] == {"prev": True, "ly": False}
    by = {g["name"]: g for g in s["groups"]}
    assert [g["name"] for g in s["groups"]] == ["Housing", "Food", "Utilities"], "biggest group first"
    assert by["Food"]["now"] == 360 and by["Food"]["prev"] == 200 and by["Housing"]["prev"] == 1000
    rows = {r["category"]: r for r in s["variance"]}
    assert "groceries" in rows and "housing" not in rows, "a 20% move is not a big swing"
    g = rows["groceries"]
    assert g["limit"] == 250 and g["over"] == 50 and g["change"] == 100
    assert "Up $100 on Aug." in g["reason"] and "Over the $250 budget by $50." in g["reason"] and "Costco $300" in g["reason"]
    assert rows["dining"]["reason"].startswith("New this month.")
    assert "fuel" in rows and rows["fuel"]["now"] == 0 and rows["fuel"]["over"] == -100, "a budget line with no spending still shows"
    assert "allowance:Kid" not in rows and s["budget_total"] == 350


def test_first_month_has_no_new_labels_and_empty_data_is_none(modules):
    ms = modules("month_statement")
    aug = ms.statement(_con(), "2026-08")
    assert aug["have"] == {"prev": False, "ly": False} and aug["groups"][0]["prev"] == 0
    assert not any("New this month" in r["reason"] for r in aug["variance"])
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE transactions(id INTEGER PRIMARY KEY, txn_date TEXT)")
    assert ms.statement(con, None) is None


pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def test_statement_page_and_month_switch(root, modules):
    auth, config, paths = modules("auth"), modules("config"), modules("paths")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")}]
    config.write_json(root / "config" / "family.json", fam)
    con = sqlite3.connect(paths.DB)
    with con:
        aid = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Main','checking','0001')").lastrowid
        con.executemany("INSERT INTO transactions(account_id, txn_date, description, payee, amount, category, txn_type) "
                        "VALUES (?,?,?,?,?,?,?)",
                        [(aid, "2026-08-02", "pay", "Employer", 3000, None, "income"),
                         (aid, "2026-08-03", "rent", "Landlord", -1000, "housing", "spend"),
                         (aid, "2026-09-01", "pay", "Employer", 4000, None, "income"),
                         (aid, "2026-09-05", "food", "Grocer <b>", -300, "groceries", "spend"),
                         (aid, "2026-09-06", "rent", "Landlord", -1200, "housing", "spend")])
    con.close()
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/money", params={"part": "statement", "ym": "2026-09"}).text
    for text in ("Home income statement", "Total income", "Total expenses", "Housing", "Food", "Budget and what moved", "Left over"):
        assert text in page
    assert 'href="/money?part=statement"' in page and 'aria-current="true">Statement' in page
    assert 'href="/money?part=statement&amp;ym=2026-08"' in page and "Employer" in page
    assert ' style="' not in page.split('id="mst"')[1], "the CSP blocks inline styles"
    aug = c.get("/money", params={"part": "statement", "ym": "2026-08"}).text
    assert '<option value="2026-08" selected>' in aug and "$3,000" in aug and "$4,000" not in aug
    assert c.get("/money", params={"part": "statement", "ym": "junk"}).status_code == 200
