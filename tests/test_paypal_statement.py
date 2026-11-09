"""PayPal account statements without AI (data/paypal_statement.py): the activity table is read from the layout text, a wrapped
year and a wrapped merchant name are put back together, the Balance view is not read twice, payments become receipts that
the matcher links to the card charge (never new spending), and intake files the paper before any AI is asked.
Text and a hand-made PDF with made-up data stand in for a real statement."""
import pytest

from conftest import db, q, run

HEAD = """                  ACCOUNT STATEMENTS
                  Example, Pat
  Statement Period          PayPal Account ID
  Jul 1, 2026 - Jul 31,     pat@example.com
  2026
  This document contains two statements
  PayPal account statement  - A view of all PayPal account activity
  PayPal Balance account statement - A separate view of your PayPal Balance account activity
  PAYPAL ACCOUNT
  ACCOUNT ACTIVITY
   DATE        DESCRIPTION                                   CURRENCY        AMOUNT         FEES          TOTAL*
"""
ROWS = """
   07/03/202   Express Checkout Payment: ZED GADGET                USD           -4.99          0.00          -4.99
   6           Shop
                 GOLD Card                                      4.99
               USD
               ID: 0AA00000AA0000000

   07/16/2026  PreApproved Payment Bill User Payment:            USD           -191.81         0.00          -191.81
               Quill Hosting INC.
               ID: 9B000000BB0000000

   07/16/2026  General Credit Card Deposit                       USD            191.81         0.00           191.81
               ID: 9C000000CC0000000

   07/20/2026  Payment Refund: ZED GADGET Shop                   USD              4.99         0.00             4.99
"""
BALANCE = """                  ACCOUNT STATEMENTS
  PayPal account statement
  PAYPAL BALANCE ACCOUNT
  ACCOUNT ACTIVITY
   07/16/2026  PreApproved Payment Bill User Payment:            USD           -191.81         0.00          -191.81
"""


@pytest.fixture(scope="module")
def pp(modules):
    return modules("paypal_statement")


def test_payments_are_read_and_the_rest_is_counted(pp):
    r = pp.parse([HEAD + ROWS, BALANCE])
    assert r["period"][0].isoformat() == "2026-07-01" and r["period"][1].isoformat() == "2026-07-31", "the end year wrapped"
    got = [(p["date"].isoformat(), p["merchant"], p["total"]) for p in r["payments"]]
    assert got == [("2026-07-03", "ZED GADGET Shop", 4.99), ("2026-07-16", "Quill Hosting INC", 191.81)]
    assert r["lines"] == 4 and r["other"] == 2, "the card deposit and the refund are not payments; the Balance view is not read"


def test_an_empty_statement_is_fine_and_odd_ones_are_refused(pp):
    assert pp.parse([HEAD, BALANCE])["payments"] == []
    with pytest.raises(pp.StatementError, match="US dollar"):
        pp.parse([HEAD + ROWS.replace("USD  ", "EUR  ", 1)])
    with pytest.raises(pp.StatementError, match="layout"):
        pp.parse([HEAD + "\n   07/21/2026  Something odd happened here\n"])
    with pytest.raises(pp.StatementError, match="not a PayPal"):
        pp.parse(["Everyday Checking\nAccount number ending: 7070"])
    assert pp.looks_like(HEAD) and not pp.looks_like("Everyday Checking statement")


def test_payments_become_receipts_matched_to_the_card_charge_and_are_not_filed_twice(root, pp):
    with db(root) as con:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('PP Card', 'credit', '8181')").lastrowid
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                    (acc, "2026-07-17", "PAYPAL *QUILLHOSTING 402-935-7733", -191.81))
        res = pp.parse([HEAD + ROWS, BALANCE])
        con.row_factory = None
        rep = pp.store(con, res)
        again = pp.store(con, res)
    assert rep["filed"] == 2 and rep["skipped"] == 0 and again == {"filed": 0, "skipped": 2, "matched": 0}
    got = q(root, "SELECT merchant, total, status FROM receipts WHERE merchant IN ('ZED GADGET Shop', 'Quill Hosting INC') ORDER BY total")
    assert got[0][:2] == ("ZED GADGET Shop", 4.99) and got[1][:2] == ("Quill Hosting INC", 191.81)
    # "Quill" is not a word of the card text ("QUILLHOSTING"): the same amount in the window still links it
    assert got[1][2] == "matched"
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE description LIKE '%ZED GADGET%'") == [(0,)], "no new spending"


