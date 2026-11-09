"""Statement PDFs without AI (data/pdf_statement.py): bank layout with Deposits / Withdrawals / Checks sections, card
layout with posted and transaction dates and references, the balance check, the year of MM/DD dates from the period
(December-January), dedupe on a second import, refusal when the balances do not add up, intake routing of
statements, and receipts matched after the import. Text fixtures stand in for the PDF text layer (made-up data)."""
import pytest

from conftest import db, q, run

BANK = """                                                                     Everyday Checking
                                                                     Account number ending: 7070
                                                                     July 31, 2026 to August 31, 2026
Account Summary
Beginning Balance on July 31, 2026                                    $1,000.00
Deposits (Money In)
       Deposits                                                                $2,510.00
Withdrawals (Money Out)
       Withdrawals                                                             -$1,234.56
Ending Balance on August 31, 2026                                     $2,275.44
                                                                                          Page 1 of 2
Deposits
Date                 Description                                                         Amount
08/03               EXAMPLE CORP    PAYROLL                                             $2,500.00
08/31               INTEREST PAYMENT                                                       $10.00
Total Deposits                                                                          $2,510.00
Withdrawals
Other Withdrawals
       Date                 Description                                                  Amount
       08/05                POWER CO        AUTOPAY                                     $134.56
       08/18                NEW YORK STATE  DMV FEE                                     $100.00
       Total Other Withdrawals                                                       -$234.56
Checks
       1367  08/15  $1,000.00
       Total Checks                                                                  -$1,000.00
Total Withdrawals                                                                    -$1,234.56
"""

CARD = """   SAMPLE CASHBACK CARD
   Account Number XXXX XXXX XXXX 9191   Monthly Statement Dec 26, 2026 to Jan 25, 2027
 *Previous Balance   $100.00   *New Balance   $160.25
   Transactions
  POST   TRAN   REFERENCE
  DATE   DATE   NUMBER   DESCRIPTION   AMOUNT $
   12/28   12/27   24692163001234567   CORNER CAFE   ALBANY   NY   12.50
   01/03   01/02   24692163001234568   GROCERY MART #12   LATHAM   NY   87.75
   01/10   01/10   AUTOMATIC PAYMENT - THANK YOU   -100.00
   01/20   01/19   24692163001234569   BOOK SHOP   TROY   NY   60.00
"""


@pytest.fixture(scope="module")
def PS(root, modules):
    return modules("pdf_statement")


@pytest.fixture(scope="module")
def accts(root):
    con = db(root)
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('PDF Checking', 'checking', '7070')")
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('PDF Card', 'credit', '9191')")
    con.commit()
    con.close()
    return root


def _write(tmp_path, name, text):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


def test_bank_sections_checks_and_balance(PS):
    r = PS.parse(BANK, card=False)
    got = [(x["date"], x["amount"], x["desc"]) for x in r["rows"]]
    assert ("2026-08-03", 2500.0, "EXAMPLE CORP PAYROLL") in got
    assert ("2026-08-18", -100.0, "NEW YORK STATE DMV FEE") in got, "a description starting with 'NEW' is not a balance line"
    assert ("2026-08-15", -1000.0, "Check 1367") in got
    assert r["money_in"] == 2510 and r["money_out"] == 1234.56 and r["verified"] is True
    assert r["begin"] == 1000 and r["end"] == 2275.44


def test_card_signs_refs_and_year_rollover(PS):
    r = PS.parse(CARD, card=True)
    rows = {x["desc"].split()[0]: x for x in r["rows"]}
    assert rows["CORNER"]["date"] == "2026-12-27" and rows["CORNER"]["amount"] == -12.5
    assert rows["GROCERY"]["date"] == "2027-01-02" and rows["GROCERY"]["ref"] == "24692163001234568"
    assert rows["AUTOMATIC"]["amount"] == 100.0
    assert r["verified"] is True and "9191" in r["last4"]


