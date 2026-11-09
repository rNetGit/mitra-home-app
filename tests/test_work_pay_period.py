"""Work: the pay period of a job (migration 069) is set apart from its schedule cycle."""
import datetime as D

import pytest
from conftest import db, q, read_family, write_family

ADULT = {"name": "Alex", "role": "adult"}


@pytest.fixture(autouse=True)
def _clean(root, modules):
    modules("edit_actions")
    fam = read_family(root)
    fam.setdefault("packs", {})["contracts"] = True
    write_family(root, fam)
    with db(root) as con:
        for t in ("work_calendar", "work_hours", "contracts"):
            con.execute(f"DELETE FROM {t}")
    yield


def _job(ea, root, **profile):
    ok, msg = ea.work_contract_add(ADULT, "Acme Corp", None, None, "Alex", None, None, None, "employment", "primary", True)
    assert ok, msg
    cid = q(root, "SELECT id FROM contracts WHERE client='Acme Corp'")[0][0]
    if profile:
        ok, msg = ea.work_profile(ADULT, cid, **profile)
        assert ok, msg
    return cid


def test_pay_period_repeats_and_leaves_the_schedule_alone(root, modules):
    ea, W = modules("edit_actions"), modules("work")
    cid = _job(ea, root, schedule="-WWWWW-" * 2, cycle_anchor="2026-11-01", timesheet_cycle="biweekly",
               period_start="2026-08-27", period_end="2026-09-09")
    with db(root) as con:
        c = W.get_by_id(con, cid)
    assert W.pay_period(c, D.date(2026, 9, 9)) == (D.date(2026, 8, 27), D.date(2026, 9, 9))
    assert W.pay_period(c, D.date(2026, 9, 10)) == (D.date(2026, 9, 10), D.date(2026, 9, 23))
    assert W.pay_period(c, D.date(2026, 8, 26)) == (D.date(2026, 8, 13), D.date(2026, 8, 26))
    assert W.cycle_bounds(c, D.date(2026, 11, 3))[0] == D.date(2026, 11, 1)  # schedule cycle unchanged


def test_without_a_pay_period_the_cycle_is_used(root, modules):
    ea, W = modules("edit_actions"), modules("work")
    cid = _job(ea, root, cycle_anchor="2026-01-05", timesheet_cycle="weekly")
    with db(root) as con:
        c = W.get_by_id(con, cid)
    assert W.pay_period(c, D.date(2026, 1, 13)) == W.cycle_bounds(c, D.date(2026, 1, 13))


def test_pay_period_checks(root, modules):
    ea = modules("edit_actions")
    cid = _job(ea, root)
    ok, msg = ea.work_profile(ADULT, cid, period_start="2026-08-27")
    assert not ok and "both" in msg
    ok, msg = ea.work_profile(ADULT, cid, period_start="2026-08-27", period_end="2026-08-30")
    assert not ok and "7 to 31" in msg
    ok, msg = ea.work_profile(ADULT, cid, period_start="2026-08-27", period_end="2026-09-09")
    assert ok, msg
    ok, msg = ea.work_profile(ADULT, cid, period_start="", period_end="")
    assert ok, msg
    assert q(root, "SELECT period_start, period_end FROM contracts WHERE id=?", cid) == [(None, None)]


def test_timesheet_periods_and_reminder_follow_the_pay_period(root, modules):
    ea, W, wd = modules("edit_actions"), modules("work"), modules("work_data")
    cid = _job(ea, root, period_start="2026-08-27", period_end="2026-09-09")
    with db(root) as con:
        c = W.get_by_id(con, cid)
        cyc = wd._cycles(W, c, D.date(2026, 9, 12))
        assert cyc[1] == (D.date(2026, 9, 10), D.date(2026, 9, 23))  # this period, second in the list
        assert cyc[0][0] == D.date(2026, 9, 24) and cyc[2] == (D.date(2026, 8, 27), D.date(2026, 9, 9))
        rows = W.alerts(con, D.date(2026, 9, 12))
    assert rows and "Aug 27 - Sep 09" in rows[0]["title"]


def test_summary_tab_month_calendar_and_year_table(root, modules):
    ea, wd = modules("edit_actions"), modules("work_data")
    wd.on = lambda: True
    cid = _job(ea, root, schedule="-WWWWW-", cycle_anchor="2026-01-04", timesheet_cycle="weekly")
    ok, msg = ea.work_hours_save(ADULT, cid, [("2026-09-01", 8, "onsite"), ("2026-09-02", 7.5, "offsite"), ("2026-10-05", 6, None)])
    assert ok, msg
    today = D.date(2026, 10, 20)
    r = wd.view(ADULT, {"c": str(cid), "tab": "report", "ym": "2026-09"}, today)["report"]
    assert r["view"] == "month" and r["month_label"] == "September 2026" and r["hours"] == "15.5"
    assert r["days"] == 2 and r["onsite"] == 1 and r["offsite"] == 1
    cells = {x["n"]: x for wk in r["weeks"] for x in wk if x}
    assert len(cells) == 30 and cells[1]["hours"] == "8" and cells[1]["where"] == "Office" and cells[2]["where"] == "Remote"
    assert all(len(wk) == 7 for wk in r["weeks"]) and r["planned"] > 0, "planned past days stay out of the total"
    assert "2026-10" in [k for k, _ in r["months"]] and "2026-09" in [k for k, _ in r["months"]]
    y = wd.view(ADULT, {"c": str(cid), "tab": "report", "view": "year", "year": "2026"}, today)["report"]
    assert y["view"] == "year" and len(y["rows"]) == 12 and y["hours"] == "21.5"
    assert [x["hours"] for x in y["rows"] if x["hours"]] == ["15.5", "6"]
    bad = wd.view(ADULT, {"c": str(cid), "tab": "report", "ym": "1999-01", "view": "year", "year": "abc"}, today)["report"]
    assert bad["year"] == 2026 and bad["ym"] == "2026-10"
