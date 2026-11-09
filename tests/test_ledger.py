"""Money > Ledger: every account's lines in one list, filtered by dates / period / account / words / amount /
category / type; the period fills From and To; each filter is checked; totals cover the whole filtered set."""
import datetime as D

from conftest import db

TODAY = D.date(2031, 10, 15)  # a Wednesday; years the demo data never reaches


def _clean(con):
    """`root` is shared by the tests of a file: remove what an earlier test put in the years this file uses."""
    con.execute("DELETE FROM transactions WHERE txn_date >= '2031-01-01'")
    con.execute("DELETE FROM accounts WHERE last4 IN ('1111', '2222', '9999') AND name IN ('Joint Checking', 'Visa', 'Checking')")


def _seed(con):
    _clean(con)
    chk = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Joint Checking', 'checking', '1111')").lastrowid
    card = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Visa', 'credit', '2222')").lastrowid
    rows = [(chk, "2031-10-14", "ACME PAYROLL", "Acme", "income", "Salary", 3000.00),
            (chk, "2031-10-12", "PAYMENT TO VISA", None, "card_payment", None, -500.00),
            (card, "2031-10-13", "SAFEWAY #12", "Safeway", "spend", "Groceries", -82.45),
            (card, "2031-10-05", "SHELL OIL", None, "spend", None, -40.00),
            (card, "2031-09-20", "100% COTTON_CO", None, "spend", "Clothes", -25.00),
            (chk, "2031-01-02", "OLD DEPOSIT", None, "income", "Salary", 10.00)]
    for r in rows:
        con.execute("INSERT INTO transactions(account_id, txn_date, description, payee, txn_type, category, amount) "
                    "VALUES (?,?,?,?,?,?,?)", r)
    return chk, card


def test_period_fills_the_dates(modules):
    L = modules("ledger_data")
    assert L.period_dates("week", TODAY) == ("2031-10-13", "2031-10-19"), "Monday to Sunday of the current week"
    assert L.period_dates("month", TODAY) == ("2031-10-01", "2031-10-31")
    assert L.period_dates("year", TODAY) == ("2031-01-01", "2031-12-31")
    assert L.period_dates("decade", TODAY) is None
    f = L.parse({"period": "week"}, TODAY)
    assert (f["from"], f["to"], f["period"]) == ("2031-10-13", "2031-10-19", "week")
    f = L.parse({}, TODAY)
    assert (f["from"], f["to"], f["period"]) == ("2031-10-01", "2031-10-31", "month"), "nothing asked = this month"
    f = L.parse({"period": "year", "from": "2031-03-01", "to": "2031-03-31"}, TODAY)
    assert f["period"] == "custom" and f["from"] == "2031-03-01", "typed dates win over a period"
    f = L.parse({"from": "2031-10-20", "to": "2031-10-10"}, TODAY)
    assert (f["from"], f["to"]) == ("2031-10-10", "2031-10-20"), "a reversed range is turned round"
    f = L.parse({"from": "2031-10-10"}, TODAY)
    assert f["from"] == f["to"] == "2031-10-10", "one date is one day"
    f = L.parse({"from": "garbage", "to": "2031-13-45", "min": "x", "max": "-5", "type": "bogus", "account": "9"}, TODAY)
    assert f["period"] == "month" and f["min"] is None and f["max"] is None and f["type"] == "" and f["account"] == ""


def test_all_accounts_in_one_list_and_totals(root, modules):
    L, fd = modules("ledger_data"), modules("finance_data")
    with db(root) as con:
        chk, card = _seed(con)
        v = fd.ledger(con, TODAY, {})
        rows = v["ledger"]["rows"]
        assert len(rows) == 4, "this month: payroll, card payment, Safeway, Shell, from every account"
        assert {r["account"] for r in rows} == {"Joint Checking x1111", "Visa x2222"}
        tiles = {t[0]: t[1] for t in v["tiles"]}
        assert tiles["Lines"] == 4 and tiles["Income"] == "$3,000.00" and tiles["Spending"] == "$122.45"
        assert tiles["Card payments"] == "$500.00" and tiles["Left over"] == "$2,877.55"
        assert rows[0]["id"] is not None and rows[0]["amount_text"] == "$3,000.00" and rows[0]["manual"] == 0
        assert fd.ledger(con, TODAY, {"period": "year"})["filters"]["period"] == "year"
        assert {t[0]: t[1] for t in fd.ledger(con, TODAY, {"period": "year"})["tiles"]}["Lines"] == 6
        assert L.rows(con, L.parse({"from": "2031-10-01", "to": "2031-10-31"}, TODAY), 2)[0]["description"] == "ACME PAYROLL"