def test_import_dedupes_and_records_the_balance(accts, tmp_path):
    f = _write(tmp_path, "aug.txt", BANK)
    r = run(["data/pdf_statement.py", str(f)], accts)
    assert r.returncode == 0, r.stderr[-400:]
    assert "PDF Checking x7070" in r.stdout and "balances check out" in r.stdout and "added 5" in r.stdout
    again = run(["data/pdf_statement.py", str(f)], accts)
    assert "added 0, skipped 5" in again.stdout
    acct = q(accts, "SELECT id FROM accounts WHERE last4='7070'")[0][0]
    assert q(accts, "SELECT balance FROM account_balances WHERE account_id=? AND as_of='2026-08-31'", acct) == [(2275.44,)]
    assert q(accts, "SELECT round(sum(amount),2) FROM transactions WHERE account_id=?", acct) == [(1275.44,)]


def test_unbalanced_statement_is_refused(accts, tmp_path):
    f = _write(tmp_path, "bad.txt", CARD.replace("   01/20   01/19   24692163001234569   BOOK SHOP   TROY   NY   60.00\n", ""))
    r = run(["data/pdf_statement.py", str(f)], accts)
    assert r.returncode != 0 and "do not add up" in r.stderr
    assert not q(accts, "SELECT 1 FROM transactions WHERE description LIKE 'GROCERY MART%'")
    r = run(["data/pdf_statement.py", "check", str(f)], accts)
    assert r.returncode == 0 and "BALANCES DO NOT ADD UP" in r.stdout


def test_unknown_account_and_picture(PS, accts, tmp_path):
    r = run(["data/pdf_statement.py", str(_write(tmp_path, "x.txt", BANK.replace("7070", "1111")))], accts)
    assert r.returncode != 0 and "no account with the last four digits 1111" in r.stderr
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(width=612, height=792)
    pdf = tmp_path / "scan.pdf"
    with open(pdf, "wb") as fh:
        w.write(fh)
    r = run(["data/pdf_statement.py", str(pdf)], accts)
    assert r.returncode != 0 and "picture" in r.stderr


def test_review_queue_statement_is_imported(accts, modules, tmp_path):
    ea = modules("edit_actions")
    (accts / "inbox" / "needs_review").mkdir(parents=True, exist_ok=True)
    (accts / "inbox" / "needs_review" / "card_jan.txt").write_text(CARD, encoding="utf-8")
    con = db(accts)
    con.execute("INSERT INTO review_queue(path, reason, created_at) VALUES ('inbox/needs_review/card_jan.txt', 'statement', '2027-01-26')")
    con.commit()
    rv = con.execute("SELECT max(id) FROM review_queue").fetchone()[0]
    con.close()
    ok, msg = ea.review_file({"name": "Alex", "role": "adult"}, rv, "statement", "Sample Card", "2027-01-25")
    assert ok and "4 transactions added" in msg, msg
    doc = q(accts, "SELECT id FROM documents WHERE doc_type='statement' ORDER BY id DESC LIMIT 1")[0][0]
    assert q(accts, "SELECT count(*) FROM transactions WHERE document_id=?", doc) == [(4,)]


