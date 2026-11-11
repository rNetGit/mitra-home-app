"""Money trends (data/trends.py): month over month, this year against last year, categories; no AI."""
import datetime as dt
import sqlite3

import pytest

from conftest import run


def _fill(root):
    """Two years of made-up statements: a checking account (income + spend) and a card (its own lines + the payment)."""
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM transactions")
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Chk', 'checking', '1111'), ('Card', 'credit', '2222')")
    chk = con.execute("SELECT id FROM accounts WHERE name='Chk'").fetchone()[0]
    card = con.execute("SELECT id FROM accounts WHERE name='Card'").fetchone()[0]
    end = dt.date(2026, 9, 1)
    for k in range(24):
        y, m = (end.year * 12 + end.month - 1 - k) // 12, (end.year * 12 + end.month - 1 - k) % 12 + 1
        day = f"{y:04d}-{m:02d}-10"
        grow = 1.0 if k >= 12 else 1.2  # this year costs 20% more than last year
        rows = [(chk, day, "PAYROLL", 4000.0, "salary", "income"), (chk, day, "RENT", -1500.0 * grow, "housing", "spend"),
                (chk, day, "CARD PAYMENT", -600.0, None, "card_payment"), (chk, day, "TO SAVINGS", -300.0, None, "transfer"),
                (card, day, "GROCER", -400.0 * grow, "groceries", "spend"), (card, day, "FUEL", -200.0, "fuel", "spend")]
        con.executemany("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) VALUES (?,?,?,?,?,?)", rows)
    con.commit()
    con.close()


def test_monthly_counts_income_expenses_and_skips_internal_moves(root, modules):
    _fill(root)
    T, db = modules("trends"), modules("db")
    with db.open(readonly=True) as con:
        rows = T.monthly(con, 12)
        t = T.totals(rows)
    assert [r["month"] for r in rows][-1] == "2026-09" and len(rows) == 12
    last = rows[-1]
    assert last["income"] == 4000.0
    # card payment not counted (the card has its own lines); transfer never counted
    assert last["expenses"] == pytest.approx(1500 * 1.2 + 400 * 1.2 + 200)
    assert last["left"] == pytest.approx(4000 - last["expenses"])
    assert last["last_year"] == pytest.approx(1500 + 400 + 200) and last["vs_last_year"] == pytest.approx(18.1, abs=0.1)
    assert last["vs_prev"] == 0.0
    assert t["months"] == 12 and t["compared"] == 12 and t["this_year"] > t["last_year"]


def test_card_payment_counts_when_no_card_lines(root, modules):
    _fill(root)
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM transactions WHERE account_id=(SELECT id FROM accounts WHERE name='Card') AND txn_date LIKE '2026-09%'")
    con.commit()
    con.close()
    T, db = modules("trends"), modules("db")
    with db.open(readonly=True) as con:
        last = T.monthly(con, 12)[-1]
    assert last["expenses"] == pytest.approx(1500 * 1.2 + 600)


def test_categories_and_lines(root, modules):
    _fill(root)
    T, db = modules("trends"), modules("db")
    with db.open(readonly=True) as con:
        cats = T.categories(con, 12)
        said = T.lines(con, 12)
        md = T.markdown(con, 12)
    by = {c["category"]: c for c in cats}
    assert by["housing"]["pct"] == pytest.approx(20.0) and by["fuel"]["change"] == 0
    assert cats[0]["category"] == "housing"  # biggest move first
    assert said and "Sep 2026" in said[0] and any("Against Sep 2025" in l for l in said) and any("housing up 20%" in l for l in said)
    assert "| Sep 2026 |" in md and "Categories that moved most" in md


def test_empty_database_has_no_trends(root, modules):
    T, db = modules("trends"), modules("db")
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM transactions")
    con.commit()
    con.close()
    with db.open(readonly=True) as con:
        assert T.monthly(con) == [] and T.lines(con) == [] and "no transactions" in T.markdown(con)


