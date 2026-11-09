"""The Add page says why and starts from what the AI read (audit 2026-10-18, slice S2): review cards fold out the steps
that were tried, the File it form is filled in from the AI's guess, a file left in the inbox keeps its reason after
the run's panel is gone, an AI-read statement must also match its own printed totals, and lines dated outside the
statement period are pointed out. Made-up data."""
import datetime as dt
import sqlite3

import pytest

from test_webapp import _login, web  # noqa: F401  (the web fixture)

REASON = ("statement not imported automatically: no account with the last four digits 2424. Add the account first "
          "(Money > Accounts > Add an account), then file the statement again; AI reader: the AI was not sure (confidence 0.30)")


def test_review_card_says_why_and_fills_in_the_guess(web, modules):  # noqa: F811
    c, _, _ = web
    _login(c)
    paths, pr = modules("paths"), modules("proposals")
    con = sqlite3.connect(paths.DB)
    with con:
        con.execute("DELETE FROM proposals")
        con.execute("INSERT INTO review_queue(path, reason, detail) VALUES (?,?,?)",
                    ("inbox/needs_review/aug_statement.pdf", REASON,
                     "guess type=statement vendor=Sample Bank date=2026-08-31 amount=25.0"))
    con.close()
    pr.sync()
    html = c.get("/inbox/body?view=files").text
    assert "<summary>Why?</summary>" in html and "<li>AI reader: the AI was not sure (confidence 0.30)</li>" in html
    assert "ending 2424 that is not set up yet" in html, "the plain sentence stays on top"
    assert '<option value="statement" selected>' in html and 'value="Sample Bank"' in html
    assert 'value="2026-08-31"' in html and 'value="25.0"' in html and "Filled in from what the AI read" in html


def test_guess_of_reads_every_note_shape(modules):
    pr = modules("proposals")
    assert pr.guess_of("guess type=bill vendor=City Water Co date=2026-09-01 amount=41.2 due=2026-09-20") == {
        "type": "bill", "vendor": "City Water Co", "date": "2026-09-01", "amount": 41.2, "due": "2026-09-20"}
    assert pr.guess_of("guess store=Corner Cafe date=2026-10-01 total=12.5 confidence 0.40") == {
        "vendor": "Corner Cafe", "date": "2026-10-01", "amount": 12.5}
    assert pr.guess_of("guess type=other vendor=None date=soon amount=-3") == {}
    assert pr.guess_of("AI answer failed validation") == {}
    assert pr._plain_guess("guess type=bill vendor=City Water") == "It looked like a bill from City Water."


def test_a_file_left_in_the_inbox_keeps_its_reason(root, modules):
    paths, prog, inbox_data = modules("paths"), modules("intake_progress"), modules("inbox_data")
    paths.INBOX.mkdir(parents=True, exist_ok=True)
    for f in paths.INBOX.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()
    (paths.INBOX / "left.pdf").write_bytes(b"%PDF-1.4 x")
    run = prog.Run(["left.pdf"])
    run.done("left.pdf", "skipped", "AI unavailable: network error: URLError")
    run.finish()
    later = prog.time.time() + prog.RECENT_S + 60
    p = inbox_data.progress(now=later)
    assert p["state"] == "waiting" and p["rows"][0]["label"] == "Try again later"
    assert "could not be reached" in p["rows"][0]["line"], p["rows"]
    run = prog.Run(["left.pdf"])
    run.done("left.pdf", "filed", "statement: 3 transactions added, 0 already loaded")
    assert "left.pdf" not in prog.outcomes(), "a filed file is forgotten"
    assert inbox_data._plain_info("filed", "statement: 3 transactions added, 0 already loaded") == \
        "Statement: 3 transactions added, 0 already loaded."
    (paths.INBOX / "left.pdf").unlink()


def test_an_ai_statement_must_match_its_printed_totals(modules):
    de = modules("doc_extract")
    rows = [{"amount": 1500.0}, {"amount": -250.0}]
    de._check_printed_totals({"total_in": 1500, "total_out": 250}, rows, 100.0, 1350.0, False)  # matches: fine
    de._check_printed_totals({"total_in": 1500, "total_out": 999}, rows, 100.0, 1350.0, False)  # totals misread: ignored
    de._check_printed_totals({}, rows, 100.0, 1350.0, False)  # not printed: nothing to check
    with pytest.raises(de.Unusable, match="printed totals"):  # two lines misread the same amount the other way
        de._check_printed_totals({"total_in": 1600, "total_out": 350}, rows, 100.0, 1350.0, False)
    card = [{"amount": 500.0}, {"amount": -212.34}]
    de._check_printed_totals({"total_in": 500, "total_out": 212.34}, card, 500.0, 212.34, True)


def test_lines_outside_the_period_are_pointed_out(modules):
    ai = modules("ai_intake")
    per = (dt.date(2026, 10, 10), dt.date(2026, 11, 9))
    rows = [{"date": "2026-10-02"}, {"date": "2026-10-08"}, {"date": "2026-11-09"}]
    assert ai._outside_period({"period": per, "rows": rows}) == ["2026-10-02"], "a few days' slack, then pointed out"
    assert ai._outside_period({"period": None, "rows": rows}) == []
