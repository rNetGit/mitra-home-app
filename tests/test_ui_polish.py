"""Small UI fixes from the October 2026 audit: dates read as words, the setup people list keeps its names readable,
the phone keeps Help in the More sheet, plain plurals."""
import datetime as D
import re


def test_dates_read_as_words(modules):
    dates = modules("dates")
    assert dates.md_text("03-14") == "March 14" and dates.md_text("03-14", 1980) == "March 14, 1980"
    assert dates.md_text("12-01", short=True) == "Dec 1" and dates.md_text("13-40") == "" and dates.md_text(None) == ""
    today = D.date(2026, 10, 18)
    assert dates.day_text("2026-10-23", today) == "Fri, Oct 23"
    assert dates.day_text("2027-01-02", today) == "Sat, Jan 2, 2027"
    assert dates.day_text("someday") == "someday"


def test_setup_people_read_back_with_words_for_birthdays(modules):
    sd = modules("setup_data")
    assert sd.birthday_text("03-14", 1980) == "March 14, 1980"
    assert sd.birthday_text("", 2012) == "born 2012" and sd.birthday_text("", None) == "no birthday"


def test_records_show_birthdays_as_words(modules):
    rd = modules("records_data")
    row = rd.list_row(["id", "name", "role", "birthday"], {"id": 1, "name": "Alex", "role": "adult", "birthday": "03-14"},
                      D.date(2026, 10, 18))
    assert row["right"] == "Mar 14"


def test_the_setup_role_dropdown_does_not_squeeze_the_name(root):
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.nform \.checklist select\{[^}]*width:auto", css), ".nform select{width:100%} must not apply in the row"


def test_phones_find_help_in_the_more_sheet(root):
    base = (root / "data" / "webapp" / "templates" / "base.html").read_text(encoding="utf-8")
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    assert "Help on this page" in base
    assert "helpbtn" not in base and "helpbtn" not in css, "no floating ? button: Help is in the More menu"
    assert "helptip" not in base and "helptip" not in css


def test_phone_fields_never_zoom_and_text_is_at_least_12px(root):
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    small = [v for v in re.findall(r"font-size:\s*(0?\.\d+)rem", css) if float(v) < 0.8]
    assert small == [], "the root size is 15 px: .8rem is the smallest that stays at 12 px"
    phone = css[css.rindex("@media (max-width:760px){\n  input:not"):]
    assert "font-size:16px" in phone and "min-height:44px" in phone


def test_the_week_rolls_from_the_day_shown(modules):
    cd = modules("calendar_data")
    sunday = D.date(2026, 10, 18)
    days = cd.week_days(sunday)
    assert days[0] == sunday and days[-1] == D.date(2026, 10, 24), "a Sunday shows the week ahead, not the one ending"
    assert cd.shift("week", sunday, 1) == D.date(2026, 10, 25) and cd.shift("week", sunday, -1) == D.date(2026, 10, 11)
    assert cd.title("week", sunday) == "Oct 18 to 24, 2026"
    assert cd.title("week", D.date(2026, 10, 29)) == "Oct 29 to 4 Nov, 2026"