def test_filters_account_type_category_amount_and_words(root, modules):
    L = modules("ledger_data")
    with db(root) as con:
        chk, card = _seed(con)
        accounts, cats = L.account_list(con), L.categories(con)

        def n(**args):
            f = L.parse({"period": "year", **{k: str(v) for k, v in args.items()}}, TODAY, accounts, cats)
            return len(L.rows(con, f)), L.totals(con, f)[0]
        assert n() == (6, 6)
        assert n(account=chk)[0] == 3 and n(account=card)[0] == 3
        assert n(type="spend")[0] == 3 and n(type="income")[0] == 2 and n(type="card_payment")[0] == 1
        assert n(cat="Groceries")[0] == 1 and n(cat=L.NONE)[0] == 2, "Uncategorized = no category at all"
        assert n(cat="Not a category")[0] == 6, "an unknown category is ignored, not an empty result"
        assert n(min=80)[0] == 3 and n(min=80, max=100)[0] == 1 and n(max=10)[0] == 1
        assert n(min=100, max=80)[0] == 1, "reversed min / max are turned round"
        assert n(min="3000", max="3000")[0] == 1, "size, whatever the sign: 500 matches the payment out"
        assert n(min="500", max="500")[0] == 1
        assert n(q="safeway")[0] == 1 and n(q="acme")[0] == 1, "description and payee"
        assert n(q="groceries")[0] == 1, "category"
        assert n(q="shell oil")[0] == 1 and n(q="oil shell")[0] == 1, "every word, any order"
        assert n(q="100%")[0] == 1 and n(q="%")[0] == 1, "% and _ in a search are letters, not wildcards"
        assert n(q="cotton_co")[0] == 1 and n(q="cotton_xx")[0] == 0
        assert n(q="nothing like it")[0] == 0


def test_paging_and_empty_state(root, modules):
    fd, L = modules("finance_data"), modules("ledger_data")
    with db(root) as con:
        _clean(con)
        chk = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Checking', 'checking', '9999')").lastrowid
        for i in range(L.PAGE + 5):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                        (chk, "2031-10-%02d" % (1 + i % 28), f"ITEM {i:03d}", -1.0))
        v = fd.ledger(con, TODAY, {})
        assert v["filters"]["pages"] == 2 and len(v["ledger"]["rows"]) == L.PAGE
        assert v["filters"]["base"]["from"] == "2031-10-01" and "page" not in v["filters"]["base"]
        v2 = fd.ledger(con, TODAY, {"page": "2"})
        assert len(v2["ledger"]["rows"]) == 5 and v2["filters"]["page"] == 2
        assert fd.ledger(con, TODAY, {"page": "99"})["filters"]["page"] == 2, "a page past the end is the last page"
        assert fd.ledger(con, TODAY, {"page": "x"})["filters"]["page"] == 1
        none = fd.ledger(con, TODAY, {"q": "zzz"})
        assert none["ledger"]["rows"] == [] and "Nothing matches" in none["ledger"]["empty"]


def test_ledger_is_a_part_of_look_back(modules):
    fd = modules("finance_data")
    assert ("ledger", "Ledger") in fd.parts()
    grp = dict(fd.groups())
    assert grp["Look back"][0] == ("ledger", "Ledger"), "Ledger leads Look back"
    assert fd.part_of("ledger") == "ledger" and fd.group_of("ledger") == "Look back" and fd.title("ledger") == "Ledger"


