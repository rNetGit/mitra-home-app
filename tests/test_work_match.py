"""Which job does a timesheet belong to (Work S2): the matcher, "Which job?" in the Inbox, saved phrases, private jobs,
and the safety rules of an import (no wrong-job fallthrough, days outside the job are not written)."""
import datetime as D

import pytest
from conftest import db, q

@pytest.fixture(autouse=True)
def _clean(root, modules):
    modules("edit_actions")  # the household's database exists
    with db(root) as con:
        for t in ("work_match_rules", "work_hours", "work_invoices", "contracts", "review_queue", "proposals"):
            con.execute(f"DELETE FROM {t}")
    yield


ADULT = {"name": "Alex", "role": "adult"}
OTHER = {"name": "Bo", "role": "adult"}


def _job(ea, name, person="Alex", **kw):
    ok, msg = ea.work_contract_add(ADULT, name, kw.get("vendor"), kw.get("number"), person, kw.get("start"), kw.get("end"), None,
                                   kw.get("kind", "employment"), kw.get("rank", "primary"), True)
    assert ok, msg
    return None


def _ids(root):
    return {r[0]: r[1] for r in q(root, "SELECT client, id FROM contracts")}


def test_matcher_picks_by_name_number_and_never_guesses_between_two(root, modules):
    ea, wm = modules("edit_actions"), modules("work_match")
    _job(ea, "Acme Corp", number="AC-7788")
    _job(ea, "Globex", person="Bo")
    con = modules("db").connect(modules("paths").DB)
    c = wm.candidates(con, "Timesheet for Acme Corp week of Oct 5")
    assert c[0]["label"].startswith("Acme") and wm.choose(c)["label"].startswith("Acme")
    assert wm.choose(wm.candidates(con, "contract AC-7788 hours"))["label"].startswith("Acme")
    assert wm.choose(wm.candidates(con, "some unrelated sheet")) is None, "two jobs and no clue: a person picks"
    assert wm.choose(wm.candidates(con, "some unrelated sheet", uploader="Bo")) is None, "being the uploader alone is not enough"
    assert wm.choose(wm.candidates(con, "Acme Corp and Globex both appear")) is None
    wm.rule_add(con, _ids(root)["Globex"], "G-Time Portal")
    con.commit()
    assert wm.choose(wm.candidates(con, "exported from the g-time portal"))["label"].startswith("Globex")
    con.close()


def test_one_job_needing_timesheets_takes_the_sheet_and_private_jobs_stay_private(root, modules):
    ea, wm = modules("edit_actions"), modules("work_match")
    _job(ea, "Only Employer")
    con = modules("db").connect(modules("paths").DB)
    assert wm.choose(wm.candidates(con, "anything"))["label"].startswith("Only")
    cid = _ids(root)["Only Employer"]
    ea.work_profile(ADULT, cid, visibility="private")
    assert wm.candidates(con, "anything") == [], "a private job is not offered without its owner"
    assert [x["label"] for x in wm.candidates(con, "anything", uploader="Alex")] == ["Only Employer (Alex)"]
    assert modules("work_data")._guard(OTHER, cid) == "That job is private to its owner."
    assert modules("work_data")._guard(ADULT, cid) is None
    assert modules("work_data")._guard(ADULT, 9999) == "No such job."
    con.close()


def test_which_job_card_imports_and_remembers(root, modules):
    ea, paths = modules("edit_actions"), modules("paths")
    _job(ea, "Acme Corp")
    _job(ea, "Globex", person="Bo")
    ids = _ids(root)
    nr = paths.INBOX / "needs_review"
    nr.mkdir(parents=True, exist_ok=True)
    day = D.date.today().replace(day=1)
    f = nr / "sheet.csv"
    f.write_text(f"Date,Hours\n{day:%m/%d/%Y},6\n", encoding="utf-8")
    con = modules("db").connect(paths.DB)
    con.execute("INSERT INTO review_queue(path, reason, detail) VALUES (?,?,?)", (paths.rel(f), "timesheet: which job is it for?", ""))
    con.commit()
    rid = con.execute("SELECT id FROM review_queue ORDER BY id DESC").fetchone()[0]
    con.close()
    pr = modules("proposals")
    pr.sync()
    c = modules("db").connect(paths.DB)
    item = next(i for i in pr.items(c) if i["source"] == "review" and i["payload"].get("review_id") == rid)
    c.close()
    assert "job" in item["options"] and [j["label"] for j in item["payload"]["jobs"]] == ["Acme Corp (Alex)", "Globex (Bo)"]
    assert "whose timesheet" in item["summary"]
    assert pr.decide({"name": "Sam", "role": "limited"}, item["id"], "job", contract=str(ids["Acme Corp"]))[0] is False
    assert pr.decide(ADULT, item["id"], "job")[0] is False, "the job is required"
    ok, msg = pr.decide(ADULT, item["id"], "job", contract=str(ids["Acme Corp"]), phrase="ACME Payroll Portal")
    assert ok, msg
    assert q(root, "SELECT hours, source FROM work_hours WHERE contract_id=? AND work_date=?", ids["Acme Corp"], day.isoformat()) == [(6.0, "timesheet")]
    assert q(root, "SELECT pattern, contract_id FROM work_match_rules") == [("acme payroll portal", ids["Acme Corp"])]
    assert q(root, "SELECT resolved FROM review_queue WHERE id=?", rid) == [(1,)]


def test_web_ids_never_fall_through_and_imports_skip_days_outside_the_job(root, modules):
    ea, paths, W = modules("edit_actions"), modules("paths"), modules("work")
    _job(ea, "Acme Corp", number="7", start="2026-03-01", end="2026-03-31")
    cid = _ids(root)["Acme Corp"]
    assert ea.work_hours_save(ADULT, 7, [("2026-03-02", "8", None)])[0] is False, "id 7 does not exist; contract number 7 is not used"
    assert ea.work_hours_save(ADULT, cid, [("2026-03-02", "8", None)])[0] is True
    f = paths.INBOX / "march.csv"
    f.write_text("Date,Hours\n03/03/2026,7\n04/02/2026,5\n", encoding="utf-8")
    con = modules("db").connect(paths.DB)
    rep = W.import_timesheet(con, W.get_by_id(con, cid), f)
    con.commit()
    con.close()
    assert [r.isoformat() for r in rep["outside_contract"]] == ["2026-04-02"]
    assert q(root, "SELECT work_date FROM work_hours WHERE contract_id=? ORDER BY work_date", cid) == [("2026-03-02",), ("2026-03-03",)]
    assert W._hours_value("7:30") == 7.5
    try:
        W._hours_value("8:75")
        raise AssertionError("minutes of 60 or more must be refused")
    except ValueError:
        pass


def test_planned_hours_are_not_saved_as_worked_hours(root, modules):
    ea, wd = modules("edit_actions"), modules("work_data")
    _job(ea, "Acme Corp")
    cid = _ids(root)["Acme Corp"]
    wd.on = lambda: True  # the work pack is switched on for this household
    ok, msg = wd.act(ADULT, "hours", {"c": str(cid), "h_2026-03-02": "8", "w_2026-03-02": "onsite", "e_2026-03-02": "8|onsite"})
    assert (ok, msg) == (False, "No days to save."), "an untouched planned row is skipped"
    ok, msg = wd.act(ADULT, "hours", {"c": str(cid), "h_2026-03-02": "7", "w_2026-03-02": "onsite", "e_2026-03-02": "8|onsite"})
    assert ok, msg
    assert q(root, "SELECT hours, source FROM work_hours") == [(7.0, "manual")], "a changed row is saved"
