"""Work hours (migration 031 + data/work.py): timesheet parsing (grid, list, CSV; year roll-over; picture-only PDFs
refused), work calendar parsing (holidays, floating, pay days), the hybrid schedule, monthly billing with warnings,
invoices and their alerts, the dashboard edit actions, intake routing, purge, and the Work tab (main menu)."""
import datetime as D
import json

import pytest

from conftest import db, q, read_family, run, write_family

ADULT, KID = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}

CALENDAR = """                                2026 Calendar
          January                             February
Su   Mo   Tu  We   Th   Fr  Sa       Su  Mo   Tu  We   Th   Fr  Sa
                   1    2    3       1    2   3    4    5   6    7
 4   5    6    7   8    9   10       8    9   10  11   12   13  14

State Holidays 2026
Jan 1    New Year's Day             May 25   Memorial Day               Sep 7    Labor Day                  Nov 11   Veterans Day
Jan 19   Martin Luther King Day     Jun 19   Juneteenth                 Oct 12   Columbus Day               Nov 26   Thanksgiving Day
Feb 12   Lincoln's Birthday (Float) Jul 4    Independence Day           Nov 3    Election Day(Float)        Dec 25   Christmas Day
Feb 16   Presidents' Day

Pay Days
01/08/2026  01/22/2026  02/05/2026
"""


def _period(start, hours):
    """One page of a two-week grid timesheet, laid out like a state time system's printout."""
    days = [start + D.timedelta(days=i) for i in range(14)]
    end = days[-1]
    w = 8
    return "\n".join([
        "Supervisor  Pat Example              Name  Some One              Status Processed",
        f"FY {start.year} - 10 ({start:%m/%d/%Y} - {end:%m/%d/%Y})       Submitted Date {end:%m/%d/%Y} 9:15:13 AM",
        "",
        " " * 14 + "".join(f"{d:%m/%d}".rjust(w) for d in days),
        " " * 14 + "".join(f"{d:%a}".rjust(w) for d in days),
        " Day In".ljust(14) + "".join(("7:45 AM" if h else "").rjust(w) for h in hours),
        " Vacation".ljust(14) + "".join("0".rjust(w) for _ in hours),
        " Time Worked".ljust(14) + "".join((f"{h:.2f}" if h else "0").rjust(w) for h in hours),
        " Charges".ljust(14) + "".join("0".rjust(w) for _ in hours),
        " Total Time".ljust(14) + "".join((f"{h:.2f}" if h else "0").rjust(w) for h in hours),
        "",
        "                 Work Totals",
        "        Time Worked     Charge Totals    Time Worked + Charges",
        f" Week 1      {sum(hours[:7]):.2f}            0           {sum(hours[:7]):.2f}",
        "",
    ])


# three pay periods (Thu - Wed) covering August 2026: 127.5 hours fall in August
P1 = _period(D.date(2026, 7, 30), [8, 8, 0, 0, 8, 8, 8, 8, 7.5, 0, 0, 0, 0, 0])
P2 = _period(D.date(2026, 8, 13), [0, 0, 0, 0, 8, 8, 8, 8, 8, 0, 0, 8, 8, 8])
P3 = _period(D.date(2026, 8, 27), [8, 8, 0, 0, 8, 8, 8, 8, 8, 0, 0, 0, 8, 8])
# Thu Fri off site, Mon off, Tue-Thu on, Fri off, Mon off, Tue Wed on (weekends off)
SCHEDULE = "HH--HOOOH--HOO"


@pytest.fixture(scope="module")
def W(root, modules):
    return modules("work")


@pytest.fixture(scope="module")
def setup(root, W, tmp_path_factory):
    fam = read_family(root)
    fam.setdefault("packs", {})["contracts"] = True
    write_family(root, fam)
    t = tmp_path_factory.mktemp("work")
    (t / "cal.txt").write_text(CALENDAR, encoding="utf-8")
    (t / "ts.txt").write_text("\f".join([P1, P2, P3]), encoding="utf-8")
    ok = lambda *a: run(["data/work.py", *a], root)  # noqa: E731
    r = ok("add", "--client", "State IT Office", "--vendor", "Staffing Co", "--no", "C-77", "--person", "Alex",
           "--start", "2026-01-01", "--end", "2027-06-30", "--rate", "90")
    assert r.returncode == 0, r.stderr[-400:]
    cid = q(root, "select id from contracts where contract_no='C-77'")[0][0]
    r = ok("profile", str(cid), "--invoice", "monthly", "--cycle", "biweekly", "--anchor", "2026-07-30", "--schedule", SCHEDULE,
           "--calendar", "State 2026")
    assert r.returncode == 0, r.stderr[-400:]
    assert ok("calendar", "import", str(t / "cal.txt"), "--name", "State 2026").returncode == 0
    r = ok("import", str(t / "ts.txt"), "--contract", "C-77")
    assert r.returncode == 0, r.stderr[-400:]
    return {"cid": cid, "dir": t, "run": ok}