def test_a_hand_edit_sets_category_and_type_and_rules_leave_it_alone(root, modules):
    ea, rm, L = modules("edit_actions"), modules("rule_match"), modules("ledger_data")
    adult = {"name": "Ann", "role": "adult"}
    with db(root) as con:
        chk, card = _seed(con)
        shell = con.execute("SELECT id FROM transactions WHERE description='SHELL OIL'").fetchone()[0]
        pay = con.execute("SELECT id FROM transactions WHERE description='ACME PAYROLL'").fetchone()[0]
        assert con.execute("SELECT manual FROM transactions WHERE id=?", (shell,)).fetchone()[0] == 0
    assert ea.txn_update({"name": "Kid", "role": "limited"}, shell, "fuel") == (False, "only an adult can change this")
    ok, msg = ea.txn_update(adult, shell, "Fuel ", "")
    assert ok and msg == "Saved."
    with db(root) as con:
        assert con.execute("SELECT category, txn_type, manual FROM transactions WHERE id=?", (shell,)).fetchone() == ("fuel", "spend", 1)
        # only category and type change
        assert con.execute("SELECT txn_date, description, amount FROM transactions WHERE id=?", (shell,)).fetchone() == ("2031-10-05", "SHELL OIL", -40.0)
    assert ea.txn_update(adult, shell, "fuel", "spend") == (True, "Nothing changed.")
    ok, msg = ea.txn_update(adult, pay, None, "transfer")
    assert ok
    assert ea.txn_update(adult, shell, "x", "nonsense")[0] is False
    assert ea.txn_update(adult, 999999, "x")[0] is False and ea.txn_update(adult, "abc", "x")[0] is False
    assert f"txn_update	id={shell} fields=category" in (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8"), "logged by id and field"
    with db(root) as con:
        # a rule that matches both: the hand-edited line keeps its own category and type
        con.execute("INSERT OR REPLACE INTO category_rules(pattern, category, payee_type, priority) VALUES ('ACME PAYROLL%', 'wages', 'income', 1)")
        rm.reapply(con, "ACME PAYROLL%")
        assert con.execute("SELECT category, txn_type FROM transactions WHERE id=?", (pay,)).fetchone() == ("Salary", "transfer")
        con.execute("UPDATE transactions SET manual=0 WHERE id=?", (pay,))
        rm.reapply(con, "ACME PAYROLL%")
        assert con.execute("SELECT category, txn_type FROM transactions WHERE id=?", (pay,)).fetchone() == ("wages", "income")
        con.execute("DELETE FROM category_rules WHERE pattern='ACME PAYROLL%'")
        # the ledger shows the edited flag
        f = L.parse({"period": "year"}, TODAY)
        flags = {r["description"]: r["manual"] for r in L.rows(con, f)}
        assert flags["SHELL OIL"] == 1 and flags["SAFEWAY #12"] == 0


def test_pairing_and_data_check_skip_hand_edited_lines(root, modules):
    rm, af = modules("rule_match"), modules("audit_fix")
    with db(root) as con:
        chk, card = _seed(con)
        sav = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Checking', 'savings', '9999')").lastrowid
        a = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, manual) VALUES (?,?,?,?,1)",
                        (chk, "2031-11-01", "TO SAVINGS", -700)).lastrowid
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (sav, "2031-11-01", "FROM CHECKING", 700))
        assert rm.pair_transfers(con) == 0, "a hand-edited line is not paired behind the person's back"
        con.execute("UPDATE transactions SET manual=0 WHERE id=?", (a,))
        assert rm.pair_transfers(con) == 1
        con.execute("INSERT INTO category_rules(pattern, category, payee_type, priority) VALUES ('KEEPME%', 'rule cat', 'spend', 1)")
        m = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, manual) VALUES (?,?,?,?,1)",
                        (card, "2031-11-02", "KEEPME SHOP", -5)).lastrowid
        af.categorize(con)
        assert con.execute("SELECT COALESCE(category,'') FROM transactions WHERE id=?", (m,)).fetchone()[0] == "", "the data check does not fill it in"
        con.execute("DELETE FROM category_rules WHERE pattern='KEEPME%'")


