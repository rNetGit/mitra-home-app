"""Work S3: a job that asks to show on the Calendar puts Remote / Office days, work holidays and pay days there."""
import datetime as D

import pytest
from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}


@pytest.fixture(autouse=True)
def _clean(root, modules):
    modules("edit_actions")
    with db(root) as con:
        for t in ("work_calendar", "work_hours", "contracts"):
            con.execute(f"DELETE FROM {t}")
    yield


def _job(ea, root, schedule, **profile):
    ok, msg = ea.work_contract_add(ADULT, "Acme Corp", None, None, "Alex", None, None, None, "employment", "primary", True)
    assert ok, msg
    cid = q(root, "SELECT id FROM contracts WHERE client='Acme Corp'")[0][0]
    ok, msg = ea.work_profile(ADULT, cid, schedule=schedule, cycle_anchor="2026-01-05", **profile)
    assert ok, msg
    return cid


def _events(modules):
    return modules("calendar_data").load_events(2026, 2026)


def test_nothing_shows_until_the_job_asks_to(root, modules):
    ea = modules("edit_actions")
    _job(ea, root, "HHHHHHH")
    assert not [1 for v in _events(modules).values() for k, _ in v if k in ("Remote", "Office")]


def test_remote_and_office_days_follow_the_pattern_and_the_job_dates(root, modules):
    ea = modules("edit_actions")
    cid = _job(ea, root, "OHOH--W", show_on_calendar="1", start_date="2026-03-02", end_date="2026-03-08")
    ev = _events(modules)
    got = {d: [x for x in v if x[0] in ("Remote", "Office")] for d, v in ev.items()}
    got = {d: v for d, v in got.items() if v}
    assert sorted(got) == [D.date(2026, 3, 2), D.date(2026, 3, 3), D.date(2026, 3, 4), D.date(2026, 3, 5)], "Mon-Thu only, inside the dates"
    assert got[D.date(2026, 3, 2)] == [("Office", "Office (Alex)")]
    assert got[D.date(2026, 3, 3)] == [("Remote", "Remote (Alex)")]
    assert cid


def test_work_holidays_replace_the_chip_and_pay_days_show(root, modules):
    ea = modules("edit_actions")
    _job(ea, root, "HHHHHHH", show_on_calendar="1", work_calendar="Acme cal")
    assert ea.work_calendar_add(ADULT, "Acme cal", "2026-12-25", "holiday", "Christmas")[0]
    assert ea.work_calendar_add(ADULT, "Acme cal", "2026-12-31", "payday", None)[0]
    ev = _events(modules)
    xmas = ev[D.date(2026, 12, 25)]
    assert ("Holiday", "Christmas (Alex)") in xmas and not [1 for k, _ in xmas if k == "Remote"]
    assert ("Pay day", "Pay day (Alex)") in ev[D.date(2026, 12, 31)]
    assert ("Remote", "Remote (Alex)") in ev[D.date(2026, 12, 30)]


def test_a_private_job_stays_off_the_shared_calendar(root, modules):
    ea = modules("edit_actions")
    cid = _job(ea, root, "HHHHHHH", show_on_calendar="1")
    assert ea.work_profile(ADULT, cid, visibility="private")[0]
    assert not [1 for v in _events(modules).values() for k, _ in v if k == "Remote"]
