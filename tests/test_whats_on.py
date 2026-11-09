"""0.46.1 'what is on' and a steadier assistant (data/whats_on.py, assistant.py): one read-only list of what is coming
up (records, festivals, Google calendar and a holiday calendar), a query that fails on a wrong column is repaired once,
and a failed lookup never says anything was changed."""
import datetime as D
import json


from conftest import run

ADULT = {"name": "Alex", "role": "adult"}


def say(reply, actions=None):
    return json.dumps({"reply": reply, "actions": actions or [], "question": None})


def test_whats_on_lists_records_with_plain_lines(root):
    today = D.date.today()
    r = run(["data/whats_on.py", "--days", "30", "--no-google"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert r.stdout.startswith("Coming up from ")
    lines = [ln for ln in r.stdout.splitlines()[1:] if ln.strip()]
    assert lines and all(" - " in ln for ln in lines)
    assert any("Bill - " in ln for ln in lines)
    assert "\\" not in r.stdout and ".db" not in r.stdout and str(root) not in r.stdout
    quiet = D.date(today.year + 8, 3, 2)  # far ahead, no public holiday in early March (US rules), Mon-Thu: no demo class
    quiet += D.timedelta(days=(7 - quiet.weekday()) % 7)
    empty = run(["data/whats_on.py", "--start", quiet.isoformat(), "--days", "4", "--no-google"], root)
    assert "Nothing is on the calendar" in empty.stdout
    assert run(["data/whats_on.py", "--days", "9999", "--no-google"], root).returncode == 0, "days is capped, not an error"


def test_whats_on_adds_google_events_and_the_holiday_calendar(root, modules, monkeypatch):
    wo = modules("whats_on")
    gc = modules("google_calendar")
    monkeypatch.setattr(gc, "status", lambda: {"client": True, "signed_in": True, "enabled": True, "calendars": ["me@example.com"]})
    monkeypatch.setattr(gc, "configured_calendars", lambda: ["me@example.com"])
    monkeypatch.setattr(gc, "calendars", lambda: [
        {"id": "me@example.com", "name": "Me", "primary": True},
        {"id": "en.usa#holiday@group.v.calendar.google.com", "name": "Holidays in United States", "primary": False},
        {"id": "other@group.calendar.google.com", "name": "Other", "primary": False}])
    asked = []

    def events(days, start, cals):
        asked.append(list(cals))
        d = start + D.timedelta(days=2)
        return [{"date": d.isoformat(), "time": "15:30", "end": "16:00", "all_day": False, "calendar": cals[0], "title": "Dentist"},
                {"date": d.isoformat(), "time": "", "end": "", "all_day": True, "calendar": cals[-1], "title": "Columbus Day"}]
    monkeypatch.setattr(gc, "events", events)
    start, end, rows, note = wo.build(D.date.today(), 14, google=True)
    titles = [r[2] for r in rows]
    assert "Dentist at 15:30" in titles and "Columbus Day" in titles and note == ""
    assert asked[0] == ["me@example.com", "en.usa#holiday@group.v.calendar.google.com"], "holiday calendar included, others not"
    _, _, rows2, _ = wo.build(D.date.today(), 14, google=False)
    assert "Columbus Day" not in [r[2] for r in rows2]

    def boom(*a):
        raise RuntimeError("secret detail")
    monkeypatch.setattr(gc, "events", boom)
    _, _, rows3, note3 = wo.build(D.date.today(), 14, google=True)
    assert rows3 and "not available" in note3 and "secret detail" not in note3, "a Google failure is a short note"


def test_a_query_with_a_wrong_column_is_repaired_once(root, mock_llm, modules):
    mock_llm.use("anthropic")
    aa = modules("admin_actions")
    mock_llm.queue = [
        say("Checking.", [{"name": "sql_query", "args": {"sql": "SELECT a.name FROM accounts a WHERE a.nosuchcolumn = 1"}}]),
        json.dumps({"sql": "SELECT COUNT(*) AS n FROM members"}),
        say("There are people on record."),
    ]
    r = aa.ask(ADULT, "how many people are there?")
    text = "\n".join(r["lines"])
    assert r["ok"] and "There are people on record." in text and "couldn't" not in text and "nosuchcolumn" not in text
    log = (root / "logs" / "assistant.log").read_text(encoding="utf-8")
    assert "repaired query" in log
    mock_llm.queue = []


def test_a_failed_lookup_does_not_claim_a_change(root, mock_llm, modules):
    mock_llm.use("anthropic")
    aa = modules("admin_actions")
    bad = {"name": "sql_query", "args": {"sql": "SELECT nosuchcolumn FROM accounts"}}
    mock_llm.queue = [say("Looking.", [bad]), json.dumps({"sql": "SELECT nosuchcolumn FROM accounts"})]
    r = aa.ask(ADULT, "what is the balance?")
    text = "\n".join(r["lines"])
    assert "look that up" in text and "nothing was changed" not in text.lower()
    mock_llm.queue = []


def test_assistant_uses_whats_on_for_next_week(root, mock_llm, modules):
    mock_llm.use("anthropic")
    aa = modules("admin_actions")
    mock_llm.queue = [say("Let me look.", [{"name": "whats_on", "args": {"days": 7}}]),
                      say("You have a bill and a school form coming up.")]
    r = aa.ask(ADULT, "any events for next week?")
    text = "\n".join(r["lines"])
    assert r["ok"] and "bill and a school form" in text and "whats_on" not in text
    sent = " ".join(json.dumps(x) for x in mock_llm.seen)
    assert "Coming up from" in sent, "the model was given the list to summarise"
    mock_llm.queue = []
