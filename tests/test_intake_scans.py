"""Scanned PDFs (pictures of the pages, no text layer): with photo reading on, the family's AI reads the file itself
(sent as each API's PDF part); a statement is imported only when its lines add up to the printed balances, long
numbers in its lines keep only their last four digits, a scanned bill is filed like a text one; with photo reading off
nothing is sent and the card says how to turn it on. Made-up data; the AI is the test suite's mock provider."""
import json

from conftest import KEYS, q, run
from test_paypal_statement import _pdf

CLASSIFY = {"doc_type": "statement", "vendor": "Sample Community Bank", "doc_date": "2026-10-31", "amount": None,
            "due_date": None, "account_last4": "5858", "period": "Oct 2026", "confidence": 0.9}
STATEMENT = {"institution": "Sample Community Bank", "account_type": "checking", "account_last4": "5858",
             "period_start": "2026-10-01", "period_end": "2026-10-31", "opening_balance": 100.0, "closing_balance": 1350.0,
             "transactions": [{"date": "2026-10-03", "description": "PREAUTHORIZED CREDIT PAYROLL 123456789012", "amount": 1500.0},
                              {"date": "2026-10-10", "description": "ATM WITHDRAWAL", "amount": -250.0}],
             "confidence": 0.9}


def _scan(root, name):
    box = root / "inbox"
    box.mkdir(exist_ok=True)
    _pdf(box / name, [])  # a page with no text at all: what a scanner makes
    with open(box / name, "ab") as fh:  # each scan its own bytes, or the exact-copy check files it as a duplicate
        fh.write(f"\n% {name}\n".encode())
    return box / name


def _ai(mock_llm, provider="anthropic", photos=True, replies=()):
    mock_llm.use(provider, read_receipt_photos=photos)
    mock_llm.set(replies[-1] if replies else "{}")
    mock_llm.queue[:] = [json.dumps(r) for r in replies]


def test_a_scanned_statement_that_adds_up_is_imported(root, mock_llm):
    _scan(root, "scan_oct.pdf")
    _ai(mock_llm, replies=(CLASSIFY, STATEMENT))
    r = run(["data/ai_intake.py"], root, env=KEYS)
    assert r.returncode == 0 and "filed" in r.stdout, r.stdout[-600:] + r.stderr[-600:]
    parts = [p for s in mock_llm.seen for m in s["body"]["messages"] for p in m["content"] if isinstance(p, dict)]
    assert [p["source"]["media_type"] for p in parts if p["type"] == "document"] == ["application/pdf"] * 2
    assert q(root, "SELECT type FROM accounts WHERE last4='5858'") == [("checking",)]
    rows = q(root, "SELECT description, amount FROM transactions t JOIN accounts a ON a.id=t.account_id "
                   "WHERE a.last4='5858' ORDER BY t.txn_date")
    assert [a for _, a in rows] == [1500.0, -250.0]
    assert "123456789012" not in rows[0][0] and "x9012" in rows[0][0], rows[0][0]
    assert "scanned PDF read by AI" in q(root, "SELECT notes FROM documents WHERE doc_type='statement' ORDER BY id DESC LIMIT 1")[0][0]


def test_a_scanned_statement_that_does_not_add_up_waits_with_the_reason(root, mock_llm, modules):
    _scan(root, "scan_bad.pdf")
    off = {**STATEMENT, "account_last4": "6969", "closing_balance": 1349.0}
    _ai(mock_llm, replies=({**CLASSIFY, "account_last4": "6969"}, off))
    run(["data/ai_intake.py"], root, env=KEYS)
    assert (root / "inbox" / "needs_review" / "scan_bad.pdf").exists()
    assert not q(root, "SELECT 1 FROM accounts WHERE last4='6969'"), "no account left behind"
    reason = q(root, "SELECT reason FROM review_queue WHERE path LIKE '%scan_bad.pdf'")[0][0]
    assert "not imported" in reason and "add up" in reason, reason
    assert "did not add up" in modules("proposals")._plain_reason(reason)


def test_a_scanned_bill_is_filed_and_openrouter_gets_a_file_part(root, mock_llm):
    _scan(root, "scan_bill.pdf")
    bill = {**CLASSIFY, "doc_type": "bill", "vendor": "Sample Water", "amount": 41.2, "due_date": "2026-11-20"}
    _ai(mock_llm, provider="openrouter", replies=(bill,))
    r = run(["data/ai_intake.py"], root, env=KEYS)
    assert r.returncode == 0 and (root / "archive" / "2026" / "bills" / "2026-10-31_sample_water_bill.pdf").exists(), r.stdout
    part = mock_llm.seen[0]["body"]["messages"][1]["content"][1]
    assert part["type"] == "file" and part["file"]["file_data"].startswith("data:application/pdf;base64,")
    assert q(root, "SELECT amount, due_date FROM bills WHERE vendor='Sample Water'") == [(41.2, "2026-11-20")]


def test_with_photo_reading_off_nothing_is_sent(root, mock_llm, modules):
    _scan(root, "scan_private.pdf")
    _ai(mock_llm, photos=False, replies=(CLASSIFY,))
    run(["data/ai_intake.py"], root, env=KEYS)
    assert mock_llm.seen == [], "a scan cannot be masked: it leaves the PC only with photo reading on"
    reason = q(root, "SELECT reason FROM review_queue WHERE path LIKE '%scan_private.pdf'")[0][0]
    assert "photo reading" in reason
    assert "Settings > Connections" in modules("proposals")._plain_reason(reason)


def test_an_ai_account_out_of_credit_keeps_the_scan_in_the_inbox(root, mock_llm, modules):
    """HTTP 402 (no credit left): the provider's own words are kept (keys hidden), the file waits in the inbox and the
    line says to add credit, instead of sending it to a person as unreadable."""
    import http.server
    import threading

    class Broke(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            body = json.dumps({"error": {"code": 402, "message": "Insufficient credits for sk-or-v1-abcdefabcdefabcdef1234"}}).encode()
            self.send_response(402)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Broke)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        _scan(root, "scan_broke.pdf")
        mock_llm.use("openrouter", read_receipt_photos=True, base_url=f"http://127.0.0.1:{srv.server_port}")
        r = run(["data/ai_intake.py"], root, env=KEYS)
    finally:
        srv.shutdown()
    assert (root / "inbox" / "scan_broke.pdf").exists(), r.stdout
    assert "HTTP 402 from provider: Insufficient credits" in r.stdout and "abcdef" not in r.stdout, r.stdout
    line = modules("inbox_data")._plain_info("skipped", r.stdout.split("-> ", 1)[1])
    assert "out of credit" in line and "File them now" in line
    (root / "inbox" / "scan_broke.pdf").unlink()