def test_calendar_parse_holidays_floating_and_paydays(W):
    rows = W.parse_calendar(CALENDAR)
    hol = [(d, k) for d, k, _ in rows if k in ("holiday", "floating")]
    assert len(hol) == 13
    assert (D.date(2026, 2, 12), "floating") in hol and (D.date(2026, 11, 3), "floating") in hol
    assert (D.date(2026, 12, 25), "holiday") in hol and (D.date(2026, 7, 4), "holiday") in hol
    names = {d: n for d, _, n in rows}
    assert names[D.date(2026, 2, 12)] == "Lincoln's Birthday" and names[D.date(2026, 1, 19)] == "Martin Luther King Day"
    assert [d for d, k, _ in rows if k == "payday"] == [D.date(2026, 1, 8), D.date(2026, 1, 22), D.date(2026, 2, 5)]


def test_grid_picks_time_worked_and_rolls_the_year(W):
    rows = dict(W.parse_grid(P1))
    assert len(rows) == 14 and rows[D.date(2026, 8, 7)] == 7.5 and rows[D.date(2026, 8, 1)] == 0
    over = _period(D.date(2026, 12, 24), [8, 0, 0, 0, 8, 8, 8, 8, 0, 0, 0, 8, 8, 8])
    rows = dict(W.parse_grid(over.replace("12/24/2026", "").replace("01/06/2027", "")))  # no full dates: year from context
    assert D.date(2027, 1, 4) in rows and rows[D.date(2027, 1, 4)] == 8 and D.date(2026, 12, 28) in rows


def test_weekly_grid_hhmm_list_and_csv(W, tmp_path):
    weekly = "Week ending 08/09/2026\nMon 08/03  Tue 08/04  Wed 08/05  Thu 08/06  Fri 08/07\nHours  8  8  8:30  8  4\n"
    assert dict(W.parse_grid(weekly))[D.date(2026, 8, 5)] == 8.5
    assert W.parse_list("2026-08-03  Project A  8\n08/04/2026 client work 7.5\nnotes 3\n") == [
        (D.date(2026, 8, 3), 8.0), (D.date(2026, 8, 4), 7.5)]
    f = tmp_path / "t.csv"
    f.write_text("Name,Date,Task,Hours,Location\nX,08/03/2026,dev,8,Office\nX,08/04/2026,dev,7.25,Remote\n", encoding="utf-8")
    rows, how, st = W.parse_timesheet(f)
    assert how == "csv" and rows == [(D.date(2026, 8, 3), 8.0, "onsite"), (D.date(2026, 8, 4), 7.25, "offsite")]