def test_similar_lines_follow_and_the_migration_is_idempotent(root, modules):
    ea = modules("edit_actions")
    adult = {"name": "Ann", "role": "adult"}
    with db(root) as con:
        chk, card = _seed(con)
        for d in ("2031-12-01", "2031-12-02"):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (card, d, "ZZQ PIZZA #7", -12))
        one = con.execute("SELECT id FROM transactions WHERE description='ZZQ PIZZA #7' ORDER BY id").fetchone()[0]
    assert ea.txn_update(adult, one, "", "", True)[0] is False, "similar needs a category"
    assert ea.txn_update(adult, one, "dining", "card_payment", True)[0] is False, "a type with no rule cannot be remembered"
    ok, msg = ea.txn_update(adult, one, "dining", "spend", True)
    assert ok and "Remembered" in msg, msg
    with db(root) as con:
        got = con.execute("SELECT category, manual FROM transactions WHERE description='ZZQ PIZZA #7' ORDER BY id").fetchall()
        assert got == [("dining", 1), ("dining", 0)], "the other line follows the new rule; only the edited one is manual"
        con.execute("DELETE FROM category_rules WHERE pattern LIKE 'ZZQ PIZZA%'")
    import json
    rules = modules("paths").CONFIG / "category_rules.json"
    if rules.exists():
        rows = [r for r in json.loads(rules.read_text(encoding="utf-8")) if not str(r[0]).startswith("ZZQ PIZZA")]
        rules.write_text(json.dumps(rows), encoding="utf-8")
    with db(root) as con:
        cols = [r[1] for r in con.execute("PRAGMA table_info(transactions)")]
        assert cols.count("manual") == 1


def test_csv_has_every_filtered_line_not_just_a_page(root, modules):
    import csv
    import io
    L, fd = modules("ledger_data"), modules("finance_data")
    with db(root) as con:
        chk, card = _seed(con)
        for i in range(L.PAGE + 3):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                        (card, "2031-10-20", f"BULK {i:03d}", -1.0))
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, manual, category) VALUES (?,?,?,?,1,'x')",
                    (card, "2031-10-21", "=HYPERLINK(\"http://x\")", -2.0))
        name, body = L.csv_file(con, {"period": "month"}, TODAY)
        assert name == "ledger_2031-10-01_2031-10-31.csv"
        rows = list(csv.reader(io.StringIO(body.decode("utf-8"))))
        assert rows[0] == ["date", "account", "description", "category", "type", "amount", "card_member", "edited"]
        assert len(rows) - 1 == 4 + L.PAGE + 3 + 1, "all lines, not the 50 of page one"
        evil = [r for r in rows if "HYPERLINK" in r[2]][0]
        assert evil[2].startswith("'=") and evil[7] == "yes" and evil[5] == "-2.00", "formula kept as text, number left alone"
        assert len(list(csv.reader(io.StringIO(L.csv_file(con, {"period": "month", "q": "safeway"}, TODAY)[1].decode())))) == 2
        got = fd.download("ledger", TODAY, {"period": "month", "account": str(card)})
        assert got[0].endswith(".csv") and got[1].startswith("text/csv") and b"SAFEWAY" in got[2] and b"ACME PAYROLL" not in got[2]


def test_card_member_is_shown_filtered_and_searched(root, modules):
    L, fd = modules("ledger_data"), modules("finance_data")
    with db(root) as con:
        chk, card = _seed(con)
        con.execute("UPDATE transactions SET cardholder='Rita Rao' WHERE description='SAFEWAY #12'")
        con.execute("UPDATE transactions SET cardholder=' Sam Rao ' WHERE description='SHELL OIL'")
        people = L.members(con)
        assert "Rita Rao" in people and "Sam Rao" in people, "names in use, trimmed"
        v = fd.ledger(con, TODAY, {"period": "month", "member": "Rita Rao"})
        rows = v["ledger"]["rows"]
        assert [r["description"] for r in rows] == ["SAFEWAY #12"] and rows[0]["member"] == "Rita Rao"
        assert v["filters"]["member"] == "Rita Rao" and v["filters"]["base"]["member"] == "Rita Rao" and "Sam Rao" in v["filters"]["members"]
        assert v["ledger"]["members"] == v["filters"]["members"]
        assert len(fd.ledger(con, TODAY, {"period": "month", "member": "Nobody"})["ledger"]["rows"]) == 4, "an unknown member is ignored"
        assert len(fd.ledger(con, TODAY, {"period": "month", "q": "sam"})["ledger"]["rows"]) == 1, "the word search covers the card member"
        csv_text = L.csv_file(con, {"period": "month", "member": "Rita Rao"}, TODAY)[1].decode()
        assert csv_text.splitlines()[1].split(",")[6] == "Rita Rao"
        con.execute("UPDATE transactions SET cardholder=NULL WHERE txn_date >= '2031-01-01'")
        assert [r for r in L.members(con) if r in ("Rita Rao", "Sam Rao")] == []


