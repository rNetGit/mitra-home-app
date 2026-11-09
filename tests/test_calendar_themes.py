"""Calendar day themes: a day takes the look of its most important item (data/calendar_themes.py, app.css .th-<key>,
static/themes/<key>.svg)."""
import pathlib
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from test_webapp import _login, web  # noqa: F401 (the web fixture)

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = ROOT / "data" / "webapp" / "static"


def _themes(modules):
    return modules("calendar_themes")


def test_named_festivals_and_holidays_get_their_own_theme(modules):
    ct = _themes(modules)
    assert ct.day_theme([("Festival", "Diwali (Lakshmi Puja)")]) == "diwali"
    assert ct.day_theme([("Festival", "Dhanteras")]) == "diwali"
    assert ct.day_theme([("Festival", "Govardhan Puja"), ("Festival", "Karthika Masam begins (Telugu, to Dec 8)")]) == "diwali"
    assert ct.day_theme([("Holiday", "Thanksgiving")]) == "thanksgiving"
    assert ct.day_theme([("Holiday", "Christmas Day")]) == "christmas"
    assert ct.day_theme([("Holiday", "Veterans Day")]) == "patriot"
    assert ct.day_theme([("Holiday", "Independence Day")]) == "patriot"


def test_a_shopping_list_named_after_a_holiday_does_not_theme_the_day(modules):
    ct = _themes(modules)
    assert ct.day_theme([("Shopping", "Thanksgiving 2026: Pillows")]) == ""


def test_priority_and_plain_tints(modules):
    ct = _themes(modules)
    assert ct.day_theme([("Appointment", "Doctor appointment 3:30 PM"), ("Festival", "Diwali (Lakshmi Puja)")]) == "diwali"
    assert ct.day_theme([("Bill", "Electric $10"), ("Appointment", "Dr. Lee – checkup")]) == "medical"
    assert ct.day_theme([("Medical", "Flu shot"), ("Birthday", "Sam's birthday")]) == "birthday"
    assert ct.day_theme([("Appointment", "Piano lesson 5:00 PM")]) == ""
    assert ct.day_theme([("Festival", "Karthika Masam begins")]) == "festival"
    assert ct.day_theme([("Holiday", "Columbus Day")]) == "holiday"
    assert ct.day_theme([("Activity", "Soccer"), ("Bill", "Water")]) == "class"
    assert ct.day_theme([("Bill", "Water")]) == "bill"
    assert ct.day_theme([]) == "" and ct.day_theme(None) == ""


def test_every_theme_with_art_has_its_drawing_and_its_colour(modules):
    ct = _themes(modules)
    css = (STATIC / "app.css").read_text(encoding="utf-8")
    for key in ct.ART:
        art = STATIC / "themes" / f"{key}.svg"
        assert art.is_file() and art.read_text(encoding="utf-8").lstrip().startswith("<svg"), key
        assert f".th-{key}{{--th:" in css.replace(" ", ""), key
        assert f"/static/themes/{key}.svg" in css, key
    for key in ("festival", "holiday", "medical", "class", "bill", "birthday"):
        assert (STATIC / "themes" / f"icon-{key}.svg").is_file(), key
    assert not re.search(r"<script|onload|href=", "".join(p.read_text(encoding="utf-8") for p in (STATIC / "themes").glob("*.svg")))


def test_the_week_view_marks_the_day_with_its_theme(web, modules, root):  # noqa: F811
    c, _, _ = web
    _login(c)
    import datetime as D
    import sqlite3
    d = D.date.today() + D.timedelta(days=1)
    con = sqlite3.connect(modules("paths").DB)
    try:
        con.execute("INSERT INTO events (name, event_date, recurs_yearly) VALUES ('Diwali night', ?, 0)", (d.isoformat(),))
        con.commit()
    finally:
        con.close()
    # an Event is not a Festival: the day stays plain; the page and its classes still render
    page = c.get(f"/calendar/body?view=week&ref={d.isoformat()}").text
    assert 'class="cal week"' in page or "cal week" in page
    assert "static/themes" not in page, "the art comes from the stylesheet, never inline"
