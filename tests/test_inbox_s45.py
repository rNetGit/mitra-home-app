"""Statements a person helps with, and the bank downloads read without AI (audit 2026-10-18, slices S4 and S5):
OFX / QFX downloads and activity CSV exports are imported on this PC into the account they name (never a guessed
one); "Import as statement" reads a waiting PDF, CSV or OFX into the account a person picks, refuses a PDF whose lines
do not add up unless they tick Import anyway, and can read it as a card or a bank statement. Made-up data."""
import sqlite3

from conftest import q, run, set_ai
from test_pdf_statement import BANK, CARD

ADULT = {"name": "Ann", "role": "adult"}

OFX_SGML = """OFXHEADER:100
DATA:OFXSGML
VERSION:102

<OFX><SIGNONMSGSRSV1><SONRS><FI><ORG>Sample Federal<FID>1</FI></SONRS></SIGNONMSGSRSV1>
<BANKMSGSRSV1><STMTTRNRS><STMTRS><CURDEF>USD
<BANKACCTFROM><BANKID>011000015<ACCTID>000123458181<ACCTTYPE>CHECKING</BANKACCTFROM>
<BANKTRANLIST><DTSTART>20261001<DTEND>20261031
<STMTTRN><TRNTYPE>CREDIT<DTPOSTED>20261003120000<TRNAMT>2500.00<FITID>A1<NAME>EXAMPLE CORP PAYROLL</STMTTRN>
<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20261005<TRNAMT>-100.25<FITID>A2<NAME>GROCERY MART<MEMO>POS 123456789012</STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>3399.75<DTASOF>20261031</LEDGERBAL></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>
"""
QFX_XML = """<?xml version="1.0" encoding="UTF-8"?>
<?OFX OFXHEADER="200" VERSION="220"?>
<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><CURDEF>USD</CURDEF>
<CCACCTFROM><ACCTID>4111XXXXXXXX9292</ACCTID></CCACCTFROM>
<BANKTRANLIST><DTSTART>20261001</DTSTART><DTEND>20261031</DTEND>
<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20261004</DTPOSTED><TRNAMT>-45.10</TRNAMT><FITID>C1</FITID><NAME>BOOK SHOP</NAME></STMTTRN>
<STMTTRN><TRNTYPE>CREDIT</TRNTYPE><DTPOSTED>20261020</DTPOSTED><TRNAMT>300.00</TRNAMT><FITID>C2</FITID><NAME>PAYMENT THANK YOU</NAME></STMTTRN>
</BANKTRANLIST><LEDGERBAL><BALAMT>-512.40</BALAMT><DTASOF>20261031</DTASOF></LEDGERBAL></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>
"""
CARD_CSV = "Date,Description,Amount\n10/02/2026,CORNER CAFE,12.50\n10/09/2026,BOOK SHOP,30.00\n10/15/2026,PAYMENT THANK YOU,-42.50\n"
BANK_CSV = ("Account #,Posting Date,Description,Amount\n-03131,10/03/2026,EXAMPLE CORP PAYROLL,2500.00\n"
            "-03131,10/05/2026,GROCERY MART,-80.00\n")


def _inbox(root, files):
    box = root / "inbox"
    box.mkdir(exist_ok=True)
    for name, body in files.items():
        (box / name).write_text(body, encoding="utf-8")
    return box


def _lines(root, last4):
    return q(root, "SELECT txn_date, amount, ref FROM transactions t JOIN accounts a ON a.id=t.account_id "
                   "WHERE a.last4=? ORDER BY txn_date, amount", last4)


def test_ofx_and_qfx_downloads_are_read_without_ai(root):
    set_ai(root, "none")
    box = _inbox(root, {"october.ofx": OFX_SGML, "card_oct.qfx": QFX_XML})
    r = run(["data/ai_intake.py", "local"], root)
    assert r.returncode == 0 and not (box / "october.ofx").exists() and not (box / "card_oct.qfx").exists(), r.stdout
    assert q(root, "SELECT name, type FROM accounts WHERE last4='8181'") == [("Sample Federal checking", "checking")]
    assert _lines(root, "8181") == [("2026-10-03", 2500.0, "ofx:A1"), ("2026-10-05", -100.25, "ofx:A2")]
    assert "x9012" in q(root, "SELECT description FROM transactions WHERE ref='ofx:A2'")[0][0], "long numbers: last four"
    assert q(root, "SELECT type FROM accounts WHERE last4='9292'") == [("credit",)]
    assert _lines(root, "9292") == [("2026-10-04", -45.1, "ofx:C1"), ("2026-10-20", 300.0, "ofx:C2")]
    _inbox(root, {"october_again.ofx": OFX_SGML.replace("VERSION:102", "VERSION:102\n")})  # a new download, same days
    r = run(["data/ai_intake.py", "local"], root)
    assert "0 transactions added, 2 already loaded" in r.stdout, r.stdout
    assert len(_lines(root, "8181")) == 2


