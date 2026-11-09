"""Family events (0.110), the parts that use the family's AI: their traditions (traditions.py, kept only in
config/family.json), the yearly look-up of their dates (only the tradition, year and country are sent; the answer is
checked and waits in the Inbox), school calendar papers read into proposed days off, and the Inbox item (proposals
source 'days') that puts them on the calendar. Mock provider, no network."""
import datetime as D
import json
import re

import pytest
from starlette.testclient import TestClient

from conftest import KEYS, q, read_family, run

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}
DIWALI = {"days": [{"date": "2027-10-29", "name": "Diwali", "kind": "holiday"},
                   {"date": "2027-03-22", "name": "Holi", "kind": "festival"},
                   {"date": "2027-04-07", "end": "2027-04-15", "name": "Navratri"},
                   {"date": "2026-11-08", "name": "Wrong year"},
                   {"date": "2027-02-30", "name": "Not a date"},
                   {"date": "2027-05-01", "name": "See https://example.com"},
                   {"date": "2027-06-01", "name": ""}]}


@pytest.fixture(scope="module")
def T(root, modules, mock_llm):
    return modules("traditions")


def test_traditions_are_checked_and_kept_only_in_family_json(root, modules, T):
    aa = modules("admin_actions")
    assert aa.traditions_set(KID, "Hindu", True)[0] is False, "adults only"
    ok, msg = aa.traditions_set(ADULT, "Hindu (Telugu)\nChristian, Hindu (Telugu)", True)
    assert ok, msg
    assert read_family(root)["traditions"] == ["Hindu (Telugu)", "Christian"], "cleaned, no repeats"
    for bad in ("<script>", "1234 5678", "x" * 41, "https://evil.example"):
        assert aa.traditions_set(ADULT, bad, True)[0] is False, bad
    assert aa.traditions_set(ADULT, "\n".join(f"T{i}" for i in "abcdefg"), True)[0] is False, "at most six"
    assert T.get() == {"traditions": ["Hindu (Telugu)", "Christian"], "lookup": True}
    audit = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "traditions_set" in audit and "Telugu" not in audit, "the audit log counts, never names the tradition"
    s = modules("sync_data")
    assert not any("tradition" in str(v) for v in s.SOURCES.values())


def test_the_look_up_sends_only_tradition_year_and_country(root, T, mock_llm):
    mock_llm.use("anthropic")
    mock_llm.set(json.dumps(DIWALI))
    n, msg = T.fetch(2027, "Hindu (Telugu)")
    assert n == 3, msg
    sent = json.dumps(mock_llm.seen[-1]["body"])
    assert "Hindu (Telugu)" in sent and "2027" in sent and "Country: US" in sent
    for private in ("Alex", "Sam", "Biscuit", "TX"):
        assert private not in sent, f"{private} must not leave the PC"
    rows = q(root, "SELECT day, end_day, kind, name, status, source, label FROM calendar_days "
                   "WHERE source='tradition' ORDER BY day")
    assert rows == [("2027-03-22", None, "festival", "Holi", "proposed", "tradition", "Hindu (Telugu)"),
                    ("2027-04-07", "2027-04-15", "festival", "Navratri", "proposed", "tradition", "Hindu (Telugu)"),
                    ("2027-10-29", None, "holiday", "Diwali", "proposed", "tradition", "Hindu (Telugu)")]
    assert T.fetch(2027, "Hindu (Telugu)")[0] == 0, "asking again adds nothing twice"
    cd = __import__("calendar_days")
    assert not any(r["name"] == "Diwali" for r in cd.between(D.date(2027, 10, 1), D.date(2027, 10, 31))), \
        "nothing shows until an adult accepts"


def test_the_yearly_step_asks_once_and_next_year_from_october(root, T, mock_llm):
    mock_llm.use("anthropic")
    con = __import__("db").connect(root / "data" / "family.db")
    try:
        assert T.due(D.date(2027, 9, 30), con) == [("Christian", 2027)], "Hindu 2027 was asked already"
        assert ("Christian", 2028) in T.due(D.date(2027, 10, 1), con) and ("Hindu (Telugu)", 2028) in T.due(D.date(2027, 10, 1), con)
    finally:
        con.close()
    mock_llm.set(json.dumps({"days": []}))
    out = T.auto(D.date(2027, 9, 30))
    assert out and "No new dates for Christian 2027" in out[0]
    con = __import__("db").connect(root / "data" / "family.db")
    try:
        assert T.due(D.date(2027, 9, 30), con) == [], "an empty answer is remembered: not asked every morning"
    finally:
        con.close()


def test_without_an_ai_nothing_is_asked(root, T, mock_llm):
    from conftest import set_ai
    set_ai(root, "none")
    try:
        assert "no AI provider" in T.ai_ready()
        n, msg = T.fetch(2029, "Christian")
        assert n == -1 and "Not asked" in msg
    finally:
        mock_llm.use("anthropic")


