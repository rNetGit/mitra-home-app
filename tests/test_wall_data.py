"""What the Mitra Wall shows (data/wall_data.py): the week grid (rows, lanes for overlaps, events outside the grid), the
money lane without amounts (late bills on today, future weeks only their own), a person's filter, Today's line, meals,
and Money's amounts (shown only after an adult's PIN)."""
import datetime as dt

import pytest

MON = dt.date(2027, 3, 1)          # a Monday
WED = MON + dt.timedelta(days=2)   # "today" in these tests
ADULT = {"name": "Alex", "role": "adult"}


@pytest.fixture()
def WD(modules):
    return modules("wall_data")


@pytest.fixture()
def con(modules):
    W = modules("wall")
    c = W._con()
    for t in ("routine_done", "routines", "appointments", "bills", "subscriptions", "work_calendar", "activity_schedules",
              "life_items", "events", "meal_plan", "calendar_days"):
        c.execute(f"DELETE FROM {t}")
    c.executemany("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES (?,?,?,?)", [
        ("Sam", "Dr Lee", "Dentist", "2027-03-03 09:00"),
        ("Alex", None, "Car service", "2027-03-03 09:30"),
        ("Alex", None, "Late call", "2027-03-03 23:30"),
        ("Sam", None, "Haircut", "2027-03-04"),
    ])
    c.executemany("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES (?,?,?,?,?)", [
        ("Internet", "Net Provider", 99.5, "2027-02-20", "due"),
        ("Power", "Electric Co", 120.0, "2027-03-05", "due"),
        ("Water", "City Water", 40.0, "2027-03-04", "paid"),
        ("Phone", "Phone Co", 55.0, "2027-03-10", "due"),
    ])
    c.commit()
    yield c
    c.close()


def _day(v, d):
    return next(x for x in v["days"] if x["date"] == d)


def test_timed_events_get_rows_and_lanes(WD, con):
    v = WD.week(con, MON, WED)
    wed = _day(v, WED)
    by = {e["title"].split(" · ")[0]: e for e in wed["events"]}
    assert set(by) == {"Dentist", "Car service"}, "the 11:30 PM call is off the grid"
    assert by["Dentist"]["title"] == "Dentist · Dr Lee"
    assert (by["Dentist"]["r0"], by["Dentist"]["r1"]) == (5, 9), "8 AM grid: 9:00-10:00 = rows 5..9"
    assert (by["Car service"]["r0"], by["Car service"]["r1"]) == (7, 11)
    assert {by["Dentist"]["col"], by["Car service"]["col"]} == {"l1", "l2"} and wed["lanes"] == 2
    assert by["Dentist"]["time"] == "9 AM – 10 AM"
    assert any(a["title"] == "Late call · 11:30 PM" for a in wed["allday"]), "outside the grid = an all-day line with its time"
    assert any(a["title"] == "Haircut" for a in _day(v, WED + dt.timedelta(days=1))["allday"])
    assert v["hours"][0] == {"label": "8 AM", "row": 1} and v["slots"] == 48
    assert v["now_row"] is None or 1 <= v["now_row"] <= v["slots"]


def test_one_person_dims_the_rest_and_an_unknown_name_dims_nobody(WD, con):
    v = WD.week(con, MON, WED, who="Sam")
    ev = {e["title"].split(" · ")[0]: e["dim"] for e in _day(v, WED)["events"]}
    assert ev == {"Dentist": False, "Car service": True} and v["who"] == "Sam"
    sam = next(c for c in v["chips"] if c["name"] == "Sam")
    assert sam["on"] and sam["n"] == 2
    assert all(not i["dim"] and i["cls"] != "ch" for d in v["days"] for i in d["things"]), "the tiles: only Sam's things"
    v = WD.week(con, MON, WED, who="Nobody")
    assert v["who"] is None and not any(e["dim"] for d in v["days"] for e in d["events"])