def test_credit_cards_such_as_amex_are_in_the_account_filter(root, modules):
    L = modules("ledger_data")
    with db(root) as con:
        con.execute("DELETE FROM transactions WHERE txn_date >= '2031-01-01'")
        a = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Amex Gold Card', 'credit', '3333')").lastrowid
        con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Amex Empty Card', 'credit', '4444')")
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (a, "2031-10-02", "AMEX TEST BUY", -9))
        labels = [lbl for _, lbl in L.account_list(con)]
        assert "Amex Gold Card x3333" in labels and "Amex Empty Card x4444" not in labels, "accounts with lines only"
        con.execute("DELETE FROM transactions WHERE description='AMEX TEST BUY'")
        con.execute("DELETE FROM accounts WHERE name LIKE 'Amex % Card' AND last4 IN ('3333','4444')")


def test_quick_view_detail_and_neighbors_follow_the_filtered_list(root, modules):
    L = modules("ledger_data")
    with db(root) as con:
        chk, card = _seed(con)
        con.execute("UPDATE transactions SET cardholder='Rita Rao', ref='REF-1', payee='Shell' WHERE description='SHELL OIL'")
        ids = {r[0]: r[1] for r in con.execute("SELECT description, id FROM transactions WHERE txn_date >= '2031-01-01'")}
        t = L.txn_detail(con, ids["SHELL OIL"])
        assert (t["description"], t["amount_text"], t["member"], t["ref"], t["payee"]) == ("SHELL OIL", "-$40.00", "Rita Rao", "REF-1", "Shell")
        assert t["account"] == "Visa x2222" and t["category"] == "Uncategorized" and t["type"] == "Spending" and t["manual"] is False
        assert L.txn_detail(con, 999999) is None and L.txn_detail(con, "x") is None
        f = L.parse({"from": "2031-10-01", "to": "2031-10-31"}, TODAY)
        # newest first: payroll 14th, card payment 12th... as listed: 10-14, 10-13, 10-12, 10-05
        pos, total, prev, nxt = L.neighbors(con, f, ids["SAFEWAY #12"])
        assert (pos, total) == (2, 4) and prev == ids["ACME PAYROLL"] and nxt == ids["PAYMENT TO VISA"]
        assert L.neighbors(con, f, ids["ACME PAYROLL"])[2] is None, "nothing above the first line"
        assert L.neighbors(con, f, ids["SHELL OIL"])[3] is None, "nothing below the last"
        assert L.neighbors(con, f, ids["OLD DEPOSIT"]) == (None, 4, None, None), "a line outside the filter has no place in it"
        only = L.parse({"from": "2031-10-01", "to": "2031-10-31", "account": str(card)}, TODAY, L.account_list(con))
        assert L.neighbors(con, only, ids["SAFEWAY #12"])[3] == ids["SHELL OIL"], "the filters decide the neighbours"


