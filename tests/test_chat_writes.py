"""Changes from Chat through edit_actions (phase 3): appointment_add, bill_add and event_add are validated, adults only,
logged in logs/edits.log, and "a doctor's appointment with a bill" becomes two changes on one confirm card that run
exactly as shown after the yes."""
import json

import pytest

from conftest import KEYS, q, run

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


@pytest.fixture(scope="module")
def ea(root, modules):
    return modules("edit_actions")


def test_iso_datetime(modules):
    v = modules("validators")
    assert v.iso_datetime("2026-12-10 9:30") == "2026-12-10 09:30" == v.iso_datetime("2026-12-10T09:30")
    for bad in ("2026-12-10", "2026-12-10 25:00", "2026-13-01 09:00", "tomorrow 9am", "2026-12-10 09:30:00"):
        with pytest.raises(ValueError):
            v.iso_datetime(bad)


def test_appointment_add(ea, root):
    ok, msg = ea.appointment_add(ADULT, "joe", "2026-12-10 09:30")
    assert not ok and "not a family member" in msg
    ok, msg = ea.appointment_add(ADULT, "sam", "2026-12-10 09:30", provider="Dr Lee", purpose="checkup")
    assert ok, msg
    assert q(root, "select person, provider, purpose, appt_datetime from appointments where provider='Dr Lee'") == \
        [("Sam", "Dr Lee", "checkup", "2026-12-10 09:30")]
    assert not ea.appointment_add(ADULT, "Sam", "2026-12-10 09:30")[0], "the same time twice is refused"
    assert not ea.appointment_add(KID, "Sam", "2026-12-11 09:30")[0]
    assert not ea.appointment_add(ADULT, "", "2026-12-11 09:30")[0]
    assert not ea.appointment_add(ADULT, "Sam", "2026-12-11")[0]
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "\tAlex\tappointment_add\tid=" in log and "Dr Lee" not in log


def test_bill_add(ea, root):
    ok, msg = ea.bill_add(ADULT, "Dr Lee visit, Sam", "2026-12-10")
    assert ok and "amount not known yet" in msg, msg
    assert q(root, "select vendor, frequency, amount, status from bills where name='Dr Lee visit, Sam'") == [(None, "once", None, "due")]
    assert not ea.bill_add(ADULT, "dr lee visit, sam", "2026-12-10")[0], "same name and due date is refused"
    ok, msg = ea.bill_add(ADULT, "Water", "2026-11-05", amount="$41.20", vendor="Northwind Water", frequency="monthly")
    assert ok and q(root, "select amount, vendor, frequency from bills where name='Water'") == [(41.2, "Northwind Water", "monthly")]
    assert not ea.bill_add(KID, "Toys", "2026-11-05")[0]
    assert not ea.bill_add(ADULT, "Water", "next week")[0] and not ea.bill_add(ADULT, "Water", "2026-11-06", frequency="daily")[0]
    assert not ea.bill_add(ADULT, "Acct 1234567890123456", "2026-11-06")[0], "a full account number is refused"


def test_event_add(ea, root):
    assert ea.event_add(ADULT, "Wedding anniversary", "2027-06-14")[0]
    assert q(root, "select recurs_yearly from events where name='Wedding anniversary'") == [(1,)]
    assert not ea.event_add(ADULT, "wedding anniversary", "2027-06-14")[0]
    assert ea.event_add(ADULT, "Passport renewal", "2029-03-01", yearly=False)[0]
    assert q(root, "select recurs_yearly from events where name='Passport renewal'") == [(0,)]
    assert not ea.event_add(KID, "Party", "2027-06-14")[0]


def test_event_add_with_a_time(ea, root):
    ok, msg = ea.event_add(ADULT, "Family dinner", "2027-06-15", start_time="8pm", end_time="20:30")
    assert ok and msg == "Added Family dinner on 2027-06-15, 8:00–8:30 PM.", msg
    assert q(root, "select start_time, end_time, recurs_yearly from events where name='Family dinner'") == [("20:00", "20:30", 0)],         "a time makes it a one-off unless yearly is asked for"
    assert ea.event_add(ADULT, "Family dinner", "2027-06-15", start_time="18:00")[0], "the same name at another time is fine"
    assert not ea.event_add(ADULT, "family dinner", "2027-06-15", start_time="20:00")[0], "same name, day and time twice"
    assert ea.event_add(ADULT, "Movie night", "2027-06-16 19:30")[0], "a time inside the date is the start time"
    assert q(root, "select event_date, start_time, end_time from events where name='Movie night'") == [("2027-06-16", "19:30", None)]
    assert ea.event_add(ADULT, "Anniversary dinner", "2027-06-17", yearly=True, start_time="19:00")[0]
    assert q(root, "select recurs_yearly from events where name='Anniversary dinner'") == [(1,)]
    for bad in ({"start_time": "20:00", "end_time": "19:00"}, {"end_time": "21:00"}, {"start_time": "25:00"},
                {"start_time": "dinner"}):
        ok, msg = ea.event_add(ADULT, "Bad time", "2027-06-18", **bad)
        assert not ok and ("starts" in msg or "ends" in msg), (bad, msg)
    assert q(root, "select count(*) from events where name='Bad time'") == [(0,)]


