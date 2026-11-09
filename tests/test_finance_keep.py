"""Finance > Keep: cash (checking, savings) apart from investment accounts; below zero is owed. Deposits and Bills:
From / To months, a category filter and a search over every column a person reads."""
import datetime as D

from conftest import db


def test_keep_splits_cash_from_investments(modules):
    fd = modules("finance_data")
    bal = [{"type": "checking", "signed_balance": 100.0}, {"type": "savings", "signed_balance": 50.0},
           {"type": "investment", "signed_balance": 1000.0}, {"type": "credit", "signed_balance": -30.0},
           {"type": "checking", "signed_balance": -5.0}, {"type": "savings", "signed_balance": None}]
    assert fd.keep_split(bal) == (150.0, 1000.0, 35.0)


def test_deposit_sources_and_bills_take_a_month_range_a_category_and_a_wide_search(root, modules):
    fd, R = modules("finance_data"), modules("records")
    assert dict(R.GROUPS["money"])["Keep"] == ["accounts", "budget", "benefits"]
    assert dict(R.GROUPS["money"])["Look back"][:2] == ["ledger", "deposits"], "R5: Deposit sources next to the Ledger"
    today = D.date(2026, 10, 17)
    with db(root) as con:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Joint Savings', 'savings', '0080')").lastrowid
        for day, desc, payee, typ, cat, amt in (("2026-08-15", "ACME PAYROLL", "Acme", "income", "Salary", 3000),
                                                ("2026-09-30", "INTEREST PAID", "TrustCo", "interest", "Interest", 0.05),
                                                ("2026-10-02", "ZELLE FROM PAT", None, "transfer", "Transfers", 40)):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, payee, txn_type, category, amount) "
                        "VALUES (?,?,?,?,?,?,?)", (acc, day, desc, payee, typ, cat, amt))
        con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Electric & gas', 'Power Co', 90, "
                    "'2026-09-09', 'paid')")
        con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Home insurance premium', 'Acme Mutual', 30, '2026-10-12', "
                    "'due')")
        c = con

        v = fd.deposits(c, today, {"from": "2026-08", "to": "2026-10"})
        keys = " ".join(m["key"] for m in v["rules"]["merchants"])
        assert "ACME PAYROLL" in keys and v["filters"]["range"] and v["rules"]["deposits"] and not v.get("blocks")
        assert v["go"] == [("See the pay in the Ledger", "/money?part=ledger&type=income&from=2026-08-01&to=2026-10-31")]
        assert fd.deposits(c, today, {"from": "2026-10", "to": "2026-08"})["filters"]["from"] == "2026-08", "turned round"

        b = fd.bills(c, today, {"from": "2026-09", "to": "2026-10"})
        assert "Electric &amp; gas" in str(b["blocks"]) or "Electric & gas" in str(b["blocks"])
        assert "Home insurance premium" in str(b["blocks"]) and "Sep 2026 - Oct 2026" in str(b["blocks"])
        assert "Utilities" in b["filters"]["cats"] and b["filters"]["from"] == "2026-09"
        u = fd.bills(c, today, {"from": "2026-09", "to": "2026-10", "cat": "Utilities"})
        assert "Electric & gas" in str(u["blocks"]) and "Home insurance premium" not in str(u["blocks"])
        assert "Electric & gas" in str(fd.bills(c, today, {"from": "2026-09", "to": "2026-10", "q": "power co"})["blocks"])


def test_bills_and_accounts_lead_with_what_is_scanned_first(root, modules):
    """Bills: Due, Status, Amount, then the name (the link and the phone title); Accounts: the name, then the balance."""
    fd = modules("finance_data")
    today = D.date(2035, 2, 10)
    with db(root) as con:
        con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Order Test Water', 'Order Co', 12.5, '2035-02-12', 'due')")
        b = fd.bills(con, today, {"from": "2035-02", "to": "2035-02"})["blocks"][-1]
        assert b["cols"][:6] == ["Due", "Status", "Amount", "Name", "Vendor", "Category"] and b["title_ix"] == 3
        assert b["nums"] == {2}, "the amount stays right-aligned"
        row = [r for r in b["rows"] if "Order Test Water" in r["cells"]][0]
        assert row["list"]["title"] == "Order Test Water" and row["list"]["amount"] == "$12.50", "the phone row is still named by the bill"
        assert row["pills"] == {1: "warn"} or 1 in row["pills"], "Status keeps its pill"
        a = fd.accounts(con, today, {})["blocks"][0]
        if a["rows"]:
            assert a["cols"][:2] == ["Account", "Reported"] and a["title_ix"] == 0


def test_net_worth_by_month_from_reported_balances(root, modules):
    """Money > Keep > Accounts: each month's latest balance per account, cards owed, oldest month with any balance first."""
    fd = modules("finance_data")
    today = D.date(2041, 3, 10)
    with db(root) as con:
        chk = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('NW checking', 'checking', '1111')").lastrowid
        card = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('NW card', 'credit', '2222')").lastrowid
        inv = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('NW broker', 'investment', '3333')").lastrowid
        for acct, day, bal in ((chk, "2041-01-31", 1000), (card, "2041-01-31", 200), (chk, "2041-02-28", 1500),
                               (inv, "2041-02-15", 5000), (chk, "2041-03-05", 1200), (card, "2041-03-05", 300)):
            con.execute("INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?,?,?, 'statement')",
                        (acct, day, bal))
        con.commit()
        mine = [h for h in fd.net_worth_history(con, today, months=4)]
        # balances of other tests' accounts are dated before 2041 and count too; compare month to month
        by = {h["month"]: h for h in mine}
        assert list(by)[-3:] == ["Jan 2041", "Feb 2041", "Mar 2041"]
        assert by["Feb 2041"]["net"] - by["Jan 2041"]["net"] == 500 + 5000, "checking up 500, the broker counted from Feb"
        assert by["Mar 2041"]["net"] - by["Feb 2041"]["net"] == -300 - 100, "checking down 300, the card owes 100 more"
        assert by["Mar 2041"]["owed"] - by["Jan 2041"]["owed"] == 100
        blk = [b for b in fd.accounts(con, today, {})["blocks"] if b["heading"] == "Net worth by month"][0]
        assert blk["cols"][:5] == ["Month", "Cash", "Investments", "Cards and loans owed", "Net worth"]
        assert blk["rows"][0]["cells"][0] == "Mar 2041" and blk["rows"][0]["cells"][-1].startswith("-"), "newest first"
