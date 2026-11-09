"""Vaccination history (migration 065, data/health_records.py): a shot is a record; a next due date keeps one open
life_items reminder so Today, the Calendar and the digest need no new code; marking the reminder done writes the next row."""
import datetime as dt

import pytest
from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}
CHILD = {"name": "Sam", "role": "child"}
TODAY = dt.date.today()


@pytest.fixture(autouse=True)
def _clean(root):
    """The test copy is shared by the module: each test starts with no shots and no vaccine reminders."""
    with db(root) as con:
        con.execute("DELETE FROM vaccinations")
        con.execute("DELETE FROM life_items WHERE domain='vaccine' OR title IN ('Dentist')")


def _reminders(root, who):
    return q(root, f"SELECT title, due_date, status FROM life_items WHERE domain='vaccine' AND member='{who}' ORDER BY id")


def test_a_shot_with_a_next_date_keeps_one_reminder(root, modules):
    ea = modules("edit_actions")
    first = (TODAY - dt.timedelta(days=30)).isoformat()
    nxt = (TODAY + dt.timedelta(days=200)).isoformat()
    ok, msg = ea.vaccination_add(ADULT, "Sam", "Flu", first, nxt, "City clinic")
    assert ok, msg
    assert q(root, "SELECT member, vaccine, given_on, next_due, provider FROM vaccinations") == [
        ("Sam", "Flu", first, nxt, "City clinic")]
    assert _reminders(root, "Sam") == [("Flu due", nxt, "open")]
    # a newer shot of the same vaccine moves the reminder, it does not add a second one
    later = (TODAY + dt.timedelta(days=400)).isoformat()
    ok, msg = ea.vaccination_add(ADULT, "Sam", "flu", (TODAY - dt.timedelta(days=1)).isoformat(), later)
    assert ok, msg
    assert _reminders(root, "Sam") == [("Flu due", later, "open")]


def test_the_reminder_reaches_the_alerts_that_feed_today(root, modules):
    ea, life = modules("edit_actions"), modules("life")
    soon = (TODAY + dt.timedelta(days=5)).isoformat()
    ok, msg = ea.vaccination_add(ADULT, "Biscuit", "Rabies", TODAY.isoformat(), soon)
    assert ok, msg
    with db(root) as con:
        titles = [a["title"] for a in life.alerts(con, TODAY)]
    assert "Rabies due (Biscuit)" in titles


def test_marking_the_reminder_done_writes_history_and_rolls_forward(root, modules):
    ea = modules("edit_actions")
    nxt = (TODAY + dt.timedelta(days=3)).isoformat()
    ea.vaccination_add(ADULT, "Sam", "Tdap", (TODAY - dt.timedelta(days=30)).isoformat(), nxt)
    (item_id,) = q(root, "SELECT id FROM life_items WHERE domain='vaccine' AND member='Sam'")[0]
    with db(root) as con:
        con.execute("UPDATE life_items SET recur_months=12 WHERE id=?", (item_id,))
    ok, msg = ea.life_done(ADULT, item_id, TODAY.isoformat())
    assert ok, msg
    rows = q(root, "SELECT vaccine, given_on, next_due FROM vaccinations WHERE member='Sam' ORDER BY id")
    assert rows[0][0] == "Tdap" and rows[1][0] == "Tdap" and rows[1][1] == TODAY.isoformat()
    assert rows[1][2] is not None and rows[1][2] > TODAY.isoformat()


def test_a_one_off_vaccine_reminder_done_leaves_history_and_no_reminder(root, modules):
    ea = modules("edit_actions")
    with db(root) as con:
        con.execute("INSERT INTO life_items(domain, member, title, due_date) VALUES ('vaccine','Sam','HPV due',?)",
                    (TODAY.isoformat(),))
        item_id = con.execute("SELECT id FROM life_items WHERE title='HPV due'").fetchone()[0]
    ok, msg = ea.life_done(ADULT, item_id, TODAY.isoformat())
    assert ok, msg
    assert q(root, "SELECT vaccine, next_due, life_item_id FROM vaccinations WHERE member='Sam'") == [("HPV", None, None)]


