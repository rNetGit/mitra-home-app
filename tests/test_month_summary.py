"""The This month summary card: month_summary figures, month picker, and the page."""
import sqlite3

import pytest


def _con():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE accounts(id INTEGER PRIMARY KEY, type TEXT);
        CREATE TABLE transactions(id INTEGER PRIMARY KEY, account_id INT, txn_date TEXT, payee TEXT, amount REAL,
                                  category TEXT, txn_type TEXT, description TEXT,
                                  amount_cents INTEGER GENERATED ALWAYS AS (CAST(ROUND(COALESCE(amount, 0) * 100) AS INTEGER)) VIRTUAL);
        INSERT INTO accounts VALUES (1,'checking');
    """)
    rows = [("2026-08-02", "Employer", 3000, None, "income"), ("2026-08-03", "Landlord", -1000, "housing", "spend"),
            ("2026-09-01", "Employer", 4000, None, "income"), ("2026-09-02", "Landlord", -1200, "housing", "spend"),
            ("2026-09-05", "Grocer", -300, "groceries", "spend"), ("2026-09-06", "Grocer", -100, "groceries", "spend"),
            ("2026-09-07", "Broker", -500, None, "investment_transfer"), ("2026-09-08", "Own savings", -50, None, "transfer")]
    con.executemany("INSERT INTO transactions(account_id, txn_date, payee, amount, category, txn_type) VALUES (1,?,?,?,?,?)", rows)
    return con


def test_month_summary_figures(root, modules):
    trends = modules("trends")
    s = trends.month_summary(_con(), "2026-09")
    assert (s["income"], s["spent"], s["invested"], s["left"]) == (4000, 1600, 500, 1900)
    assert [c["category"] for c in s["categories"]] == ["housing", "groceries"]
    assert s["categories"][0]["pct"] == 75.0 and s["n"] == 3
    assert s["vs_prev"] == pytest.approx(60.0)
    assert s["biggest"]["amount"] == 300 and s["merchant"] == {"payee": "Grocer", "n": 2, "amount": 400}, "everyday spending only"
    assert (s["fixed"], s["flexible"], s["saved"]) == (1200, 400, 500)
    assert s["categories"][1]["change"] is None and s["categories"][0]["change"] == pytest.approx(20.0)
    assert s["older"] == "2026-08" and s["newer"] is None and s["sources"] == [{"payee": "Employer", "amount": 4000}]
    assert [m for m, _ in s["months"]] == ["2026-09", "2026-08"]


def test_month_summary_unknown_month_falls_back_and_empty_is_none(root, modules):
    trends = modules("trends")
    assert trends.month_summary(_con(), "1999-01")["month"] == "2026-09"
    empty = sqlite3.connect(":memory:")
    assert trends.month_summary(empty, None) is None


def test_month_summary_counts_savings_transfers_and_paces_a_running_month(root, modules):
    import datetime as dt
    trends = modules("trends")
    con = _con()
    con.execute("INSERT INTO accounts VALUES (2,'savings')")
    con.executemany("INSERT INTO transactions(account_id, txn_date, payee, amount, category, txn_type) VALUES (?,?,?,?,?,?)",
                    [(2, "2026-09-08", "From checking", 50, None, "transfer"),
                     (1, "2026-10-01", "Employer", 4000, None, "income"), (1, "2026-10-05", "Grocer", -200, "groceries", "spend")])
    s = trends.month_summary(con, "2026-09", today=dt.date(2026, 10, 10))
    assert (s["saved"], s["to_savings"], s["left"]) == (550, 50, 1850)
    oct_ = trends.month_summary(con, "2026-10", today=dt.date(2026, 10, 10))
    assert oct_["partial"] and oct_["projected"] == pytest.approx(620.0) and oct_["pace_vs_prev"] == pytest.approx(-61.3)
    assert [h["month"] for h in oct_["history"]][-2:] == ["2026-09", "2026-10"] and oct_["newer"] is None


pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def test_month_page_shows_the_story_card_and_switches_month(root, modules):
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
                         (aid, "2026-09-05", "food", "Grocer <b>", -300, "groceries", "spend")])
    con.close()
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/money", params={"part": "month", "ym": "2026-09"}).text
    assert 'data-story' in page and page.count('class="slide ') == 5
    for part in ("Overview", "Cash flow", "Where it went", "Six months", "Highlights", "All categories, Sep 2026"):
        assert part in page
    assert 'href="/money?part=month&amp;ym=2026-08"' in page and "Grocer &lt;b&gt;" in page and "Grocer <b>" not in page
    assert ' style="' not in page.split('id="msum"')[1].split('<div class="mgrid">')[0], "the CSP blocks inline styles"
    aug = c.get("/money", params={"part": "month", "ym": "2026-08"}).text
    assert '<option value="2026-08" selected>' in aug and "Landlord" in aug
