"""US household extras (0.110): school year calendars read without AI (data/school_calendar.py, intake `local`),
daylight saving clock changes from the holiday rules (holidays.observances, shown as "Clocks change"), and yearly home
tax bills from setup (school tax, property tax) that roll to next year once paid. The calendar text is made up in the
layout of a district PDF calendar (no real school)."""
import datetime as dt
import sqlite3

from conftest import q, run, set_ai

CAL = """Sample Valley Central School District 2026-2027 School Calendar
July 2026 Su M Tu W Th F S 1 2 3 4 5 6 7 8 9 10
September 2026 Su M Tu W Th F S 1 2 3 4 5 6 7 8 School Day = 17
Sep 3 K-12 Superintendent's Conference Day Sep 7 Labor Day Sep 8 First Day of Classes K-12
October 2026 Su M Tu W Th F S School Day Tally = 21 1 2 3
Oct 2 Emergency Release Dismiss 15 Min Early Oct 12 Columbus Day/Indigenous Peoples� Day
November 2026 Su M Tu W Th F S 1 2 3 Nov 25-27 Thanksgiving Holiday
December 2026 Su M Tu W Th F S Days = 17 1 2 3 Dec 24-Jan 1 Winter Recess
January 2027 Su M Tu W Th F S Jan 4 Classes Resume Jan 26-29 Regents Exam Days
March 2027 Su M Tu W Th F S Mar 26-Apr 2 Spring Recess
June 2027 Su M Tu W Th F S Jun 24 Half Day Gr K-8, Last Day of School
"""


def test_reads_days_off_and_early_dismissals(modules):
    sc = modules("school_calendar")
    assert sc.looks_like(CAL) and not sc.looks_like("Electric bill for September 2026, amount due $80")
    r = sc.read(CAL)
    assert r["school"] == "Sample Valley Central School District" and r["school_year"] == "2026-27"
    by = {d["date"]: d for d in r["days"]}
    assert by["2026-09-07"]["kind"] == "closure" and by["2026-10-02"]["kind"] == "early"
    assert by["2026-12-24"]["end"] == "2027-01-01", "a break across New Year keeps both years"
    assert by["2027-03-26"]["end"] == "2027-04-02" and by["2027-06-24"]["kind"] == "early"
    assert by["2026-10-12"]["name"] == "Columbus Day/Indigenous Peoples' Day"
    assert "2026-09-08" not in by and "2027-01-04" not in by and "2027-01-26" not in by, "school days are left out"


def test_too_little_is_not_guessed(modules):
    sc = modules("school_calendar")
    try:
        sc.read("Sample School 2026-2027 School Calendar Sep 7 Labor Day")
    except sc.CalendarError:
        return
    raise AssertionError("one day is not a calendar")


def test_intake_without_ai_files_a_school_calendar_as_proposed_days(root):
    set_ai(root, "none")
    (root / "inbox").mkdir(exist_ok=True)
    (root / "inbox" / "district_calendar.txt").write_text(CAL, encoding="utf-8")
    (root / "inbox" / "other.txt").write_text("A letter about something else entirely.", encoding="utf-8")
    r = run(["data/ai_intake.py", "local"], root)
    assert r.returncode == 0, r.stdout + r.stderr[-400:]
    assert "waiting from the school calendar" not in r.stdout and "waiting" in r.stdout
    assert (root / "inbox" / "other.txt").exists(), "a paper that needs an AI stays in the inbox"
    rows = q(root, "SELECT day, end_day, kind, status, source FROM calendar_days WHERE source='school' ORDER BY day")
    assert ("2026-12-24", "2027-01-01", "closure", "proposed", "school") in rows and len(rows) >= 8
    assert q(root, "SELECT doc_type FROM documents ORDER BY id DESC LIMIT 1") == [("school_calendar",)]


def test_daylight_saving_dates(modules):
    h = modules("holidays")
    us = dict((n.split(":")[0], d) for d, n in h.observances(2026, "US", "NY"))
    assert us == {"Daylight saving time starts": dt.date(2026, 3, 8), "Daylight saving time ends": dt.date(2026, 11, 1)}
    assert h.observances(2026, "US", "AZ") == [] and h.observances(2026, "US", "Hawaii") == []
    assert [d for d, _ in h.observances(2027, "UK", "")] == [dt.date(2027, 3, 28), dt.date(2027, 10, 31)]
    assert all("clocks" not in n for _, n in h.public(2026, "US", "NY")), "not a day off"


def test_clock_changes_show_on_the_calendar(modules, root):
    fam = __import__("conftest").read_family(root)
    fam["country"] = "US"
    fam.setdefault("region", {})["state"] = "NY"
    __import__("conftest").write_family(root, fam)
    cd = modules("calendar_days")
    rows = cd.between(dt.date(2026, 3, 1), dt.date(2026, 3, 31))
    assert any(r["kind"] == "Clocks change" and r["start"] == dt.date(2026, 3, 8) for r in rows)


def test_home_tax_bills_from_setup_roll_forward_when_paid(modules, root):
    si, ea = modules("setup_interview"), modules("edit_actions")
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM bills WHERE name IN ('School tax', 'Property tax')")
    con.commit()
    con.close()
    today = dt.date(2026, 10, 16)
    msgs = si.home_tax_bills({"school_tax": "2025-09-30", "property_tax": "2027-01-31"}, today=today)
    assert len(msgs) == 2
    assert si.home_tax_bills({"school_tax": "2026-09-30"}, today=today) == [], "a re-run adds no second open bill"
    rows = dict(q(root, "SELECT name, due_date FROM bills WHERE name IN ('School tax', 'Property tax') AND status='due'"))
    assert rows == {"School tax": "2027-09-30", "Property tax": "2027-01-31"}, "a passed date moves to next year"
    bid = q(root, "SELECT id FROM bills WHERE name='School tax' AND status='due'")[0][0]
    ok, out = ea.bill_paid({"name": "Alex", "role": "adult"}, bid)
    assert ok and "2028-09-30" in out
    assert q(root, "SELECT due_date, frequency FROM bills WHERE name='School tax' AND status='due'") == [("2028-09-30", "yearly")]


def test_setup_home_step_takes_tax_dates_for_owners(modules):
    sd = modules("setup_data")
    a = {"country": "US", "tenure": "own"}
    assert sd._take(a, "Home", {"tenure": "own", "tax_school_tax": "2026-09-30", "tax_property_tax": ""}) == []
    assert a["home_taxes"] == {"school_tax": "2026-09-30"}
    assert "pick the date" in sd._take(a, "Home", {"tenure": "own", "tax_school_tax": "30/9"})[0]
    sd._take(a, "Home", {"tenure": "rent", "tax_school_tax": "2026-09-30"})
    assert a["home_taxes"] == {}, "renters do not pay these bills themselves"
    home = next(i for i, (_, secs) in enumerate(sd.SCREENS) if "Home" in secs)

    def taxes(c):
        return [k for k, _, _ in next(p for p in sd.view({"country": c}, home)["parts"] if p["name"] == "Home")["taxes"]]
    assert taxes("US") == ["school_tax", "property_tax"]
    assert taxes("UK") == ["property_tax"]
