"""The data/ scripts a family runs: digests and reports, done/snooze, date validation, life/budget/loans/home office,
ask_sql safety, demo removal, the scheduled runner, doctor, seasonal packs."""
import datetime as dt
import re
import sqlite3

import pytest

from conftest import DRY, db, q, run

REPORTS = (["data/make_digest.py"], ["data/make_this_week.py"], ["data/make_family_meeting.py"],
           ["data/make_family_meeting.py", "--who", "Sam"], ["data/make_report.py", "weekly"],
           ["data/make_report.py", "monthly"], ["data/tax_prep.py"], ["data/year_end.py"],
           ["data/emergency_sheet.py"], ["data/make_dashboard.py"], ["data/backup.py"])


@pytest.mark.parametrize("args", REPORTS, ids=lambda a: " ".join(a))
def test_report_scripts_run(root, args):
    r = run(args, root)
    assert r.returncode == 0, (r.stderr.strip().splitlines() or [""])[-1]


def _digest(root):
    run(["data/make_digest.py"], root)
    return next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")


def test_digest_and_meeting_content(root):
    digest = _digest(root)
    assert "| Id |" in digest
    run(["data/make_family_meeting.py"], root)
    meeting = next((root / "brief").glob("*_family_meeting.md")).read_text(encoding="utf-8")
    assert "birthday" in meeting.lower()


def test_action_state_done_and_snooze(root):
    ids = re.findall(r"^\| ([0-9a-f]{8}) \|", _digest(root), re.M)
    assert ids, "digest exposes item ids"
    assert run(["data/action_state.py", "done", ids[0]], root).returncode == 0
    assert ids[0] not in _digest(root)
    run(["data/action_state.py", "snooze", ids[-1], "7"], root)
    assert run(["data/action_state.py", "list"], root).returncode == 0
    r = run(["data/action_state.py", "snooze", ids[-1], "tomorrow"], root)
    assert r.returncode != 0 and "YYYY-MM-DD" in (r.stderr + r.stdout)


def test_digest_survives_bad_rows_and_lists_one_off_events_once(root):
    con = db(root)
    con.execute("INSERT OR REPLACE INTO action_state(key, state, until) VALUES ('deadbeef','snoozed','tomorrow')")
    con.execute("INSERT INTO events(name, event_date, recurs_yearly) VALUES ('One-off party', ?, 0)",
                ((dt.date.today() + dt.timedelta(days=5)).isoformat(),))
    con.commit()
    con.close()
    r = run(["data/make_digest.py"], root)
    assert r.returncode == 0, r.stderr[-300:]
    d = next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")
    assert d.count("One-off party") == 1


def test_seasonal_add_refuses_impossible_day(root):
    assert run(["data/seasonal.py", "add", "Bad window", "Home", "02-30", "03-15"], root).returncode != 0


def test_life_items(root):
    assert run(["data/life.py", "add", "school", "Report card signed", "--who", "sam", "--due", "2099-01-05"], root).returncode == 0
    assert "Sam" in run(["data/life.py", "list", "school"], root).stdout
    r = run(["data/life.py", "done", "Report card signed", "2026-13-01"], root)
    assert r.returncode != 0 and "YYYY-MM-DD" in (r.stderr + r.stdout)
    assert run(["data/life.py", "done", "Vet checkup"], root).returncode in (0, 1)


def test_budget_and_loans(root):
    assert run(["data/budget.py", "set", "groceries", "300"], root).returncode == 0
    assert "groceries" in run(["data/budget.py", "report"], root).stdout
    assert run(["data/loans.py", "add", "Test loan", "--kind", "auto", "--balance", "5000", "--rate", "6", "--payment", "200"], root).returncode == 0


def test_home_office_report(root):
    assert run(["data/home_office.py", "profile", "2025", "Alex", "--office-sqft", "100", "--home-sqft", "1000", "--months", "12",
                "--self-employed", "1", "--exclusive", "1", "--regular", "1", "--principal", "1", "--income", "40000"], root).returncode == 0
    assert run(["data/home_office.py", "add", "2025", "utilities", "1200", "--desc", "annual electric"], root).returncode == 0
    r = run(["data/home_office.py", "report", "2025"], root)
    rep = root / "reports" / "2025_home_office.md"
    assert r.returncode == 0 and rep.exists()
    txt = rep.read_text(encoding="utf-8")
    assert "$500.00" in txt, "simplified = 100 sqft x $5"
    assert "$120.00" in txt, "regular = 1200 x 10%"
    assert "not tax advice" in txt.lower()
    run(["data/tax_prep.py", "2025"], root)
    assert "Home office" in (root / "reports" / "2025_tax_prep.md").read_text(encoding="utf-8")


def test_ask_sql_is_read_only(root):
    assert run(["data/ask_sql.py", "SELECT count(*) FROM members"], root).returncode == 0
    assert run(["data/ask_sql.py", "DELETE FROM members"], root).returncode != 0
    assert run(["data/ask_sql.py", "SELECT 1; DROP TABLE members"], root).returncode != 0
    assert q(root, "select count(*) from members")[0][0] == 3


def test_demo_remove_leaves_no_demo_rows(root):
    assert run(["data/seed_demo.py", "--remove"], root).returncode == 0
    assert q(root, "select count(*) from bills where name like '[DEMO]%'")[0][0] == 0


def test_run_task_weekly_backup_records_heartbeat(root):
    r = run(["tasks/run_task.py", "weekly_backup"], root)
    assert r.returncode == 0, r.stderr[-200:]
    hb = root / "logs" / "heartbeat.json"
    assert hb.exists() and "weekly_backup" in hb.read_text(encoding="utf-8")


def test_doctor_runs_dry(root):
    r = run(["onboard.py", "doctor"], root, env=DRY)
    assert "checks passed" in r.stdout, r.stderr[-200:]


def test_seasonal_packs(root):
    assert "uk" in run(["data/seasonal_packs.py", "list"], root).stdout
    r = run(["data/seasonal_packs.py", "apply", "us_hot", "--addons", "hurricane"], root)
    assert r.returncode == 0, r.stderr[-200:]
    active = [n for (n,) in q(root, "select name from seasonal_tasks where active=1")]
    assert not any("Snow blower" in n for n in active)
    assert any("Hurricane kit" in n for n in active)
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("insert into seasonal_tasks(name, category, start_md, end_md) values ('My own task','Home','01-01','01-31')")
    con.commit()
    con.close()
    run(["data/seasonal_packs.py", "apply", "uk"], root)
    assert q(root, "select active from seasonal_tasks where name='My own task'")[0][0] == 1
    assert q(root, "select active from seasonal_tasks where name='Boiler annual service'")[0][0] == 1
    assert run(["data/seasonal_packs.py", "recommend", "AU"], root).stdout.strip() == "australia_nz"