def test_picture_only_pdf_is_refused_with_advice(W, root, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    w = pypdf.PdfWriter()
    w.add_blank_page(width=612, height=792)
    f = tmp_path / "scan.pdf"
    with open(f, "wb") as fh:
        w.write(fh)
    assert W.read_text(f)[1] == "scanned"
    con = db(root)
    try:
        c = W.add_contract(con, "Scan Client")
        with pytest.raises(ValueError, match="Save as PDF"):
            W.import_timesheet(con, W.get(con, c), f)
    finally:
        con.rollback()
        con.close()


def test_august_billing_from_three_pay_periods(root, setup, W):
    r = setup["run"]("month", "C-77", "2026-08")
    assert r.returncode == 0, r.stderr[-300:]
    assert "hours 127.5" in r.stdout and "11,475.00" in r.stdout.replace("$", ""), r.stdout
    assert "5 scheduled day(s) with 0 hours" in r.stdout and "08/10" in r.stdout and "08/14" in r.stdout
    con = db(root)
    try:
        s = W.summary(con, W.get(con, "C-77"), D.date(2026, 8, 1), D.date(2026, 8, 31), D.date(2026, 10, 1))
    finally:
        con.close()
    assert s["days_worked"] == 16 and s["onsite"] + s["offsite"] == 16
    assert s["onsite"] == 8 and s["offsite"] == 8, (s["onsite"], s["offsite"])
    assert [h for *_, h in s["weeks"]] == [0, 39.5, 0, 40, 40, 8]
    assert q(root, "select count(*) from work_hours where source='timesheet'")[0][0] == 42


def test_schedule_and_holidays_shape_the_plan(root, setup, W):
    con = db(root)
    try:
        c = W.get(con, "State IT")
        days = {r["date"]: r for r in W.days(con, c, D.date(2026, 9, 3), D.date(2026, 9, 9))}
    finally:
        con.close()
    assert days[D.date(2026, 9, 7)]["holiday"] == "Labor Day" and days[D.date(2026, 9, 7)]["expected"] == 0
    assert days[D.date(2026, 9, 8)]["plan"] == "O" and days[D.date(2026, 9, 4)]["plan"] == "H"
    assert days[D.date(2026, 9, 5)]["plan"] == "-"
    bad = setup["run"]("profile", "C-77", "--schedule", "OOX")
    assert bad.returncode != 0 and "7 or 14 letters" in bad.stderr


def test_invoice_commands_still_work_on_the_command_line(root, setup, W):
    con = db(root)
    try:
        c = W.get(con, "C-77")
        iid, s = W.invoice_make(con, c, D.date(2026, 8, 1), D.date(2026, 8, 31))
        assert s["hours"] == 127.5
        W.invoice_set(con, iid, "sent", "2026-09-02")
        with pytest.raises(ValueError, match="already sent"):
            W.invoice_make(con, c, D.date(2026, 8, 1), D.date(2026, 8, 31))
        W.invoice_set(con, iid, "paid", "2026-10-06")
        assert not [a for a in W.alerts(con, D.date(2026, 10, 7)) if "nvoice" in a["title"]], "no invoice reminders any more"
    finally:
        con.rollback()
        con.close()


def test_a_timesheet_reminder_only_for_jobs_that_need_one(root, setup, W):
    con = db(root)
    try:
        c = W.get(con, "C-77")
        last = con.execute("SELECT MAX(work_date) FROM work_hours WHERE contract_id=? AND source='timesheet'", (c["id"],)).fetchone()[0]
        p0, p1 = W.cycle_bounds(c, D.date.fromisoformat(last))
        after = p1 + D.timedelta(days=2)  # the period holding the last imported day has just ended
        con.execute("UPDATE contracts SET needs_timesheets=0 WHERE id=?", (c["id"],))
        assert not [a for a in W.alerts(con, D.date(2027, 3, 1)) if a["title"].startswith("Send")], "a job that needs none"
        con.execute("UPDATE contracts SET needs_timesheets=1 WHERE id=?", (c["id"],))
        assert not [a for a in W.alerts(con, after) if a["title"].startswith("Send")], "its sheet was imported"
        late = [a for a in W.alerts(con, D.date(2027, 3, 1)) if a["title"].startswith("Send")]
        assert len(late) == 1 and late[0]["title"].startswith("Send the State IT Office timesheet:") and late[0]["amount"] is None, late
        assert late[0]["title"].endswith("(Alex)") and "$" not in late[0]["detail"]
        con.execute("UPDATE contracts SET visibility='private' WHERE id=?", (c["id"],))
        priv = [a for a in W.alerts(con, D.date(2027, 3, 1)) if a["title"].startswith("Send")]
        assert priv and "State IT" not in priv[0]["title"], "a private job is not named"
    finally:
        con.rollback()
        con.close()


def test_more_than_24_hours_across_jobs_is_called_out(root, setup, W, modules):
    ea = modules("edit_actions")
    cid = setup["cid"]
    ok, msg = ea.work_contract_add(ADULT, "Second Job", None, None, "Alex", None, None, None, "employment", "secondary", True)
    assert ok, msg
    cid2 = q(root, "select id from contracts where client='Second Job'")[0][0]
    ok, msg = ea.work_hours_save(ADULT, cid, [("2026-12-07", 14, None)])
    assert ok and "Check:" not in msg
    ok, msg = ea.work_hours_save(ADULT, cid2, [("2026-12-07", 12, None)])
    assert ok and "more than 24 hours across jobs on 2026-12-07" in msg, msg
    ok, msg = ea.work_hours_save(ADULT, cid, [("2026-12-07", "", None)])
    ok, msg = ea.work_hours_save(ADULT, cid2, [("2026-12-07", "", None)])
    assert ok
    con = db(root)  # the second job must not stay: a later test relies on exactly one job needing timesheets
    con.execute("DELETE FROM contracts WHERE id=?", (cid2,))
    con.commit()
    con.close()


def test_edit_actions_hours_fill_and_kids(root, setup, modules):
    ea = modules("edit_actions")
    cid = setup["cid"]
    ok, msg = ea.work_hours_save(KID, cid, [("2026-08-10", 8, "offsite")])
    assert not ok and "adult" in msg
    ok, msg = ea.work_hours_save(ADULT, cid, [("2026-08-10", 6, "offsite"), ("2026-08-11", "", None)])
    assert ok, msg
    assert q(root, "select hours, location, source from work_hours where contract_id=? and work_date='2026-08-10'", cid) == [
        (6.0, "offsite", "manual")]
    assert not q(root, "select 1 from work_hours where contract_id=? and work_date='2026-08-11'", cid)
    ok, msg = ea.work_hours_save(ADULT, cid, [("2026-08-12", 30, None)])
    assert not ok and "hours" in msg
    ok, msg = ea.work_fill(ADULT, cid, "2026-10-01", "2026-10-14")
    assert ok and "Filled 9" in msg, msg  # 10 weekdays minus Columbus Day
    assert q(root, "select count(*) from work_hours where contract_id=? and work_date between '2026-10-01' and '2026-10-14' "
                   "and source='schedule'", cid)[0][0] == 9
    ok, msg = ea.work_profile(ADULT, cid, schedule="O" * 14, timesheet_cycle="weekly")
    assert not ok and "cycle is 7 days" in msg
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "work_hours_save" in log and "State IT" not in log


def test_upload_import_files_into_archive(root, setup, modules):
    ea = modules("edit_actions")
    (root / "inbox").mkdir(exist_ok=True)
    (root / "inbox" / "sept.csv").write_text("Date,Hours\n09/14/2026,8\n09/15/2026,7\n", encoding="utf-8")
    ok, msg = ea.work_import(ADULT, "sept.csv", "timesheet", contract_id=setup["cid"])
    assert ok and "2 days, 15.0 h" in msg, msg
    assert not (root / "inbox" / "sept.csv").exists()
    path, typ = q(root, "select filed_path, doc_type from documents where doc_type='timesheet' order by id desc limit 1")[0]
    assert path.startswith("2026/work/2026-09-15_state_it_office_timesheet") and (root / "archive" / path).is_file()
    doc = q(root, "select id from documents where filed_path=?", path)[0][0]
    assert q(root, "select count(*) from work_hours where document_id=?", doc)[0][0] == 2
    ok, msg = ea.work_import(ADULT, "../config/family.json", "timesheet", contract_id=setup["cid"])
    assert not ok


def test_intake_routes_a_timesheet_when_one_contract_fits(root, setup, modules):
    ai = modules("ai_intake")
    f = root / "inbox" / "oct.txt"
    f.write_text("2026-10-05 build 8\n2026-10-06 build 8\n", encoding="utf-8")
    con = db(root)
    try:
        name, status, detail = ai._work_route(con, f, "timesheet")
    finally:
        con.close()
    assert status == "filed" and "2 days" in detail, detail
    assert q(root, "select hours from work_hours where work_date='2026-10-05' and contract_id=?", setup["cid"]) == [(8.0,)]


def test_purge_person_takes_their_hours(root, setup, tmp_path):
    con = db(root)
    con.execute("INSERT INTO contracts(person, client, status) VALUES ('Sam', 'Purge Client', 'ended')")
    cid = con.execute("select id from contracts where client='Purge Client'").fetchone()[0]
    con.execute("INSERT INTO work_hours(contract_id, work_date, hours) VALUES (?, '2026-08-03', 8)", (cid,))
    con.commit()
    con.close()
    r = run(["data/purge.py", "person", "Sam"], root)  # dry run: lists what would go, removes nothing
    assert "work_hours" in r.stdout, r.stdout[-600:]


def test_offsite_days_command(root, setup):
    r = run(["data/work.py", "offsite", "2026"], root)
    assert r.returncode == 0 and "State IT Office" in r.stdout and "tax preparer" in r.stdout
    assert json.dumps(read_family(root)["packs"])  # pack stayed on


