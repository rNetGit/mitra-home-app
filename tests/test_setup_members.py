"""The setup page's household members as one row per person (first_run.rows_*, setup_data ops addrow / remove / paste):
parsing, plain error messages, pets and children, the pasted-list fallback, and the form posts end to end."""
import importlib
import json
import re

import pytest

from conftest import bind, copy_template

@pytest.fixture(scope="module")
def fr(tmp_path_factory):
    bind(copy_template(tmp_path_factory.mktemp("fr") / "t", family=False))
    return importlib.import_module("first_run")


def _row(name="", role="", month="", day="", year=""):
    return {"name": name, "role": role, "month": month, "day": day, "year": year}


def test_rows_to_members_reads_every_field(fr):
    ms, bad = fr.rows_to_members([_row("Alex", "adult", "3", "14", "1980"), _row("Sam", "child", "5", "2"),
                                  _row("Rex", "pet"), _row()])
    assert bad == []
    assert ms == [{"name": "Alex", "role": "adult", "birth_month_day": "03-14", "birth_year": 1980},
                  {"name": "Sam", "role": "child", "birth_month_day": "05-02", "birth_year": None},
                  {"name": "Rex", "role": "pet", "birth_month_day": "", "birth_year": None}]


@pytest.mark.parametrize("row,words", [
    (_row("", "adult", "3", "14"), "type a name"),
    (_row("Alex", "", ""), "choose adult, child or pet"),
    (_row("Alex", "robot"), "adult, child or pet"),
    (_row("Alex", "adult", "3", ""), "both a month and a day"),
    (_row("Alex", "adult", "", "9"), "both a month and a day"),
    (_row("Alex", "adult", "2", "30"), "not a real date"),
    (_row("Alex", "adult", "13", "1"), "not a real date"),
    (_row("Alex", "adult", "", "", "78"), "four digits"),
    (_row("Alex", "adult", "", "", "3000"), "birth year"),
    (_row("A<b>", "adult"), "letters"),
])
def test_row_problems_are_plain_and_name_the_row(fr, row, words):
    ms, bad = fr.rows_to_members([_row("First", "adult"), row])
    assert [m["name"] for m in ms] == ["First"]
    assert len(bad) == 1 and bad[0].startswith("Person 2") and words in bad[0], bad


def test_duplicate_names_and_year_only(fr):
    ms, bad = fr.rows_to_members([_row("Alex", "adult", "", "", "1980"), _row("alex", "child")])
    assert ms[0]["birth_year"] == 1980 and ms[0]["birth_month_day"] == ""
    assert len(bad) == 1 and "already in the list" in bad[0]


def test_form_rows_keep_screen_order_and_paste_is_appended(fr):
    d = {"m_name_10": "Third", "m_role_10": "pet", "m_name_2": "First", "m_role_2": "adult", "m_name_3": "Second",
         "m_month_3": "12", "m_day_3": "25", "other": "x"}
    rows, bad = fr.rows_from_form(d, "Mia, child, 5/2/2012\n12/05", "mdy")
    assert [r["name"] for r in rows[:3]] == ["First", "Second", "Third"]
    assert rows[3]["name"] == "Mia" and rows[3]["month"] == "5" and rows[3]["day"] == "2" and rows[3]["year"] == "2012"
    assert rows[1]["month"] == "12"
    assert bad, "a pasted line with no name is reported, not lost"


def test_rows_round_trip_through_saved_members(fr):
    ms = [{"name": "Alex", "role": "adult", "birth_month_day": "03-14", "birth_year": 1980},
          {"name": "Rex", "role": "pet", "birth_month_day": "", "birth_year": None}]
    assert fr.rows_to_members(fr.member_rows(ms)) == (ms, [])


def test_row_count_is_capped(fr):
    d = {f"m_name_{i}": f"P{i}" for i in range(60)}
    assert len(fr.rows_from_form(d)[0]) == fr.MAX_ROWS


