"""Every alerts() provider and collect_items() must cope with leap days and year boundaries, and with empty tables."""
import datetime as dt

import pytest

from conftest import db

PROVIDERS = ("members", "life", "loans", "spikes", "id_docs", "assets", "vehicle_log", "contracts", "shopping", "home_office",
             "activities")
DAYS = (dt.date(2028, 2, 29), dt.date(2027, 2, 28), dt.date(2026, 12, 31), dt.date(2027, 1, 1), dt.date(2028, 3, 1))


@pytest.fixture(scope="module")
def edge_rows(root, modules):
    con = db(root)
    con.execute("INSERT INTO members(name, role, birth_month_day, birth_year) VALUES ('Leap', 'adult', '02-29', 2000)")
    con.execute("INSERT INTO life_items(domain, title, member, due_date, status) VALUES ('school', 'Leap day form', 'Sam', '2028-02-29', 'open')")
    con.execute("INSERT INTO life_items(domain, title, member, due_date, status) VALUES ('chore', 'New year chore', 'Sam', '2027-01-01', 'open')")
    con.execute("INSERT INTO loans(name, kind, balance, payoff_date, status) VALUES ('Edge loan', 'auto', 10, '2027-01-02', 'active')")
    con.execute("INSERT INTO events(name, event_date, recurs_yearly) VALUES ('Leap anniversary', '2024-02-29', 1)")
    con.execute("INSERT INTO events(name, event_date, recurs_yearly) VALUES ('Year end', '2026-12-31', 1)")
    con.execute("INSERT INTO activity_schedules(member, title, weekdays, start_time, term_end) "
                "VALUES ('Sam', 'Leap swim', 'MO,TU,WE,TH,FR,SA,SU', '17:00', '2028-03-01')")
    con.commit()
    con.close()
    return root


@pytest.mark.parametrize("today", DAYS, ids=str)
@pytest.mark.parametrize("name", PROVIDERS)
def test_every_provider_returns_well_formed_alerts(edge_rows, modules, name, today):
    mod = modules(name)
    con = db(edge_rows)
    try:
        out = mod.alerts(con, today)
    finally:
        con.close()
    assert isinstance(out, list)
    for a in out:
        assert isinstance(a["date"], dt.date), a
        assert a["kind"] and a["title"], a


@pytest.mark.parametrize("today", DAYS, ids=str)
def test_collect_items_on_edge_days(edge_rows, modules, today):
    ai = modules("action_items")
    con = db(edge_rows)
    try:
        items = ai.collect_items(con, today, 60)
    finally:
        con.close()
    assert all(isinstance(i["date"], dt.date) for i in items)
    titles = [i["title"] for i in items]
    assert titles.count("Leap anniversary") <= 1 and titles.count("Year end") <= 1


def test_feb_29_birthday_resolves_in_leap_and_common_years(edge_rows, modules):
    members = modules("members")
    con = db(edge_rows)
    try:
        leap = [a for a in members.alerts(con, dt.date(2028, 1, 1)) if a["title"].startswith("Leap")]
        common = [a for a in members.alerts(con, dt.date(2027, 1, 1)) if a["title"].startswith("Leap")]
    finally:
        con.close()
    assert leap and leap[0]["date"] == dt.date(2028, 2, 29)
    assert common and common[0]["date"] == dt.date(2027, 2, 28)


def test_year_boundary_items_are_due_from_december(edge_rows, modules):
    life, loans = modules("life"), modules("loans")
    con = db(edge_rows)
    try:
        dec = {a["title"] for a in life.alerts(con, dt.date(2026, 12, 20))}
        payoff = [a for a in loans.alerts(con, dt.date(2026, 12, 31)) if a["title"].startswith("Edge loan")]
    finally:
        con.close()
    assert any(t.startswith("New year chore") for t in dec)
    assert payoff and payoff[0]["date"] == dt.date(2027, 1, 2)


def test_add_months_clamps_to_month_end(modules):
    ai = modules("action_items")
    assert ai.add_months(dt.date(2027, 1, 31), 1) == dt.date(2027, 2, 28)
    assert ai.add_months(dt.date(2028, 1, 31), 1) == dt.date(2028, 2, 29)
    assert ai.add_months(dt.date(2026, 12, 15), 1) == dt.date(2027, 1, 15)
