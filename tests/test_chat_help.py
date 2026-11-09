"""Chat answers questions about the app itself: help_text.lookup for any wording (no "how do I" needed), the glossary
the assistant always sees, the help_lookup action, and the Help links under the answer."""
import json
import re
from pathlib import Path

import pytest

from conftest import KEYS, run

TEMPLATES = Path(__file__).resolve().parent.parent / "data" / "webapp" / "templates"


@pytest.fixture(scope="module")
def ht(root, modules):
    return modules("help_text")


@pytest.mark.parametrize("text,key", [
    ("my bill shows the wrong category", "finance:bills"),
    ("this charge is in the wrong category", "finance:ledger"),
    ("why is this under needs a look", "inbox"),
    ("duplicate charge", "settings"),
    ("where do i change a wrong amount on a bill", "finance:bills"),
    ("a paper was filed as the wrong type", "records:papers:papers"),
    ("how do I add a dentist appointment", "records:people:health"),
    ("snooze a reminder", "home"),
])
def test_lookup_answers_app_questions_in_any_wording(ht, text, key):
    assert key in ht.lookup(text)[:2], (text, ht.lookup(text))


def test_lookup_finds_nothing_for_nonsense_and_at_most_three(ht):
    assert ht.lookup("xyzzy plugh") == [] and ht.lookup("") == []
    assert len(ht.lookup("bill receipt subscription budget account statement")) == 3


def test_as_data_and_cli_are_plain_text_without_urls(ht, root):
    d = ht.as_data("finance:bills")
    assert d.startswith("Bills: ") and "Mark paid" in d and "[" not in d and "http" not in d and "/records" not in d
    r = run(["data/help_text.py", "lookup", "wrong category charge"], root)
    assert r.returncode == 0 and "[finance:ledger]" in r.stdout and "Do the same for every line like this one" in r.stdout
    assert "No help entry matches" in run(["data/help_text.py", "lookup", "xyzzy"], root).stdout
    assert "Data check" in run(["data/help_text.py", "glossary"], root).stdout


def test_glossary_names_only_buttons_and_phrases_that_exist(ht, modules):
    # buttons live in the templates; a few labels are built in Python (the Inbox cards, the record forms)
    source = " ".join(p.read_text(encoding="utf-8") for p in TEMPLATES.glob("*.html"))
    source += " ".join(Path(modules(m).__file__).read_text(encoding="utf-8") for m in ("inbox_data", "records_edit", "webapp.app"))
    for line in ht.GLOSSARY:
        for name in re.findall(r"\[([^\]]+)\]", line):
            assert name in source, f"the glossary names [{name}], which is on no screen"
    text = ht.glossary_text()
    for phrase in ("Mark paid", "Mark as not paid", "Do the same for every line like this one", "Data check", "Remember", "Why?",
                   "Change it", "File it by hand", "Reprocess", "Hidden from Today"):
        assert phrase in text and phrase in source, phrase
    assert "[" not in text and len(text) < 5000, "the glossary rides in every planning prompt"
    assert all(k in ht.HELP for k in ht.SYNONYMS.values())


# ---- the assistant

def say(reply, actions=None, question=None):
    return json.dumps({"reply": reply, "actions": actions or [], "question": question})


@pytest.fixture(scope="module")
def ask(root, mock_llm):
    def go(*replies, text="request"):
        mock_llm.use("anthropic")
        mock_llm.seen = []
        mock_llm.queue = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        return run(["data/assistant.py", "--yes", text], root, env=KEYS)
    yield go
    mock_llm.queue = []


def test_the_planning_prompt_carries_the_glossary_and_help_lookup(root, ask, mock_llm):
    r = ask(say("Hello!"), text="hi")
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    sent = json.dumps(mock_llm.seen[0]["body"])
    assert "help_lookup(words)" in sent and "About the app itself" in sent
    assert "Settings > Data > Data check" in sent and "never invent a page, button or setting" in sent


def test_help_lookup_round_feeds_the_answer_and_links_to_help(root, modules, mock_llm):
    mock_llm.use("anthropic")
    mock_llm.seen = []
    mock_llm.queue = [say("Let me check.", [{"name": "help_lookup", "args": {"words": "wrong category charge"}}]),
                      say("Open the line in Money > Ledger, pick the category and press Save.")]
    A = modules("assistant")
    res = A.run("one of my charges shows the wrong category, how do I fix it?", user={"name": "Alex", "role": "adult"})
    mock_llm.queue = []
    assert res["ok"] and "Money > Ledger" in res["answer"], res
    second = json.dumps(mock_llm.seen[1]["body"])
    assert "Do the same for every line like this one" in second, "the help entry went back to the model as data"
    assert {"help": "finance:ledger", "label": "Help > Ledger"} in res["refs"]
    assert not res["writes"]


def test_help_lookup_is_read_only_and_never_runs_on_bad_words(root, ask):
    r = ask(say("ok", [{"name": "help_lookup", "args": {"words": "x" * 200}}]), text="x")
    assert "I couldn't do one part of that" in r.stdout
    r = ask(say("Looking.", [{"name": "help_lookup", "args": {"words": "xyzzy"}}]), say("I have no help on that."), text="xyzzy?")
    assert r.returncode == 0 and "I have no help on that." in r.stdout, r.stdout + r.stderr[-200:]