def test_monthly_report_has_a_trends_section(root):
    _fill(root)
    r = run(["data/make_report.py", "monthly", "2026-09"], root)
    assert r.returncode == 0, r.stderr
    text = (root / "reports" / "2026-09_monthly.md").read_text(encoding="utf-8")
    assert "## Trends" in text and "| Sep 2026 |" in text and "| Oct 2025 |" in text


def test_cli_prints_the_table(root):
    _fill(root)
    r = run(["data/trends.py"], root)
    assert r.returncode == 0 and "| Sep 2026 |" in r.stdout
    r = run(["data/trends.py", "categories"], root)
    assert r.returncode == 0 and "housing" in r.stdout




def test_running_month_is_partial_and_gaps_are_not_zero_in_charts(root, modules):
    _fill(root)
    con = sqlite3.connect(root / "data" / "family.db")
    chk = con.execute("SELECT id FROM accounts WHERE name='Chk'").fetchone()[0]
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) VALUES (?,?,?,?,?,?)",
                (chk, "2026-10-03", "COFFEE", -20.0, "dining", "spend"))
    con.commit()
    con.close()
    T, db = modules("trends"), modules("db")
    with db.open(readonly=True) as con:
        rows = T.monthly(con, 12, today=dt.date(2026, 10, 13))
        done = T.monthly(con, 12, today=dt.date(2026, 11, 2))
    oct_ = rows[-1]
    assert oct_["month"] == "2026-10" and oct_["partial"] and oct_["vs_prev"] is None and oct_["vs_last_year"] is None
    assert not rows[-2]["partial"] and rows[-2]["vs_prev"] is not None
    assert T.totals(rows)["months"] == 11  # the running month is not a "typical month"
    assert not done[-1]["partial"]  # once the month is over it is compared like any other
    with db.open(readonly=True) as con:
        text = T.markdown(con, 12, "2026-10", today=dt.date(2026, 10, 13))
    assert "Oct 2026 (so far)" in text


def test_money_totals_are_summed_in_cents(root, modules):
    """D11: ten payments of $0.10 are $1.00 exactly (floats would give 0.9999999999999999) in Trends and the tax list."""
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM transactions")
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Cents', 'checking', '3131')")
    acct = con.execute("SELECT id FROM accounts WHERE name='Cents'").fetchone()[0]
    con.executemany("INSERT INTO transactions(account_id, txn_date, description, amount, payee, txn_type) VALUES (?,?,?,?,?,?)",
                    [(acct, f"2026-03-{d:02d}", f"INTEREST {d}", 0.1, "Bank", "interest") for d in range(1, 11)]
                    + [(acct, f"2026-03-{d:02d}", f"BROKER {d}", -0.1, "Broker", "investment_transfer") for d in range(1, 11)])
    con.commit()
    con.row_factory = sqlite3.Row
    s = modules("trends").month_summary(con, "2026-03", today=dt.date(2026, 4, 1))
    assert s["invested"] == 1.0 and [x["amount"] for x in s["sources"] if x["payee"] == "Bank"] == [1.0]
    assert con.execute("SELECT SUM(amount_cents)/100.0 FROM transactions WHERE txn_type='interest'").fetchone()[0] == 1.0
    out = modules("tax_prep").build(con, 2026)
    text = "\n".join(out) if isinstance(out, list) else str(out)
    assert "Bank interest credited (txn_type 'interest'): $1.00" in text, text[-800:]
    con.close()


def test_a_report_month_with_no_statements_does_not_crash(root, modules):
    """A fresh household: the weekly digest asks for last month's report, and none of the twelve listed months has a line."""
    T, db = modules("trends"), modules("db")
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM transactions")
    con.commit()
    con.close()
    with db.open(readonly=True) as con:
        assert T.lines(con, 12, "2026-10") == [] and "no transactions" in T.markdown(con, 12, "2026-10")
    r = run(["data/make_report.py", "monthly", "2026-10"], root)
    assert r.returncode == 0, r.stderr
    assert "no transactions" in (root / "reports" / "2026-10_monthly.md").read_text(encoding="utf-8")
