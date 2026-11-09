"""One spending rule (ledger_data.spend_lines) behind every money figure: the Ledger, This month (trends.month_summary),
Trends, the budget and the Mitra Wall / phone pages agree to the cent. Tax is apart, a refund comes off, and a card
payment counts only in a month with no card statement."""
import datetime as D

from conftest import db

TODAY = D.date(2033, 5, 20)


def _seed(con):
    con.execute("DELETE FROM transactions WHERE txn_date >= '2033-01-01'")
    con.execute("DELETE FROM accounts WHERE name IN ('Rule Checking', 'Rule Visa')")
    con.execute("DELETE FROM budget WHERE category IN ('groceries', 'dining')")
    chk = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Rule Checking', 'checking', '7001')").lastrowid
    card = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Rule Visa', 'credit', '7002')").lastrowid
    rows = [  # April: card lines filed; May: only the bank statement
        (chk, "2033-04-01", "PAYROLL", "Acme", "income", "salary", 5000.00),
        (card, "2033-04-03", "GROCER", "Grocer", "spend", "groceries", -300.00),
        (card, "2033-04-04", "GROCER REFUND", "Grocer", "spend", "groceries", 25.00),
        (card, "2033-04-05", "CAFE", "Cafe", "", "dining", -40.00),
        (chk, "2033-04-06", "PAYMENT TO VISA", None, "card_payment", "credit card", -315.00),
        (chk, "2033-04-07", "IRS", None, "tax", "tax", -2200.00),
        (chk, "2033-04-08", "CITY POWER", None, "utility", "utilities", -110.00),
        (chk, "2033-04-09", "BROKER", None, "investment_transfer", "investing", -500.00),
        (chk, "2033-05-01", "PAYROLL", "Acme", "income", "salary", 5000.00),
        (chk, "2033-05-06", "PAYMENT TO VISA", None, "card_payment", "credit card", -420.00),
        (chk, "2033-05-08", "CITY POWER", None, "utility", "utilities", -120.00)]
    for r in rows:
        con.execute("INSERT INTO transactions(account_id, txn_date, description, payee, txn_type, category, amount) "
                    "VALUES (?,?,?,?,?,?,?)", r)
    con.execute("INSERT INTO budget(category, monthly_limit) VALUES ('groceries', 400), ('dining', 100)")


def test_every_screen_counts_the_same_spending(root, modules):
    L, T, B, WM = modules("ledger_data"), modules("trends"), modules("budget"), modules("wall_money")
    with db(root) as con:
        _seed(con)
        con.commit()
        april = T.month_summary(con, "2033-04", today=TODAY)
        assert april["spent"] == 425.00, "groceries 300 - 25 refund + dining 40 + power 110; tax and the card payment apart"
        assert april["tax"] == 2200.00 and april["left"] == 5000 - 425 - 2200 - 500
        f = L.parse({"from": "2033-04-01", "to": "2033-04-30"}, TODAY)
        S = L.summary(con, f)
        assert -S["spending"] == 425.00 and -S["tax"] == 2200.00 and S["card_spend"] == 0
        assert T.monthly(con, 2, end="2033-05", today=TODAY)[0]["expenses"] == 425.00
        assert B._actuals(con, "2033-04") == {"groceries": 275.00, "dining": 40.00, "utilities": 110.00}
        assert WM.spending(con, D.date(2033, 4, 30))["totals"]["now"] == 425.00

        may = T.month_summary(con, "2033-05", today=TODAY)
        assert may["spent"] == 540.00, "no card lines in May: the card payment stands for the card's spending"
        S = L.summary(con, L.parse({"from": "2033-05-01", "to": "2033-05-31"}, TODAY))
        assert -S["spending"] == 540.00 and S["card_spend"] == 420.00 and S["cards"] == 0
        tiles, notes = L._tiles(S, [])
        assert any("count as spending" in text and "May 2033" in text for _tone, text in notes)
        assert WM.spending(con, TODAY)["totals"]["now"] == 540.00
        assert sorted(L.months_without_cards(con, "2033-04-01", "2033-05-31")) == ["2033-05"]
        con.execute("DELETE FROM transactions WHERE txn_date >= '2033-01-01'")
        con.execute("DELETE FROM accounts WHERE name IN ('Rule Checking', 'Rule Visa')")
        con.execute("DELETE FROM budget WHERE category IN ('groceries', 'dining')")
        con.commit()
