"""The Mitra Wall's money pages behind the adult's PIN (data/wall_money.py): Spending by category for this month, last
month and the same month a year ago (the Ledger's spending: no transfers, card payments or investing); Bills paid this
month against last month (paid / waiting / new, open bill-list rows); Regular bills and subscriptions (seen in two of
the last four months, tracked subscriptions, the bill list; one row per payee; no long numbers on the wall)."""
import datetime as D
import re

TODAY = D.date(2032, 3, 18)


def _clean(con):
    con.execute("DELETE FROM transactions WHERE txn_date >= '2031-01-01'")
    con.execute("DELETE FROM accounts WHERE name IN ('Wall Checking', 'Wall Visa')")
    con.execute("DELETE FROM bills WHERE due_date >= '2031-01-01'")
    con.execute("DELETE FROM subscriptions WHERE name LIKE 'Wall %'")


def _seed(con):
    _clean(con)
    chk = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Wall Checking', 'checking', '4321')").lastrowid
    card = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Wall Visa', 'credit', '8765')").lastrowid
    rows = [  # account, date, description, payee, type, category, amount
        (card, "2032-03-04", "FRESHMART 22", "Freshmart", "spend", "groceries", -120.00),
        (card, "2032-02-06", "FRESHMART 22", "Freshmart", "spend", "groceries", -200.00),
        (card, "2031-03-09", "FRESHMART 22", "Freshmart", "spend", "groceries", -90.00),
        (card, "2032-03-05", "FRESHMART REFUND", "Freshmart", "spend", "groceries", 20.00),
        (chk, "2032-03-06", "PAYMENT TO VISA", None, "card_payment", "credit card", -900.00),
        (chk, "2032-03-07", "TO SAVINGS", None, "transfer", "transfer", -500.00),
        (chk, "2032-03-08", "BROKER DEPOSIT", None, "investment_transfer", "investing", -300.00),
        (chk, "2032-02-03", "CITY POWER 99887766", None, "utility", "utilities", -110.00),
        (chk, "2032-03-03", "CITY POWER 99887766", None, "utility", "utilities", -140.00),
        (chk, "2032-01-03", "CITY POWER 99887766", None, "utility", "utilities", -105.00),
        (chk, "2032-02-10", "HOMELOAN CO", "Homeloan Co", "loan_payment", "housing", -1500.00),
        (chk, "2032-01-10", "HOMELOAN CO", "Homeloan Co", "loan_payment", "housing", -1500.00),
        (chk, "2032-03-11", "NEW WATER CO", "New Water Co", "utility", "utilities", -45.00),
        (card, "2032-02-14", "STREAMFLIX", "Streamflix", "spend", "subscriptions", -15.99),
        (card, "2032-03-14", "STREAMFLIX", "Streamflix", "spend", "subscriptions", -15.99),
        (card, "2032-03-02", "ONE OFF GYM DAY", "Gym Day", "spend", "subscriptions", -12.00),
    ]
    for r in rows:
        con.execute("INSERT INTO transactions(account_id, txn_date, description, payee, txn_type, category, amount) "
                    "VALUES (?,?,?,?,?,?,?)", r)
    con.execute("INSERT INTO bills(name, vendor, frequency, amount, due_date, status) VALUES "
                "('Phone', 'Wall Phone Co', 'monthly', 60.0, '2032-03-25', 'due'), "
                "('Old phone', 'Wall Phone Co', 'monthly', 60.0, '2032-03-01', 'overdue')")
    con.execute("INSERT INTO subscriptions(name, amount, frequency, decision, active, match_payee) VALUES "
                "('Wall Music', 9.99, 'monthly', 'cancel', 1, 'Wall Music'), "
                "('Wall Old Paper', 5.0, 'monthly', 'cancelled', 1, 'Wall Old Paper')")
    con.commit()


def test_spending_by_category_three_months(modules):
    WM, db = modules("wall_money"), modules("db")
    con = db.connect()
    try:
        _seed(con)
        v = WM.spending(con, TODAY)
    finally:
        _clean(con)
        con.commit()
        con.close()
    by = {r["cat"]: r for r in v["rows"]}
    g = by["groceries"]
    assert (g["now"], g["prev"], g["ly"]) == (100.0, 200.0, 90.0), "a refund lowers the month; a card charge counts once"
    assert (g["now_text"], g["ly_text"]) == ("$100", "$90")
    assert "transfer" not in by and "investing" not in by and "credit card" not in by, "money that only moved is not spent"
    assert by["utilities"]["now"] == 185.0 and by["housing"]["prev"] == 1500.0
    assert v["names"] == {"now": "March", "prev": "February", "ly": "March 2031"}
    assert max(max(r["now_w"], r["prev_w"], r["ly_w"]) for r in v["rows"]) == 100, "bars against the biggest figure"
    assert all(0 <= r[k] <= 100 for r in v["rows"] for k in ("now_w", "prev_w", "ly_w"))
    assert v["through"] == "Mar 14" and v["day"] == 18 and v["days"] == 31


def test_spending_without_last_years_statements_shows_a_dash(modules):
    WM, db = modules("wall_money"), modules("db")
    con = db.connect()
    try:
        _seed(con)
        con.execute("DELETE FROM transactions WHERE txn_date LIKE '2031-03-%'")
        v = WM.spending(con, TODAY)
    finally:
        _clean(con)
        con.commit()
        con.close()
    assert v["totals"]["ly"] is None and not v["have"]["ly"]
    assert all(r["ly_text"] == "—" for r in v["rows"])


