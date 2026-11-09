"""Inbox over the phone bot (0.49): /inbox lists open items with numbered choices, /ok ID [N] [DATE] and /no ID decide
them through proposals.decide. Adults in private chats only; filing a document stays on the PC. No AI."""
import datetime as D

import pytest

from conftest import db, q

NOW = D.datetime.now().replace(microsecond=0)


@pytest.fixture(scope="module")
def C(root, modules):
    c = modules("chat_core")
    con = c._con(root / "data" / "family.db")
    try:
        for name, uid in (("Alex", "801"), ("Sam", "802")):
            code, *_ = c.invite(con, name, now=NOW)
            assert "linked" in H(c, root, uid, f"/start {code}")
    finally:
        con.close()
    modules("proposals").sync()
    return c


def H(C, root, uid, text, private=True):
    return C.handle("telegram", uid, text, private=private, today=NOW.date(), db=root / "data" / "family.db", now=NOW)


def _open(root, source):
    return q(root, "SELECT id FROM proposals WHERE status='open' AND source=? ORDER BY id", source)


def test_inbox_lists_items_with_numbered_choices(C, root):
    r = H(C, root, "801", "/inbox")
    assert "waiting" in r and "/ok ID" in r, r
    pid = _open(root, "undated")[0][0]
    assert f"#{pid} When was" in r and "1) Pick date" in r and "2) Not sure" in r, r
    assert "/inbox" in H(C, root, "801", "/help")


def test_only_adults_in_private_chats(C, root):
    pid = _open(root, "undated")[0][0]
    assert H(C, root, "802", "/inbox") == "The Inbox is for adults."
    assert H(C, root, "802", f"/ok {pid}") == "Only adults can decide Inbox items."
    assert "private chat" in H(C, root, "801", "/inbox", private=False)
    assert "private chat" in H(C, root, "801", f"/no {pid}", private=False)
    assert q(root, "SELECT status FROM proposals WHERE id=?", pid) == [("open",)]
    assert H(C, root, "999", "/inbox") is None, "strangers get silence"


def test_ok_with_a_date_records_it(C, root):
    pid = _open(root, "undated")[0][0]
    item = q(root, "SELECT json_extract(payload, '$.item_id') FROM proposals WHERE id=?", pid)[0][0]
    assert "Send the date too" in H(C, root, "801", f"/ok {pid}")
    assert "Choose 1 to 3" in H(C, root, "801", f"/ok {pid} 9")
    r = H(C, root, "801", f"/ok {pid} 1 2026-04-02")
    assert r.startswith("Recorded:"), r
    assert q(root, "SELECT last_done FROM recurring_items WHERE id=?", item) == [("2026-04-02",)]
    assert q(root, "SELECT status, decided_by FROM proposals WHERE id=?", pid) == [("done", "Alex")]
    assert H(C, root, "801", f"/ok {pid} 1 2026-04-02") == "That one is already handled."


def test_no_snoozes_a_question_and_ignores_a_payment(C, root):
    pid = _open(root, "undated")[0][0]
    assert "ask again in a month" in H(C, root, "801", f"/no #{pid}")
    assert q(root, "SELECT status FROM proposals WHERE id=?", pid) == [("snoozed",)]
    rec = _open(root, "recurring")
    if rec:
        assert "not be suggested again" in H(C, root, "801", f"/no {rec[0][0]}")
        assert q(root, "SELECT status FROM proposals WHERE id=?", rec[0][0]) == [("dismissed",)]


def test_filing_a_document_stays_on_the_pc(C, root, modules):
    con = db(root)
    con.execute("INSERT INTO review_queue(path, reason, detail) VALUES ('inbox/needs_review/w.pdf', 'low confidence', "
                "'guess type=bill vendor=City Water')")
    con.commit()
    con.close()
    modules("proposals").sync()
    pid = _open(root, "review")[0][0]
    assert q(root, "SELECT detail FROM proposals WHERE id=?", pid) == \
        [("The assistant was not sure what it is. It looked like a bill from City Water.",)]
    assert "on the family PC" in H(C, root, "801", f"/ok {pid}")
    assert "Dismissed" in H(C, root, "801", f"/no {pid}")


def test_bad_input(C, root):
    assert "e.g. /ok 12" in H(C, root, "801", "/ok")
    assert "e.g. /no 12" in H(C, root, "801", "/no abc")
    assert H(C, root, "801", "/ok 999999") == "That one is already handled."
