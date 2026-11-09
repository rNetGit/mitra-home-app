"""Work is jobs and businesses (migration 066): kind, primary / secondary, needs timesheets, who can see it; no money fields."""
from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}
OTHER = {"name": "Bo", "role": "adult"}


def test_jobs_have_a_kind_a_rank_and_timesheet_flag(root, modules):
    ea = modules("edit_actions")
    cols = {r[1] for r in q(root, "PRAGMA table_info(contracts)")}
    assert {"kind", "rank", "needs_timesheets", "show_on_calendar", "visibility"} <= cols
    ok, msg = ea.work_contract_add(ADULT, "Acme Corp", None, None, "Alex", None, None, None, "employment", "primary", True)
    assert ok, msg
    ok, msg = ea.work_contract_add(ADULT, "Rental LLC", None, None, "Alex", None, None, None, "rental", "secondary", False)
    assert ok, msg
    assert q(root, "SELECT client, kind, rank, needs_timesheets, visibility, hourly_rate FROM contracts ORDER BY id") == \
        [("Acme Corp", "employment", "primary", 1, "shared", None), ("Rental LLC", "rental", "secondary", 0, "shared", None)]
    assert ea.work_contract_add(ADULT, "X", None, None, None, None, None, None, "bogus")[0] is False
    assert ea.work_contract_add(ADULT, "X", None, None, None, None, None, None, "contract", "third")[0] is False
    assert ea.work_contract_add(KID, "X")[0] is False, "children cannot"


def test_profile_can_change_kind_rank_visibility(root, modules):
    ea = modules("edit_actions")
    ea.work_contract_add(ADULT, "Side gig", None, None, "Alex", None, None, None, "side", "secondary", False)
    cid = q(root, "SELECT id FROM contracts WHERE client='Side gig'")[0][0]
    ok, msg = ea.work_profile(ADULT, cid, rank="primary", needs_timesheets="1", visibility="private", kind="business")
    assert ok, msg
    assert q(root, "SELECT kind, rank, needs_timesheets, visibility FROM contracts WHERE id=?", cid) == [("business", "primary", 1, "private")]
    assert ea.work_profile(ADULT, cid, visibility="everyone")[0] is False
    assert ea.work_profile(ADULT, cid, needs_timesheets="2")[0] is False
    assert ea.work_profile(ADULT, cid, kind="")[0] is False, "kind cannot be cleared"


def test_the_work_page_opens_on_your_primary_job(root, modules):
    ea, wd = modules("edit_actions"), modules("work_data")
    wd.on = lambda: True
    with db(root) as con:
        if not con.execute("SELECT 1 FROM members WHERE name='Bo'").fetchone():
            con.execute("INSERT INTO members (name, role) VALUES ('Bo', 'adult')")
    ea.work_contract_add(ADULT, "AAA Side Gig", None, None, "Alex", None, None, None, "side", "secondary", False)
    ea.work_contract_add(ADULT, "ZZZ Main Employer", None, None, "Alex", None, None, None, "employment", "primary", True)
    ea.work_contract_add(OTHER, "000 Bo Employer", None, None, "Bo", None, None, None, "employment", "primary", True)
    labels = [c["label"] for c in wd.view(ADULT, {})["contracts"] if c["label"][:3] in ("AAA", "ZZZ", "000")]
    assert labels == ["ZZZ Main Employer", "AAA Side Gig (secondary)"], "the signed-in adult's own jobs only"
    v = wd.view(ADULT, {"who": "Bo"})
    assert v["who"] == "Bo" and [c["label"] for c in v["contracts"] if c["label"][:3] == "000"] == ["000 Bo Employer"]
    assert not [c for c in v["contracts"] if c["label"][:3] in ("AAA", "ZZZ")], "Alex's jobs are not under Bo"
    assert wd.view(ADULT, {"c": str(v["c"]["id"])})["who"] == "Bo", "a link to one job shows its person"
    assert wd.view(ADULT, {"who": "Nobody"})["who"] == "Alex" and "Alex" in wd.view(ADULT, {})["people"]
    assert wd.view(ADULT, {})["c"]["client"] == "ZZZ Main Employer" or wd.view(ADULT, {})["c"]["person"] == "Alex"


def test_who_lists_adults_only_and_a_child_cannot_hold_a_job(root, modules):
    ea, wd = modules("edit_actions"), modules("work_data")
    wd.on = lambda: True
    assert "Sam" not in wd.view(ADULT, {})["people"] and "Alex" in wd.view(ADULT, {})["people"] and "Biscuit" not in wd.view(ADULT, {})["people"]
    ok, msg = ea.work_contract_add(ADULT, "Kid Job", None, None, "Sam", None, None, None, "side", "secondary", False)
    assert not ok and "adult" in msg, msg
    ea.work_contract_add(ADULT, "Adult Job", None, None, "Alex", None, None, None, "employment", "primary", False)
    cid = q(root, "SELECT id FROM contracts WHERE client='Adult Job'")[0][0]
    ok, msg = ea.work_profile(ADULT, cid, person="Sam")
    assert not ok and "adult" in msg, msg
    assert ea.work_profile(ADULT, cid, person="Alex")[0]


def test_remote_and_office_words_are_the_same_everywhere(root, modules):
    wd = modules("work_data")
    assert wd.PLAN_LABEL["O"].startswith("Office") and wd.PLAN_LABEL["H"].startswith("Remote")
    assert wd.LOC_LABEL == {"onsite": "Office (on site)", "offsite": "Remote (off site)"}
