"""Family events (0.110): weekly classes (activities.py, migration 048), public holidays from the country's rules
(holidays.py) and the household's own holidays, festivals and school days off (calendar_days.py, migration 049), wired
into the Brief, Today, the Calendar, What's on, Records, the child's page, phones and the .ics file."""
import datetime as D

import pytest

from conftest import db, q, run

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


# ---- parsing ----------------------------------------------------------------------------------------------------
def test_days_and_times_are_parsed_from_plain_words(modules):
    A = modules("activities")
    assert A.parse_days("Mon Wed") == "MO,WE"
    assert A.parse_days("wednesday, monday") == "MO,WE", "week order, not typing order"
    assert A.parse_days("Tuesdays and Thursdays") == "TU,TH"
    assert A.parse_days("weekdays") == "MO,TU,WE,TH,FR"
    assert A.parse_days("Sat & Sun") == "SA,SU"
    for bad in ("", "someday", "Mon Funday"):
        with pytest.raises(ValueError):
            A.parse_days(bad)
    assert A.parse_time("17:00") == "17:00" and A.parse_time("5pm") == "17:00" and A.parse_time("5:30 pm") == "17:30"
    assert A.parse_time("12am") == "00:00" and A.parse_time("12pm") == "12:00" and A.parse_time("9") == "09:00"
    for bad in ("25:00", "13pm", "noonish", "7:75"):
        with pytest.raises(ValueError):
            A.parse_time(bad)


# ---- weekly classes ---------------------------------------------------------------------------------------------
def test_adding_a_class_validates_and_logs(root, modules):
    ea = modules("edit_actions")
    ok, msg = ea.activity_add(ADULT, "Swimming", "Mon Wed", who="Sam", start_time="5pm", end_time="17:45",
                              provider="YMCA", term_start="2026-09-01", term_end="2026-12-15", school_days=True)
    assert ok, msg
    assert "Swimming, Mon Wed 17:00-17:45 at YMCA (Sam)" in msg
    row = q(root, "SELECT member, weekdays, start_time, end_time, school_days, status FROM activity_schedules "
                  "WHERE title='Swimming'")
    assert row == [("Sam", "MO,WE", "17:00", "17:45", 1, "active")]
    assert ea.activity_add(KID, "Piano", "Sat")[0] is False, "children cannot add"
    assert ea.activity_add(ADULT, "Piano", "")[0] is False, "a day is needed"
    assert ea.activity_add(ADULT, "Piano", "Sat", who="Nobody")[0] is False
    assert ea.activity_add(ADULT, "Piano", "Sat", start_time="10:00", end_time="09:00")[0] is False
    assert ea.activity_add(ADULT, "Piano", "Sat", term_start="2026-10-01", term_end="2026-09-01")[0] is False
    assert ea.activity_add(ADULT, "Card 4111111111111111", "Sat")[0] is False, "no full numbers in titles"
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "activity_add\tid=" in log and "YMCA" not in log, "ids only in the edit log"


def test_occurrences_follow_days_term_skips_and_school_closures(root, modules):
    A, ea = modules("activities"), modules("edit_actions")
    sid = q(root, "SELECT id FROM activity_schedules WHERE title='Swimming'")[0][0]
    con = db(root)
    try:
        got = [o for o in A.occurrences(con, D.date(2026, 8, 30), D.date(2026, 9, 13), who="Sam") if o["title"] == "Swimming"]
    finally:
        con.close()
    assert [o["date"] for o in got] == [D.date(2026, 9, 2), D.date(2026, 9, 7), D.date(2026, 9, 9)], \
        "Wednesday 2 Sep is the first: the term starts 1 Sep (a Tuesday)"
    assert got[0]["label"] == "Swimming 17:00-17:45 (Sam)"
    assert ea.activity_skip(ADULT, sid, "2026-09-07")[0]
    assert "already off" in ea.activity_skip(ADULT, sid, "2026-09-07")[1]
    assert ea.calendar_day_add(ADULT, "2026-09-09", "Teacher training day", "closure")[0]
    con = db(root)
    try:
        days = [o["date"] for o in A.occurrences(con, D.date(2026, 9, 1), D.date(2026, 9, 13))
                if o["title"] == "Swimming"]
        late = [o["date"] for o in A.occurrences(con, D.date(2026, 12, 1), D.date(2026, 12, 31)) if o["title"] == "Swimming"]
    finally:
        con.close()
    assert days == [D.date(2026, 9, 2)], "skipped lesson and school closure both left out"
    assert late and max(late) <= D.date(2026, 12, 15), "nothing after the last day of the term"


