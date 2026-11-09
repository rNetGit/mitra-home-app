"""Money plans: paying loans off sooner (arithmetic on the balance, rate and payment on file)."""
import datetime as D

from conftest import db


def test_payoff_matches_the_closed_form_and_extra_pays_off_sooner(modules):
    ln = modules("loans")
    months, interest = ln.payoff(10000, 6.0, 200)
    assert months == ln.months_left(10000, 6.0, 200) == 58
    assert 1500 < interest < 1600
    assert ln.payoff(1000, 0, 100) == (10, 0.0), "no interest: balance / payment"
    assert ln.payoff(10000, 24.0, 150) is None, "the payment never covers the interest"
    assert ln.payoff(None, 5, 100) is None and ln.payoff(1000, 5, 0) is None
    plan = ln.payoff_plan(10000, 6.0, 200, today=D.date(2030, 1, 15))
    assert [p["extra"] for p in plan] == [0, 50, 100, 250]
    assert plan[0]["months_sooner"] == 0 and plan[0]["paid_off"] == D.date(2034, 11, 1)
    assert all(a["months"] > b["months"] and a["interest"] > b["interest"] for a, b in zip(plan, plan[1:]))
    assert plan[1]["interest_saved"] == round(plan[0]["interest"] - plan[1]["interest"], 2)
    stuck = ln.payoff_plan(10000, 24.0, 150, today=D.date(2030, 1, 15))
    assert [p["extra"] for p in stuck] == [100, 250] and stuck[0]["months_sooner"] is None


def test_budget_page_shows_paying_off_sooner(root, modules):
    fd = modules("finance_data")
    with db(root) as con:
        con.execute("INSERT INTO loans(name, lender, kind, balance, rate_pct, payment, status) "
                    "VALUES ('Plan test car', 'Bank', 'auto', 10000, 6.0, 200, 'active')")
        con.commit()
        v = fd.budget(con, D.date(2030, 1, 15), {})
    blk = [b for b in v["blocks"] if b["heading"] == "Paying loans off sooner"][0]
    mine = [r["cells"] for r in blk["rows"] if r["cells"][0] == "Plan test car"]
    assert mine[0][1] == "$200 (now)" and mine[0][2] == "Nov 2034" and mine[1][1] == "$250 (+$50)"
    assert "months" in mine[1][4] and blk["fold"]
    assert any("not advice" in t for _, t in v["notes"])
