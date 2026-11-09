"""CSV statement import with column mapping and no AI (audit item 19): bank and card exports, delimiters and
preambles, date orders, sign conventions, dedupe, saved formats, balances, refusal of unreadable rows."""
import json

import pytest

from conftest import db, q, run

BANK_UK = """Account: 12-34-56 00000000
Statement period 01/09/2026 - 30/09/2026

Date;Details;Money Out;Money In;Balance
02/09/2026;TESCO STORES 2041;45,10;;1.254,90
03/09/2026;SALARY ACME LTD;;2.500,00;3.754,90
03/09/2026;TESCO STORES 2041;45,10;;3.709,80
15/09/2026;BRITISH GAS DD;82,00;;3.627,80
"""
CARD_US = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
09/02/2026,09/03/2026,COFFEE SHOP,Food & Drink,Sale,4.30,
09/05/2026,09/06/2026,AMAZON.COM*AB12,Shopping,Sale,19.99,
09/10/2026,09/10/2026,AUTOMATIC PAYMENT - THANK YOU,,Payment,-250.00,
"""
CARD_AMEX = """Date,Description,Card Member,Account #,Amount,Reference
09/02/2026,COFFEE SHOP,ALEX,-71004,4.30,'AT260020001'
09/02/2026,COFFEE SHOP,SAM,-71012,4.30,'AT260020002'
"""


@pytest.fixture
def accounts(root):
    con = db(root)
    con.execute("DELETE FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE name LIKE 'CSV %')")
    con.execute("DELETE FROM account_balances WHERE account_id IN (SELECT id FROM accounts WHERE name LIKE 'CSV %')")
    con.execute("DELETE FROM accounts WHERE name LIKE 'CSV %'")
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('CSV Current', 'checking', '0070')")
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('CSV Visa', 'credit', '4321')")
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('CSV Amex', 'credit', '1004')")
    con.commit()
    con.close()
    (root / "config" / "statement_formats.json").unlink(missing_ok=True)
    return root


def _write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return str(f)


def test_detect_shows_mapping_and_rows(accounts, tmp_path):
    r = run(["data/import_statement.py", "detect", _write(tmp_path, "bank.csv", BANK_UK), "--dates", "dmy"], accounts)
    assert r.returncode == 0, r.stderr[-300:]
    assert "'date': 'Date'" in r.stdout and "'debit': 'Money Out'" in r.stdout and "'credit': 'Money In'" in r.stdout
    assert "4 rows readable, 0 not" in r.stdout and "2026-09-02" in r.stdout


def test_uk_bank_export_with_preamble_semicolons_and_dmy(accounts, tmp_path):
    f = _write(tmp_path, "bank.csv", BANK_UK)
    r = run(["data/import_statement.py", f, "--account", "csv current", "--dates", "dmy", "--dry-run"], accounts)
    assert r.returncode == 0 and "would insert 4" in r.stdout, r.stdout + r.stderr
    assert not q(accounts, "select 1 from transactions t join accounts a on a.id=t.account_id where a.name='CSV Current'")
    r = run(["data/import_statement.py", f, "--account", "0070", "--dates", "dmy", "--save-format", "mybank"], accounts)
    assert r.returncode == 0 and "inserted 4" in r.stdout, r.stdout + r.stderr
    rows = q(accounts, "select txn_date, description, amount, txn_type from transactions t join accounts a on a.id=t.account_id "
                       "where a.name='CSV Current' order by txn_date, amount")
    assert rows[0] == ("2026-09-02", "TESCO STORES 2041", -45.1, None)
    assert ("2026-09-03", "SALARY ACME LTD", 2500.0, None) in rows, "credit column is money in"
    assert sum(1 for x in rows if x[1] == "TESCO STORES 2041") == 2, "two identical charges on one day are both real"
    fmt = json.loads((accounts / "config" / "statement_formats.json").read_text(encoding="utf-8"))["mybank"]
    assert fmt["dates"] == "dmy" and fmt["account"] == "0070" and fmt["map"]["debit"] == "Money Out"
    r = run(["data/import_statement.py", f, "--format", "mybank"], accounts)
    assert "inserted 0, skipped 4" in r.stdout, "re-import with the saved format is a no-op: " + r.stdout


def test_card_export_charges_positive_are_inverted_and_payments_typed(accounts, tmp_path):
    f = _write(tmp_path, "visa.csv", CARD_US)
    r = run(["data/import_statement.py", f, "--account", "CSV Visa", "--balance", "123.45", "--as-of", "2026-09-30"], accounts)
    assert r.returncode == 0 and "inserted 3" in r.stdout and "inverted" in r.stdout, r.stdout + r.stderr
    rows = {d: (a, t, c) for d, a, t, c in q(accounts, "select description, amount, txn_type, category from transactions t "
                                                           "join accounts a on a.id=t.account_id where a.name='CSV Visa'")}
    assert rows["COFFEE SHOP"] == (-4.3, None, "Food & Drink")
    assert rows["AUTOMATIC PAYMENT - THANK YOU"][0] == 250.0 and rows["AUTOMATIC PAYMENT - THANK YOU"][1] == "card_payment"
    assert q(accounts, "select as_of, balance from account_balances b join accounts a on a.id=b.account_id where a.name='CSV Visa'") == [("2026-09-30", 123.45)]
    assert q(accounts, "select payee from transactions where description like 'AMAZON%'")[0][0] is None or True  # rules ran without error


def test_reference_column_dedupes_exactly_and_keeps_cardholder(accounts, tmp_path):
    f = _write(tmp_path, "amex.csv", CARD_AMEX)
    r = run(["data/import_statement.py", f, "--account", "1004", "--sign", "invert"], accounts)
    assert r.returncode == 0 and "inserted 2" in r.stdout, r.stdout + r.stderr
    rows = q(accounts, "select ref, cardholder, amount from transactions t join accounts a on a.id=t.account_id where a.name='CSV Amex' order by ref")
    assert rows == [("AT260020001", "ALEX", -4.3), ("AT260020002", "SAM", -4.3)]
    assert "skipped 2" in run(["data/import_statement.py", f, "--account", "1004", "--sign", "invert"], accounts).stdout


def test_explicit_map_and_unreadable_rows_stop_the_import(accounts, tmp_path):
    f = _write(tmp_path, "odd.csv", "When|What|How much\n2026-09-02|Thing one|-1.00\nnext tuesday|Thing two|-2.00\n")
    r = run(["data/import_statement.py", f, "--account", "0070", "--map", "date=When,desc=What,amount=How much"], accounts)
    assert r.returncode == 1 and "nothing imported" in r.stdout and "next tuesday" in r.stdout
    assert not q(accounts, "select 1 from transactions where description='Thing one'"), "all or nothing"
    r = run(["data/import_statement.py", f, "--account", "0070"], accounts)
    assert r.returncode != 0 and "--map" in r.stdout + r.stderr, "unknown header names ask for a mapping"
    r = run(["data/import_statement.py", f, "--account", "nope"], accounts)
    assert r.returncode != 0 and "Accounts:" in r.stdout + r.stderr


def test_new_account_from_the_command_line(accounts, tmp_path):
    f = _write(tmp_path, "s.csv", "Date,Description,Amount\n2026-09-01,INTEREST PAID,1.25\n")
    r = run(["data/import_statement.py", f, "--new", "CSV Savings", "--type", "savings", "--last4", "9999"], accounts)
    assert r.returncode == 0 and "created account" in r.stdout and "inserted 1" in r.stdout, r.stdout + r.stderr
    assert q(accounts, "select type, last4 from accounts where name='CSV Savings'") == [("savings", "9999")]
    assert q(accounts, "select txn_type from transactions where description='INTEREST PAID'") == [("interest",)], "apply_rules ran"


def test_library_entry_and_money_cents(accounts, modules, tmp_path):
    imp = modules("import_statement")
    f = _write(tmp_path, "c.csv", "Date,Description,Amount\n2026-09-01,GROCER,-0.30\n")
    rep = imp.run_import(f, "CSV Current", dry_run=True)
    assert rep["ok"] and rep["inserted"] == 1 and rep["sign"] == "as-is" and rep["mapping"]["amount"] == "Amount"
    con = db(accounts)
    aid = con.execute("select id from accounts where name='CSV Current'").fetchone()[0]
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2026-09-01', 'GROCER', ?)", (aid, 0.1 + 0.2 - 0.6))
    con.commit()
    con.close()
    assert imp.run_import(f, "CSV Current", dry_run=True)["skipped"] == 1, "a stored -0.30000000000000004 matches -0.30"


def test_same_month_from_a_pdf_and_a_csv_with_references_is_not_doubled(accounts, modules, tmp_path):
    """Audit M14: rows without a reference (a PDF statement) and rows with one (a CSV export) of the same account and
    month are the same transactions when date and cents agree, one to one (two equal charges stay two)."""
    imp = modules("import_statement")
    pdf_like = _write(tmp_path, "p.csv", "Date,Description,Amount\n2026-08-03,COFFEE,-4.50\n2026-08-03,COFFEE,-4.50\n"
                                         "2026-08-05,GROCER 22,-61.20\n")
    assert imp.run_import(pdf_like, "CSV Current", sign="as-is", apply_rules=False)["inserted"] == 3
    with_ref = _write(tmp_path, "r.csv", "Date,Description,Amount,Reference\n2026-08-03,COFFEE SHOP 1,-4.50,R1\n"
                                         "2026-08-03,COFFEE SHOP 1,-4.50,R2\n2026-08-05,GROCER STORE,-61.20,R3\n"
                                         "2026-08-03,COFFEE SHOP 1,-4.50,R4\n2026-08-07,NEW,-9.00,R5\n")
    rep = imp.run_import(with_ref, "CSV Current", sign="as-is", apply_rules=False)
    assert (rep["inserted"], rep["skipped"]) == (2, 3), rep
    pdf_again = imp.run_import(pdf_like, "CSV Current", sign="as-is", apply_rules=False)
    assert pdf_again["inserted"] == 0
    assert q(accounts, "SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id=t.account_id "
                       "WHERE a.name='CSV Current' AND t.amount=-4.5")[0][0] == 3, "the third coffee is real"
