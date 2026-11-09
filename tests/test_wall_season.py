"""Seasonal wall looks (data/wall_season.py): the looks are plain data that validate; the picker gives the festival day and
the 3 days before it a look, never the days after, only when switched on; Diwali comes from the PC's special days."""
import datetime as D

import pytest

ADULT = {"name": "Alex", "role": "adult"}


@pytest.fixture(scope="module")
def ws(root, modules):
    modules("edit_actions")
    return modules("wall_season")


def test_every_shipped_look_validates(ws):
    assert set(ws.LOOKS) == {"halloween", "diwali", "christmas", "holi", "ganesh", "navratri", "dussehra", "sankranti", "onam",
                             "shivaratri", "ugadi", "newyear", "july4", "india", "canada", "thanksgiving"}
    for key, look in ws.LOOKS.items():
        assert ws.validate(look) == [], key
    assert ws.main(["check"]) == 0
    assert {look["backdrop"] for look in ws.LOOKS.values()} == set(ws.BACKDROPS), "every scene is used, every look has one"


def test_the_template_draws_every_backdrop(ws, root):
    tpl = (root / "data" / "webapp" / "templates" / "_wall_season.html").read_text(encoding="utf-8")
    for b in ws.BACKDROPS:
        assert f"season.backdrop == '{b}'" in tpl, b
    assert "<text" not in tpl and "<script" not in tpl and "style=" not in tpl


def _add(modules, day, name):
    ok, msg = modules("edit_actions").calendar_day_add(ADULT, day, name, "festival")
    assert ok, msg


def test_indian_festivals_come_from_their_days_with_the_days_own_name(ws, modules):
    for day, name, key in (("2027-03-22", "Holi", "holi"), ("2027-09-04", "Ganesh Chaturthi", "ganesh"),
                           ("2027-01-14", "Makar Sankranti / Pongal", "sankranti"), ("2027-01-13", "Lohri", "sankranti"),
                           ("2027-04-14", "Baisakhi", "sankranti"), ("2027-08-21", "Thiruvonam (Onam)", "onam"),
                           ("2027-03-06", "Maha Shivaratri", "shivaratri"), ("2027-04-07", "Ugadi / Gudi Padwa", "ugadi"),
                           ("2027-10-09", "Dussehra (Vijayadashami)", "dussehra")):
        _add(modules, day, name)
        look = ws.look_for_day(D.date.fromisoformat(day))
        assert look and look["key"] == key and look["name"] == name, (name, look and look["key"])


def test_a_festival_of_several_days_holds_its_look_and_the_nearest_wins(ws, modules):
    ea = modules("edit_actions")
    ok, msg = ea.calendar_day_add(ADULT, "2027-09-30", "Navratri (Sharad)", "festival", end="2027-10-08")
    assert ok, msg
    _add(modules, "2027-10-09", "Dussehra")
    assert ws.look_for_day(D.date(2027, 10, 5))["key"] == "navratri"
    assert ws.look_for_day(D.date(2027, 10, 8))["key"] == "navratri", "on its last day it is nearer than Dussehra"
    assert ws.look_for_day(D.date(2027, 10, 9))["key"] == "dussehra"


def test_names_are_whole_words_and_months_keep_two_independence_days_apart(ws, modules):
    _add(modules, "2027-05-20", "Holiday party")
    assert ws.look_for_day(D.date(2027, 5, 20)) is None, "Holi is not in Holiday"
    _add(modules, "2027-07-04", "Independence Day")
    _add(modules, "2027-08-15", "Independence Day")
    assert ws.look_for_day(D.date(2027, 7, 4))["key"] == "july4"
    assert ws.look_for_day(D.date(2027, 8, 15))["key"] == "india"
    _add(modules, "2027-01-26", "Republic Day")
    assert ws.look_for_day(D.date(2027, 1, 26))["key"] == "india"


