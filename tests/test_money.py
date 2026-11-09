"""Money as integer cents behind data/money.py (audit item 13): exact rounding, parsing, matching, generated columns."""
import csv
import sqlite3

import pytest

from conftest import db, q, run


def test_cents_rounding_and_equality(modules):
    m = modules("money")
    assert m.cents(0.1 + 0.2) == 30 and m.cents("12.345") == 1235 and m.cents(-2.005) == -201
    assert m.round2(0.1 + 0.2) == 0.3 and m.from_cents(1235) == 12.35
    assert m.eq(0.1 + 0.2, 0.3) and not m.eq(1.00, 1.01)
    assert m.total([0.1, 0.2, 0.3, None]) == 0.6
    assert m.total(0.01 for _ in range(1000)) == 10.0, "no drift over a long sum"
    with pytest.raises(ValueError):
        m.cents("abc")


@pytest.mark.parametrize("text, value", [("$1,234.56", 1234.56), ("1,234.56", 1234.56), ("1.234,56", 1234.56), ("(12.00)", -12.0),
                                         ("-12", -12.0), ("12.00 CR", -12.0), ("£40", 40.0), ("₹2,50,000", 250000.0), (7, 7.0), ("0.005", 0.01)])
def test_parse_amounts_people_type(modules, text, value):
    assert modules("money").parse(text) == value


def test_parse_refuses_non_amounts(modules):
    m = modules("money")
    for bad in ("", "abc", "$", None):
        with pytest.raises(ValueError):
            m.parse(bad)


def test_validator_rounds_and_ranges(modules):
    v = modules("validators")
    assert v.money(0, 1e7)("1,234.567") == 1234.57
    assert v.money()("$40") == 40.0
    for bad in (-1, "1e12", True, "soon"):
        with pytest.raises(ValueError):
            v.money(0, 1e9)(bad)


def test_edits_store_whole_cents(root, modules):
    ea = modules("edit_actions")
    ok, _ = ea.budget_set({"name": "Alex", "role": "adult"}, "cents-test", 0.1 + 0.2)
    assert ok and q(root, "select monthly_limit from budget where category='cents-test'") == [(0.3,)]
    ok, _ = ea.loan_add({"name": "Alex", "role": "adult"}, "Cents loan", "auto", "Bank", "8,200.005", 5.9, "310.4")
    assert ok and q(root, "select balance, payment from loans where name='Cents loan'") == [(8200.01, 310.4)]


def test_generated_cent_columns_exist_and_track_amount(root):
    con = db(root)
    con.execute("INSERT INTO bills(name, amount, due_date) VALUES ('cents bill', 19.99, '2030-01-01')")
    assert con.execute("SELECT amount_cents FROM bills WHERE name='cents bill'").fetchone() == (1999,)
    con.execute("UPDATE bills SET amount=20.5 WHERE name='cents bill'")
    assert con.execute("SELECT amount_cents FROM bills WHERE name='cents bill'").fetchone() == (2050,)
    with pytest.raises(sqlite3.OperationalError):
        con.execute("UPDATE bills SET amount_cents=1 WHERE name='cents bill'")
    con.execute("DELETE FROM bills WHERE name='cents bill'")
    con.commit()
    assert "amount_cents" in {r[1] for r in con.execute("PRAGMA table_xinfo(transactions)")}
    con.close()


def test_card_import_dedupes_on_cents_not_floats(root, tmp_path):
    con = db(root)
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Cents Card', 'credit', '7777')")
    con.commit()
    con.close()
    f = tmp_path / "card.csv"
    with open(f, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "description", "amount"])
        w.writerow(["2026-01-05", "COFFEE SHOP", "-4.30"])
        w.writerow(["2026-01-05", "COFFEE SHOP", "-4.30"])  # two identical same-day charges are both real
        w.writerow(["2026-01-06", "GROCER", "-0.30"])
    r = run(["data/import_card_txns.py", str(f), "--last4", "7777"], root)
    assert r.returncode == 0 and "inserted 3" in r.stdout, r.stdout + r.stderr
    con = db(root)
    aid = con.execute("select id from accounts where last4='7777'").fetchone()[0]
    con.execute("UPDATE transactions SET amount=? WHERE account_id=? AND description='GROCER'", (0.1 + 0.2 - 0.6, aid))  # -0.30000000000000004
    con.commit()
    con.close()
    r = run(["data/import_card_txns.py", str(f), "--last4", "7777"], root)
    assert "inserted 0, skipped 3" in r.stdout, "a stored float that is 0.30 to the cent still matches: " + r.stdout


def test_amazon_match_uses_cent_equality(root, modules):
    import datetime as dt
    am = modules("amazon_match")
    con = db(root)
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Amz Card', 'credit', '8888')")
    aid = con.execute("select id from accounts where last4='8888'").fetchone()[0]
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2026-02-03', 'AMAZON.COM*ABC', ?)", (aid, -(0.1 + 0.2)))
    con.execute("INSERT INTO amazon_orders(order_no, order_date, total, status, items) VALUES ('111-1', '2026-02-02', 0.3, 'delivered', 'x')")
    con.commit()
    today = dt.date(2026, 2, 10)
    try:
        am.run(con)
        tid = con.execute("select transaction_id from amazon_orders where order_no='111-1'").fetchone()[0]
    finally:
        con.close()
    assert tid is not None, "a charge of 0.30000000000000004 matches a 0.30 order"
    del today