# ---- through the assistant

def say(reply, actions=None, question=None):
    return json.dumps({"reply": reply, "actions": actions or [], "question": question})


@pytest.fixture(scope="module")
def ask(root, mock_llm):
    def go(*replies, yes=True, text="request"):
        mock_llm.use("anthropic")
        mock_llm.seen = []
        mock_llm.queue = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        return run(["data/assistant.py"] + (["--yes"] if yes else []) + [text], root, env=KEYS)
    yield go
    mock_llm.queue = []


APPT = {"name": "appointment_add", "args": {"who": "Sam", "when": "2026-12-10 10:15", "provider": "Dr Patel", "purpose": "doctor"}}
BILL = {"name": "bill_add", "args": {"name": "Dr Patel visit, Sam", "due": "2026-12-10", "vendor": "Dr Patel"}}


def test_an_appointment_with_a_bill_is_two_changes_on_one_card(root, ask, mock_llm):
    r = ask(say("I'll add both.", [APPT, BILL]), yes=False, text="Dr appointment with bill for Sam, Dec 10 at 9:30 am")
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    assert "Before I change anything, please check:" in r.stdout
    assert "- Add an appointment for Sam on December 10 at 10:15 am with Dr Patel (doctor)" in r.stdout
    assert "- Add the bill Dr Patel visit, Sam from Dr Patel, amount not known yet, due December 10" in r.stdout
    assert "Nothing was changed" in r.stdout
    assert q(root, "select count(*) from appointments where provider='Dr Patel'")[0][0] == 0
    sent = json.dumps(mock_llm.seen[0]["body"])
    assert "appointment_add(who, when, provider?, purpose?, followup?) [CHANGES DATA]" in sent and "bill_add(" in sent and "event_add(" in sent
    assert "appointment_add and bill_add together" in sent


def test_after_the_yes_both_run_through_edit_actions(root, ask):
    r = ask(say("I'll add both.", [APPT, BILL]), text="Dr appointment with bill for Sam, Dec 10 at 9:30 am")
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    assert "Done: Add an appointment for Sam on December 10 at 10:15 am with Dr Patel (doctor)." in r.stdout
    assert "Done: Add the bill Dr Patel visit, Sam" in r.stdout
    assert q(root, "select person, appt_datetime from appointments where provider='Dr Patel'") == [("Sam", "2026-12-10 10:15")]
    assert q(root, "select amount, due_date, status from bills where name='Dr Patel visit, Sam'") == [(None, "2026-12-10", "due")]
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "\tthis PC\tappointment_add\t" in log and "\tthis PC\tbill_add\t" in log, "the terminal's changes are logged like a form's"
    r = ask(say("Again.", [APPT]), text="again")
    assert "already recorded" in r.stdout and "FAILED" not in r.stdout
    assert q(root, "select count(*) from appointments where provider='Dr Patel'")[0][0] == 1


DINNER = {"name": "event_add", "args": {"name": "Family dinner tonight", "date": "2026-11-20 20:00", "ends": "20:30"}}


def test_a_family_event_with_a_time_shows_the_time_on_the_card_and_keeps_it(root, ask, modules):
    voice = modules("assistant_voice")
    card = f"- Add Family dinner tonight on {voice.nice_date('2026-11-20')}, 8:00–8:30 PM (once)"
    r = ask(say("I'll add it.", [DINNER]), yes=False, text="family dinner Nov 20 8:00 to 8:30 PM")
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    assert card in r.stdout, r.stdout
    assert q(root, "select count(*) from events where name='Family dinner tonight'") == [(0,)]
    r = ask(say("I'll add it.", [DINNER]), text="family dinner Nov 20 8:00 to 8:30 PM")
    assert "FAILED" not in r.stdout and "couldn't" not in r.stdout, r.stdout
    assert q(root, "select event_date, start_time, end_time, recurs_yearly from events where name='Family dinner tonight'") ==         [("2026-11-20", "20:00", "20:30", 0)]


