"""Inbox filing that does not leave a person guessing (audit 2026-10-18, slice S1): a statement this PC can read is
filed before any AI call, also when an AI is set and also for a card with "Statement Balance" wording; a statement the
PC cannot read still goes to the AI; a run that ends early closes the progress panel with the reason instead of
spinning; outcome lines and review cards say what to do next. Statement texts are made-up data."""
import subprocess

from conftest import KEYS, q, run, set_ai
from test_paypal_statement import _pdf
from test_pdf_statement import BANK, CARD

BILL = {"doc_type": "bill", "vendor": "Sample Bank", "doc_date": "2026-08-31", "amount": 25.0, "due_date": "2026-09-20",
        "account_last4": "2424", "period": "Aug 2026", "confidence": 0.95}
CARD_WORDS = (CARD.replace("9191", "3535").replace("Dec 26, 2026 to Jan 25, 2027", "Dec 26, 2025 to Jan 25, 2026")
              .replace("*Previous Balance   $100.00   *New Balance   $160.25",
                       "Previous Statement Balance   $100.00   Statement Balance   $160.25"))


def _statement_pdf(path, text):
    esc = lambda t: t.replace("(", "\\(").replace(")", "\\)")  # noqa: E731
    _pdf(path, [(20, 770 - i * 11, esc(line)) for i, line in enumerate(text.splitlines()) if line.strip()])


def _inbox(root):
    box = root / "inbox"
    box.mkdir(exist_ok=True)
    for f in box.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()
    return box


def test_statements_are_read_here_before_any_ai_call(root, mock_llm):
    """With an AI set (which would call these a bill), a bank and a card statement of accounts this PC does not know
    are read on this PC, the accounts added by last four, the lines imported; the AI is never asked."""
    box = _inbox(root)
    _statement_pdf(box / "bank_aug.pdf", BANK.replace("7070", "2424"))
    _statement_pdf(box / "card_jan.pdf", CARD_WORDS)
    mock_llm.use("anthropic")
    mock_llm.set(BILL)
    r = run(["data/ai_intake.py"], root, env=KEYS)
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-600:]
    assert mock_llm.seen == [], "a statement read on this PC is never sent to the AI"
    assert not (box / "bank_aug.pdf").exists() and not (box / "card_jan.pdf").exists(), r.stdout
    assert q(root, "SELECT type FROM accounts WHERE last4='2424'") == [("checking",)]
    assert q(root, "SELECT type FROM accounts WHERE last4='3535'") == [("credit",)], "Statement Balance wording = a card"
    assert q(root, "SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE a.last4='3535'")[0][0] == 4
    assert not q(root, "SELECT 1 FROM bills WHERE vendor='Sample Bank'"), "not filed as a bill"
    notes = [n for (n,) in q(root, "SELECT notes FROM documents WHERE doc_type='statement' ORDER BY id DESC LIMIT 2")]
    assert all("pdf_statement (no AI)" in n for n in notes), notes


def test_a_statement_not_read_here_still_goes_to_the_ai(root, mock_llm):
    """Lines that do not add up: with an AI set the file is not parked as "waiting" but handed to the AI."""
    box = _inbox(root)
    broken = "\n".join(ln for ln in BANK.replace("7070", "4646").splitlines() if "INTEREST" not in ln)
    _statement_pdf(box / "cut.pdf", broken)
    mock_llm.use("anthropic")
    mock_llm.set({**BILL, "confidence": 0.3})
    r = run(["data/ai_intake.py"], root, env=KEYS)
    assert mock_llm.seen, r.stdout
    assert (root / "inbox" / "needs_review" / "cut.pdf").exists(), r.stdout
    assert not q(root, "SELECT 1 FROM accounts WHERE last4='4646'"), "no account left behind"


def test_a_run_that_ends_early_closes_the_progress_panel(root, modules):
    prog, inbox_data = modules("intake_progress"), modules("inbox_data")
    _inbox(root)
    prog.starting(["a.pdf", "b.pdf"])
    assert inbox_data.progress()["state"] == "running"
    assert prog.close_open("Stopped for a test.") == 2
    p = inbox_data.progress()
    assert p["state"] == "done" and not p["poll"] and p["title"] == "Done: 2 not read yet", p["title"]
    assert {r["line"] for r in p["rows"]} == {"Stopped for a test."} and {r["label"] for r in p["rows"]} == {"Not read yet"}
    assert prog.close_open("again") == 0, "a finished run is left alone"