def test_new_year_is_fixed_and_thanksgiving_and_canada_day_come_from_the_holidays(ws, modules):
    look = ws.look_for_day(D.date(2027, 12, 30))
    assert look["key"] == "newyear" and look["festival_day"] == "2028-01-01" and look["name"] == "New Year"
    _add(modules, "2027-11-25", "Thanksgiving")
    _add(modules, "2027-07-01", "Canada Day")
    assert ws.look_for_day(D.date(2027, 11, 25))["key"] == "thanksgiving"
    assert ws.look_for_day(D.date(2027, 7, 1))["key"] == "canada"


def test_validation_catches_bad_data(ws):
    good = ws.LOOKS["halloween"]
    bad = {**good, "colours": {**good["colours"], "text": "#777777", "accent": "red"}, "backdrop": "nope", "clock": "nope",
           "marks": [{"mark": "ghost", "animation": "spin"}], "runup_days": 40}
    probs = " | ".join(ws.validate(bad))
    for part in ("accent is not", "unknown mark", "unknown animation", "unknown backdrop", "unknown clock face", "run-up days"):
        assert part in probs, probs
    low = {**good, "colours": {**good["colours"], "text": "#3a2a4a"}}
    assert any("text on bg" in p for p in ws.validate(low))
    assert ws.contrast("#000000", "#ffffff") == pytest.approx(21.0)


def test_halloween_runs_up_three_days_and_stops_after(ws):
    assert ws.look_for_day(D.date(2026, 10, 27)) is None
    for d in (28, 29, 30, 31):
        look = ws.look_for_day(D.date(2026, 10, d))
        assert look and look["key"] == "halloween" and look["festival_day"] == "2026-10-31", d
    assert ws.look_for_day(D.date(2026, 11, 1)) is None, "nothing after the festival"


def test_christmas_runup_and_year_end(ws):
    assert ws.look_for_day(D.date(2026, 12, 21)) is None
    for d in (22, 23, 24, 25):
        assert ws.look_for_day(D.date(2026, 12, d))["key"] == "christmas"
    for d in (26, 27, 28):
        assert ws.look_for_day(D.date(2026, 12, d)) is None, d
    assert ws.look_for_day(D.date(2027, 1, 1))["key"] == "newyear", "then New Year, from Dec 29"
    assert ws.look_for_day(D.date(2027, 1, 2)) is None


def test_diwali_comes_from_the_special_days_not_from_a_date_in_code(ws, modules):
    ea = modules("edit_actions")
    assert ws.look_for_day(D.date(2026, 11, 7)) is None, "no Diwali known to the PC: no look"
    ok, msg = ea.calendar_day_add(ADULT, "2026-11-08", "Diwali (Lakshmi Puja)", "festival")
    assert ok, msg
    assert ws.look_for_day(D.date(2026, 11, 4)) is None
    for d in (5, 6, 7, 8):
        look = ws.look_for_day(D.date(2026, 11, d))
        assert look and look["key"] == "diwali" and look["festival_day"] == "2026-11-08", d
    assert ws.look_for_day(D.date(2026, 11, 9)) is None


def test_switched_off_and_plain_days_give_nothing_and_the_nearest_festival_wins(ws, modules):
    assert ws.look_for_day(D.date(2026, 10, 31), enabled=False) is None
    assert ws.look_for_day(D.date(2026, 3, 3)) is None
    ea = modules("edit_actions")
    ea.calendar_day_add(ADULT, "2026-11-01", "Diwali", "festival")  # a Diwali one day after Halloween
    assert ws.look_for_day(D.date(2026, 10, 30))["key"] == "halloween", "Oct 31 is nearer than Nov 1"
    assert ws.look_for_day(D.date(2026, 11, 1))["key"] == "diwali"


def test_the_picker_never_reads_the_system_date(ws):
    src = open(ws.__file__, encoding="utf-8").read()
    assert "date.today()" not in src and "datetime.now" not in src