def test_a_class_that_ignores_school_days_still_runs_on_a_closure(root, modules):
    A, ea = modules("activities"), modules("edit_actions")
    assert ea.activity_add(ADULT, "Karate", "Wed", who="Sam", start_time="18:00")[0]
    con = db(root)
    try:
        got = [o for o in A.occurrences(con, D.date(2026, 9, 9), D.date(2026, 9, 9)) if o["title"] == "Karate"]
    finally:
        con.close()
    assert len(got) == 1, "the YMCA does not close for a school closure"


def test_change_and_end_a_class(root, modules):
    ea = modules("edit_actions")
    sid = q(root, "SELECT id FROM activity_schedules WHERE title='Karate'")[0][0]
    ok, msg = ea.activity_update(ADULT, sid, weekdays="Tue Thu", provider="")
    assert ok and q(root, "SELECT weekdays, provider FROM activity_schedules WHERE id=?", sid) == [("TU,TH", None)]
    assert ea.activity_update(ADULT, sid, colour="red")[0] is False
    assert ea.activity_update(KID, sid, title="x")[0] is False
    assert ea.activity_end(ADULT, sid)[0]
    assert q(root, "SELECT status FROM activity_schedules WHERE id=?", sid) == [("ended",)]
    assert ea.activity_end(ADULT, sid)[0] is False, "ended once"


def test_todays_classes_reach_the_brief_and_today(root, modules):
    ea, ai = modules("edit_actions"), modules("action_items")
    today = D.date.today()
    code = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")[today.weekday()]
    assert ea.activity_add(ADULT, "Violin", code, who="Sam", start_time="16:00")[0]
    con = db(root)
    try:
        items = ai.collect_items(con, today, 30)
    finally:
        con.close()
    mine = [i for i in items if i["kind"] == "Class" and i["title"].startswith("Violin")]
    assert [i["date"] for i in mine] == [today], "only today and tomorrow, not a month of lessons"
    assert mine[0]["title"] == "Violin 16:00 (Sam)" and mine[0]["ref"][0] == "activity_schedules"
    td = modules("today_data")
    assert "Class" in td.TIMED and "No school" in td.TIMED


def test_the_kid_page_shows_own_classes_and_days_off(root, modules):
    lv = modules("limited_view")
    today = D.date.today()
    ea = modules("edit_actions")
    assert ea.calendar_day_add(ADULT, (today + D.timedelta(days=3)).isoformat(), "Field trip day off", "closure", who="Sam")[0]
    assert ea.calendar_day_add(ADULT, (today + D.timedelta(days=3)).isoformat(), "Alex day off", "closure", who="Alex")[0]
    got = lv.data("Sam", today, root / "data" / "family.db")
    assert any(c["title"].startswith("Violin") for c in got["classes"])
    titles = [d["title"] for d in got["days_off"]]
    assert "Field trip day off (Sam)" in titles and not any("Alex day off" in t for t in titles)