def test_the_inbox_card_adds_a_traditions_dates(root, modules):
    pr, ea = modules("proposals"), modules("edit_actions")
    pr.sync()
    items = [it for it in pr.items(__import__("db").connect(root / "data" / "family.db")) if it["source"] == "days"]
    hindu = [it for it in items if "Hindu (Telugu)" in it["summary"]]
    assert len(hindu) == 1 and hindu[0]["summary"].startswith("3 dates for Hindu (Telugu), 2027")
    assert "Lunar and regional dates can differ" in hindu[0]["detail"] and "Mar 22: Holi" in hindu[0]["detail"]
    assert list(hindu[0]["options"])[0] == "accept"
    assert pr.decide(KID, hindu[0]["id"], "accept")[0] is False
    ok, msg = pr.decide(ADULT, hindu[0]["id"], "accept")
    assert ok and "Added 3 days" in msg, msg
    assert q(root, "SELECT COUNT(*) FROM calendar_days WHERE label='Hindu (Telugu)' AND status='active'") == [(3,)]
    cd = modules("calendar_days")
    assert any(r["name"] == "Diwali" and r["kind"] == "Holiday" for r in cd.between(D.date(2027, 10, 1), D.date(2027, 10, 31)))
    pr.sync()
    assert pr.get(__import__("db").connect(root / "data" / "family.db"), hindu[0]["id"])["status"] == "done"
    ids = [r[0] for r in q(root, "SELECT id FROM calendar_days WHERE label='Hindu (Telugu)'")]
    assert ea.calendar_days_decide(ADULT, ids, True) == (True, "Those days were already decided.")
    assert ea.calendar_days_decide(ADULT, ["x"], True)[0] is False


def test_chat_bots_never_list_or_decide_the_days_card(root, modules):
    cc = modules("chat_core")
    assert "days" in cc.PC_ONLY
    con = __import__("db").connect(root / "data" / "family.db")
    try:
        con.execute("INSERT OR IGNORE INTO calendar_days(day, kind, name, source, label, status) "
                    "VALUES ('2027-12-25', 'holiday', 'Christmas', 'tradition', 'Christian', 'proposed')")
        con.commit()
        modules("proposals").sync(con)
        text = cc._inbox(con, {"role": "adult", "member": "Alex"}, True)
        pid = [it["id"] for it in modules("proposals").items(con) if it["source"] == "days"][0]
        said = cc._decide(con, {"role": "adult", "member": "Alex"}, [str(pid)], True)
    finally:
        con.close()
    assert "Christian" not in text and "tradition" not in text.lower()
    assert "family PC" in said


def test_a_school_calendar_paper_becomes_proposed_days_off(root, mock_llm):
    details = {"school": "Zz Unified School District", "school_year": "2026-27", "confidence": 0.93,
               "days": [{"date": "2026-11-23", "end": "2026-11-27", "name": "Thanksgiving break", "kind": "closure"},
                        {"date": "2026-10-09", "name": "Staff development", "kind": "closure"},
                        {"date": "2026-12-18", "name": "Early release", "kind": "early"},
                        {"date": "2026-12-21", "end": "2027-03-30", "name": "Too long to be a break"},
                        {"date": "no date", "name": "Broken"}]}
    classify = {"doc_type": "school_calendar", "vendor": "Zz Unified School District", "doc_date": None, "amount": None,
                "due_date": None, "account_last4": None, "period": None, "confidence": 0.95}
    mock_llm.use("openai")
    mock_llm.set(json.dumps(details))
    mock_llm.queue[:] = [json.dumps(classify), json.dumps(details)]
    (root / "inbox" / "district_calendar.txt").write_text("Zz Unified School District 2026-27 calendar ...", encoding="utf-8")
    r = run(["data/ai_intake.py"], root, env=KEYS)
    mock_llm.queue[:] = []
    assert r.returncode == 0, r.stderr[-500:]
    rows = q(root, "SELECT day, end_day, kind, name, source, label, status, document_id IS NOT NULL FROM calendar_days "
                   "WHERE source='school' ORDER BY day")
    assert rows == [("2026-10-09", None, "closure", "Staff development", "school", "Zz Unified School District", "proposed", 1),
                    ("2026-11-23", "2026-11-27", "closure", "Thanksgiving break", "school", "Zz Unified School District", "proposed", 1),
                    ("2026-12-18", None, "early", "Early release", "school", "Zz Unified School District", "proposed", 1),
                    ("2026-12-21", None, "closure", "Too long to be a break", "school", "Zz Unified School District", "proposed", 1)]
    filed = q(root, "SELECT filed_path FROM documents WHERE doc_type='school_calendar'")
    assert filed and re.search(r"[/\\]school[/\\]", filed[0][0]), filed
    assert not (root / "inbox" / "district_calendar.txt").exists()


def test_the_settings_card_saves_traditions(root, modules):
    auth, config = modules("auth"), modules("config")
    app_mod, sessions = modules("webapp.app"), modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")}]
    config.write_json(root / "config" / "family.json", fam)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/settings?group=household").text
    assert "Traditions and holidays" in page and "US federal holidays" in page and "Christian" in page
    tok = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    r = c.post("/settings/traditions", data={"names": "Jewish", "lookup": "1"}, headers={"X-CSRF-Token": tok, "HX-Request": "true"})
    assert r.status_code in (200, 204, 303), r.text[:300]
    assert read_family(root)["traditions"] == ["Jewish"]
    sessions.clear()
