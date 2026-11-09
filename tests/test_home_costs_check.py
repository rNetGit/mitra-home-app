"""Home costs (data/home_costs.py) and the month check (data/month_check.py), then both pages."""
import datetime as dt
import sqlite3

import pytest


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT, type TEXT, last4 TEXT);
        CREATE TABLE bills(id INTEGER PRIMARY KEY, name TEXT, amount REAL, due_date TEXT, status TEXT);
        CREATE TABLE transactions(id INTEGER PRIMARY KEY, account_id INT, txn_date TEXT, payee TEXT, amount REAL,
                                  category TEXT, txn_type TEXT, description TEXT,
                                  amount_cents INTEGER GENERATED ALWAYS AS (CAST(ROUND(COALESCE(amount, 0) * 100) AS INTEGER)) VIRTUAL);
        INSERT INTO accounts VALUES (1,'Main','checking','0001'), (2,'Visa','credit','0002'), (3,'Broker','investment','0003');
        INSERT INTO bills VALUES (1,'Water',60,'2026-09-20','due'), (2,'Power',90,'2026-09-12','paid'), (3,'Old',10,'2026-08-05','overdue');
    """)
    rows = [(1, "2026-08-02", "Employer", 3000, None, "income"), (1, "2026-08-03", "Landlord", -1000, "housing", "spend"),
            (1, "2026-08-10", "Duke", -100, "electric", "spend"), (1, "2026-08-11", "Acme Ins", -50, "home insurance", "spend"),
            (2, "2026-08-12", "Grocer", -200, "groceries", "spend"),
            (1, "2026-09-01", "Employer", 4000, None, "income"), (1, "2026-09-02", "Landlord", -1200, "housing", "spend"),
            (1, "2026-09-10", "Duke", -140, "electric", "spend"), (1, "2026-09-11", "Acme Ins", -50, "home insurance", "spend"),
            (1, "2026-09-12", "Car Ins", -80, "auto insurance", "spend"), (1, "2026-09-13", "Shop", -30, None, "spend")]
    con.executemany("INSERT INTO transactions(account_id, txn_date, payee, amount, category, txn_type) VALUES (?,?,?,?,?,?)", rows)
    return con


def test_home_costs_series_groups_and_shares(modules):
    hc = modules("home_costs")
    r = hc.costs(_con(), "2026-09")
    assert r["month"] == "2026-09" and len(r["series"]) == 12 and r["months_counted"] == 2
    assert [s["total"] for s in r["series"][-2:]] == [1150, 1390], "housing + electric + home insurance only"
    assert r["this"] == 1390 and r["year"] == 2540 and r["avg"] == 1270 and r["vs_avg"] == 9
    assert r["share"] == round(2540 / 7000 * 100)
    by = {g["name"]: g for g in r["groups"]}
    assert set(by) == {"Housing", "Utilities", "Insurance"} and by["Housing"]["year"] == 2200
    assert [x["category"] for x in by["Insurance"]["rows"]] == ["home insurance"], "auto insurance is not a home cost"
    assert not any(s["rows"] for s in r["series"][:-2]), "months with no statements are marked, not zero costs"


def test_home_costs_none_without_data(modules):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE transactions(id INTEGER PRIMARY KEY, txn_date TEXT)")
    assert modules("home_costs").costs(con, None) is None


def test_month_check_items(modules):
    mc = modules("month_check")
    r = mc.checks(_con(), "2026-09", today=dt.date(2026, 11, 8))
    by = {i["key"]: i for i in r["lines"]}
    assert by["over"]["status"] == "ok"
    assert by["accounts"]["status"] == "todo" and "Visa (x0002)" in by["accounts"]["detail"], "the card had lines in August only"
    assert by["uncategorized"]["status"] == "todo" and "1 charge ($30)" in by["uncategorized"]["detail"]
    assert by["bills"]["status"] == "todo" and "1 bill ($60)" in by["bills"]["detail"], "only open bills due in September"
    assert by["cards"]["status"] == "ok" and not r["ready"] and r["todo"] == 3
    aug = {i["key"]: i for i in mc.checks(_con(), "2026-08", today=dt.date(2026, 11, 8))["lines"]}
    assert aug["accounts"]["status"] == "ok" and aug["bills"]["detail"].startswith("1 bill ($10)")
    run = mc.checks(_con(), "2026-11", today=dt.date(2026, 11, 8))
    assert {i["key"]: i for i in run["lines"]}["over"]["status"] == "todo", "a running month is never ready"


def test_month_check_ready_when_everything_is_clean(modules):
    con = _con()
    con.execute("DELETE FROM bills")
    con.execute("DELETE FROM transactions WHERE category IS NULL AND txn_type='spend'")
    con.execute("INSERT INTO transactions(account_id, txn_date, payee, amount, category, txn_type) VALUES (2,'2026-09-14','Grocer',-20,'groceries','spend')")
    r = modules("month_check").checks(con, "2026-09", today=dt.date(2026, 11, 8))
    assert r["ready"] and r["todo"] == 0


pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def test_pages_render_the_check_and_home_costs(root, modules):
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
                         (aid, "2026-09-02", "rent", "Landlord", -1200, "housing", "spend"),
                         (aid, "2026-09-10", "power", "Duke", -140, "electric", "spend")])
    con.close()
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    st = c.get("/money", params={"part": "statement", "ym": "2026-09"}).text
    assert "Month check" in st and "Nothing left uncategorized" in st and "The month is over" in st
    hc = c.get("/money", params={"part": "homecosts", "ym": "2026-09"}).text
    for text in ("Month by month", "Where it goes", "Average a month", "Housing", "Utilities", "Last 12 months"):
        assert text in hc
    assert 'aria-current="true">Home costs' in hc and ' style="' not in hc.split('id="hcosts"')[1]
    assert c.get("/money", params={"part": "homecosts", "ym": "junk"}).status_code == 200
