"""0.44.0 setup interview (data/setup_interview.py, data/dashboard/interview.py): answers are validated in plain
language, progress is saved as a draft without secrets, finishing builds the database through the wizard's own
code, PINs are stored hashed, and the dashboard shows the interview on a PC that is not set up yet."""
import json

import pytest

from conftest import bind, copy_template, q

PIN = "4821"


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    """A template copy with NO family set up and no database."""
    r = copy_template(tmp_path_factory.mktemp("iv") / "t")
    for f in ("config/family.json", "data/family.db"):
        (r / f).unlink(missing_ok=True)
    bind(r)
    return r


@pytest.fixture(scope="module")
def S(fresh):
    import importlib
    return importlib.import_module("setup_interview")


def answers(**kw):
    a = {"family_name": "The Test family", "country": "US", "place": "Austin", "state": "TX", "zip": "78701", "climate": "mild",
         "currency": "", "home_office": False, "accept_rules": True,
         "members": [{"name": "Alex", "role": "adult", "birth_month_day": "03-14", "birth_year": 1980},
                     {"name": "Sam", "role": "child", "birth_month_day": "", "birth_year": None},
                     {"name": "Rex", "role": "pet", "birth_month_day": "", "birth_year": None}]}
    a.update(kw)
    return a


def test_a_fresh_pc_needs_setup_and_answers_are_checked_in_plain_language(fresh, S):
    assert S.needed() is True
    assert S.validate("Family", answers(family_name="  ")) and "name" in S.validate("Family", answers(family_name=""))[0]
    assert S.validate("Family", answers(climate="stormy"))
    assert S.validate("Family", answers(currency="DOLLARS"))
    assert S.validate("Family", answers()) == []
    assert S.validate("People", answers(members=[])) == ["Add at least one person."]
    kids = [{"name": "Sam", "role": "child", "birth_month_day": "", "birth_year": None}]
    assert any("adult" in p for p in S.validate("People", answers(members=kids)))
    dup = answers()["members"] + [{"name": "alex", "role": "adult", "birth_month_day": "", "birth_year": None}]
    assert any("already" in p for p in S.validate("People", answers(members=dup)))
    bad = answers()["members"] + [{"name": "Zed", "role": "adult", "birth_month_day": "78-01", "birth_year": 1980}]
    assert any("month" in p for p in S.validate("People", answers(members=bad)))
    assert S.valid_birthday(2, 29) and not S.valid_birthday(2, 30) and not S.valid_birthday(13, 1) and not S.valid_birthday(4, 31)
    assert S.member_problem({"name": "A<b>", "role": "adult"}) and S.member_problem({"name": "Ann", "role": "robot"})
    assert S.member_problem({"name": "Ann", "role": "adult", "birth_year": "19"}) and S.member_problem({"name": "Ann", "role": "adult", "birth_year": 2999})
    assert any("rules" in p for p in S.validate("Finish", answers(accept_rules=False)))


def test_draft_saves_progress_and_never_a_pin(fresh, S):
    a = answers(step=3, pins={"Alex": PIN}, logins_on=True)
    S.save_draft(a)
    raw = (fresh / "config" / "setup_draft.json").read_text(encoding="utf-8")
    assert PIN not in raw and "pins" not in raw
    d = S.defaults()
    assert d["family_name"] == "The Test family" and d["step"] == 3 and len(d["members"]) == 3
    S.clear_draft()
    assert not (fresh / "config" / "setup_draft.json").exists()


def test_finish_builds_everything_and_stores_pins_hashed(fresh, S):
    ok, msgs = S.finish(answers(accept_rules=False))
    assert ok is False and any("rules" in m for m in msgs) and S.needed() is True, "nothing built without the rules"
    ok, msgs = S.finish(answers(), pins={"Alex": PIN, "Sam": "1357", "Rex": "9999", "Nobody": "5555"})
    assert ok, msgs
    assert S.needed() is False
    fam = json.loads((fresh / "config" / "family.json").read_text(encoding="utf-8"))
    assert fam["family_name"] == "The Test family" and fam["country"] == "US" and fam["climate"] == "mild"
    assert fam["region"]["place"] == "Austin" and fam["currency"] == "USD" and fam["seasonal_pack"]
    assert [m["name"] for m in fam["members"]] == ["Alex", "Sam", "Rex"]
    users = {u["name"]: u for u in fam["dashboard_users"]}
    assert set(users) == {"Alex", "Sam"}, "pets and unknown names get no login"
    assert users["Alex"]["role"] == "adult" and users["Sam"]["role"] == "limited"
    # PINs only as salted hashes. Look outside the hashes: their random hex can hold "4821" by chance (failed CI once).
    assert all(u["pin_hash"].startswith("pbkdf2$") for u in users.values())
    plain = json.dumps({**fam, "dashboard_users": [{k: v for k, v in u.items() if k != "pin_hash"} for u in fam["dashboard_users"]]})
    assert PIN not in plain and "1357" not in plain
    assert fam["ui"] == {"mode": "advanced"}, "a brand-new install starts in the Advanced view"
    assert fam["ai"]["provider"] == "none", "no AI picked = No AI, so the Inbox's File now works without one"
    assert {r[0] for r in q(fresh, "select name from members")} >= {"Alex", "Sam", "Rex"}
    assert q(fresh, "select count(*) from recurring_items where who='Alex'")[0][0] >= 2
    assert not (fresh / "config" / "setup_draft.json").exists()
    ok2, _ = S.finish(answers(paper_names=["Alexander Q Test"]), pins=None)
    assert ok2, "safe to run again"
    fam = json.loads((fresh / "config" / "family.json").read_text(encoding="utf-8"))
    assert fam["privacy"]["paper_names"] == ["Alexander Q Test"], "names on papers from the People step"
    assert fam["ui"] == {"mode": "advanced"}
    assert q(fresh, "select count(*) from members where name='Alex'") == [(1,)]


def test_no_car_in_the_interview_counts_as_answered_in_the_profile_meter(fresh, S):
    import importlib
    import db
    G = importlib.import_module("profile_gaps")

    def vehicles_done():
        con = db.connect(fresh / "data" / "family.db", readonly=True)
        try:
            return {c["key"]: c["done"] for c in G.checks(con)}["profile:vehicles"]
        finally:
            con.close()

    def household():
        return json.loads((fresh / "config" / "family.json").read_text(encoding="utf-8")).get("household") or {}

    assert S.finish(answers(cars_done=False, vehicles=[]))[0]
    assert vehicles_done() is False and "no_vehicles" not in household(), "step not reached: still a gap"
    assert S.finish(answers(cars_done=True, vehicles=[]))[0]
    assert household().get("no_vehicles") is True and vehicles_done() is True
    assert S.finish(answers(cars_done=True, vehicles=[{"year": 2019, "make": "Honda", "model": "CR-V"}]))[0]
    assert "no_vehicles" not in household() and vehicles_done() is True, "a car on file answers it too"