def test_event_times_are_checked_before_the_card(modules):
    A = modules("assistant")
    clean, err = A.validate_action({"name": "event_add", "args": {"name": "Party", "date": "2026-11-21", "starts": "7 pm",
                                                                  "ends": "9:30 PM"}})
    assert err is None and clean == {"name": "Party", "date": "2026-11-21", "starts": "19:00", "ends": "21:30"}
    clean, err = A.validate_action({"name": "event_add", "args": {"name": "Party", "date": "2026-11-21T19:00"}})
    assert err is None and (clean["date"], clean["starts"]) == ("2026-11-21", "19:00")
    for args, expect in (({"date": "2026-11-21", "starts": "19:00", "ends": "18:00"}, "after starts"),
                         ({"date": "2026-11-21", "ends": "18:00"}, "after starts"),
                         ({"date": "tonight"}, "YYYY-MM-DD"), ({"date": "2026-11-21", "starts": "late"}, "time must")):
        clean, err = A.validate_action({"name": "event_add", "args": {"name": "Party", **args}})
        assert clean is None and expect in err, (args, err)
    assert "event_add(name, date, starts?, ends?, yearly?)" in A.catalog_text()


@pytest.mark.parametrize("action,expect", [
    ({"name": "appointment_add", "args": {"who": "Sam", "when": "2026-12-10"}}, "YYYY-MM-DD HH:MM"),
    ({"name": "appointment_add", "args": {"who": "Sam", "when": "2026-12-10 09:30", "notes": "x"}}, "unknown argument"),
    ({"name": "bill_add", "args": {"name": "Gas", "due": "2026-12-10", "amount": "-5"}}, "out of range"),
    ({"name": "bill_add", "args": {"name": "Gas", "due": "2026-12-10", "frequency": "daily"}}, "must be one of"),
    ({"name": "event_add", "args": {"name": "Party"}}, "missing 'date'"),
])
def test_bad_arguments_never_reach_edit_actions(root, ask, action, expect):
    before = q(root, "select (select count(*) from appointments), (select count(*) from bills), (select count(*) from events)")
    r = ask(say("ok", [action]), text="x")
    assert "I couldn't do one part of that" in r.stdout and expect not in r.stdout
    assert expect in (root / "logs" / "assistant.log").read_text(encoding="utf-8")
    assert q(root, "select (select count(*) from appointments), (select count(*) from bills), (select count(*) from events)") == before


def test_a_skipped_change_is_never_reported_as_done(root, ask):
    """The model sent event_add a date that does not exist and said it was added: the check skips it, so its reply never
    shows. (Until 0.124.0 a time inside the date was the example; timed events now take it.)"""
    timed = {"name": "event_add", "args": {"name": "Skipped dinner", "date": "2026-02-30", "yearly": 0}}
    r = ask(say("I've added Skipped dinner today from 8:00 to 8:30 PM.", [timed]), text="add an event today 8:00 to 8:30 pm")
    assert r.returncode == 1, "a request that did nothing is not ok: " + r.stdout + r.stderr[-300:]
    assert "I couldn't do one part of that" in r.stdout and "Nothing was added or changed." in r.stdout
    assert "I've added" not in r.stdout and "Before I change anything" not in r.stdout
    assert q(root, "select count(*) from events where name='Skipped dinner'")[0][0] == 0
    # one good change next to the bad one: the card still shows the good one, nothing claims the bad one
    r = ask(say("I'll add both.", [timed, {"name": "event_add", "args": {"name": "Book fair", "date": "2026-11-02", "yearly": 0}}]),
            yes=False, text="two dates")
    assert "Before I change anything, please check:" in r.stdout and "Book fair" in r.stdout
    assert "Nothing was added or changed." not in r.stdout


def test_the_app_runs_chat_changes_as_the_signed_in_adult_only(root, modules):
    A = modules("assistant")
    res = A.apply([("event_add", {"name": "Tax day", "date": "2027-04-15"})], user={"name": "Alex", "role": "adult"})
    assert res["ok"] and "Done: Add Tax day on April 15, 2027 (every year)." in res["lines"]
    assert "\tAlex\tevent_add\t" in (root / "logs" / "edits.log").read_text(encoding="utf-8")
    res = A.apply([("event_add", {"name": "Party", "date": "2027-04-16"})], user={"name": "Sam", "role": "limited"})
    assert not res["ok"] and q(root, "select count(*) from events where name='Party'")[0][0] == 0
    assert {"ref": None, "section": "people/dates", "label": "Holidays and dates"} in A.apply(
        [("event_add", {"name": "Graduation", "date": "2027-06-01", "yearly": 0})], user={"name": "Alex", "role": "adult"})["refs"]
