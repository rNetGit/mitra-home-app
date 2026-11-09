"""The AI sentence on Brief > Today (data/brief_narrative.py): nothing without an AI, one call per day and list, names are
masked on the way out, and an answer with a number or link that is not in the list is thrown away."""
import datetime as D
import json

import pytest

from conftest import read_family, set_ai

TODAY = D.date.today()


def rows(*titles, days=0, amount=None, kind="Bill"):
    return [{"date": TODAY + D.timedelta(days=days), "kind": kind, "title": t, "amount": amount} for t in titles]


@pytest.fixture()
def bn(root, modules, chdir_root):
    mod = modules("brief_narrative")
    (root / "logs").mkdir(exist_ok=True)
    mod.CACHE.unlink(missing_ok=True)
    set_ai(root, "fake")
    (root / "config" / "fake_llm.json").write_text("You have one bill due today.", encoding="utf-8")
    yield mod
    (root / "config" / "fake_llm.json").unlink(missing_ok=True)
    mod.CACHE.unlink(missing_ok=True)


def calls(root):
    """Fresh AI calls made today for the Brief (the fake provider skips the daily counter, so the cache counts them)."""
    try:
        c = json.loads((root / "logs" / "brief_narrative.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return int(c.get("calls", 0)) if c.get("day") == TODAY.isoformat() else 0


def test_clean_keeps_plain_sentences_and_drops_invented_numbers_or_links(bn):
    src = "- Bill: Power (84.50), overdue by 3 days\n- Bill: Water, on Friday October 16"
    assert bn.clean("Your power bill of $84.50 is 3 days late.", src, 2) == "Your power bill of $84.50 is 3 days late."
    assert bn.clean("**Two** bills need you.", src, 2) == "Two bills need you."
    assert bn.clean("Your power bill is $99.00.", src, 2) == "", "an amount that is not in the list"
    assert bn.clean("Pay 5 bills today.", src, 2) == "", "a count larger than the list"
    assert bn.clean("See https://example.com for more.", src, 2) == ""
    assert bn.clean("Hello [person1].", src, 2) == "", "a leftover mask"
    assert bn.clean("x" * 500, src, 2) == ""
    assert bn.clean("", src, 2) == ""


def test_no_ai_or_no_rows_means_no_call_and_no_text(root, bn):
    set_ai(root, "none")
    assert bn.provider_ok() is False
    assert bn.narrate(rows("Power"), TODAY) == "" and calls(root) == 0
    set_ai(root, "claude_cli")
    assert bn.provider_ok() is False, "a signed-in CLI is too slow for a page that opens on a click"
    set_ai(root, "fake")
    assert bn.narrate([], TODAY) == "" and calls(root) == 0


def test_one_call_per_day_and_list_then_a_new_list_calls_again(root, bn):
    before = calls(root)
    a = rows("Power company")
    assert bn.cached(a, TODAY) is False
    assert bn.narrate(a, TODAY) == "You have one bill due today."
    assert calls(root) == before + 1
    assert bn.cached(a, TODAY) is True
    assert bn.narrate(a, TODAY) == "You have one bill due today." and calls(root) == before + 1, "served from the cache"
    bn.narrate(a + rows("Water company", days=2), TODAY)
    assert calls(root) == before + 2, "a changed list is a new call"


def test_the_daily_cap_stops_fresh_calls(root, bn):
    for i in range(bn.MAX_PER_DAY):
        bn.narrate(rows(f"Bill number {i}"), TODAY)
    n = calls(root)
    assert bn.narrate(rows("One more bill"), TODAY) == "" and calls(root) == n


def test_names_are_masked_before_the_call_and_restored_in_the_answer(root, bn, monkeypatch):
    fam = read_family(root)
    who = fam["members"][0]["name"]
    seen = {}

    def fake_complete(prompt, **kw):
        seen["prompt"] = prompt
        return "[person1] has one thing today."

    monkeypatch.setattr(bn.llm, "complete", fake_complete)
    out = bn.narrate(rows(f"{who} dentist", kind="Checkup"), TODAY)
    assert who not in seen["prompt"], "the name never left"
    assert out == f"{who} has one thing today."


