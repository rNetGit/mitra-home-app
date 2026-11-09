"""Budget vs actual, live: pace (red/amber/green up to the newest loaded transaction), suggested limits, allowance
lines, the CLI, the digest line and the dashboard tab. No AI, no migration."""
import datetime as D

import pytest

from conftest import db, q, run

TODAY = D.date(2026, 10, 20)  # October has 31 days
CLOCK = {"MITRAHOME_TODAY": TODAY.isoformat()}  # the command line reads the clock too: pin it to the same day


def _txn(root, date, desc, amount, cat, typ=None):
    con = db(root)
    acct = con.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) VALUES (?,?,?,?,?,?)",
                (acct, date, desc, amount, cat, typ))
    con.commit()
    con.close()


@pytest.fixture(scope="module")
def bud(root, modules):
    con = db(root)
    con.execute("DELETE FROM budget")
    con.execute("DELETE FROM transactions WHERE txn_date >= '2026-04-01'")
    con.commit()
    con.close()
    # six full months of dining (Apr..Sep 2026), 80..130, and petrol in three of them
    for i, m in enumerate(range(4, 10)):
        _txn(root, f"2026-{m:02d}-10", "DINER", -(80 + 10 * i), "dining")
        if m in (5, 7, 9):
            _txn(root, f"2026-{m:02d}-12", "FUEL STOP", -50.0, "petrol")
    _txn(root, "2026-09-15", "SALARY", 3000.0, "salary", "income")
    _txn(root, "2026-09-16", "CARD PAYMENT", -400.0, "card", "card_payment")
    # October so far: statement loaded through the 10th
    _txn(root, "2026-10-03", "DINER", -60.0, "dining")
    _txn(root, "2026-10-08", "GROCER", -140.0, "groceries")
    _txn(root, "2026-10-10", "TOYS", -25.0, "allowance:Sam")
    _txn(root, "2026-10-10", "FUEL STOP", -20.0, "petrol")
    b = modules("budget")
    con = db(root)
    for c, lim in (("dining", 150.0), ("groceries", 500.0), ("petrol", 40.0), ("allowance:Sam", 30.0)):
        con.execute("INSERT INTO budget(category, monthly_limit) VALUES (?,?)", (c, lim))
    con.commit()
    con.close()
    return b


def test_pace_measures_up_to_the_newest_loaded_transaction(root, bud):
    con = db(root)
    try:
        p = bud.pace(con, TODAY)
    finally:
        con.close()
    assert p["month"] == "2026-10" and p["through"] == D.date(2026, 10, 10) and p["day"] == 10 and p["days"] == 31 and p["loaded"]
    by = {r["category"]: r for r in p["lines"]}
    d = by["dining"]  # 60 spent of 150 by day 10: expected 48.39, projected 186 -> amber
    assert d["spent"] == 60.0 and d["expected"] == 48.39 and d["projected"] == 186.0 and d["status"] == "amber" and d["pct"] == 40
    g = by["groceries"]  # 140 of 500, projected 434 -> green
    assert g["status"] == "green" and g["projected"] == 434.0
    assert by["petrol"]["status"] == "amber" and by["petrol"]["spent"] == 20.0 and by["petrol"]["projected"] == 62.0
    a = by["allowance:Sam"]
    assert a["allowance"] and a["label"] == "Sam's allowance" and a["status"] == "amber"
    assert [r["allowance"] for r in p["lines"]][-1] is True, "allowance lines last"
    _txn(root, "2026-10-12", "DINER", -100.0, "dining")  # now 160 of 150 -> red, and the month runs through the 12th
    con = db(root)
    try:
        p = bud.pace(con, TODAY)
        assert p["through"] == D.date(2026, 10, 12)
        assert [r["category"] for r in p["lines"] if r["status"] == "red"] == ["dining"]
        assert p["lines"][0]["category"] == "dining", "red first"
        # a month with nothing loaded: day 1, nothing spent, all green, loaded False
        p2 = bud.pace(con, D.date(2026, 12, 20))
        assert not p2["loaded"] and p2["day"] == 1 and all(r["status"] == "green" and r["spent"] == 0 for r in p2["lines"])
    finally:
        con.close()


def test_suggest_uses_six_full_months(root, bud):
    con = db(root)
    try:
        s = {r["category"]: r for r in bud.suggest(con, TODAY)}
    finally:
        con.close()
    assert set(s) == {"dining", "petrol"}, set(s)  # groceries only in October, not a full month yet
    d = s["dining"]  # (80+90+100+110+120+130)/6 = 105 -> suggest 110, limit 150 -> change -40
    assert d["months"] == 6 and d["average"] == 105.0 and d["suggested"] == 110.0 and d["limit"] == 150.0 and d["change"] == -40.0
    p = s["petrol"]  # 150 over 6 months = 25 -> 30; current 40
    assert p["months"] == 3 and p["average"] == 25.0 and p["suggested"] == 30.0 and p["change"] == -10.0
    assert "salary" not in s and "card" not in s and not any(k.startswith("allowance:") for k in s)
    assert [r["category"] for r in bud.suggest(db(root), TODAY)][0] == "dining", "largest average first"


def test_digest_line_and_report(root, bud):
    con = db(root)
    try:
        line = bud.digest_line(con, TODAY)
    finally:
        con.close()
    assert line.startswith("Budget, October so far (through Oct 12): over: **dining** $160.00 of $150.00; on course to pass: ")
    assert "Sam's allowance" in line and "on track" in line
    assert run(["data/make_digest.py"], root, env=CLOCK).returncode == 0
    out = next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")
    assert "## Budget this month" in out and "Budget, " in out
    r = run(["data/budget.py", "report", "2026-09"], root, env=CLOCK)
    assert r.returncode == 0 and "dining" in r.stdout and "Sam's allowance" in r.stdout


def test_cli(root, bud):
    r = run(["data/budget.py", "pace"], root, env=CLOCK)
    assert r.returncode == 0 and "RED" in r.stdout and "dining" in r.stdout, r.stdout
    r = run(["data/budget.py", "suggest"], root, env=CLOCK)
    assert r.returncode == 0 and "dining" in r.stdout and "suggest" in r.stdout
    r = run(["data/budget.py", "allowance", "Sam", "35"], root, env=CLOCK)
    assert r.returncode == 0 and q(root, "select monthly_limit from budget where category='allowance:Sam'") == [(35.0,)]
    assert run(["data/budget.py", "allowance", "Sam", "-1"], root, env=CLOCK).returncode != 0
    assert run(["data/budget.py", "allowance", "Sam"], root, env=CLOCK).returncode != 0
    assert run(["data/budget.py", "set", "dining", "abc"], root, env=CLOCK).returncode != 0
    assert run(["data/budget.py", "list"], root, env=CLOCK).returncode == 0