def test_the_paypal_part_lists_every_payment_matched_or_waiting(root, pp, modules):
    import datetime as dt
    fd = modules("finance_data")
    with db(root) as con:
        acc = con.execute("SELECT id FROM accounts WHERE name='PP Card'").fetchone()[0]
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                    (acc, "2026-08-02", "PAYPAL *SOMESTORE 4029357733", -12.5))
        v = fd.paypal(con, dt.date(2026, 10, 17), {"months": "6"})
    assert "paypal" in dict(fd.parts()) and fd.part_of("paypal") == "paypal"
    pay = {b["heading"]: b for b in v["blocks"]}
    rows = [dict(zip(pay["Payments"]["cols"], r["cells"])) for r in pay["Payments"]["rows"]]
    by = {r["Merchant"]: r for r in rows}
    assert by["Quill Hosting INC"]["Status"] == "matched" and "PP Card" in by["Quill Hosting INC"]["Paid with"]
    assert by["ZED GADGET Shop"]["Status"] == "waiting", "an unmatched payment is listed too"
    month = [dict(zip(pay["Month by month"]["cols"], r["cells"])) for r in pay["Month by month"]["rows"]]
    assert month[-1]["Month"] == "2026-07" and str(month[-1]["Payments"]) == "2" and str(month[-1]["Waiting"]) == "1"
    loose = pay["PayPal charges with no statement line"]
    assert len(loose["rows"]) == 1 and "SOMESTORE" in str(loose["rows"][0]["cells"]), "the matched charge is not listed again"
    assert dict((t[0], t[1]) for t in v["tiles"])["Payments"] == 2


def _pdf(path, lines):
    """A one-page PDF with each (x, y, text) placed as given (Helvetica 9)."""
    stream = "BT /F1 9 Tf\n" + "\n".join(f"1 0 0 1 {x} {y} Tm ({t}) Tj" for x, y, t in lines) + "\nET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream", "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offs = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode() + "".join(f"{o:010d} 00000 n \n" for o in offs).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    path.write_bytes(out)


def test_intake_files_a_paypal_pdf_without_any_ai(root, pp):
    f = root / "inbox" / "paypal_jul.pdf"
    _pdf(f, [(30, 760, "PayPal account statement - A view of all PayPal account activity"),
             (30, 745, "Statement Period"), (30, 733, "Jul 1, 2026 - Jul 31, 2026"),
             (30, 700, "ACCOUNT ACTIVITY"), (30, 680, "DATE"), (110, 680, "DESCRIPTION"), (330, 680, "CURRENCY"),
             (30, 660, "07/03/2026"), (110, 660, "Express Checkout Payment: TEST WIDGET CO"), (330, 660, "USD"),
             (390, 660, "-12.34"), (450, 660, "0.00"), (510, 660, "-12.34"),
             (30, 640, "07/03/2026"), (110, 640, "General Credit Card Deposit"), (330, 640, "USD"),
             (390, 640, "12.34"), (450, 640, "0.00"), (510, 640, "12.34")])
    r = run(["data/ai_intake.py", "local"], root)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    assert "PayPal statement: 1 payment filed as receipts" in r.stdout, r.stdout[-600:]
    assert q(root, "SELECT doc_type, vendor FROM documents WHERE vendor='PayPal' ORDER BY id DESC LIMIT 1") == [("statement", "PayPal")]
    assert q(root, "SELECT merchant, total FROM receipts WHERE merchant='TEST WIDGET CO'") == [("TEST WIDGET CO", 12.34)]
    assert not f.exists(), "the paper moved to the archive"