def test_file_now_closes_the_panel_with_the_reason(root, modules, monkeypatch):
    prog, inbox_data, joblock = modules("intake_progress"), modules("inbox_data"), modules("joblock")
    set_ai(root, "anthropic")
    said = {"out": ""}
    monkeypatch.setattr(inbox_data.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, said["out"], ""))
    said["out"] = "an update or restore is running; the files wait for the next run\n"
    prog.starting(["c.pdf"])
    ok, msg = inbox_data.file_now(wait=True)
    assert not ok and msg == inbox_data.STOPPED_UPDATE
    assert inbox_data.progress()["rows"][0]["line"] == inbox_data.STOPPED_UPDATE
    said["out"] = "another filing run is reading the inbox; the files wait for the next one\n"
    prog.starting(["d.pdf"])
    ok, msg = inbox_data.file_now(wait=True)
    assert ok and "Another filing run" in msg
    assert inbox_data.progress()["state"] == "running", "the other run owns the panel"

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(a, 1)
    monkeypatch.setattr(inbox_data.subprocess, "run", slow)
    ok, msg = inbox_data.file_now(wait=True)
    assert not ok and inbox_data.progress()["rows"][0]["line"] == inbox_data.STOPPED_SLOW
    box = _inbox(root)
    (box / "e.pdf").write_bytes(b"%PDF-1.4 x")
    before = prog.path().read_bytes()
    with joblock.held("intake"):  # a scheduled run is reading: no second run, the panel is not overwritten
        ok, msg = inbox_data.file_now(wait=False)
    assert ok and msg.startswith("Already reading") and prog.path().read_bytes() == before
    (box / "e.pdf").unlink()
    set_ai(root, "none")


def test_outcome_lines_and_cards_say_what_to_do(modules):
    inbox_data, pr = modules("inbox_data"), modules("proposals")
    line = inbox_data._plain_info("skipped", "AI unavailable: Daily AI call cap reached (200/200). Raise ai.max_calls")
    assert "limit is used up" in line and "tomorrow" in line
    assert "could not be reached" in inbox_data._plain_info("skipped", "AI unavailable: network error")
    r = pr._plain_reason("statement not imported automatically: no account with the last four digits 2424, 5151. Add "
                         "the account first (Money > Accounts > Add an account), then file the statement again; AI reader: x")
    assert "ending 2424 or 5151" in r and "Add the account" in r
    assert "did not add up" in pr._plain_reason("statement not imported automatically: balances do not add up")
    assert "HEIC" in pr._plain_reason("file type not read by the Python pipeline", "IMG_1.HEIC"), "older rows too"
    assert "Settings > Connections" in pr._plain_reason("photo not read: reading photos with AI is off (ai.x)")
    assert "Python" not in pr._plain_reason("file type not read by the Python pipeline", "a.ofx")


def test_a_full_account_number_printed_as_is_gives_its_last_four(modules):
    ps = modules("pdf_statement")
    assert ps.last4s("Relationship Checking - Account 123456789 continued") == ["6789"]
    assert ps.last4s("Account Number: 0012345678") == ["5678"] and ps.last4s("Account # 1234") == ["1234"]
    assert ps.last4s("Account 2026 summary") == [] and ps.last4s("account 500000.00") == [], "years and amounts are not numbers"


def test_photo_cards_say_what_happened(modules):
    """A photo the AI read is never called unreadable: each photo outcome says what happened and what to do."""
    pr = modules("proposals")
    assert pr._plain_reason("photo is not a receipt (AI)").startswith("The AI read the photo, but it does not look like a receipt")
    assert "store, date or total" in pr._plain_reason("receipt photo: low confidence or missing store/date/total")
    assert "could not be used" in pr._plain_reason("AI answer for the photo failed validation")
    assert pr._plain_reason("photo not read by AI").startswith("The AI could not read the photo")
    assert "Settings > Connections" in pr._plain_reason("photo not read: reading photos with AI is off (ai.x)")