# ---- holidays ---------------------------------------------------------------------------------------------------
def test_public_holidays_follow_the_rules(modules):
    H = modules("holidays")
    us = dict((n, d) for d, n in H.public(2026, "US"))
    assert us["Thanksgiving"] == D.date(2026, 11, 26) and us["Memorial Day"] == D.date(2026, 5, 25)
    assert us["Martin Luther King Jr. Day"] == D.date(2026, 1, 19) and us["Labor Day"] == D.date(2026, 9, 7)
    assert us["Independence Day (observed)"] == D.date(2026, 7, 3), "4 July 2026 is a Saturday"
    assert "Juneteenth" not in dict((n, d) for d, n in H.public(2020, "US")), "only since 2021"
    uk = dict((n, d) for d, n in H.public(2027, "UK"))
    assert uk["Good Friday"] == D.date(2027, 3, 26) and uk["Easter Monday"] == D.date(2027, 3, 29)
    assert uk["Christmas Day (observed)"] == D.date(2027, 12, 27) and uk["Boxing Day (observed)"] == D.date(2027, 12, 28)
    ca = dict((n, d) for d, n in H.public(2026, "CA"))
    assert ca["Victoria Day"] == D.date(2026, 5, 18) and ca["Thanksgiving"] == D.date(2026, 10, 12)
    assert H.easter(2026) == D.date(2026, 4, 5) and H.easter(2024) == D.date(2024, 3, 31)
    assert H.public(2026, "ZZ") == [] and H.public(2026, "../us") == []


def test_state_province_and_nation_days(modules):
    H = modules("holidays")
    tx = dict((n, d) for d, n in H.public(2026, "US", "Texas"))
    assert tx["Texas Independence Day"] == D.date(2026, 3, 2) and tx["Day after Thanksgiving"] == D.date(2026, 11, 27)
    assert "Patriots' Day" not in tx
    assert dict((n, d) for d, n in H.public(2026, "US", "MA"))["Patriots' Day"] == D.date(2026, 4, 20)
    assert "Texas Independence Day" not in dict((n, d) for d, n in H.public(2026, "US", "")), "no region = national only"
    sct = dict((n, d) for d, n in H.public(2027, "UK", "Scotland"))
    assert "Easter Monday" not in sct and sct["Summer bank holiday"] == D.date(2027, 8, 2)
    assert sct["2nd January (observed)"] == D.date(2027, 1, 4) and sct["St Andrew's Day"] == D.date(2027, 11, 30)
    on = dict((n, d) for d, n in H.public(2026, "CA", "ON"))
    assert on["Family Day"] == D.date(2026, 2, 16) and on["Civic Holiday"] == D.date(2026, 8, 3)
    # the household's own region (the test family lives in TX)
    assert any(n == "San Jacinto Day" for d, n in H.public(2026))


def test_every_us_state_and_dc_has_rules(modules):
    import json
    H = modules("holidays")
    r = H.rules("us")
    states = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
                 "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
    assert set(r["regions"]) == states | {"DC"}
    federal = {h["name"] for h in r["holidays"]}
    for code_, reg in r["regions"].items():
        assert reg.get("name") and set(reg.get("drop") or []) <= federal, code_
        for h in reg.get("holidays") or []:
            assert H.one(h, 2027), (code_, json.dumps(h))
    # Mardi Gras 2027 = 47 days before Easter (28 March)
    la = dict((n, d) for d, n in H.public(2027, "US", "Louisiana"))
    assert la["Mardi Gras"] == D.date(2027, 2, 9) and la["Good Friday"] == D.date(2027, 3, 26)
    assert "Presidents' Day" not in la
    ma = dict((n, d) for d, n in H.public(2027, "US", "MA"))
    assert ma["Patriots' Day"] == D.date(2027, 4, 19)
    # drop: Wisconsin keeps neither Columbus Day nor Veterans Day, but has Christmas Eve and New Year's Eve
    wi = dict((n, d) for d, n in H.public(2027, "US", "WI"))
    assert "Veterans Day" not in wi and "Columbus Day / Indigenous Peoples' Day" not in wi
    assert wi["Christmas Eve"] == D.date(2027, 12, 24) and wi["New Year's Eve"] == D.date(2027, 12, 31)
    assert "Thanksgiving" in wi and "Veterans Day" in dict((n, d) for d, n in H.public(2027, "US", "OH"))
    # DC Emancipation Day: Friday 16 April 2027; Sunday 16 April 2028 is observed on Monday 17 April
    assert dict((n, d) for d, n in H.public(2027, "US", "DC"))["D.C. Emancipation Day"] == D.date(2027, 4, 16)
    dc28 = dict((n, d) for d, n in H.public(2028, "US", "District of Columbia"))
    assert dc28["D.C. Emancipation Day (observed)"] == D.date(2028, 4, 17)
    # New Jersey keeps Juneteenth on the third Friday of June; Election Day every year
    nj = [(d, n) for d, n in H.public(2027, "US", "NJ")]
    assert (D.date(2027, 6, 18), "Juneteenth") in nj and (D.date(2027, 6, 19), "Juneteenth") not in nj
    assert (D.date(2027, 11, 2), "Election Day") in nj
    nv = dict((n, d) for d, n in H.public(2027, "US", "NV"))
    assert nv["Nevada Day"] == D.date(2027, 10, 29) and nv["Family Day"] == D.date(2027, 11, 26)
    assert dict((n, d) for d, n in H.public(2027, "US", "MO"))["Truman Day"] == D.date(2027, 5, 8)
    assert H.observances(2027, "US", "AZ") == [] and H.observances(2027, "US", "TX")


