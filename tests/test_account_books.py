"""Accounts as books, slice 1 (PLAN_money_books): detailed types (account_types.py, migration 070), the Edit account
form (records_edit + edit_actions.account_update), merging two rows of one bank account, and bank sync keeping the
bank's name and never re-guessing a type a person picked."""
from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


def _acct(root, name, typ, last4=None, **extra):
    con = db(root)
    cols = ["name", "type", "last4", *extra]
    cur = con.execute(f"INSERT INTO accounts({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                      (name, typ, last4, *extra.values()))
    con.commit()
    rid = cur.lastrowid
    con.close()
    return rid


def test_guesses_from_name_and_bank(modules):
    AT = modules("account_types")
    cases = {("Home Mortgage", None): "mortgage", ("Highlander", "Toyota Financial Services"): "auto",
             ("Mateo College 529", None): "529", ("Retirement 401(k)", None): "401k", ("Roth IRA", None): "roth_ira",
             ("Rollover IRA", None): "ira", ("12-month CD", None): "cd", ("I Bonds", "TreasuryDirect"): "treasury_direct",
             ("Health Savings Account", None): "hsa", ("Rainy Day Money Market", None): "money_market",
             ("Family Savings", None): "savings", ("Gold Card", "American Express"): "credit_card",
             ("RedCard", "Target"): "store_card", ("Individual Brokerage", "Fidelity"): "brokerage",
             ("Home Equity Line", None): "heloc", ("Sofa plan", "Ashley Furniture"): "furniture",
             ("Everyday Checking", None): "checking"}
    for (name, org), want in cases.items():
        assert AT.guess(name, org) == (want, True), (name, org)
    assert AT.guess("Joint", None) == ("checking", False), "no word = checking, not sure"
    for sub, (group, coarse, label) in AT.SUBTYPES.items():
        assert group in AT.GROUPS and coarse in AT.DEFAULT_OF_TYPE and label
    assert AT.resolve("savings", "Rainy Day Money Market") == "money_market"
    assert AT.resolve("checking", "Home Mortgage") == "checking", "a guess that disagrees with the known type loses"
    assert AT.owed("mortgage") and AT.owed("credit_card") and not AT.owed("529")


def test_migration_gives_old_rows_a_subtype_and_owners(root, modules):
    cols = {r[1] for r in q(root, "PRAGMA table_info(accounts)")}
    assert {"subtype", "subtype_locked", "institution", "ownership", "owners", "closed_on", "credit_limit", "apr_pct",
            "due_day", "min_payment", "sort"} <= cols
    assert "account_id" in {r[1] for r in q(root, "PRAGMA table_info(loans)")}
    assert "account_id" in {r[1] for r in q(root, "PRAGMA table_info(investments)")}
    rid = _acct(root, "Old Mortgage", "loan", owner="Alex")
    con = db(root)
    con.execute("UPDATE accounts SET subtype=NULL, owners=NULL WHERE id=?", (rid,))
    con.execute("DELETE FROM schema_migrations WHERE name LIKE 'migrate_070%'")
    con.commit()
    con.close()
    modules("migrate").run()
    assert q(root, "SELECT subtype, owners, ownership, subtype_locked FROM accounts WHERE id=?", rid)[0] == \
        ("mortgage", "Alex", "individual", 0)
    assert not q(root, "SELECT id FROM accounts WHERE subtype IS NULL")


def test_edit_account_changes_type_locks_it_and_checks_joint(root, modules):
    ea, re_ = modules("edit_actions"), modules("records_edit")
    rid = _acct(root, "Rainy Day", "checking", "5521", subtype="checking")
    v = re_.values("accounts", rid)
    assert v["kind"] == "checking" and v["guessed"] and v["group"] == "bank"
    form = {"name": "Rainy Day", "kind": "money_market", "institution": "Discover", "ownership": "joint",
            "owners": "Alex", "closed_on": "", "credit_limit": "", "apr": "", "due_day": "", "min_payment": ""}
    ok, msg, _ = re_.edit(ADULT, "accounts", "save", rid, form)
    assert not ok and "two owners" in msg
    ok, msg, gone = re_.edit(ADULT, "accounts", "save", rid, {**form, "owners": "Alex, Jordan"})
    assert ok and not gone, msg
    assert q(root, "SELECT type, subtype, subtype_locked, institution, ownership, owners FROM accounts WHERE id=?", rid)[0] == \
        ("savings", "money_market", 1, "Discover", "joint", "Alex, Jordan")
    assert not re_.values("accounts", rid)["guessed"]
    assert ea.account_update(ADULT, rid, closed_on="2999-01-01")[0] is False, "closed in the future"
    assert ea.account_update(KID, rid, name="Mine")[0] is False, "adults only"
    assert ea.account_update(ADULT, rid, name="Rainy Day")[1] == "Nothing changed."
    card = _acct(root, "Gold Card", "credit", "1004", subtype="credit_card")
    assert re_.values("accounts", card)["group"] == "card"
    ok, msg = ea.account_update(ADULT, card, credit_limit="15000", apr="24.99", due_day="22", min_payment="40")
    assert ok, msg
    assert q(root, "SELECT credit_limit, apr_pct, due_day, min_payment FROM accounts WHERE id=?", card)[0] == (15000, 24.99, 22, 40)
    assert ea.account_update(ADULT, card, due_day="32")[0] is False


def test_add_account_takes_a_subtype_or_an_old_type(root, modules):
    ea = modules("edit_actions")
    assert ea.account_add(ADULT, "Mateo 529", "529", "3390", "Alex", "NY Saves", "individual")[0]
    assert ea.account_add(ADULT, "Plain savings", "savings")[0]
    assert ea.account_add(ADULT, "Bad", "rocket")[0] is False
    assert q(root, "SELECT type, subtype, subtype_locked, institution FROM accounts WHERE name='Mateo 529'")[0] == \
        ("investment", "529", 1, "NY Saves")
    assert q(root, "SELECT type, subtype FROM accounts WHERE name='Plain savings'")[0] == ("savings", "savings")


def test_merge_moves_lines_and_balances_and_keeps_repeats_once(root, modules):
    ea, re_ = modules("edit_actions"), modules("records_edit")
    keep = _acct(root, "Merge Checking", "checking", "7001")
    drop = _acct(root, "MERGE CHK (bank sync)", "checking", None, simplefin_id="ACT-m", institution="Test Bank")
    other = _acct(root, "Merge Card", "credit", "7002")
    con = db(root)
    con.executemany("INSERT INTO transactions(account_id, txn_date, description, amount, ref) VALUES (?,?,?,?,?)",
                    [(keep, "2026-11-01", "A", -10, "r1"), (drop, "2026-11-01", "A", -10, "r1"),
                     (drop, "2026-11-02", "B", -20, "r2"), (drop, "2026-11-03", "C", -30, None)])
    con.executemany("INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?,?,?,'snapshot')",
                    [(keep, "2026-11-03", 100), (drop, "2026-11-03", 100), (drop, "2026-11-04", 70)])
    con.commit()
    con.close()
    v = re_.values("accounts", keep)
    assert str(drop) in {i for i, _ in v["others"]} and str(other) not in {i for i, _ in v["others"]}, "same kind only"
    assert re_.edit(ADULT, "accounts", "merge", keep, {"other": str(drop)})[0] is False, "needs the tick box"
    assert re_.edit(ADULT, "accounts", "merge", keep, {"other": str(other), "sure": "1"})[0] is False
    ok, msg, _ = re_.edit(ADULT, "accounts", "merge", keep, {"other": str(drop), "sure": "1"})
    assert ok, msg
    assert not q(root, "SELECT 1 FROM accounts WHERE id=?", drop)
    assert sorted(q(root, "SELECT description, ref FROM transactions WHERE account_id=?", keep), key=str) == \
        sorted([("A", "r1"), ("B", "r2"), ("C", None)], key=str)
    assert q(root, "SELECT as_of, balance FROM account_balances WHERE account_id=? ORDER BY as_of", keep) == \
        [("2026-11-03", 100), ("2026-11-04", 70)]
    assert q(root, "SELECT last4, simplefin_id, institution FROM accounts WHERE id=?", keep)[0] == ("7001", "ACT-m", "Test Bank")
    assert ea.account_merge(ADULT, keep, keep)[0] is False
    assert ea.account_merge(ADULT, keep, other)[0] is False, "a card is not a checking account"


def test_bank_sync_keeps_the_bank_name_and_a_picked_type(root, modules):
    bs, ea = modules("bank_sync"), modules("edit_actions")
    con = db(root)
    a = bs.map_account(con, {"id": "ACT-hm", "name": "Home Loan", "last4": "5532", "org": "Rocket Mortgage", "currency": "USD"})
    con.commit()
    assert q(root, "SELECT type, subtype, institution, subtype_locked FROM accounts WHERE id=?", a["id"])[0] == \
        ("loan", "mortgage", "Rocket Mortgage", 0)
    b = bs.map_account(con, {"id": "ACT-sv", "name": "Rainy Day", "last4": "8812", "org": "Some Bank", "currency": "USD"})
    con.commit()
    con.close()
    assert ea.account_update(ADULT, b["id"], kind="hsa")[0]
    con = db(root)
    bs.map_account(con, {"id": "ACT-sv", "name": "Rainy Day", "last4": "8812", "org": "Other Name", "currency": "USD"})
    con.commit()
    con.close()
    assert q(root, "SELECT subtype, subtype_locked, institution FROM accounts WHERE id=?", b["id"])[0] == \
        ("hsa", 1, "Some Bank"), "a picked type and an existing bank name are kept"
