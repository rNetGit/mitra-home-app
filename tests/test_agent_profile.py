"""Agent profile, Settings in four groups and the profile completion meter (0.53): the profile card in family.json
(name, tone, brief schedule, watch list, approvers), changing it from Chat with a confirm card, the Brief leaving out
what is not watched, phone approvers, gap questions in the Inbox (two new a day) and the Settings page."""
import datetime as D
import json

import pytest

from conftest import db, imported_from, q, read_family, write_family

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "child"}
NOW = D.datetime.now().replace(microsecond=0)


@pytest.fixture(scope="module")
def P(root, modules):
    return modules("agent_profile")


def _reset(root):
    fam = read_family(root)
    fam.pop("agent", None)
    fam.pop("household", None)
    fam["ai"] = {"provider": "none"}
    write_family(root, fam)


# ------------------------------------------------------------------ the profile itself
def test_defaults_and_checked_values(root, P):
    _reset(root)
    p = P.get()
    assert p["name"] == "Mitra" and p["tone"] == "brief" and p["brief_time"] == "07:00"
    assert p["weekly_day"] == "SUN" and p["watch"] == list(P.WATCH) and p["approvers"] == []
    for raw, want in (("6", "06:00"), ("6:30", "06:30"), ("6pm", "18:00"), ("6:30 PM", "18:30"), ("12am", "00:00"),
                      ("18:05", "18:05"), ("7.15", "07:15")):
        assert P.clean_time(raw) == want, raw
    for bad in ("25", "6:75", "13pm", "noon", ""):
        with pytest.raises(ValueError):
            P.clean_time(bad)
    assert P.clean_day("sunday") == "SUN" and P.clean_name("  Ollie   the  Owl ") == "Ollie the Owl"
    for bad in ("", "x" * 41, "<script>"):
        with pytest.raises(ValueError):
            P.clean_name(bad)
    fam = read_family(root)
    fam["agent"] = {"name": "<bad>", "tone": "shouty", "brief_time": "99:99", "watch": ["bills", "nope"], "approvers": "Alex"}
    write_family(root, fam)
    p = P.get()
    assert (p["name"], p["tone"], p["brief_time"], p["watch"], p["approvers"]) == ("Mitra", "brief", "07:00", ["bills"], [])
    _reset(root)


def test_set_field_saves_and_explains(root, P):
    ok, msg = P.set_field("brief_time", "6")
    assert ok and msg == "The daily brief is made at 06:00 from now on."
    assert read_family(root)["agent"]["brief_time"] == "06:00"
    assert P.set_field("name", "Ollie")[0] and P.name() == "Ollie"
    ok, msg = P.set_field("watch_off", "dates")
    assert ok and "leaves out birthdays" in msg and "dates" not in P.get()["watch"]
    assert P.watched("Birthday") is False and P.watched("Bill") is True and P.watched("Backup") is True
    assert P.set_field("watch_on", "dates")[0] and P.watched("Birthday")
    assert P.set_field("tone", "loud") == (False, "Tone is brief or warm.")
    assert P.set_field("approvers", "Sam")[0] is False, "approvers are not a set_field field (Settings only)"
    assert read_family(root)["family_name"] == "Test", "the rest of family.json is kept"
    _reset(root)


def test_approvers_are_adults_only(root, P):
    ok, probs = P.set_profile({"approvers": ["Sam"]})
    assert not ok and "Only adults" in probs[0]
    assert P.set_profile({"approvers": ["alex"]})[0] and P.get()["approvers"] == ["Alex"]
    assert P.may_approve("Alex") and not P.may_approve("Jordan")
    _reset(root)
    assert P.may_approve("Jordan"), "empty list = every adult"


