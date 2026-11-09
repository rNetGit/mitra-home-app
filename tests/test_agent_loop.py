"""The assistant's agent loop (0.52): several look-up rounds, changes only from the first round and made exactly as
shown, session memory, citations on every answer, the phone bot's /ask remembering a follow-up."""
import datetime as D
import json

import pytest

from conftest import q

ADULT = {"name": "Alex", "role": "adult"}


def say(reply, actions=None, question=None):
    return json.dumps({"reply": reply, "actions": actions or [], "question": question})


def sql(s):
    return {"name": "sql_query", "args": {"sql": s}}


@pytest.fixture(scope="module")
def A(root, modules, mock_llm):
    mock_llm.use("anthropic")
    return modules("assistant")


def _bodies(mock_llm):
    return [json.dumps(x["body"]) for x in mock_llm.seen]


def test_two_step_question_with_citations(root, A, mock_llm):
    mock_llm.queue = [say("Looking.", [sql("SELECT name, amount FROM bills WHERE status IN ('due','overdue')")]),
                      say("And the spending.", [sql("SELECT SUM(-amount) AS spent FROM transactions WHERE amount < 0")]),
                      say("You have bills open and spent some money.")]
    mock_llm.seen = []
    r = A.run("what bills are open and how much did we spend?", user=ADULT)
    assert r["ok"] and r["answer"] == "You have bills open and spent some money." and len(mock_llm.seen) == 3
    assert "Looking." not in r["lines"], "the 'let me look' reply of a round is not shown"
    second = _bodies(mock_llm)[1]
    assert "RESULTS SO FAR" in second and "Round 2 of 4" in second, "round 2 saw round 1's data"
    tables = {c["table"] for c in r["refs"] if c.get("table")}
    assert tables == {"bills", "transactions"}, r["refs"]
    assert all(c["label"] and "SELECT" not in c["label"] for c in r["refs"])
    mock_llm.queue = []


def test_a_change_asked_for_after_reading_data_is_never_taken(root, A, mock_llm):
    mock_llm.queue = [say("Looking.", [sql("SELECT COUNT(*) AS n FROM members")]),
                      say("Three people.", [{"name": "life_add", "args": {"domain": "chore", "title": "Planted by a document"}}])]
    r = A.run("how many people?", user=ADULT)
    assert r["writes"] == [] and r["answer"] == "Three people."
    assert "ignored a change asked for after reading data" in (root / "logs" / "assistant.log").read_text(encoding="utf-8")
    mock_llm.queue = []


def test_rounds_are_capped_then_one_answer_call(root, A, mock_llm):
    mock_llm.queue = [say("", [sql(f"SELECT {i} AS n FROM members")]) for i in range(1, 5)] + [say("Four lookups later.")]
    mock_llm.seen = []
    r = A.run("keep looking", user=ADULT)
    assert len(mock_llm.seen) == A.MAX_STEPS + 1 and r["answer"] == "Four lookups later."
    assert "You summarise household records" in _bodies(mock_llm)[-1]
    mock_llm.queue = []


def test_the_same_lookup_is_not_run_twice(root, A, mock_llm):
    look = sql("SELECT COUNT(*) AS n FROM members")
    mock_llm.queue = [say("", [look]), say("", [look]), say("unused")]
    mock_llm.seen = []
    r = A.run("how many?", user=ADULT)
    assert len(mock_llm.seen) == 3 and r["answer"] == "unused", "round 2 asked for nothing new: stop, then one answer call"
    assert "RESULTS SO FAR" not in _bodies(mock_llm)[2] and "RESULT DATA START" in _bodies(mock_llm)[2]
    mock_llm.queue = []