def test_the_digest_and_this_week_list_days_off_and_classes_but_not_tradition_days(root, modules):
    con = db(root)
    con.execute("INSERT OR IGNORE INTO calendar_days(day, kind, name, source, label, status) VALUES "
                "(date('now', '+3 days'), 'festival', 'Secret tradition day', 'tradition', 'Hindu', 'active')")
    con.execute("INSERT OR IGNORE INTO calendar_days(day, kind, name, source, status) VALUES "
                "(date('now', '+4 days'), 'closure', 'Snow make-up day', 'manual', 'active')")
    con.commit()
    con.close()
    for script, name in (("data/make_digest.py", "_weekly_digest.md"), ("data/make_this_week.py", "_this_week.md")):
        r = run([script], root)
        assert r.returncode == 0, r.stderr[-400:]
        text = (root / "brief" / f"{D.date.today().isoformat()}{name}").read_text(encoding="utf-8")
        assert "Snow make-up day" in text and "Secret tradition day" not in text, script
        assert "Swimming" in text, f"{script}: the demo class on Saturdays is within 7 days"
    cd = modules("calendar_days")
    t = D.date.today()
    assert any(r["name"] == "Secret tradition day" for r in cd.between(t, t + D.timedelta(days=7))), "still on the PC"


def test_holidays_can_be_switched_off(root, modules):
    from conftest import read_family, write_family
    H = modules("holidays")
    fam = read_family(root)
    fam.setdefault("packs", {})["holidays"] = False
    write_family(root, fam)
    try:
        r = run(["data/holidays.py", "2026"], root)
        assert "switched off" in r.stdout
    finally:
        fam["packs"]["holidays"] = True
        write_family(root, fam)
    r = run(["data/holidays.py", "2026", "--country", "UK"], root)
    assert "Boxing Day" in r.stdout and r.returncode == 0
    assert H.rules("in")["country"] == "IN"


def test_calendar_days_merge_rules_pack_and_own_rows(root, modules):
    cd, ea = modules("calendar_days"), modules("edit_actions")
    ok, msg = ea.calendar_day_add(ADULT, "2026-12-21", "Winter break", "closure", end="2027-01-01")
    assert ok, msg
    assert "already on the calendar" in ea.calendar_day_add(ADULT, "2026-12-21", "Winter break", "closure", end="2027-01-01")[1]
    assert ea.calendar_day_add(ADULT, "2026-12-21", "Too long", "closure", end="2027-06-01")[0] is False
    assert ea.calendar_day_add(ADULT, "2026-12-21", "Odd", "party")[0] is False
    got = cd.between(D.date(2026, 12, 20), D.date(2026, 12, 31))
    kinds = {(r["name"], r["kind"]) for r in got}
    assert ("Winter break", "No school") in kinds and ("Christmas Day", "Holiday") in kinds
    ev = cd.by_day(D.date(2026, 12, 20), D.date(2026, 12, 31))
    assert ("No school", "Winter break") in ev[D.date(2026, 12, 30)], "a break covers every day of the span"
    rid = q(root, "SELECT id FROM calendar_days WHERE name='Winter break'")[0][0]
    assert ea.calendar_day_drop(ADULT, rid)[0] and not any(r["name"] == "Winter break" for r in cd.between(
        D.date(2026, 12, 20), D.date(2026, 12, 31)))
    assert ea.calendar_day_add(ADULT, "2026-12-21", "Winter break", "closure", end="2027-01-01")[0], "added again"