def test_schedule_follows_the_profile(root, P, modules):
    P.set_profile({"brief_time": "06:30", "weekly_day": "SAT", "weekly_time": "17:00"})
    assert P.schtasks_args("daily_digest") == ["/sc", "daily", "/st", "06:30"]
    assert P.schtasks_args("weekly_digest") == ["/sc", "weekly", "/d", "SAT", "/st", "17:00"]
    assert P.cron_line("daily_digest") == "30 6 * * *" and P.cron_line("weekly_digest") == "0 17 * * 6"
    assert P.schtasks_args("weekly_backup") == ["/sc", "weekly", "/d", "SUN", "/st", "09:00"], "default backup time"
    assert P.schtasks_args("inbox_cycle") is None and P.when_text("inbox_cycle") is None
    assert P.when_text("daily_digest") == "Every day at 06:30" and P.when_text("weekly_digest") == "Saturdays at 17:00"
    calls = []

    class R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout = rc, out

    here = f"<Command>{root / 'tasks' / 'daily_digest.bat'}</Command>"

    def fake(args, **kw):
        calls.append(args)
        return R(0, here)
    import platform
    if platform.system() == "Windows":
        assert P.reschedule("daily_digest", run=fake) is True
        assert calls[0][:2] == ["schtasks", "/query"] and calls[1][-2:] == ["/st", "06:30"] and "/f" in calls[1]
        assert P.reschedule("daily_digest", run=lambda a, **k: R(1)) is None, "not registered here: nothing to move"
        other = lambda a, **k: calls.append(a) or R(0, "<Command>D:/other/tasks/daily_digest.bat</Command>")  # noqa: E731
        calls.clear()
        assert P.reschedule("daily_digest", run=other) is None and len(calls) == 1, "another copy's task is left alone"
    assert P.reschedule("daily_digest") is None, "the test suite never touches the real scheduler"
    with imported_from(root, "onboard") as onboard:
        assert onboard._sched("daily_digest", ["/sc", "daily", "/st", "07:00"])[-1] == "06:30"
        assert onboard._sched("inbox_cycle", ["/sc", "hourly"]) == ["/sc", "hourly"]
        assert onboard._cron("weekly_digest") == "0 17 * * 6" and onboard._cron("inbox_cycle") == onboard.CRON["inbox_cycle"]
    _reset(root)


# ------------------------------------------------------------------ from Chat
def test_chat_changes_the_profile_with_a_confirm_card(root, modules, mock_llm):
    mock_llm.use("anthropic")
    A = modules("assistant")
    mock_llm.queue = [json.dumps({"reply": "Sure.", "actions": [{"name": "agent_set", "args": {"field": "brief_time", "value": "6"}}],
                                  "question": None})]
    r = A.run("send the brief at 6 instead", user=ADULT)
    assert r["writes"] == [("agent_set", {"field": "brief_time", "value": "06:00"})], r
    assert read_family(root).get("agent", {}).get("brief_time") in (None, "07:00"), "nothing changes before the OK"
    res = A.apply(r["writes"], user=ADULT)
    assert res["ok"] and res["lines"] == ["Done: Make the daily brief at 06:00."], res
    assert read_family(root)["agent"]["brief_time"] == "06:00"
    clean, err = A.validate_action({"name": "agent_set", "args": {"field": "brief_time", "value": "26:00"}})
    assert clean is None and "time" in err
    clean, err = A.validate_action({"name": "agent_set", "args": {"field": "approvers", "value": "Sam"}})
    assert clean is None, "who approves is not changed from chat"
    modules("agent_profile").set_field("name", "Ollie")
    modules("agent_profile").set_field("tone", "warm")
    con = db(root)
    try:
        prompt = A.system_prompt(con)
    finally:
        con.close()
    assert prompt.startswith("You are Ollie, the assistant for ONE household") and "Write warmly" in prompt
    _reset(root)
    fam = read_family(root)
    fam["ai"] = {"provider": "none"}
    write_family(root, fam)