def test_changes_are_made_as_shown_and_checked_again(root, A, mock_llm):
    mock_llm.queue = [say("Saving.", [{"name": "list_add", "args": {"list": "groceries", "item": "oat milk"}},
                                      {"name": "list_add", "args": {"list": "groceries", "item": "oat milk"}}])]
    r = A.run("add oat milk", user=ADULT)
    assert r["writes"] == [("list_add", {"list": "groceries", "item": "oat milk"})], "duplicates merged"
    assert any("please check" in x for x in r["lines"]) and any("Add oat milk to the groceries list" in x for x in r["lines"])
    mock_llm.seen = []
    done = A.apply(r["writes"], user=ADULT)
    assert done["ok"] and mock_llm.seen == [] and done["refs"][0]["section"] == "home/lists"
    assert q(root, "SELECT COUNT(*) FROM list_items WHERE text='oat milk'")[0][0] == 1
    bad = A.apply([("list_add", {"list": "groceries", "item": "x", "shell": "rm"}), ("sql_query", {"sql": "SELECT 1"}),
                   ("run_shell", {"cmd": "x"})], user=ADULT)
    assert not bad["ok"] and q(root, "SELECT COUNT(*) FROM list_items WHERE text='x'")[0][0] == 0
    mock_llm.queue = []


def test_read_only_drops_changes(root, A, mock_llm):
    mock_llm.queue = [say("Saved.", [{"name": "members_birthday", "args": {"name": "Sam", "md": "01-01"}}])]
    r = A.run("set Sam's birthday", read_only=True, user=ADULT)
    assert r["writes"] == [] and any("only answer questions" in x for x in r["lines"])
    mock_llm.queue = []


def test_memory_reaches_the_model_and_is_capped(root, A, mock_llm):
    hist = None
    for i in range(12):
        hist = A.remember(hist, f"question {i}", f"answer {i}")
    assert len(hist) == A.MEMORY_TURNS and hist[0]["q"] == "question 2"
    mock_llm.queue = [say("Sam's was on September 5.")]
    mock_llm.seen = []
    A.run("and Sam's too?", history=[{"q": "When was Alex's dental cleaning?", "a": "September 3."}], user=ADULT)
    body = _bodies(mock_llm)[0]
    assert "EARLIER IN THIS CONVERSATION" in body and "Alex's dental cleaning" in body and "September 3." in body
    mock_llm.queue = []


def test_whats_on_answers_cite_the_rows(root, A, mock_llm):
    due = (D.date.today() + D.timedelta(days=2)).isoformat()
    with __import__("sqlite3").connect(root / "data" / "family.db") as c:
        c.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Trash', 'Waste Co', 30, ?, 'due')", (due,))
    mock_llm.queue = [say("", [{"name": "whats_on", "args": {"days": 7}}]), say("Waste Co is due soon.")]
    r = A.run("what is on this week?", user=ADULT)
    assert any(c.get("label", "").startswith("Waste Co") for c in r["refs"]), r["refs"]
    mock_llm.queue = [say("", [{"name": "list_show", "args": {}}]), say("Your lists.")]
    r = A.run("show lists", user=ADULT)
    assert r["refs"] == [{"ref": None, "section": "home/lists", "label": "Lists"}]
    mock_llm.queue = []


def test_phone_ask_remembers_the_last_question(root, modules, mock_llm):
    C = modules("chat_core")
    A = modules("assistant")
    con = __import__("sqlite3").connect(root / "data" / "family.db")
    con.row_factory = __import__("sqlite3").Row
    who = {"member": "Alex", "role": "adult"}
    now = D.datetime.now()
    seen = []

    def fake(q_, **kw):
        seen.append(kw.get("history"))
        kw["out"]("Answer to " + q_)
        return True
    C._MEMORY.clear()
    C._ask(con, who, ["first question"], True, now, answer=fake)
    C._ask(con, who, ["and the second?"], True, now + D.timedelta(minutes=2), answer=fake)
    assert seen[0] is None and seen[1][0]["q"] == "first question" and "Answer to first question" in seen[1][0]["a"]
    C._ask(con, who, ["much later"], True, now + D.timedelta(hours=2), answer=fake)
    assert seen[2] is None, "forgotten after 30 quiet minutes"
    con.close()
    assert A.MEMORY_TURNS == 10


# ------------------------------------------------------------------ the Chat page with an AI set