def _month(con):
    """A month shaped like a real one: pay missing (that account's newest line is last month), own-account transfers some
    matched and one not, card payments some matched and some without a bank line, a big insurance charge, a 529 deposit."""
    con.execute("DELETE FROM transactions WHERE txn_date >= '2031-01-01'")
    con.execute("DELETE FROM accounts WHERE name LIKE 'Ledger test %'")
    ids = {}
    for key, name, kind in (("pay", "Ledger test Pay Checking", "checking"), ("joint", "Ledger test Joint", "checking"),
                            ("side", "Ledger test Side Checking", "checking"), ("other", "Ledger test Other Bank", "checking"),
                            ("save", "Ledger test Savings", "savings"), ("x", "Ledger test Card X", "credit"),
                            ("y", "Ledger test Card Y", "credit")):
        ids[key] = con.execute("INSERT INTO accounts(name, type, last4) VALUES (?,?,?)", (name, kind, "77" + str(len(ids)) + "0")).lastrowid
    rows = [("pay", "2031-09-30", "PAY LAST MONTH", "income", "Salary", 4000.00),
            ("joint", "2031-10-05", "WEB XFER OUT", "transfer", "transfer", -2000.00), ("side", "2031-10-05", "WEB XFER IN", "transfer", "transfer", 2000.00),
            ("other", "2031-10-05", "ONLINE XFER OUT", "transfer", "transfer", -5000.00), ("save", "2031-10-06", "RTP IN", "transfer", "transfer", 5000.00),
            ("other", "2031-10-05", "XFER TO SOMEONE", "transfer", "transfer", -200.00),
            ("joint", "2031-10-10", "PAY CARD Y", "card_payment", "credit card", -300.00), ("y", "2031-10-11", "PAYMENT THANK YOU", "card_payment", None, 300.00),
            ("x", "2031-10-18", "AUTOPAY THANK YOU", "card_payment", None, 971.69), ("y", "2031-10-16", "AUTOMATIC PAYMENT", "card_payment", None, 28.75),
            ("side", "2031-10-06", "PAY OTHER CARD", "card_payment", "credit card", -65.66),
            ("joint", "2031-10-06", "529 CONTRIB", "investment_transfer", "investing", -500.00), ("joint", "2031-10-06", "529 CONTRIB 2", "investment_transfer", "investing", -1000.00),
            ("x", "2031-10-16", "SUPERMARKET", "spend", "groceries", -100.00), ("x", "2031-10-13", "INSURER", "spend", "insurance", -4797.00),
            ("side", "2031-10-13", "PHONE CARRIER", "spend", "utilities", -280.21), ("side", "2031-10-06", "PAYPAL BACK", "spend", "associations", 5.57)]
    for key, day, desc, ty, cat, amt in rows:
        con.execute("INSERT INTO transactions(account_id, txn_date, description, txn_type, category, amount) VALUES (?,?,?,?,?,?)",
                    (ids[key], day, desc, ty, cat, amt))
    return ids


def test_tiles_are_cash_flow_not_the_sum_of_the_list(root, modules):
    L, fd = modules("ledger_data"), modules("finance_data")
    with db(root) as con:
        _month(con)
        f = L.parse({"period": "month"}, TODAY)
        S = L.summary(con, f)
        assert S["n"] == 16, "the September pay line is outside the month"
        assert round(S["spending"], 2) == -5171.64 and round(S["bills"], 2) == -5077.21 and S["income"] == 0
        assert S["invested"] == -1500 and S["moved"] == 7000, "2,000 and 5,000 moved between own accounts, counted once each"
        assert round(S["moved_open_out"], 2) == -200 and S["moved_open_in"] == 0
        assert round(S["cards"], 2) == 1366.10 and S["cards_matched"] == 300
        assert round(S["cards_open_in"], 2) == 1000.44 and round(S["cards_open_out"], 2) == -65.66
        g = S["everything"]
        assert round(sum(v[0] for v in g.values()), 2) == 8306.01 and round(sum(v[1] for v in g.values()), 2) == -14242.87,             "the old Money in / out is the sum of the groups"
        v = fd.ledger(con, TODAY, {"period": "month"})
        t = {x[0]: x[1] for x in v["tiles"]}
        assert t["Spending"] == "$5,171.64" and t["Bills paid"] == "$5,077.21" and t["Invested"] == "$1,500.00"
        assert t["Between your accounts"] == "$7,000.00" and t["Income"] == "$0.00" and t["Left over"] == "-$5,171.64"
        assert [x for x in v["tiles"] if x[0] == "Left over"][0][2] == "bad"
        text = " ".join(n[1] for n in v["notes"])
        assert "Ledger test Pay Checking x7700 (Sep 30)" in text, "the account that has no line this month is named"
        assert "No pay in these dates" in text and "Other side not loaded" in text and "$1,000.44 paid onto cards" in text
        s = v["ledger"]["sums"]
        assert s["in"] == "$8,306.01" and s["out"] == "-$14,242.87"
        assert ("Between your accounts", "$7,000.00", "-$7,000.00") in s["rows"] and ("Invested", "", "-$1,500.00") in s["rows"]


