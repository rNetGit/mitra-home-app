"""Events with a kind and a person (migration 072): the kind (built in or the household's own), who it is for, and
adults only reaching nobody but adults (the wall's week, the wall's copy)."""
import datetime as D

import pytest

from conftest import db

ADULT = {"name": "Alex", "role": "adult"}
DAY = D.date(2027, 3, 3)  # a Wednesday


@pytest.fixture(scope="module")
def evs(root, modules):
    ea = modules("edit_actions")
    con = db(root)
    con.execute("DELETE FROM events")
    con.commit()
    con.close()
    assert ea.event_add(ADULT, "Food drive", DAY.isoformat(), start_time="10:00", category="volunteer", who="Alex")[0]
    assert ea.event_add(ADULT, "Client call", DAY.isoformat(), start_time="14:00", category="Business",
                        adults_only=True)[0]
    assert ea.event_add(ADULT, "Picnic", DAY.isoformat(), category="Book club")[0]
    return ea


def test_columns_and_kinds(root, evs):
    rows = {r[0]: r[1:] for r in db(root).execute("SELECT name, category, member, adults_only FROM events")}
    assert rows["Food drive"] == ("Volunteer", "Alex", 0)      # spelling follows the built-in label
    assert rows["Client call"] == ("Business", None, 1)
    assert rows["Picnic"] == ("Book club", None, 0)            # a new kind of the household's own


def test_own_kind_is_remembered_and_listed(modules, evs):
    cfg = modules("config")
    assert "Book club" in (cfg.family().get("event_categories") or [])
    assert "Book club" in evs.event_categories() and "Business" in evs.event_categories()


def test_bad_input_refused(modules, evs):
    ok, msg = evs.event_add(ADULT, "X", DAY.isoformat(), who="Nobody")
    assert not ok and "not a family member" in msg
    ok, msg = evs.event_add(ADULT, "X", DAY.isoformat(), category="<b>hi</b>")
    assert not ok
    ok, msg = evs.event_add({"name": "Sam", "role": "child"}, "X", DAY.isoformat())
    assert not ok


def test_update_changes_kind_person_and_audience(root, evs):
    rid = db(root).execute("SELECT id FROM events WHERE name='Picnic'").fetchone()[0]
    assert evs.event_update(ADULT, rid, "Picnic", DAY.isoformat(), category="Family", who="Sam", adults_only=True)[0]
    assert db(root).execute("SELECT category, member, adults_only FROM events WHERE id=?", (rid,)).fetchone() == ("Family", "Sam", 1)


def test_wall_week_hides_adults_only_and_uses_the_person(root, modules, evs):
    wd = modules("wall_data")
    con = db(root)
    names = [r[0] for r in con.execute("SELECT name FROM members")]
    timed, allday, _m = wd._collect(con, DAY, DAY, names)
    titles = [i["title"] for i in timed + allday]
    assert "Food drive" in titles and "Client call" not in titles
    food = next(i for i in timed if i["title"] == "Food drive")
    assert food["who"] == ["Alex"]


def test_sync_copy_for_a_wall_and_a_phone(root, modules, evs):
    import sqlite3
    sd = modules("sync_data")
    con = db(root)
    con.row_factory = sqlite3.Row
    ids = [r[0] for r in con.execute("SELECT rowid FROM events")]
    adult = sd._fetch(con, "events", {"role": "adult", "person": "Alex", "id": 1, "scopes": "calendar"}, ids)
    wall = sd._fetch(con, "events", {"role": "wall", "id": 1, "scopes": "calendar"}, ids)
    n_adult = [v["name"] for v in adult.values() if v]
    n_wall = [v["name"] for v in wall.values() if v]
    assert "Client call" in n_adult
    assert "Client call" not in n_wall and "Food drive" in n_wall
    assert all("adults_only" not in v for v in wall.values() if v)
