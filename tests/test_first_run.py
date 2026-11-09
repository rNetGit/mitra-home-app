"""The plain-text answers of the chat-style first run (data/first_run.py): people, cars and own / rent are read without
an AI, written back in a form the parser reads again, and mistakes come back as plain sentences."""
import pytest

from conftest import bind, copy_template


@pytest.fixture(scope="module")
def fr(tmp_path_factory):
    bind(copy_template(tmp_path_factory.mktemp("fr") / "t", family=False))
    import importlib
    return importlib.import_module("first_run")


def names(ms):
    return [(m["name"], m["role"], m["birth_month_day"], m["birth_year"]) for m in ms]


def test_people_in_the_ways_people_type_them(fr):
    ms, bad = fr.parse_people("Alex, adult, March 14 1980\nSam - child, born 5/2/2012\nRex the dog")
    assert bad == [] and names(ms) == [("Alex", "adult", "03-14", 1980), ("Sam", "child", "05-02", 2012), ("Rex", "pet", "", None)]
    ms, bad = fr.parse_people("Alex (adult, 3/14/1980), Sam (child), Rex (pet)")
    assert bad == [] and names(ms) == [("Alex", "adult", "03-14", 1980), ("Sam", "child", "", None), ("Rex", "pet", "", None)]
    ms, _ = fr.parse_people("Alex adult, Sam child; Zoe")
    assert names(ms) == [("Alex", "adult", "", None), ("Sam", "child", "", None), ("Zoe", "adult", "", None)]
    ms, _ = fr.parse_people("Mom, Dad, Sam son 14 Feb 2012")
    assert [m["name"] for m in ms] == ["Mom", "Dad", "Sam"] and ms[2]["birth_month_day"] == "02-14"
    ms, _ = fr.parse_people("Priya 1985, 12/05")
    assert names(ms) == [("Priya", "adult", "12-05", 1985)]


def test_day_month_order_follows_the_country(fr):
    assert names(fr.parse_people("Priya 12/05/1990", "mdy")[0]) == [("Priya", "adult", "12-05", 1990)]
    assert names(fr.parse_people("Priya 12/05/1990", "dmy")[0]) == [("Priya", "adult", "05-12", 1990)]
    assert names(fr.parse_people("Priya 25/12", "mdy")[0])[0][2] == "12-25", "only one reading is possible"


def test_mistakes_come_back_as_sentences(fr):
    ms, bad = fr.parse_people("Alex, adult, Feb 30")
    assert ms == [] and any("not a real date" in p for p in bad)
    ms, bad = fr.parse_people("Alex\nalex")
    assert [m["name"] for m in ms] == ["Alex"] and any("already" in p for p in bad)
    ms, bad = fr.parse_people("adult")
    assert ms == [] or ms[0]["name"] == "Adult"
    assert fr.parse_people("")[0] == []


def test_people_text_reads_back_the_same(fr):
    ms, _ = fr.parse_people("Alex, adult, March 14 1980\nSam, child\nRex, pet, born 2020")
    again, bad = fr.parse_people(fr.people_text(ms))
    assert bad == [] and again == ms


def test_cars_and_tenure(fr):
    cars, bad = fr.parse_vehicles("2019 Honda CR-V, Toyota Camry 2015 and Mazda 3")
    assert bad == [] and cars == [{"year": 2019, "make": "Honda", "model": "CR-V"},
                                  {"year": 2015, "make": "Toyota", "model": "Camry"},
                                  {"year": None, "make": "Mazda", "model": "3"}]
    assert fr.parse_vehicles("no car") == ([], []) and fr.parse_vehicles("None.") == ([], [])
    _, bad = fr.parse_vehicles("Civic")
    assert bad and "make and model" in bad[0]
    assert fr.parse_vehicles(fr.vehicles_text(cars))[0] == cars
    assert fr.parse_tenure("we rent") == "rent" and fr.parse_tenure("we own it") == "own" and fr.parse_tenure("hm") == ""