# ---- the form, end to end ----------------------------------------------------------------------------------------
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    r = copy_template(tmp_path_factory.mktemp("wm") / "t")
    for f in ("config/family.json", "data/family.db"):
        (r / f).unlink(missing_ok=True)
    bind(r)
    app_mod = importlib.import_module("webapp.app")
    importlib.import_module("webapp.sessions").clear()
    app_mod.LOCAL_HOSTS = app_mod.LOCAL_HOSTS | {"testclient"}
    return r, TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)


def _post(c, token, step, op="next", **data):
    return c.post("/setup", data={"op": op, "step": str(step), **data}, headers={"X-CSRF-Token": token})


def test_member_rows_form_posts(fresh):
    root, c = fresh
    r = c.get("/setup")
    token = re.search(r'name="csrf-token" content="([^"]+)"', r.text).group(1)
    assert "Step 1 of 6" in r.text
    assert "Step 2 of 6" in _post(c, token, 0, accept="1").text
    fam = dict(family_name="The Rows family", country="US", place="Austin", state="TX", climate="mild", currency="usd")
    page = _post(c, token, 1, op="check", **fam).text
    assert 'name="m_name_0"' in page and "Add another person" in page and "Rather paste a list?" in page
    # a refused screen shows every row again, with a plain sentence for the bad one
    rows = dict(m_name_0="Alex", m_role_0="adult", m_month_0="3", m_day_0="14", m_year_0="1980",
                m_name_1="Sam", m_role_1="child", m_month_1="2", m_day_1="31")
    r = _post(c, token, 1, **fam, **rows)
    assert "Person 2 (Sam): that birthday is not a real date." in r.text and "Step 2 of 6" in r.text
    assert 'value="Sam"' in r.text and 'value="Alex"' in r.text
    # add / remove / paste change the rows only; nothing is saved or checked
    r = _post(c, token, 1, op="addrow", **fam, **{**rows, "m_day_1": "2"})
    assert 'name="m_name_2"' in r.text and "Step 2 of 6" in r.text
    assert "The Rows family" in r.text and 'value="Austin"' in r.text, "the other boxes keep what was typed"
    r = _post(c, token, 1, op="remove", idx="0", **fam, **{**rows, "m_day_1": "2"})
    assert 'value="Alex"' not in r.text and 'value="Sam"' in r.text
    r = _post(c, token, 1, op="paste", **fam, **{**rows, "m_day_1": "2"}, people="Rex the dog; Mia, child, 5/2/2012")
    assert 'value="Rex"' in r.text and 'value="Mia"' in r.text and 'name="m_year_3"' in r.text
    # no adult: the existing rule still speaks
    r = _post(c, token, 1, **fam, m_name_0="Sam", m_role_0="child", m_name_1="Rex", m_role_1="pet")
    assert "Add at least one adult" in r.text
    # good rows move on; the draft holds the members but never a PIN
    ok = dict(rows, m_day_1="2", m_name_2="Rex", m_role_2="pet", papers="")
    assert "Step 3 of 6" in _post(c, token, 1, **fam, **ok).text
    draft = json.loads((root / "config" / "setup_draft.json").read_text(encoding="utf-8"))
    assert [(m["name"], m["role"]) for m in draft["members"]] == [("Alex", "adult"), ("Sam", "child"), ("Rex", "pet")]
    assert draft["members"][0]["birth_month_day"] == "03-14" and draft["members"][0]["birth_year"] == 1980
    assert "pin" not in json.dumps(draft).lower()
    # going back shows the saved people as rows, with a spare one at the end
    back = _post(c, token, 2, op="goto", to="1").text
    assert 'value="Sam"' in back and 'value="Rex"' in back and 'name="m_name_3"' in back
    # a pasted list alone still works, as before
    assert "Step 3 of 6" in _post(c, token, 1, **fam, people="Alex, adult, March 14 1980\nSam, child").text