def test_bills_this_month_against_last(modules):
    WM, db = modules("wall_money"), modules("db")
    con = db.connect()
    try:
        _seed(con)
        v = WM.bills(con, TODAY)
    finally:
        _clean(con)
        con.commit()
        con.close()
    by = {r["name"]: r for r in v["rows"]}
    power = by["City Power"]
    assert power["state"] == "paid" and (power["prev"], power["now"]) == (110.0, 140.0)
    assert power["note"] == "$30.00 more" and power["now_on"] == "Mar 3" and power["prev_on"] == "Feb 3"
    loan = by["Homeloan Co"]
    assert loan["state"] == "waiting" and loan["note"] == "came Feb 10 last month, not seen yet"
    assert by["New Water Co"]["state"] == "new"
    assert "Freshmart" not in by and "Streamflix" not in by, "groceries and subscriptions are not bills"
    assert not any(ch.isdigit() for r in v["rows"] for ch in r["name"]), "no long numbers on the wall"
    assert v["wait_n"] == 1 and v["wait_total"] == "$1,500.00"
    assert v["now_n"] == 2 and v["now_total"] == "$185.00" and v["prev_total"] == "$1,610.00"
    mine = [b for b in v["listed"] if b["name"] == "Wall Phone Co"]
    assert [(b["due"], b["late"]) for b in mine] == [("Mar 1", True), ("Mar 25", False)], "open rows due by the month's end"


def test_regular_bills_and_subscriptions(modules):
    WM, db = modules("wall_money"), modules("db")
    con = db.connect()
    try:
        _seed(con)
        v = WM.regular(con, TODAY)
    finally:
        _clean(con)
        con.commit()
        con.close()
    groups = {g["key"]: {r["name"]: r for r in g["rows"]} for g in v["groups"]}
    assert "City Power" in groups["home"] and groups["home"]["City Power"]["amount"] == "$140.00"
    assert groups["home"]["City Power"]["next"] == "Apr 3"
    assert "Homeloan Co" in groups["loans"]
    assert "Streamflix" in groups["subs"]
    assert "Wall Phone Co" in groups["home"], "a repeating bill on the bill list, once however many rows it has"
    assert groups["home"]["Wall Phone Co"]["next"] == "Mar 1" and groups["home"]["Wall Phone Co"]["next_late"]
    assert "Wall Music" in groups["subs"] and "cancel planned" in groups["subs"]["Wall Music"]["flags"]
    names = {n for g in groups.values() for n in g}
    assert "New Water Co" not in names and "Gym Day" not in names, "one month is not regular yet"
    assert "Wall Old Paper" not in names, "a cancelled subscription is not regular"
    assert [g["title"] for g in v["groups"]] == ["Home and utilities", "Loans and insurance", "Subscriptions"]


def test_one_payee_however_it_is_written(modules):
    WM = modules("wall_money")
    assert WM._same(WM._key("Verizon"), WM._key("VERIZON WIRELESS PAYMENTS"))
    assert WM._same(WM._key("Verizon bill"), WM._key("Verizon"))
    assert WM._key("City of Raleigh Water") == WM._key("Raleigh Water")
    assert not WM._same(WM._key("Apple iCloud"), WM._key("Apple Music")), "two services of one company stay apart"
    assert WM.nice("CITY POWER 99887766") == "City Power" and WM.nice("ACME #123456 ") == "Acme"
    assert WM.next_month(D.date(2032, 1, 31)) == D.date(2032, 2, 29)


def test_daily_paid_last_seven_days_and_due_next_seven(modules):
    WM, db = modules("wall_money"), modules("db")
    con = db.connect()
    try:
        _seed(con)
        chk = con.execute("SELECT id FROM accounts WHERE name = 'Wall Checking'").fetchone()[0]
        con.execute("INSERT INTO transactions(account_id, txn_date, description, payee, txn_type, category, amount) "
                    "VALUES (?,?,?,?,?,?,?)", (chk, "2032-03-15", "CITY POWER 11223344", None, "utility", "utilities", -150.0))
        con.execute("INSERT INTO bills(name, vendor, frequency, amount, due_date, status, paid_date) VALUES "
                    "('Gas', 'Wall Gas Co', 'monthly', 40.0, '2032-03-16', 'paid', '2032-03-16'), "
                    "('Power', 'City Power', 'monthly', 150.0, '2032-03-15', 'paid', '2032-03-15'), "
                    "('Water', 'Wall Water Co', 'monthly', 60.0, '2032-03-20', 'due', NULL), "
                    "('Far', 'Wall Far Co', 'monthly', 99.0, '2032-04-20', 'due', NULL)")
        con.commit()
        v = WM.daily(con, TODAY)
    finally:
        _clean(con)
        con.commit()
        con.close()
    assert (v["from"], v["to"]) == ("2032-03-12", "2032-03-24")
    paid = {(p["name"], p["on"]): p["amount"] for p in v["paid"]}
    assert paid[("Wall Gas Co", "2032-03-16")] == 40.0
    assert paid[("City Power", "2032-03-15")] == 150.0
    assert sum(1 for p in v["paid"] if p["name"] == "City Power") == 1, "a statement line and a paid bill-list row count once"
    assert all(p["on"] >= "2032-03-12" for p in v["paid"]), "older than a week stays out"
    assert v["paid"][0]["on"] >= v["paid"][-1]["on"], "newest first"
    assert v["upcoming"][0]["late"] and v["late_n"] >= 1, "late bills first"
    assert [c["name"] for c in v["upcoming"] if not c["late"]] == ["Wall Water Co"]
    assert all(c["due"] <= "2032-03-24" for c in v["upcoming"]), "the far bill stays out"
    assert not any(re.search(r"\d{4,}", p["name"]) for p in v["paid"]), "no long numbers in a name"
    assert v["paid_total"] == round(sum(p["amount"] for p in v["paid"]), 2)