# ------------------------------------------------------------------ phone approvers
def test_phone_approvers(root, modules):
    c = modules("chat_core")
    con = c._con(root / "data" / "family.db")
    try:
        code, *_ = c.invite(con, "Alex", now=NOW)
    finally:
        con.close()
    h = lambda t: c.handle("telegram", "901", t, private=True, today=NOW.date(), db=root / "data" / "family.db", now=NOW)  # noqa: E731
    assert "linked" in h(f"/start {code}")
    modules("proposals").sync()
    pid = q(root, "SELECT id FROM proposals WHERE status='open' AND source='undated' ORDER BY id")[0][0]
    fam = read_family(root)
    fam["members"].append({"name": "Jordan", "role": "adult"})
    fam["agent"] = {"approvers": ["Jordan"]}
    write_family(root, fam)
    r = h(f"/ok {pid} 2")
    assert r.startswith("Inbox items are decided by Jordan"), r
    assert q(root, "SELECT status FROM proposals WHERE id=?", pid) == [("open",)]
    fam["agent"] = {"approvers": []}
    fam["members"] = [m for m in fam["members"] if m["name"] != "Jordan"]
    write_family(root, fam)
    assert "ask again" in h(f"/ok {pid} 2").lower()
    _reset(root)


# ------------------------------------------------------------------ profile gaps
def test_meter_and_two_new_questions_a_day(root, modules):
    G, prop = modules("profile_gaps"), modules("proposals")
    con = db(root)
    try:
        con.execute("DELETE FROM proposals WHERE source='profile'")
        con.execute("UPDATE members SET birth_month_day='' WHERE name='Sam'")
        con.commit()
        m = {r["area"]: r for r in G.meter(con)}
    finally:
        con.close()
    assert [a for a, _ in G.AREAS] == list(m)
    assert m["people"]["total"] == 2 and m["people"]["done"] == 1, "pets are not asked for a birthday"
    assert m["home"]["next"]["summary"] == "Do you own or rent your home?"
    assert 0 <= G.overall(db(root)) < 100
    prop.sync()
    first = q(root, "SELECT dedupe_key FROM proposals WHERE source='profile' AND status='open' ORDER BY id")
    assert [k for (k,) in first] == ["profile:birthday:sam", "profile:tenure"], first
    prop.sync()
    assert len(q(root, "SELECT id FROM proposals WHERE source='profile'")) == 2, "two new a day, and they stay open"
    item = prop.get(db(root), q(root, "SELECT id FROM proposals WHERE dedupe_key='profile:tenure'")[0][0])
    assert list(item["options"]) == ["own", "rent", "later"]


def test_answers_fill_the_profile(root, modules):
    prop, G = modules("proposals"), modules("profile_gaps")
    bday = q(root, "SELECT id FROM proposals WHERE dedupe_key='profile:birthday:sam'")[0][0]
    ten = q(root, "SELECT id FROM proposals WHERE dedupe_key='profile:tenure'")[0][0]
    assert prop.decide(KID, ten, "own")[0] is False
    assert prop.decide(ADULT, bday, "birthday") == (False, "Please fill in: date.")
    ok, msg = prop.decide(ADULT, bday, "birthday", date="2016-09-02")
    assert ok, msg
    assert q(root, "SELECT birth_month_day, birth_year FROM members WHERE name='Sam'") == [("09-02", 2016)]
    assert read_family(root)["members"][1]["birth_month_day"] == "09-02"
    ok, msg = prop.decide(ADULT, ten, "own")
    assert ok and msg == "Saved: you own your home." and read_family(root)["household"]["tenure"] == "own"
    con = db(root)
    try:
        m = {r["area"]: r for r in G.meter(con)}
        assert m["people"]["done"] == 2 and m["home"]["done"] == m["home"]["total"] == 2
        # "Answer next" puts a question in the Inbox now, outside the daily cap
        pid = G.ask_now(con, "profile:vehicles")
        assert pid and q(root, "SELECT status FROM proposals WHERE id=?", pid) == [("open",)]
        assert G.ask_now(con, "profile:vehicles") == pid
    finally:
        con.close()
    ok, _ = prop.decide(ADULT, pid, "dismiss")
    assert ok
    con = db(root)
    try:
        assert {r["area"]: r for r in G.meter(con)}["vehicles"]["done"] == 1, "'No car' counts as answered"
        assert G.ask_now(con, "profile:vehicles") is None
    finally:
        con.close()
    prop.sync()
    assert q(root, "SELECT status FROM proposals WHERE id=?", pid) == [("dismissed",)], "not asked again"


# ------------------------------------------------------------------ Brief and Settings pages
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _texts(at):
    return " ".join(str(x.value) for x in list(at.markdown) + list(at.caption))