def test_household_items_and_other_domains_write_no_history(root, modules):
    ea = modules("edit_actions")
    with db(root) as con:
        con.execute("INSERT INTO life_items(domain, member, title, due_date) VALUES ('vaccine', NULL, 'Flu clinic day', ?)", (TODAY.isoformat(),))
        con.execute("INSERT INTO life_items(domain, member, title, due_date) VALUES ('medical','Sam','Dentist', ?)", (TODAY.isoformat(),))
        ids = [r[0] for r in con.execute("SELECT id FROM life_items WHERE title IN ('Flu clinic day','Dentist')")]
    for i in ids:
        assert ea.life_done(ADULT, i, TODAY.isoformat())[0]
    assert q(root, "SELECT COUNT(*) FROM vaccinations") == [(0,)]


def test_checks_and_roles(root, modules):
    ea = modules("edit_actions")
    day = TODAY.isoformat()
    assert not ea.vaccination_add(CHILD, "Sam", "Flu", day)[0]
    assert not ea.vaccination_add(ADULT, "Nobody", "Flu", day)[0]
    assert not ea.vaccination_add(ADULT, "", "Flu", day)[0]
    assert not ea.vaccination_add(ADULT, "Sam", "", day)[0]
    assert not ea.vaccination_add(ADULT, "Sam", "Flu", "not a date")[0]
    assert not ea.vaccination_add(ADULT, "Sam", "Flu", day, day)[0], "next due must be after the day given"
    assert ea.vaccination_add(ADULT, "Sam", "Flu", day)[0]
    assert not ea.vaccination_add(ADULT, "Sam", "FLU", day)[0], "the same shot twice"


def test_removing_a_record_closes_its_reminder_unless_a_later_shot_keeps_it(root, modules):
    ea = modules("edit_actions")
    nxt = (TODAY + dt.timedelta(days=100)).isoformat()
    ea.vaccination_add(ADULT, "Sam", "Flu", TODAY.isoformat(), nxt)
    (rid,) = q(root, "SELECT id FROM vaccinations")[0]
    assert not ea.vaccination_drop(CHILD, rid)[0]
    ok, msg = ea.vaccination_drop(ADULT, rid)
    assert ok, msg
    assert q(root, "SELECT status FROM vaccinations") == [("dropped",)]
    assert _reminders(root, "Sam") == [("Flu due", nxt, "dropped")]
    assert not ea.vaccination_drop(ADULT, rid)[0], "already removed"


def test_records_shows_adds_and_removes_vaccinations(root, modules):
    re_ = modules("records_edit")
    ok, msg = re_.add(ADULT, ("people", "health"), {"table": "vaccinations", "who": "Sam", "vaccine": "MMR",
                                                   "given": TODAY.isoformat(), "next_due": "", "provider": "", "notes": ""})
    assert ok, msg
    (rid,) = q(root, "SELECT id FROM vaccinations")[0]
    assert re_.values("vaccinations", rid)["vaccine"] == "MMR"
    assert "vaccinations" in [a["table"] for a in re_.adds(("people", "health"))]
    ok, msg, _ = re_.edit(ADULT, "vaccinations", "drop", rid, {})
    assert not ok and "Tick" in msg
    ok, msg, gone = re_.edit(ADULT, "vaccinations", "drop", rid, {"sure": "1"})
    assert ok and gone, msg


def test_an_older_shot_is_history_only_and_leaves_the_current_reminder(root, modules):
    """audit follow-up (Mac review of #102): typing in an old vaccine card must not close or move today's reminder"""
    ea = modules("edit_actions")
    nxt = (TODAY + dt.timedelta(days=200)).isoformat()
    assert ea.vaccination_add(ADULT, "Sam", "Flu", TODAY.isoformat(), nxt)[0]
    old1 = (TODAY - dt.timedelta(days=2000)).isoformat()
    assert ea.vaccination_add(ADULT, "Sam", "Flu", old1)[0], "older shot, no next date"
    assert _reminders(root, "Sam") == [("Flu due", nxt, "open")], "the open reminder stays"
    old2 = (TODAY - dt.timedelta(days=2500)).isoformat()
    old2_due = (TODAY - dt.timedelta(days=2300)).isoformat()
    assert ea.vaccination_add(ADULT, "Sam", "Flu", old2, old2_due)[0], "older shot with a next date long past"
    assert _reminders(root, "Sam") == [("Flu due", nxt, "open")], "no overdue reminder is made"
    assert q(root, "SELECT given_on, life_item_id IS NULL FROM vaccinations ORDER BY given_on") == [
        (old2, 1), (old1, 1), (TODAY.isoformat(), 0)], "only the newest shot owns the reminder"


