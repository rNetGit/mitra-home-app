"""Family events at a time of day (migration 061: events.start_time / end_time): the web Add form, and the event at its
time on the Calendar, the Mitra Wall's week grid and Today, Today's timeline and the .ics file."""
import datetime as D

import pytest
from fastapi.testclient import TestClient

from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}
MON = D.date(2027, 3, 1)           # a Monday
WED = MON + D.timedelta(days=2)


@pytest.fixture(scope="module")
def dinner(root, modules):
    ea = modules("edit_actions")
    con = db(root)
    con.execute("DELETE FROM events")
    con.commit()
    con.close()
    assert ea.event_add(ADULT, "Family dinner", WED.isoformat(), start_time="20:00", end_time="20:30")[0]
    assert ea.event_add(ADULT, "Game night", (WED + D.timedelta(days=1)).isoformat(), start_time="19:00")[0]
    assert ea.event_add(ADULT, "Tax day", "2027-04-15")[0]
    return WED


def test_helpers(modules):
    v, dates = modules("validators"), modules("dates")
    assert [v.clock_time(x) for x in ("20:00", "8pm", "8:30 PM", "9", "12 am", "12:15 p.m.")] == \
        ["20:00", "20:00", "20:30", "09:00", "00:00", "12:15"]
    for bad in ("24:00", "13pm", "8:75", "tonight", ""):
        with pytest.raises(ValueError):
            v.clock_time(bad)
    assert dates.time_span("20:00", "20:30") == "8:00–8:30 PM"
    assert dates.time_span("11:30", "12:30") == "11:30 AM–12:30 PM"
    assert dates.time_span("09:05") == "9:05 AM" and dates.time_span(None) == ""


def test_migration_adds_the_columns_and_checks_their_shape(root, dinner):
    cols = {r[1] for r in db(root).execute("PRAGMA table_info(events)")}
    assert {"start_time", "end_time"} <= cols
    con = db(root)
    try:
        with pytest.raises(Exception):
            con.execute("INSERT INTO events(name, event_date, start_time) VALUES ('x', '2027-01-01', '8pm')")
    finally:
        con.close()


def test_the_calendar_shows_the_time(dinner, modules):
    ev = modules("calendar_data").load_events(2027, 2027)
    assert ("Event", "Family dinner 8:00–8:30 PM") in ev[WED]
    assert ("Event", "Game night 7:00 PM") in ev[WED + D.timedelta(days=1)]
    assert ("Event", "Tax day") in ev[D.date(2027, 4, 15)], "an event without a time stays all day"


def test_the_wall_puts_it_on_the_grid_in_the_house_colour(dinner, modules, root):
    WD, W = modules("wall_data"), modules("wall")
    con = W._con()
    try:
        v = WD.week(con, MON, WED)
        wed = next(d for d in v["days"] if d["date"] == WED)
        ev = next(e for e in wed["events"] if e["title"] == "Family dinner")
        assert ev["time"] == "8 PM – 8:30 PM" and ev["kind"] == "Event" and ev["cls"] == "ch" and ev["who"] == []
        assert ev["r1"] - ev["r0"] == 2, "half an hour = two 15-minute rows"
        assert not any(a["title"] == "Family dinner" for a in wed["allday"])
        assert v["hours"][-1]["label"] == "8 PM", "the grid widens to fit 8:30 PM"
        thu = next(d for d in v["days"] if d["date"] == WED + D.timedelta(days=1))
        game = next(e for e in thu["events"] if e["title"] == "Game night")
        assert game["time"] == "7 PM – 8 PM", "no end = an hour"
        line = WD.today(con, D.datetime.combine(WED, D.time(19, 0)))["line"]
        assert [(x["title"], x["time"], x["end"]) for x in line if x["title"] == "Family dinner"] == [("Family dinner", "8 PM", "8:30 PM")]
    finally:
        con.close()


def test_today_has_it_on_the_timeline_at_its_time(dinner, modules, root):
    ai, td = modules("action_items"), modules("today_data")
    con = db(root)
    try:
        items = [i for i in ai.collect_items(con, WED, 3) if i["kind"] == "Event"]
    finally:
        con.close()
    row = next(i for i in items if i["title"] == "Family dinner")
    assert row["detail"] == "20:00-20:30" and row["at"] == ("20:00", "20:30")
    dec = td.decorate([row], WED, ["Alex", "Sam"])[0]
    assert (dec["time"], dec["t24"]) == ("8:00 PM", "20:00")
    on_today = td.assemble([row], [], WED, ["Alex", "Sam"])
    assert "8:00 PM" in str(on_today)


def test_the_ics_file_has_it_at_its_time(dinner, modules, root):
    ai, ics = modules("action_items"), modules("export_ics")
    con = db(root)
    try:
        items = [i for i in ai.collect_items(con, WED, 60) if i["kind"] == "Event"]
    finally:
        con.close()
    text = ics.build(items, WED)
    dinner_ev = text.split("SUMMARY:Event: Family dinner")[0].rsplit("BEGIN:VEVENT", 1)[1]
    assert "DTSTART:20270303T200000" in dinner_ev and "DTEND:20270303T203000" in dinner_ev
    game = text.split("SUMMARY:Event: Game night")[0].rsplit("BEGIN:VEVENT", 1)[1]
    assert "DTSTART:20270304T190000" in game and "DURATION:PT1H" in game
    tax = text.split("SUMMARY:Event: Tax day")[0].rsplit("BEGIN:VEVENT", 1)[1]
    assert "DTSTART;VALUE=DATE:20270415" in tax, "all day as before"
    assert "TRIGGER:-PT1H" in text and "TRIGGER:-P1D" in text


def test_the_records_add_form_adds_one(root, modules):
    re_, rd = modules("records_edit"), modules("records_data")
    assert re_.add_tables(("people", "dates")) == ("calendar_days", "events")
    ok, msg = re_.add(ADULT, ("people", "dates"), {"table": "events", "name": "Pizza night", "date": "2027-05-07",
                                                    "start_time": "18:30", "end_time": "19:30", "repeats": "once"})
    assert ok and "6:30–7:30 PM" in msg, msg
    ok, msg = re_.add(ADULT, ("people", "dates"), {"table": "events", "name": "Our anniversary", "date": "2027-05-08",
                                                    "start_time": "", "end_time": "", "repeats": "yearly"})
    assert ok, msg
    assert q(root, "SELECT name, start_time, end_time, recurs_yearly FROM events WHERE name IN ('Pizza night', 'Our anniversary') "
                   "ORDER BY name") == [("Our anniversary", None, None, 1), ("Pizza night", "18:30", "19:30", 0)]
    ok, msg = re_.add(ADULT, ("people", "dates"), {"table": "events", "name": "Bad", "date": "2027-05-09",
                                                    "start_time": "20:00", "end_time": "19:00", "repeats": "once"})
    assert not ok and "after it starts" in msg
    block = next(b for b in rd.blocks("people", "dates", D.date(2027, 1, 1)) if b["heading"].startswith("Family events"))
    assert any("18:30-19:30" in r["cells"] for r in block["rows"])


def test_the_dates_page_offers_the_form(root, modules):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")}]
    config.write_json(root / "config" / "family.json", fam)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/records", params={"domain": "people", "section": "dates"}).text
    assert 'id="add-events"' in page and "Add a family event or a yearly date" in page and 'name="start_time"' in page
    assert "#add-events" in c.get("/add").text, "the Family event tile"