def test_type_filter_gives_plain_totals_and_chips_follow(root, modules):
    L, fd = modules("ledger_data"), modules("finance_data")
    with db(root) as con:
        _month(con)
        v = fd.ledger(con, TODAY, {"period": "month", "type": "transfer"})
        t = {x[0]: x[1] for x in v["tiles"]}
        assert t["In"] == "$7,000.00" and t["Out"] == "-$7,200.00" and t["Total"] == "-$200.00" and t["Lines"] == 5
        assert v["notes"] == [] and v["ledger"]["sums"] is None, "a type filter shows plain totals, no cash-flow summary"
        chips = {c[0]: c for c in v["ledger"]["chips"]}
        assert chips["All"][1] == 16 and chips["Transfers"][1] == 5 and chips["Transfers"][4] is True and chips["Spending"][4] is False
        assert "type=transfer" in chips["Transfers"][3] and "type=" not in chips["All"][3], "All drops the type, the others keep the dates"
        assert "from=2031-10-01" in chips["Spending"][3]
        rows = {r["description"]: r["pair"] for r in L.ledger(con, {"type": "transfer"}, TODAY, fd)["ledger"]["rows"]}
        assert rows["WEB XFER OUT"] == rows["WEB XFER IN"] == "matched" and rows["XFER TO SOMEONE"] == "open"


def test_pairs_need_same_cents_another_account_and_a_few_days(root, modules):
    L = modules("ledger_data")
    with db(root) as con:
        ids = _month(con)
        add = lambda k, d, a: con.execute("INSERT INTO transactions(account_id, txn_date, description, txn_type, amount) VALUES (?,?,?,'transfer',?)",
                                          (ids[k], d, "t", a)).lastrowid
        o1, o2, i1 = add("pay", "2031-10-20", -500), add("pay", "2031-10-20", -500), add("save", "2031-10-23", 500)
        same, late = add("pay", "2031-10-21", 50), add("save", "2031-10-26", 50)
        p = L.pairs(con, "transfer", "2031-10-01", "2031-10-31")
        assert p.get(i1) == o1 and o2 not in p, "one deposit pairs with one withdrawal, the earlier first"
        assert same not in p and late not in p, "no partner in the same account; 5 days apart is too far"
        add("pay", "2031-10-30", -75), add("save", "2031-11-02", 75)
        assert len(L.pairs(con, "transfer", "2031-10-01", "2031-10-31")) == len(p) + 2, "a pair across the end of the month still pairs"


def test_every_ledger_type_can_be_filtered_and_edited(modules):
    L = modules("ledger_data")
    for k in ("fee", "utility", "insurance", "loan_payment"):
        assert k in dict(L.TYPES) and L.parse({"type": k}, TODAY, (), (), ())["type"] == k


def test_an_account_with_no_lines_in_the_dates_is_named(root, modules):
    fd = modules("finance_data")
    with db(root) as con:
        ids = _month(con)
        v = fd.ledger(con, TODAY, {"period": "month", "account": str(ids["pay"])})
        assert v["ledger"]["n"] == 0 and {x[0]: x[1] for x in v["tiles"]}["Lines"] == 0
        text = " ".join(n[1] for n in v["notes"])
        assert "Ledger test Pay Checking x7700 (Sep 30)" in text and "Add its latest statement." in text, text
        assert "No pay" not in text, "nothing to say about pay for an empty list"
        ok = fd.ledger(con, TODAY, {"period": "month", "account": str(ids["x"])})
        assert ok["ledger"]["n"] > 0 and "Card X" not in " ".join(n[1] for n in ok["notes"]), "an account that is up to date is not flagged"