def test_csv_exports_go_only_to_the_account_they_name(root):
    set_ai(root, "none")
    con = sqlite3.connect(root / "data" / "family.db")
    with con:
        con.execute("INSERT INTO accounts(name, type, last4) VALUES ('CSV Card', 'credit', '4747')")
        con.execute("INSERT INTO accounts(name, type, last4) VALUES ('CSV Checking', 'checking', '3131')")
        con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Year Lookalike', 'checking', '2026')")
    con.close()
    box = _inbox(root, {"Card4747_Activity.csv": CARD_CSV, "export.csv": BANK_CSV, "activity_2026.csv": CARD_CSV.replace("CAFE", "CAFE 2")})
    r = run(["data/ai_intake.py", "local"], root)
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    assert sorted(a for _, a, _ in _lines(root, "4747")) == [-30.0, -12.5, 42.5], "card export: charges become spending"
    assert sorted(a for _, a, _ in _lines(root, "3131")) == [-80.0, 2500.0], "account column"
    assert not _lines(root, "2026"), "a year in the file name is not an account"
    assert (box / "needs_review" / "activity_2026.csv").exists()
    reason = q(root, "SELECT reason FROM review_queue WHERE path LIKE '%activity_2026.csv'")[0][0]
    assert "which account" in reason


def _review(root, modules, name, body, reason):
    paths, pr = modules("paths"), modules("proposals")
    (paths.INBOX / "needs_review").mkdir(parents=True, exist_ok=True)
    (paths.INBOX / "needs_review" / name).write_text(body, encoding="utf-8")
    con = sqlite3.connect(paths.DB)
    with con:
        con.execute("DELETE FROM proposals")
        rid = con.execute("INSERT INTO review_queue(path, reason, detail) VALUES (?,?,?)",
                          (f"inbox/needs_review/{name}", reason, "guess type=statement")).lastrowid
    con.close()
    pr.sync()
    con = sqlite3.connect(paths.DB)
    con.row_factory = sqlite3.Row
    item = pr.get(con, con.execute("SELECT id FROM proposals WHERE dedupe_key=?", (f"review:{rid}",)).fetchone()[0])
    con.close()
    return item


def _account_id(root, last4):
    return q(root, "SELECT id FROM accounts WHERE last4=?", last4)[0][0]


def test_import_as_statement_checks_first_and_can_import_anyway(root, modules):
    inbox_data = modules("inbox_data")
    con = sqlite3.connect(root / "data" / "family.db")
    with con:
        con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Picked Checking', 'checking', '6262')")
    con.close()
    cut = "\n".join(ln for ln in BANK.replace("7070", "6262").splitlines() if "INTEREST" not in ln)
    item = _review(root, modules, "cut.txt", cut, "statement not imported automatically: balances do not add up")
    assert item["options"]["statement"] == "Import as statement"
    aid = _account_id(root, "6262")
    ok, msg = inbox_data.decide(ADULT, item["id"], "statement", {"account": str(aid)})
    assert not ok and "do not add up" in msg and "begin 1000.0" in msg, msg
    assert not _lines(root, "6262"), "nothing imported when the check fails"
    ok, msg = inbox_data.decide(ADULT, item["id"], "statement", {"account": str(aid), "force": "1"})
    assert ok and "transactions added" in msg, msg
    assert len(_lines(root, "6262")) == 4
    assert "imported anyway" in q(root, "SELECT notes FROM documents ORDER BY id DESC LIMIT 1")[0][0]


def test_import_as_statement_reads_it_as_a_card_and_takes_a_csv(root, modules):
    inbox_data = modules("inbox_data")
    con = sqlite3.connect(root / "data" / "family.db")
    with con:
        con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Typed Wrong', 'checking', '9191')")
        con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Picked Savings', 'savings', '5353')")
    con.close()
    item = _review(root, modules, "card.txt", CARD, "statement not imported automatically: balances do not add up")
    ok, msg = inbox_data.decide(ADULT, item["id"], "statement", {"account": str(_account_id(root, "9191")), "read_as": "card"})
    assert ok and len(_lines(root, "9191")) == 4, msg
    item = _review(root, modules, "savings.csv", "Date,Description,Amount\n10/01/2026,INTEREST,0.42\n",
                   "transactions export: it does not say which account it is from; choose the account to import it into")
    assert "Choose Import as statement" in item["detail"]
    ok, msg = inbox_data.decide(ADULT, item["id"], "statement", {"account": str(_account_id(root, "5353"))})
    assert ok and "1 transactions added to Picked Savings" in msg, msg
    item = _review(root, modules, "photo_scan.pdf", "x", "scanned PDF (no text layer): the pages are pictures")
    assert "statement" not in item["options"], "a scan cannot be read this way"