def test_the_calendar_page_and_whats_on_show_classes_and_holidays(root, modules):
    cal = modules("calendar_data")
    ev = cal.load_events(2026, 2026)
    assert ("Holiday", "Thanksgiving") in ev[D.date(2026, 11, 26)]
    assert any(k == "Class" and t.startswith("Swimming") for k, t in ev[D.date(2026, 9, 2)])
    assert {"Class", "Holiday", "No school", "Early dismissal"} <= set(cal.KIND_COLOR)
    r = run(["data/whats_on.py", "--start", "2026-11-23", "--days", "7", "--no-google"], root)
    assert "Holiday - Thanksgiving" in r.stdout, r.stdout


# ---- forms, sync, ics -------------------------------------------------------------------------------------------
def test_records_forms_add_change_and_remove(root, modules):
    re_ = modules("records_edit")
    data = {"table": "activity_schedules", "title": "Chess club", "who": "Sam", "d_tu": "1", "d_th": "on",
            "start_time": "15:30", "end_time": "", "provider": "School", "term_start": "", "term_end": "",
            "school_days": "1"}
    ok, msg = re_.add(ADULT, ("people", "classes"), data)
    assert ok, msg
    sid = q(root, "SELECT id FROM activity_schedules WHERE title='Chess club'")[0][0]
    v = re_.values("activity_schedules", sid)
    assert v["days"] == ["TU", "TH"] and v["school_days"] is True
    ok, msg, gone = re_.edit(ADULT, "activity_schedules", "skip", sid, {"skip": "2026-11-26"})
    assert ok and not gone
    ok, msg, gone = re_.edit(ADULT, "activity_schedules", "end", sid, {})
    assert not ok and "Tick" in msg
    ok, msg, gone = re_.edit(ADULT, "activity_schedules", "end", sid, {"sure": "1"})
    assert ok and gone
    ok, msg = re_.add(ADULT, ("people", "dates"), {"table": "calendar_days", "day": "2027-03-12", "name": "Spring break",
                                                    "kind": "closure", "end": "2027-03-19", "who": "household"})
    assert ok, msg
    rd = modules("records_data")
    heads = [b["heading"] for b in rd.blocks("people", "classes", D.date.today())]
    assert heads == ["Every week", "Ended"]
    cells = [c for b in rd.blocks("people", "classes", D.date.today()) for r in b["rows"] for c in r["cells"]]
    assert "Tue Thu" in cells, "weekday codes read as words"


def test_phones_get_classes_and_days_but_never_the_tradition_label(root, modules):
    s = modules("sync_data")
    assert s.SOURCES["activities"][0] == "activity_schedules" and s.SOURCES["days"][0] == "calendar_days"
    cols = s.SOURCES["days"][2]
    assert all("label" not in c and "source" not in c for c in cols.values())
    con = db(root)
    try:
        trig = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'sync_%'")}
    finally:
        con.close()
    assert {"sync_activity_schedules_i", "sync_calendar_days_u"} <= trig


def test_the_ics_file_repeats_each_class_weekly(root, modules):
    ics = modules("export_ics")
    today = D.date.today()
    sched = {"id": 7, "title": "Swim", "member": "Sam", "weekdays": "MO,WE", "start_time": "17:00", "end_time": "17:45",
             "term_start": None, "term_end": None, "skip_dates": "", "provider": "YMCA", "school_days": 0}
    nxt = today + D.timedelta(days=(7 - today.weekday()) % 7 or 7)  # a Monday ahead
    ev = "\n".join(ics.weekly(sched, today, "20260101T000000Z", off=[nxt]))
    assert "RRULE:FREQ=WEEKLY;BYDAY=MO,WE;UNTIL=" in ev and "DTSTART:" in ev and "T170000" in ev
    assert f"EXDATE:{nxt:%Y%m%d}T170000" in ev
    assert "Class: Swim 17:00-17:45 (Sam)" in ev
    allday = ics.weekly({**sched, "start_time": None, "end_time": None}, today, "20260101T000000Z")
    assert any(x.startswith("DTSTART;VALUE=DATE:") for x in allday)
    assert ics.weekly({**sched, "term_end": "2000-01-01"}, today, "x") is None, "a finished term adds nothing"
    p, n, text = ics.export("-", today=today)
    assert text.count("RRULE:FREQ=WEEKLY") >= 1 and "Class: Violin" in text