def test_the_first_record_of_a_vaccine_follows_the_normal_rule(root, modules):
    """the first shot on file is the newest there is, so its next date makes the reminder, even when that date has passed"""
    ea = modules("edit_actions")
    due = (TODAY - dt.timedelta(days=100)).isoformat()
    assert ea.vaccination_add(ADULT, "Sam", "MMR", (TODAY - dt.timedelta(days=900)).isoformat(), due)[0]
    assert _reminders(root, "Sam") == [("MMR due", due, "open")]


def test_removing_the_older_record_keeps_the_reminder_the_newer_one_owns(root, modules):
    ea = modules("edit_actions")
    a = (TODAY - dt.timedelta(days=60)).isoformat()
    b = (TODAY - dt.timedelta(days=1)).isoformat()
    nxt = (TODAY + dt.timedelta(days=300)).isoformat()
    ea.vaccination_add(ADULT, "Sam", "Flu", a, (TODAY + dt.timedelta(days=100)).isoformat())
    ea.vaccination_add(ADULT, "Sam", "Flu", b, nxt)
    (older,) = q(root, "SELECT id FROM vaccinations WHERE given_on=?", a)[0]
    (newer,) = q(root, "SELECT id FROM vaccinations WHERE given_on=?", b)[0]
    assert ea.vaccination_drop(ADULT, older)[0]
    assert _reminders(root, "Sam") == [("Flu due", nxt, "open")], "the newer shot still owns the reminder"
    assert ea.vaccination_drop(ADULT, newer)[0]
    assert _reminders(root, "Sam") == [("Flu due", nxt, "dropped")]


def test_removing_the_newer_record_hands_the_reminder_back_to_the_older_one(root, modules):
    ea = modules("edit_actions")
    a = (TODAY - dt.timedelta(days=400)).isoformat()
    b = (TODAY - dt.timedelta(days=30)).isoformat()
    a_next = (TODAY - dt.timedelta(days=35)).isoformat()
    ea.vaccination_add(ADULT, "Sam", "Flu", a, a_next)
    ea.vaccination_add(ADULT, "Sam", "Flu", b, (TODAY + dt.timedelta(days=335)).isoformat())
    (older,) = q(root, "SELECT id FROM vaccinations WHERE given_on=?", a)[0]
    (newer,) = q(root, "SELECT id FROM vaccinations WHERE given_on=?", b)[0]
    assert ea.vaccination_drop(ADULT, newer)[0]
    assert _reminders(root, "Sam") == [("Flu due", a_next, "open")], "back to the date the older shot asked for"
    assert q(root, "SELECT life_item_id IS NOT NULL FROM vaccinations WHERE id=?", older) == [(1,)]
    assert ea.vaccination_drop(ADULT, older)[0]
    assert _reminders(root, "Sam") == [("Flu due", a_next, "dropped")]


def test_removing_the_newer_record_closes_the_reminder_when_the_older_one_set_no_date(root, modules):
    ea = modules("edit_actions")
    a = (TODAY - dt.timedelta(days=400)).isoformat()
    nxt = (TODAY + dt.timedelta(days=335)).isoformat()
    ea.vaccination_add(ADULT, "Sam", "Flu", a)
    ea.vaccination_add(ADULT, "Sam", "Flu", (TODAY - dt.timedelta(days=30)).isoformat(), nxt)
    (newer,) = q(root, "SELECT id FROM vaccinations WHERE next_due IS NOT NULL")[0]
    assert ea.vaccination_drop(ADULT, newer)[0]
    assert _reminders(root, "Sam") == [("Flu due", nxt, "dropped")]


def test_purging_a_person_with_a_vaccine_reminder_works(root):
    """audit follow-up: purge deleted life_items first and the vaccinations foreign key stopped it"""
    from conftest import run
    due = (TODAY + dt.timedelta(days=300)).isoformat()
    with db(root) as con:
        con.execute("INSERT OR IGNORE INTO members(name, role) VALUES ('Jordan', 'adult')")
        item = con.execute("INSERT INTO life_items(domain, member, title, due_date) VALUES ('vaccine','Jordan','MMR due',?)",
                           (due,)).lastrowid
        con.execute("INSERT INTO vaccinations(member, vaccine, given_on, next_due, life_item_id) VALUES ('Jordan','MMR',?,?,?)",
                    (TODAY.isoformat(), due, item))
    r = run(["data/purge.py", "person", "Jordan", "--yes"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert q(root, "SELECT COUNT(*) FROM vaccinations WHERE member='Jordan'") == [(0,)]
    assert q(root, "SELECT COUNT(*) FROM life_items WHERE member='Jordan'") == [(0,)]