def test_a_photo_or_cut_off_file_is_a_message_not_a_crash(accts, modules, tmp_path):
    ea = modules("edit_actions")
    jpg = tmp_path / "scan.pdf"
    jpg.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 200)
    r = run(["data/pdf_statement.py", str(jpg)], accts)
    assert r.returncode != 0 and "not a PDF" in r.stderr and "Traceback" not in r.stderr
    cut = tmp_path / "cut.pdf"
    cut.write_bytes(b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nstream\n")
    r = run(["data/pdf_statement.py", str(cut)], accts)
    assert r.returncode != 0 and "Traceback" not in r.stderr
    (accts / "inbox" / "needs_review").mkdir(parents=True, exist_ok=True)
    (accts / "inbox" / "needs_review" / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 200)
    con = db(accts)
    con.execute("INSERT INTO review_queue(path, reason, created_at) VALUES ('inbox/needs_review/photo.jpg', 'photo', '2027-01-26')")
    con.commit()
    rv = con.execute("SELECT max(id) FROM review_queue").fetchone()[0]
    con.close()
    ok, msg = ea.review_file({"name": "Alex", "role": "adult"}, rv, "statement", "Sample Dental", "2027-01-25")
    assert ok and "photo" in msg and "Filed as" in msg, msg


def test_receipt_matched_after_pdf_import(accts, tmp_path):
    r = run(["data/receipts.py", "add", "Power Co", "2026-08-04", "134.56"], accts)
    assert "no charge yet" in r.stdout or "matched" in r.stdout
    assert q(accts, "SELECT match_confidence FROM receipts WHERE merchant='Power Co'") == [("high",)]


# Made-up Chase-style statement: no section headings in the detail, a running balance column, the section total printed
# after a heading in the summary, and a savings account on the same statement.
RUNNING = """JPMorgan Chase Bank, N.A.
August 06, 2026 through September 03, 2026
CHECKING SUMMARY
Beginning Balance                                           $1,000.00
Deposits and Additions                                         653.89
ATM & Debit Card Withdrawals                                  -120.50
Ending Balance                                              $1,533.39
TRANSACTION DETAIL
DATE      DESCRIPTION                                        AMOUNT        BALANCE
          Beginning Balance                                              $1,000.00
08/25     EXAMPLE CORP PAYROLL      PPD ID: 1462800242        653.89     1,653.89
08/28     CARD PURCHASE GROCERY MART 12                       -45.20     1,608.69
09/01     CARD PURCHASE BOOK SHOP                             -75.30     1,533.39
          Ending Balance                                              $1,533.39
SAVINGS SUMMARY
08/31     INTEREST PAYMENT                                      0.12    15,671.39
"""


def test_running_balance_gives_the_sign_and_other_accounts_are_left_out(PS):
    r = PS.parse(RUNNING, card=False)
    got = [(x["date"], x["amount"]) for x in r["rows"]]
    assert got == [("2026-08-25", 653.89), ("2026-08-28", -45.2), ("2026-09-01", -75.3)]
    assert r["begin"] == 1000 and r["end"] == 1533.39 and r["verified"] is True


def test_section_total_after_a_heading_still_sets_the_section(PS):
    t = """July 01, 2026 through July 31, 2026
Beginning Balance $100.00
Ending Balance $150.00
Deposits and Additions 60.00
07/05   EXAMPLE CORP PAYROLL   60.00
Withdrawals 10.00
07/09   POWER CO   10.00
"""
    r = PS.parse(t, card=False)
    assert [(x["amount"]) for x in r["rows"]] == [60.0, -10.0] and r["verified"] is True


# Chase's pdftotext shape: a consolidated summary whose values sit on the wrong line, then one TRANSACTION DETAIL per
# account, a running balance only on some lines, and no section headings. Made-up numbers.
TWO = """JPMorgan Chase Bank, N.A.
August 06, 2026 through September 03, 2026
CONSOLIDATED BALANCE SUMMARY
Chase Total Checking 000000123453192 $7,522.15 $8,176.04
Chase Savings 000000987659273 15,671.27 15,671.39
CHECKING SUMMARY  Account Number: 000000123453192
Beginning Balance                                  $8,176.04
Deposits and Additions
Ending Balance
TRANSACTION DETAIL
DATE      DESCRIPTION                                   AMOUNT       BALANCE
          Beginning Balance                                         $7,522.15
08/25     EXAMPLE CORP PAYROLL      PPD ID: 1462800242        653.89
          Ending Balance                                            $8,176.04
SAVINGS SUMMARY  Account Number: 000000987659273
Beginning Balance                                  $15,671.39
TRANSACTION DETAIL
DATE      DESCRIPTION                                   AMOUNT       BALANCE
          Beginning Balance                                         $15,671.27
09/03     INTEREST PAYMENT                                   0.12    15,671.39
          Ending Balance                                            $15,671.39
"""


def test_two_accounts_one_statement_and_sign_from_the_balances(PS):
    r = PS.parse(TWO, card=False, last4="3192")
    assert [(x["date"], x["amount"]) for x in r["rows"]] == [("2026-08-25", 653.89)]
    assert r["begin"] == 7522.15 and r["end"] == 8176.04 and r["verified"] is True
    s = PS.parse(TWO, card=False, last4="9273")
    assert [(x["date"], x["amount"]) for x in s["rows"]] == [("2026-09-03", 0.12)] and s["verified"] is True


def test_ambiguous_signs_are_not_guessed(PS):
    t = """July 01, 2026 through July 31, 2026
TRANSACTION DETAIL
Beginning Balance $100.00
07/05   FIRST   10.00
07/06   SECOND   10.00
Ending Balance $100.00
"""
    r = PS.parse(t, card=False)
    assert r["rows"] == [] or r["verified"] is not True


def test_long_numbers_in_descriptions_keep_last_four(PS):
    t = """July 01, 2026 through July 31, 2026
Beginning Balance $100.00
Ending Balance $160.00
Deposits and Additions 60.00
07/05   EXAMPLE CORP PAYROLL   PPD ID: 1462800242   60.00
"""
    r = PS.parse(t, card=False)
    assert r["rows"][0]["desc"] == "EXAMPLE CORP PAYROLL PPD ID: x0242" and r["verified"] is True


def test_new_account_command_and_dry_run_creates_nothing(accts, tmp_path):
    r = run(["data/import_statement.py", "account", "--new", "Dash Savings", "--type", "savings", "--last4", "5151"], accts)
    assert r.returncode == 0 and "created account Dash Savings" in r.stdout
    assert run(["data/import_statement.py", "account", "--new", "dash savings", "--type", "savings"], accts).returncode != 0
    csv = tmp_path / "x.csv"
    csv.write_text("Date,Description,Amount\n2026-07-01,Test,5.00\n", encoding="utf-8")
    r = run(["data/import_statement.py", str(csv), "--new", "Ghost Account", "--type", "checking", "--last4", "6161", "--dry-run"], accts)
    assert r.returncode == 0, r.stderr[-300:]
    assert "would create account Ghost Account" in r.stdout
    assert not q(accts, "SELECT 1 FROM accounts WHERE name='Ghost Account'")


def test_intake_without_ai_files_a_statement_that_adds_up(accts):
    """`ai_intake.py local` (No AI): a statement PDF whose lines add up is filed and imported on this PC, also the first
    one of an account the PC does not know (the account is added: name as printed, last four only); one that does not
    add up stays in the inbox and says which account to add."""
    from test_paypal_statement import _pdf
    esc = lambda t: t.replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    inbox = accts / "inbox"
    inbox.mkdir(exist_ok=True)
    broken = BANK.replace("7070", "1113").replace("08/31               INTEREST PAYMENT", "08/31               INTEREST PAYMENT X")
    broken = "\n".join(ln for ln in broken.splitlines() if "INTEREST" not in ln)
    for name, text in (("checking_aug.pdf", BANK), ("other_bank.pdf", BANK.replace("7070", "1112")), ("cut.pdf", broken)):
        _pdf(inbox / name, [(20, 770 - i * 11, esc(line)) for i, line in enumerate(text.splitlines()) if line.strip()])
    r = run(["data/ai_intake.py", "local"], accts)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    assert "new account Everyday Checking x1112" in r.stdout and "Add the account ending 1113" in r.stdout, r.stdout[-800:]
    assert not (inbox / "checking_aug.pdf").exists() and not (inbox / "other_bank.pdf").exists() and (inbox / "cut.pdf").exists()
    assert q(accts, "SELECT name, type FROM accounts WHERE last4='1112'") == [("Everyday Checking", "checking")]
    assert not q(accts, "SELECT 1 FROM accounts WHERE last4='1113'"), "no account is left behind when the lines do not add up"
    doc = q(accts, "SELECT id, notes FROM documents WHERE doc_type='statement' ORDER BY id DESC LIMIT 1")[0]
    assert "pdf_statement (no AI)" in doc[1]


def test_missing_statements_sees_statements_this_app_filed(modules):
    """Statements filed by the Inbox are named <date>_<account name>_x<last4>_statement; the watch reads both forms."""
    import sqlite3
    sw = modules("statement_watch")
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE documents(doc_type TEXT, filed_path TEXT)")
    con.executemany("INSERT INTO documents VALUES ('statement', ?)", [
        ("archive/2026/statements/2026-10-31_everyday_checking_x7070_statement.pdf",),
        ("archive/2026/statements/2026-09-30_chase_1234_statement.pdf",), ("archive/2026/statements/2026-09-30_paypal_statement.pdf",)])
    got = sw.statement_dates(con)
    assert {k[1] for k in got} == {"7070", "1234"}, got
