"""/ask over chat (data/chat_core.py + data/assistant.py read_only): adults in a private chat only, read-only actions
from the fixed catalog (changes are refused and never run), raw query output not sent, daily cap, question text never
logged, AI failure handled."""
import datetime as D
import json

import pytest

from conftest import q

NOW = D.datetime(2026, 10, 9, 9, 0, 0)


def say(reply, actions=None):
    return json.dumps({"reply": reply, "actions": actions or [], "question": None})


@pytest.fixture(scope="module")
def C(root, modules, mock_llm):
    mock_llm.use("anthropic")
    C = modules("chat_core")
    c = C._con(root / "data" / "family.db")
    try:
        for name, uid in (("Alex", "7701"), ("Sam", "7702")):
            code, *_ = C.invite(c, name, platform="telegram", now=NOW)
            C.handle("telegram", uid, f"/start {code}", db=root / "data" / "family.db", now=NOW)
    finally:
        c.close()
    return C


def H(C, root, uid, text, private=True, now=NOW):
    return C.handle("telegram", uid, text, private=private, db=root / "data" / "family.db", now=now)


def test_gates(C, root, mock_llm):
    mock_llm.set(say("hi"))
    assert "adults" in H(C, root, "7702", "/ask how much money do we have")
    assert "private chat" in H(C, root, "7701", "/ask anything", private=False)
    assert "/ask and your question" in H(C, root, "7701", "/ask")
    assert "under 500" in H(C, root, "7701", "/ask " + "x" * 600)
    assert mock_llm.seen == [], "nothing reached the AI"
    assert "/ask" in H(C, root, "7701", "/help") and "/ask" not in H(C, root, "7702", "/help")


def test_read_only_answer(C, root, mock_llm):
    mock_llm.queue = [say("Looking.", [{"name": "sql_query", "args": {"sql": "SELECT COUNT(*) AS n FROM members"}}]),
                      say("You have 3 members on record.")]
    r = H(C, root, "7701", "/ask how many family members are there?")
    mock_llm.queue = []
    assert "3 members" in r and "not professional advice" in r
    assert "done:" not in r and "| n" not in r, "raw query output stays on the PC"
    assert "how many" not in json.dumps([list(x) for x in q(root, "select * from chat_log")])


def test_changes_are_refused(C, root, mock_llm):
    before = q(root, "select birth_month_day from members where name='Sam'")
    mock_llm.queue = [say("Saved.", [{"name": "members_birthday", "args": {"name": "Sam", "md": "01-01"}}])]
    r = H(C, root, "7701", "/ask set Sam's birthday to Jan 1")
    mock_llm.queue = []
    assert "only answer questions in this chat" in r
    assert q(root, "select birth_month_day from members where name='Sam'") == before


def test_ai_failure_and_daily_cap(C, root, mock_llm, monkeypatch):
    def boom(*a, **k):
        raise TimeoutError()
    c = C._con(root / "data" / "family.db")
    try:
        who = C.identify(c, "telegram", "7701")
        assert "could not answer" in C._ask(c, who, ["q"], True, NOW, answer=boom)
    finally:
        c.close()
    monkeypatch.setattr(C, "ask_limit", lambda: 3)
    mock_llm.set(say("ok"))
    later = NOW + D.timedelta(days=1)
    replies = [H(C, root, "7701", "/ask hello", now=later) for _ in range(4)]
    assert "today's 3 questions" in replies[-1] and all("today's" not in r for r in replies[:3])
    assert "today's" not in H(C, root, "7701", "/ask hello", now=later + D.timedelta(days=1))
