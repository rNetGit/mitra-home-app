"""Card charges get a category: rules match the merchant through wallet / processor tags, rows with a type but no category are
filled in, and the Cards page lists the merchants that still have none so one answer is remembered as a family rule."""
import json

from conftest import db, q, run


def _plant(root):
    with db(root) as con:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Rule Card', 'credit', '4242')").lastrowid
        rows = [("AplPay SUNOCO 800210BUFFALO NY", -39.38, None), ("TST* YOUNG CHAM AMHERST NY", -17.39, None),
                ("HALAL MEAT MARKET MAPLE GROVE NY (card x4242)", -78.29, None), ("ALDI INC 0004 RIVERTON NY", -33.2, "spend"),
                ("WEIRD LOCAL SHOP 12 ALBANY NY", -20.0, None), ("WEIRD LOCAL SHOP 12 ALBANY NY", -10.0, None),
                ("AUTOMATIC PAYMENT - THANK YOU", 500.0, "card_payment")]
        for i, (d, a, t) in enumerate(rows):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, txn_type) VALUES (?,?,?,?,?)",
                        (acc, f"2026-10-{i + 1:02d}", d, a, t))
    return acc


def test_matching_sees_through_wallet_tags_and_the_card_note(modules):
    rm = modules("rule_match")
    assert rm.clean("AplPay SUNOCO 800210BUFFALO NY") == "SUNOCO 800210BUFFALO NY"
    assert rm.clean("SQ *TASTEFUL LUXURIES Rensselaer") == "TASTEFUL LUXURIES RENSSELAER"
    assert rm.clean("CVS/PHARMACY #00996 MAPLE GROVE NY (card x1111)") == "CVS/PHARMACY #00996 MAPLE GROVE NY"
    assert rm.merchant_key("CVS/PHARMACY #00996 MAPLE GROVE NY (card x1111)") == "CVS/PHARMACY"
    assert rm.merchant_key("ROBINSON HARDWARE MAPLE GROVE NY") == "ROBINSON HARDWARE MAPLE"
    assert rm.texts("SUNOCO X") == ["SUNOCO X"]


def test_apply_rules_categorizes_tagged_and_typed_rows_and_leaves_unknown_merchants(root):
    _plant(root)
    r = run(["data/apply_rules.py"], root)
    assert r.returncode == 0, r.stderr
    got = dict(q(root, "SELECT description, category FROM transactions WHERE account_id=(SELECT id FROM accounts WHERE name='Rule Card')"))
    assert got["AplPay SUNOCO 800210BUFFALO NY"] == "fuel", "the wallet tag does not hide the merchant"
    assert got["HALAL MEAT MARKET MAPLE GROVE NY (card x4242)"] == "groceries"
    assert got["ALDI INC 0004 RIVERTON NY"] == "groceries", "a row that already had a type still gets its category"
    assert got["WEIRD LOCAL SHOP 12 ALBANY NY"] is None and got["TST* YOUNG CHAM AMHERST NY"] is None


def test_ledger_lists_uncategorized_card_merchants(root, modules):
    fd, L = modules("finance_data"), modules("ledger_data")
    with db(root) as con:
        v = L.ledger(con, {"from": "2026-10-01", "to": "2026-10-31", "cat": L.NONE}, __import__("datetime").date(2026, 10, 17), fd)
    m = {x["key"]: x for x in v["rules"]["merchants"]}
    assert m["WEIRD LOCAL SHOP"]["n"] == 2 and m["WEIRD LOCAL SHOP"]["spent"] == 30.0
    assert "AUTOMATIC PAYMENT" not in str(m) and "SUNOCO" not in str(m), "payments and categorized rows are not listed"
    assert "fuel" in v["rules"]["cats"] and v["rules"]["back"] == "ledger"
    with db(root) as con:
        assert L.ledger(con, {"from": "2026-10-01", "to": "2026-10-31"}, __import__("datetime").date(2026, 10, 17), fd)["rules"] is None