def test_the_money_lane_names_bills_without_amounts(WD, con):
    v = WD.week(con, MON, WED)
    lanes = {d["date"]: [{k: x for k, x in m.items() if k != "day"} for m in d["money"]] for d in v["days"] if d["money"]}
    assert lanes == {WED: [{"title": "Net Provider", "kind": "late", "label": "late"}],
                     MON + dt.timedelta(days=4): [{"title": "Electric Co", "kind": "bill", "label": "due"}]}
    assert "City Water" not in str(v), "paid"
    assert "99" not in str(lanes) and "120" not in str(lanes)
    nxt = WD.week(con, MON + dt.timedelta(days=7), WED)
    assert [m["title"] for d in nxt["days"] for m in d["money"]] == ["Phone Co"], "next week: no late bill, only its own"
    past = WD.week(con, dt.date(2027, 2, 15), WED)
    assert [(d["date"], m["kind"]) for d in past["days"] for m in d["money"]] == [(dt.date(2027, 2, 20), "late")]


def test_today_line_and_counts(WD, con):
    v = WD.today(con, dt.datetime(2027, 3, 3, 9, 45))
    assert [e["title"].split(" · ")[0] for e in v["line"]] == ["Dentist", "Car service", "Late call"]
    first, second, late = v["line"]
    assert (first["time"], first["end"], first["who"], first["past"], first["now"]) == ("9 AM", "10 AM", ["S"], False, True)
    assert second["now"] and not late["past"] and late["title"] == "Late call", "today's agenda keeps the 11:30 PM call"
    assert (v["bills_n"], v["late_n"]) == (2, 1)
    assert v["part"] == "Morning" and v["dinner"] is None
    assert v["kids"] == [], "no routines yet"


def test_meals_week_and_tonight(WD, con, modules):
    M = modules("meals")
    rid = M.add_recipe(con, "Wall test tacos", ["1 lb beans", "salt (pantry)"], servings=4, notes="Warm the shells.")
    M.plan_meal(con, WED.isoformat(), "dinner", "Wall test tacos")
    M.plan_meal(con, MON.isoformat(), "breakfast", "Pancakes", note="Sam's turn")
    con.commit()
    v = WD.meals(con, MON, WED)
    assert v["tonight"] == "Wall test tacos" and v["recipe"]["servings"] == 4 and rid
    assert [i["pantry"] for i in v["recipe"]["ingredients"]] == [False, True]
    breakfast = next(r for r in v["grid"] if r["slot"] == "breakfast")
    assert breakfast["cells"][0] == {"meal": "Pancakes", "note": "Sam's turn", "today": False}
    dinner = next(r for r in v["grid"] if r["slot"] == "dinner")
    assert dinner["cells"][2]["today"] and dinner["cells"][2]["meal"] == "Wall test tacos"


def test_money_view_has_the_amounts_and_the_allowance(WD, con, modules):
    ea, W = modules("edit_actions"), modules("wall")
    ok, msg = ea.routine_add(ADULT, "Sam", "morning", "Brush teeth", stars=3, weekdays="MO")  # not on Wednesday
    assert ok, msg
    rid = con.execute("SELECT id FROM routines WHERE title='Brush teeth'").fetchone()[0]
    W.tick(con, rid, MON, "Sam")
    con.commit()
    v = WD.money(con, WED)
    texts = [i["text"] for d in v["strip"] for i in d["items"]]
    assert "Net Provider $99.50" in texts and "Electric Co $120.00" in texts and "Phone Co $55.00" in texts
    assert v["strip"][0]["today"] and v["strip"][0]["items"][0]["kind"] == "late"
    assert v["due_n"] == 3 and v["due_total"] == "$274.50"
    assert v["allowance"] == [{"name": "Sam", "initial": "S", "cls": v["allowance"][0]["cls"], "stars": 3,
                               "amount": "$" + f"{3 * W.star_cents() / 100:.2f}"}], "a child with no job today still counts"