def test_purge_removes_a_persons_classes_and_days(root, modules):
    purge = modules("purge")
    assert ("activity_schedules", "member") in purge.OWNED and ("calendar_days", "member") in purge.OWNED


# ---- change and remove a family event or an appointment added by mistake --------------------------------------------
def test_a_wrong_family_event_can_be_changed_and_removed(root, modules):
    re_ = modules("records_edit")
    ok, msg = re_.add(ADULT, ("people", "dates"), {"table": "events", "name": "Family dinner", "date": "2026-11-21",
                                                    "start_time": "20:00", "end_time": "20:30", "repeats": "once"})
    assert ok, msg
    eid = q(root, "SELECT id FROM events WHERE name='Family dinner'")[0][0]
    others = q(root, "SELECT count(*) FROM events")[0][0] - 1
    v = re_.values("events", eid)
    assert v["date"] == "2026-11-21" and v["start_time"] == "20:00" and v["repeats"] == "once"
    fix = {"name": "Family dinner", "date": "2026-11-20", "start_time": "19:30", "end_time": "20:30", "repeats": "once"}
    assert re_.edit(KID, "events", "save", eid, fix)[0] is False, "a child cannot change it"
    ok, msg, gone = re_.edit(ADULT, "events", "save", eid, fix)
    assert ok and not gone, msg
    assert q(root, f"SELECT event_date, start_time, recurs_yearly FROM events WHERE id={eid}")[0] == ("2026-11-20", "19:30", 0)
    ok, msg, gone = re_.edit(ADULT, "events", "save", eid, {**fix, "end_time": "19:00"})
    assert not ok and "after it starts" in msg, "the same checks as adding"
    ok, msg, gone = re_.edit(ADULT, "events", "drop", eid, {})
    assert not ok and "Tick" in msg and q(root, "SELECT count(*) FROM events")[0][0] == others + 1
    ok, msg, gone = re_.edit(ADULT, "events", "drop", eid, {"sure": "1"})
    assert ok and gone and q(root, "SELECT count(*) FROM events")[0][0] == others
    assert re_.edit(ADULT, "events", "drop", eid, {"sure": "1"})[0] is False, "already gone"


def test_a_wrong_appointment_can_be_changed_and_removed(root, modules):
    ea, re_ = modules("edit_actions"), modules("records_edit")
    assert ea.appointment_add(ADULT, "Sam", "2026-12-10 09:30", "Dr Rao", "Checkup")[0]
    aid = q(root, "SELECT id FROM appointments WHERE provider='Dr Rao'")[0][0]
    others = q(root, "SELECT count(*) FROM appointments")[0][0] - 1
    v = re_.values("appointments", aid)
    assert (v["who"], v["date"], v["time"], v["provider"]) == ("Sam", "2026-12-10", "09:30", "Dr Rao")
    ok, msg, gone = re_.edit(ADULT, "appointments", "save", aid, {"who": "Alex", "date": "2026-12-11", "time": "10:15",
                                                                   "provider": "Dr Rao", "purpose": "", "followup": ""})
    assert ok and not gone, msg
    assert q(root, f"SELECT person, appt_datetime, purpose FROM appointments WHERE id={aid}")[0] == ("Alex", "2026-12-11 10:15", None)
    assert re_.edit(ADULT, "appointments", "save", aid, {"who": "Alex", "date": "2026-12-11", "time": "",
                                                          "provider": "", "purpose": "", "followup": ""})[0] is False
    assert re_.edit(KID, "appointments", "drop", aid, {"sure": "1"})[0] is False
    ok, msg, gone = re_.edit(ADULT, "appointments", "drop", aid, {"sure": "1"})
    assert ok and gone and q(root, "SELECT count(*) FROM appointments")[0][0] == others