def test_remembering_a_merchant_writes_a_family_rule_and_fills_the_rows(root, modules):
    ea, config = modules("edit_actions"), modules("config")
    adult, kid = {"name": "Ann", "role": "adult"}, {"name": "Kid", "role": "limited"}
    assert ea.category_rule_add(kid, "WEIRD LOCAL", "gifts") == (False, "only an adult can change this")
    assert ea.category_rule_add(adult, "%%", "gifts")[0] is False and ea.category_rule_add(adult, "ab", "gifts")[0] is False
    assert ea.category_rule_add(adult, "WEIRD LOCAL", "")[0] is False
    ok, msg = ea.category_rule_add(adult, "weird local shop", "Gifts")
    assert ok and "2 lines updated" in msg
    assert q(root, "SELECT DISTINCT category FROM transactions WHERE description LIKE 'WEIRD LOCAL%'") == [("gifts",)]
    rules = json.loads((root / "config" / "category_rules.json").read_text(encoding="utf-8"))
    assert ["WEIRD LOCAL SHOP%", "gifts", "spend", None] in rules
    assert q(root, "SELECT category FROM category_rules WHERE pattern='WEIRD LOCAL SHOP%'") == [("gifts",)]
    ok, _ = ea.category_rule_add(adult, "WEIRD LOCAL SHOP", "presents")  # a second answer replaces the first
    assert ok and [r for r in json.loads((root / "config" / "category_rules.json").read_text(encoding="utf-8"))
                   if r[0] == "WEIRD LOCAL SHOP%"] == [["WEIRD LOCAL SHOP%", "presents", "spend", None]]
    assert "category_rule_add\tpattern=WEIRD LOCAL SHOP%" in (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert config.data_file("category_rules.json")


def test_bank_transfers_stop_counting_as_spending_and_the_month_page_names_what_is_left(root, modules):
    trends, ea = modules("trends"), modules("edit_actions")
    with db(root) as con:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Rule Checking', 'checking', '5252')").lastrowid
        for d, desc, amt in (("2026-07-05", "Online Realtime Transfer to Savings Plus", -5000.0),
                             ("2026-07-06", "XOOM DEBIT T SOMEONE FAR AWAY", -150.0),
                             ("2026-07-07", "CORNER BARBERSHOP 12 TROY NY", -30.0),
                             ("2026-07-08", "CORNER BARBERSHOP 12 TROY NY", -30.0)):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (acc, d, desc, amt))
    assert run(["data/apply_rules.py"], root).returncode == 0
    got = {d: (c, t) for d, c, t in q(root, "SELECT description, category, txn_type FROM transactions WHERE account_id=?", acc)}
    assert got["Online Realtime Transfer to Savings Plus"] == ("transfer", "transfer"), "an online transfer is not spending"
    assert got["XOOM DEBIT T SOMEONE FAR AWAY"][0] == "international transfers"
    with db(root) as con:
        con.row_factory = __import__("sqlite3").Row
        s = trends.month_summary(con, "2026-07")
    loose = {g["key"]: g for g in s["loose"]}
    assert loose["CORNER BARBERSHOP"]["n"] == 2 and loose["CORNER BARBERSHOP"]["spent"] == 60.0
    assert any("CORNER BARBERSHOP" in i["payee"] for c in s["all"] for i in c["items"]), "a bank line with no payee shows its text"
    ok, _ = ea.category_rule_add({"name": "Ann", "role": "adult"}, "CORNER BARBERSHOP", "personal care")
    assert ok and q(root, "SELECT DISTINCT category FROM transactions WHERE description LIKE 'CORNER BARBERSHOP%'") == [("personal care",)]
    ok, _ = ea.category_rule_add({"name": "Ann", "role": "adult"}, "SELF MOVE", "Transfer")
    assert ok
    rules = __import__("json").loads((root / "config" / "category_rules.json").read_text(encoding="utf-8"))
    assert ["SELF MOVE%", "transfer", "transfer", None] in rules, "choosing transfer sets the type that leaves spending"


def test_the_same_money_leaving_and_arriving_between_own_accounts_is_a_transfer(root):
    with db(root) as con:
        a = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Pair Checking', 'checking', '7171')").lastrowid
        b = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Pair Savings', 'savings', '7272')").lastrowid
        rows = [(a, "2026-06-05", "WIRE OUT MY NAME", -777.0), (b, "2026-06-06", "RTP-MY NAME", 777.0),   # a pair
                (a, "2026-06-10", "GYM", -41.0), (b, "2026-06-30", "REFUND SOMEWHERE", 41.0),               # too far apart
                (a, "2026-06-12", "CLUB A", -90.0), (a, "2026-06-12", "CLUB B", -90.0), (b, "2026-06-12", "GIFT", 90.0)]  # not unique
        for acc, d, desc, amt in rows:
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (acc, d, desc, amt))
    r = run(["data/apply_rules.py"], root)
    assert r.returncode == 0 and "1 transfer pair" in r.stdout, r.stdout + r.stderr
    got = {d: t for d, t in q(root, "SELECT description, txn_type FROM transactions WHERE account_id IN (?, ?)", a, b)}
    assert got["WIRE OUT MY NAME"] == "transfer" and got["RTP-MY NAME"] == "transfer"
    assert got["GYM"] is None and got["REFUND SOMEWHERE"] is None and got["GIFT"] is None and got["CLUB A"] is None