def test_the_stylesheet_has_a_class_for_every_position_the_wall_can_use(root, WD):
    """No inline styles (CSP): every row, column, width and offset is a class in wall.css."""
    css = (root / "data" / "webapp" / "static" / "wall.css").read_text(encoding="utf-8")
    hours = range(WD.GRID_FROM, WD.GRID_TO + 1)
    longest = (WD.GRID_TO - WD.GRID_FROM) * 60 // WD.SLOT_MIN
    shortest = (WD.END_HOUR - WD.START_HOUR) * 60 // WD.SLOT_MIN
    want = [f".slots-{n}{{" for n in range(shortest, longest + 1, 60 // WD.SLOT_MIN)]
    want += [f".gs-{n}{{" for n in range(1, longest + 1)] + [f".ge-{n}{{" for n in range(2, longest + 2)]
    want += [f".w-{n}{{" for n in range(101)] + [f".x-{n}{{" for n in range(101)]
    want += [f".lanes-{n}" for n in range(1, WD.MAX_LANES + 1)] + [f".col-l{n}" for n in range(1, WD.MAX_LANES + 1)]
    want += [f".dcols-{n} " for n in range(1, WD.DAY_LANES + 1)]
    want += [f"body.wall.theme-{t}" for t in ("slate", "night", "bold", "photo")]  # paper = the :root tokens
    missing = [w for w in want + [".col-all"] if w not in css]
    assert not missing and len(hours) > 1, missing[:10]


def test_day_view_a_lane_per_person_then_house(WD, con):
    """The Day view: Sam's dentist and Alex's car service in their own lanes (family order), the late bill in House as one
    late band, the off-grid call an all-day line in Alex's lane; the small-screen list is timed first, by time."""
    con.execute("INSERT INTO life_items(domain, title, due_date, status) VALUES ('chore', 'Sweep the porch', ?, 'open')",
                (WED.isoformat(),))
    con.commit()
    try:
        v = WD.day(con, WED, WED)
        names = [ln["name"] for ln in v["lanes"]]
        assert names[-1] == WD.HOUSE and {"Sam", "Alex"} <= set(names) and v["cols"] == len(names)
        order = [n for n, _ in WD.people(con) if n in names]
        assert names[:-1] == order, "people in family order, House last"
        lane = {ln["name"]: ln for ln in v["lanes"]}
        assert [e["title"] for e in lane["Sam"]["events"]] == ["Dentist · Dr Lee"] and lane["Sam"]["events"][0]["col"] == "all"
        assert [e["title"] for e in lane["Alex"]["events"]] == ["Car service"], "not side by side with Sam's: own lane"
        assert any(a["title"] == "Late call · 11:30 PM" for a in lane["Alex"]["bands"])
        house = lane[WD.HOUSE]
        assert [a["title"] for a in house["late"]] == ["Net Provider · late"] and "99" not in str(house)
        assert any(a["title"] == "Sweep the porch" for a in house["bands"] + house["more"])
        assert [i["time"] for i in v["line"][:2]] == ["9 AM", "9:30 AM"] and v["late_n"] == 1
        assert (v["prev"], v["next"]) == (WED - dt.timedelta(days=1), WED + dt.timedelta(days=1))
        assert v["hours"][0]["label"] == "8 AM" and v["today"]
    finally:
        con.execute("DELETE FROM life_items WHERE title='Sweep the porch'")
        con.commit()


def test_month_view_whole_weeks_with_the_days_items(WD, con):
    v = WD.month(con, WED, WED)
    assert v["title"] == "March 2027" and v["rows"] == 5 and v["dows"][0] == "Mon"
    days = [d for w in v["weeks"] for d in w]
    assert days[0]["date"] == MON and days[-1]["date"] == dt.date(2027, 4, 4) and days[-1]["out"]
    wed = next(d for d in days if d["date"] == WED)
    assert wed["today"] and [i["time"] for i in wed["things"][:3]] == ["9 AM", "9:30 AM", "11:30 PM"], "timed first"
    lines = [i for i in wed["things"] if not i["late"]]
    assert wed["shown"] == lines[:3] and wed["more"] == len(lines) - len(wed["shown"])
    assert any(i["money"] == "late" and i["title"] == "Net Provider" for i in wed["things"])
    assert wed["late_n"] == len(wed["things"]) - len(lines) >= 1, "late ones fold into one pill, still in the popup"
    assert "99" not in str(v["weeks"]) and "120" not in str(v["weeks"]), "bills named, never their amounts"
    assert (v["prev"], v["next"]) == (dt.date(2027, 2, 1), dt.date(2027, 4, 1))


def test_the_pc_todays_to_dos_reach_the_wall(WD, con):
    """What the PC's Today counts (here an overdue checkup from recurring_items) shows on the wall: late on today in the
    week, the month and Today's Needs doing; a week without today does not repeat it."""
    con.execute("DELETE FROM recurring_items WHERE name='Wall eye exam'")
    con.execute("INSERT INTO recurring_items(name, category, who, interval_months, last_done) VALUES "
                "('Wall eye exam', 'Health', 'Sam', 12, '2025-06-01')")
    con.commit()
    try:
        wed = _day(WD.week(con, MON, WED), WED)
        row = next(a for a in wed["allday"] if a["title"] == "Wall eye exam (Sam)")
        assert row["late"] and row["cls"] != "ch", "late, in Sam's colour"
        assert wed["late_n"] >= 1 and not any(i["late"] for i in wed["lines"]), "the tile folds late ones into one line"
        nxt = WD.week(con, MON + dt.timedelta(days=7), WED)
        assert not any("Wall eye exam" in a["title"] for d in nxt["days"] for a in d["allday"])
        month_wed = next(d for w in WD.month(con, WED, WED)["weeks"] for d in w if d["date"] == WED)
        assert any(i["title"] == "Wall eye exam (Sam)" and "late" in i["kind"] for i in month_wed["things"])
        needs = WD.today(con, dt.datetime(2027, 3, 3, 9, 45))["needs"]
        assert needs[0]["late"] and any(n["title"] == "Wall eye exam (Sam)" for n in needs)
    finally:
        con.execute("DELETE FROM recurring_items WHERE name='Wall eye exam'")
        con.commit()


def test_today_shows_what_is_coming_up_without_amounts(WD, con):
    c = WD.today(con, dt.datetime(2027, 3, 3, 9, 45))["coming"]
    titles = [(r["when"], r["title"], r["money"]) for r in c["rows"]]
    assert ("Tomorrow", "Haircut", "") in titles
    assert ("Friday", "Electric Co", "bill") in titles, "a bill by name"
    assert "120" not in str(c) and len(c["rows"]) <= WD.COMING_SHOWN


def test_heat_levels(WD):
    assert [WD.heat(n) for n in range(10)] == [0, 1, 1, 2, 2, 3, 3, 4, 4, 4]


def test_a_busy_day_on_the_week_shows_three_lines_and_more(WD, con):
    con.executemany("INSERT INTO life_items(domain, title, due_date, status) VALUES ('chore', ?, '2027-03-04', 'open')",
                    [(f"Busy thing {i}",) for i in range(5)])
    con.commit()
    try:
        thu = _day(WD.week(con, MON, WED), WED + dt.timedelta(days=1))
        assert len(thu["bands"]) == WD.WEEK_BANDS and len(thu["more"]) == len(thu["allday"]) - WD.WEEK_BANDS >= 3
        # the heat-map week: every thing of the day in one list, and the day's shade from how many there are
        assert len(thu["things"]) >= 5 and thu["heat"] == WD.heat(len(thu["things"])) >= 3
        assert {t["title"] for t in thu["things"]} >= {f"Busy thing {i}" for i in range(5)}
    finally:
        con.execute("DELETE FROM life_items WHERE title LIKE 'Busy thing %'")
        con.commit()


def test_a_day_with_a_festival_gets_its_theme_on_the_week_and_the_month(WD, con):
    fri = MON + dt.timedelta(days=4)
    con.execute("INSERT INTO calendar_days (day, kind, name, status, source) VALUES (?, 'festival', 'Diwali (Lakshmi Puja)', 'active', 'manual')",
                (fri.isoformat(),))
    con.commit()
    v = WD.week(con, MON, WED)
    assert _day(v, fri)["theme"] == "diwali"
    assert _day(v, MON)["theme"] in ("", "medical", "class", "bill", "festival", "holiday", "birthday")
    m = WD.month(con, MON, WED)
    cells = {c["date"]: c for week in m["weeks"] for c in week}
    assert cells[fri]["theme"] == "diwali"
