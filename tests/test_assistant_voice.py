"""0.45.0 plain-language chat (data/assistant_voice.py + assistant.py): what the assistant is about to change and what
it did are said in ordinary words; action names, JSON, SQL, ids, file names and paths stay out of the chat and go
to logs/assistant.log; a briefing is shown as its content, not its path."""
import json

import pytest


def say(reply, actions=None):
    return json.dumps({"reply": reply, "actions": actions or [], "question": None})


@pytest.fixture(scope="module")
def V(root, modules):
    return modules("assistant_voice")


def test_sentences_for_actions(V):
    assert V.describe("members_birthday", {"name": "Sam", "md": "02-02"}) == "Set Sam's birthday to February 2"
    assert V.describe("recurring_done", {"name_fragment": "dental", "who": "Raj", "date": "2026-09-03"}).startswith(
        "Record that dental was done for Raj on September 3")
    assert V.describe("list_add", {"list": "groceries", "item": "milk"}) == "Add milk to the groceries list"
    assert V.describe("budget_set", {"category": "dining", "amount": 250}) == "Set the dining budget to $250.00 a month"
    assert V.describe("no_such_action", {}, "do a thing") == "Do a thing"
    assert V.nice_date("not-a-date") == "not-a-date"


def test_failures_and_ai_trouble_have_no_internals(V):
    assert "couldn't find" in V.failure("life_done", "error: 0 matches for 'x'")
    assert "already" in V.failure("list_add", "item already on the list")
    assert V.failure("x", "Traceback (most recent call last): sqlite3.OperationalError").startswith("I couldn't do that one")
    for e in ("HTTP 404 from provider", "gemini: HTTP 500", "something odd"):
        msg = V.ai_trouble(Exception(e))
        assert "HTTP" not in msg and "MITRAHOME" not in msg and "Settings" in msg
    assert "MITRAHOME" not in V.ai_trouble(Exception("No API key for gemini. Put MITRAHOME_GEMINI_API_KEY=... in secrets"))
    assert "limit" in V.ai_trouble(Exception("daily AI call cap reached"))


def test_documents_only_from_inside_the_install(V, root, tmp_path):
    inside = root / "brief" / "x_family_meeting.md"
    inside.parent.mkdir(exist_ok=True)
    inside.write_text("# Agenda\n- Plan the week\n", encoding="utf-8")
    assert "Plan the week" in V.document_from(f"made it\n{inside}")
    outside = tmp_path / "secret.md"
    outside.write_text("nope", encoding="utf-8")
    assert V.document_from(str(outside)) is None
    assert V.document_from(str(root / "data" / "family.db")) is None
    assert V.document_from("") is None
    assert "C:\\" not in V.plain(r"saved to C:\Users\x\brief\a.md ok")
    assert "/home/x/brief" not in V.plain("at /home/x/brief/a.md fine")


def test_chat_never_shows_internals(root, mock_llm, modules):
    mock_llm.use("anthropic")
    aa = modules("admin_actions")
    adult = {"name": "Alex", "role": "adult"}
    mock_llm.queue = [say("Here you go.", [{"name": "family_meeting", "args": {}}])]
    r = aa.ask(adult, "what is on the family meeting agenda?")
    text = "\n".join(r["lines"])
    assert r["ok"] and "family_meeting" not in text and str(root) not in text and ".md" not in text
    assert "Family meeting" in text, text[:200]
    mock_llm.queue = [say("Saving.", [{"name": "list_add", "args": {"list": "groceries", "item": "milk"}}])]
    r = aa.ask(adult, "add milk to groceries")
    text = "\n".join(r["lines"])
    assert r["needs_confirm"] and "Add milk to the groceries list" in text
    assert "list_add" not in text and "{" not in text and "args" not in text
    mock_llm.seen = []
    r = aa.confirm(adult, r["writes"])
    text = "\n".join(r["lines"])
    assert mock_llm.seen == [], "the change shown is made as shown; the AI is not asked again"
    assert "Done: Add milk to the groceries list." in text and "list_add" not in text
    mock_llm.queue = [say("Bad.", [{"name": "run_shell", "args": {"cmd": "x"}}])]
    r = aa.ask(adult, "do something odd")
    joined = "\n".join(r["lines"])
    assert "run_shell" not in joined and "allowed action" not in joined
    mock_llm.queue = []
