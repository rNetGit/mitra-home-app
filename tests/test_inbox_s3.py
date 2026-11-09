"""Reading a waiting file again from the Add page (audit 2026-10-18, slice S3): "Try again" puts it back in the inbox,
"Add the account ending NNNN" adds the missing account (last four only) and reads the statement again, "Try all
again" does it for every waiting file, and a setting that would help is one click away. Made-up data."""
import sqlite3

import pytest

from conftest import q, set_ai
from test_webapp import _login, web  # noqa: F401  (the web fixture)

ADULT = {"name": "Ann", "role": "adult"}
NO_ACCOUNT = ("statement not imported automatically: no account with the last four digits 2424. Add the account first "
              "(Money > Accounts > Add an account), then file the statement again; AI reader: the AI was not sure (confidence 0.30)")


@pytest.fixture()
def waiting(root, modules):
    """add(name, reason, detail) -> proposal id of a fresh review card whose file sits in inbox/needs_review/."""
    paths, pr = modules("paths"), modules("proposals")
    set_ai(root, "claude_code")  # files go back to the inbox but no background run starts inside the test
    con = sqlite3.connect(paths.DB)
    with con:
        con.execute("DELETE FROM proposals")
        con.execute("UPDATE review_queue SET resolved=1")
    con.close()
    (paths.INBOX / "needs_review").mkdir(parents=True, exist_ok=True)

    def add(name, reason, detail=""):
        (paths.INBOX / "needs_review" / name).write_bytes(b"%PDF-1.4 " + name.encode())
        con = sqlite3.connect(paths.DB)
        with con:
            rid = con.execute("INSERT INTO review_queue(path, reason, detail) VALUES (?,?,?)",
                              (f"inbox/needs_review/{name}", reason, detail)).lastrowid
        con.close()
        pr.sync()
        con = sqlite3.connect(paths.DB)
        pid = con.execute("SELECT id FROM proposals WHERE dedupe_key=?", (f"review:{rid}",)).fetchone()[0]
        con.close()
        return pid
    yield add
    set_ai(root, "none")


def test_try_again_puts_the_file_back_in_the_inbox(root, modules, waiting):
    paths, inbox_data = modules("paths"), modules("inbox_data")
    pid = waiting("retry_me.pdf", "scanned PDF (no text layer): the pages are pictures, so there is no text to read")
    ok, msg = inbox_data.decide(ADULT, pid, "retry", {})
    assert ok and "back in the inbox" in msg, msg
    assert (paths.INBOX / "retry_me.pdf").exists() and not (paths.INBOX / "needs_review" / "retry_me.pdf").exists()
    assert q(root, "SELECT resolved FROM review_queue WHERE path LIKE '%retry_me.pdf'") == [(1,)]
    assert not inbox_data.decide(ADULT, pid, "retry", {})[0], "once only"
    (paths.INBOX / "retry_me.pdf").unlink()


def test_add_the_missing_account_then_read_again(root, modules, waiting):
    paths, inbox_data = modules("paths"), modules("inbox_data")
    pid = waiting("aug.pdf", NO_ACCOUNT, "guess type=statement vendor=Sample Card")
    con = sqlite3.connect(paths.DB)
    con.row_factory = sqlite3.Row
    item = modules("proposals").get(con, pid)
    con.close()
    assert item["options"]["account"] == "Add the account ending 2424"
    ok, msg = inbox_data.decide(ADULT, pid, "account", {"name": "Sample Card", "type": "credit", "last4": "9999"})
    assert not ok and "endings printed" in msg, "only an ending the statement printed"
    assert not q(root, "SELECT 1 FROM accounts WHERE last4='9999'")
    ok, msg = inbox_data.decide(ADULT, pid, "account", {"name": "Sample Card", "type": "credit", "last4": "2424"})
    assert ok and "Account Sample Card added" in msg and "back in the inbox" in msg, msg
    assert q(root, "SELECT type FROM accounts WHERE last4='2424'") == [("credit",)]
    assert (paths.INBOX / "aug.pdf").exists()
    (paths.INBOX / "aug.pdf").unlink()


def test_try_all_again(root, modules, waiting):
    paths, inbox_data = modules("paths"), modules("inbox_data")
    waiting("one.pdf", "could not open the file (damaged, or protected with a password?)")
    waiting("two.pdf", "low confidence or missing vendor/date (confidence 0.40)")
    ok, msg = inbox_data.retry_all(ADULT)
    assert ok and msg.startswith("2 files back in the inbox."), msg
    assert (paths.INBOX / "one.pdf").exists() and (paths.INBOX / "two.pdf").exists()
    assert inbox_data.retry_all(ADULT) == (True, "Nothing is waiting for you.")
    for n in ("one.pdf", "two.pdf"):
        (paths.INBOX / n).unlink()


def test_the_page_offers_the_fix_first(web, modules, waiting):  # noqa: F811
    c, _, _ = web
    _login(c)
    waiting("aug.pdf", NO_ACCOUNT, "guess type=statement vendor=Sample Card")
    waiting("photo.png", "photo not read: reading photos with AI is off (ai.read_receipt_photos in config/family.json)")
    html = c.get("/inbox/body?view=files").text
    card = html[html.index("aug.pdf needs you"):html.index("photo.png needs you")]
    assert card.index("Add the account ending 2424") < card.index(">File it by hand<"), "the fix comes first"
    assert '<input type="hidden" name="last4" value="2424">' in card and 'value="Sample Card"' in card
    assert ">Reprocess<" in card and "Open AI settings" not in card
    photo = html[html.index("photo.png needs you"):]
    assert 'href="/settings?group=connections#conn-ai">Open AI settings<' in photo
    assert 'hx-post="/inbox/retryall"' in html and ">Reprocess all<" in html
    r = c.post("/inbox/retryall", data={"view": "files"}, headers={"X-CSRF-Token": _token(c)})
    assert r.status_code == 200 and "2 files back in the inbox." in r.text, r.text[:300]
    paths = modules("paths")
    for n in ("aug.pdf", "photo.png"):
        (paths.INBOX / n).unlink()


def _token(c):
    import re
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/add").text).group(1)


def test_with_no_ai_a_waiting_file_leads_with_connect_an_ai(web, root, modules, waiting):  # noqa: F811
    c, _, _ = web
    _login(c)
    waiting("plain.pdf", "file type not read by the Python pipeline")
    html = c.get("/inbox/body?view=files").text
    assert ">Connect an AI<" not in html, "an AI is connected: Reprocess is the way"
    set_ai(root, "none")
    html = c.get("/inbox/body?view=files").text
    card = html[html.index("plain.pdf needs you"):]
    assert 'href="/settings?group=connections#conn-ai">Connect an AI<' in card
    assert card.index(">Connect an AI<") < card.index(">File it by hand<") < card.index(">Reprocess<")
    assert "connect an AI first" in card and "nothing more is read from the file" in card
    set_ai(root, "claude_code")