def test_a_deposit_source_is_told_once_and_only_pay_and_interest_stay_income(root, modules):
    """Finance > Deposits: an old rule called Treasury payouts income; saying "money back from investments" re-types
    every line from that source (the family's word wins over the earlier category), and the cash flow stops counting it."""
    import datetime as dt
    ea, fd = modules("edit_actions"), modules("finance_data")
    with db(root) as con:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Dep Checking', 'checking', '6161')").lastrowid
        con.execute("INSERT INTO category_rules(pattern, category, payee_type, payee, priority) "
                    "VALUES ('APA TREAS 310%', 'government payments', 'income', 'Treasury', 119)")
        for d, desc, amt in (("2025-03-03", "APA TREAS 310 MISC PAY", 5000.0), ("2025-03-09", "APA TREAS 310 MISC PAY", 44.92),
                             ("2025-03-15", "ACME CORP PAYROLL", 3000.0), ("2025-03-20", "MOBILE CHECK DEPOSIT", 250.0)):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (acc, d, desc, amt))
    assert run(["data/apply_rules.py"], root).returncode == 0
    assert q(root, "SELECT DISTINCT txn_type FROM transactions WHERE description='APA TREAS 310 MISC PAY'") == [("income",)]
    assert q(root, "SELECT txn_type, category FROM transactions WHERE description='MOBILE CHECK DEPOSIT'") == [(None, None)],         "the Mobil fuel rule no longer catches a mobile check deposit"
    with db(root) as con:
        v = fd.deposits(con, dt.date(2025, 3, 31), {"from": "2025-03", "to": "2025-03"})
    src = {m["key"]: m for m in v["rules"]["merchants"]}
    assert src["APA TREAS"]["kind"] == "income" and src["APA TREAS"]["n"] == 2 and src["APA TREAS"]["total"] == 5044.92
    assert v["rules"]["merchants"][0]["kind"] == "", "not-sorted sources come first"
    assert ("investment_transfer", "Money back from investments (TreasuryDirect, brokerage)") in v["rules"]["kinds"]
    adult = {"name": "Ann", "role": "adult"}
    assert ea.category_rule_add(adult, "APA TREAS 310", "", "salary")[0] is False, "an unknown kind is refused"
    ok, msg = ea.category_rule_add(adult, "APA TREAS 310", "", "investment_transfer")
    assert ok and "2 lines updated" in msg, msg
    assert q(root, "SELECT DISTINCT txn_type, category FROM transactions WHERE description='APA TREAS 310 MISC PAY'") ==         [("investment_transfer", "investing")]
    cf = dict(q(root, "SELECT month, income FROM v_monthly_cashflow WHERE month='2025-03'"))
    assert cf["2025-03"] == 3000.0, "only the pay is income"
    ok, _ = ea.category_rule_add(adult, "MOBILE CHECK DEPOSIT", "gift", "income")
    assert ok and q(root, "SELECT txn_type, category FROM transactions WHERE description='MOBILE CHECK DEPOSIT'") == [("income", "gift")]


def test_a_dropped_starter_rule_leaves_the_table_and_its_lines(root):
    with db(root) as con:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Old Rule Checking', 'checking', '6262')").lastrowid
        con.execute("INSERT INTO category_rules(pattern, category, payee_type, payee, priority) VALUES ('MOBIL%', 'fuel', 'spend', 'Mobil', 1025)")
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) "
                    "VALUES (?, '2025-04-07', 'MOBILE DEPOSIT DDA', 450.08, 'fuel', 'spend')", (acc,))
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) "
                    "VALUES (?, '2025-04-08', 'MOBIL 0412 TROY NY', -40.0, 'fuel', 'spend')", (acc,))
    assert run(["data/apply_rules.py"], root).returncode == 0
    assert q(root, "SELECT COUNT(*) FROM category_rules WHERE pattern='MOBIL%'") == [(0,)]
    got = dict(((d, (c, t)) for d, c, t in q(root, "SELECT description, category, txn_type FROM transactions WHERE account_id=?", acc)))
    assert got["MOBILE DEPOSIT DDA"] == (None, None) and got["MOBIL 0412 TROY NY"] == ("fuel", "spend")


def test_card_payments_count_once_in_the_cash_flow(root):
    with db(root) as con:
        bank = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('CF Checking', 'checking', '6363')").lastrowid
        card = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('CF Card', 'credit', '6464')").lastrowid
        for acc, desc, amt in ((bank, "CARD AUTOPAY", -900.0), (card, "PAYMENT RECEIVED THANK YOU", 900.0)):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, txn_type) "
                        "VALUES (?, '2024-02-10', ?, ?, 'card_payment')", (acc, desc, amt))
    assert q(root, "SELECT card_payments FROM v_monthly_cashflow WHERE month='2024-02'") == [(900.0,)]
    assert q(root, "SELECT SUM(paid) FROM v_card_payments WHERE month='2024-02'") == [(900.0,)]
