"""Critical information per person (0.110, migration 050, member_info.py): adults add, change and confirm facts; stale
ones become Inbox items; PC only (no sync, no chat, no ask_sql); the emergency sheet and purge include them."""
import datetime as D


from conftest import db, q, run

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


def test_adults_add_change_confirm_and_remove_facts(root, modules):
    ea = modules("edit_actions")
    ok, msg = ea.member_info_add(ADULT, "Sam", "medical", "Allergies", "Peanuts; carries an EpiPen")
    assert ok, msg
    rid = q(root, "SELECT id FROM member_info WHERE label='Allergies'")[0][0]
    assert q(root, "SELECT member, category, verified_on FROM member_info WHERE id=?", rid) == [("Sam", "medical", D.date.today().isoformat())]
    assert ea.member_info_add(KID, "Sam", "medical", "Doctor", "Dr Lee")[0] is False, "children cannot add"
    assert ea.member_info_add(ADULT, "Nobody", "medical", "Doctor", "Dr Lee")[0] is False
    assert ea.member_info_add(ADULT, "", "medical", "Doctor", "Dr Lee")[0] is False, "a person is needed"
    assert ea.member_info_add(ADULT, "Sam", "medical", "Allergies", "x")[0] is False, "duplicate label"
    assert ea.member_info_add(ADULT, "Sam", "bogus", "Doctor", "Dr Lee")[0] is False
    ok, msg = ea.member_info_update(ADULT, rid, value="Peanuts and sesame")
    assert ok and "confirmed today" in msg
    assert q(root, "SELECT value FROM member_info WHERE id=?", rid) == [("Peanuts and sesame",)]
    assert ea.member_info_update(KID, rid, value="x")[0] is False
    assert ea.member_info_verify(KID, [rid])[0] is False
    old = (D.date.today() - D.timedelta(days=400)).isoformat()
    with db(root) as con:
        con.execute("UPDATE member_info SET verified_on=? WHERE id=?", (old, rid))
    ok, msg = ea.member_info_verify(ADULT, [rid])
    assert ok and "Confirmed 1 fact" in msg
    assert q(root, "SELECT verified_on FROM member_info WHERE id=?", rid) == [(D.date.today().isoformat(),)]
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "member_info_add\tid=" in log and "EpiPen" not in log and "sesame" not in log, "ids only in the edit log"
    assert ea.member_info_drop(KID, rid)[0] is False
    assert ea.member_info_drop(ADULT, rid)[0] is True
    assert ea.member_info_drop(ADULT, rid)[0] is False, "already gone"
    assert ea.member_info_add(ADULT, "Sam", "medical", "Allergies", "again")[0] is True, "a removed label can be used again"


def test_stale_facts_become_one_inbox_item_per_person(root, modules):
    ea, pr, mi = modules("edit_actions"), modules("proposals"), modules("member_info")
    assert ea.member_info_add(ADULT, "Sam", "school", "Teacher", "Ms Park")[0]
    assert ea.member_info_add(ADULT, "Alex", "emergency", "Contact 1", "Jo 555-0100")[0]
    today = D.date.today()
    assert mi.stale(db(root), today) == {} or all(rows for rows in mi.stale(db(root), today).values())
    old = (today - D.timedelta(days=250)).isoformat()
    with db(root) as con:
        con.execute("UPDATE member_info SET verified_on=? WHERE member='Sam' AND status='active'", (old,))
    pr.sync()
    con = db(root)
    items = [it for it in pr.items(con) if it["source"] == "info_review"]
    assert [it["summary"].split(":")[0] for it in items] == ["Check Sam's critical info"], "Alex's fact is fresh"
    assert "Ms Park" not in items[0]["detail"] + items[0]["summary"], "the Inbox names kinds, never the facts"
    assert list(items[0]["options"]) == ["ok", "later"]
    assert pr.decide(KID, items[0]["id"], "ok")[0] is False
    ok, msg = pr.decide(ADULT, items[0]["id"], "ok")
    assert ok and "Confirmed" in msg, msg
    assert mi.stale(db(root), today) == {}
    pr.sync()
    assert [it for it in pr.items(db(root)) if it["source"] == "info_review"] == []


def test_the_review_age_is_a_setting(root, modules):
    mi = modules("member_info")
    assert mi.review_months() == 6
    assert mi.cutoff(D.date(2026, 10, 15)) == "2026-04-15"
    assert mi.cutoff(D.date(2026, 3, 31)) == "2025-09-28"


def test_records_section_and_forms_are_adult_edit_forms(root, modules):
    re_, rd = modules("records_edit"), modules("records_data")
    assert ("people", "profiles") in re_.EDIT_PARTS and re_.add_tables(("people", "profiles")) == ("member_info",)
    ok, msg = re_.add(ADULT, ("people", "profiles"), {"table": "member_info", "who": "Alex", "category": "medical",
                                                      "label": "Doctor", "value": "Dr Lee"})
    assert ok, msg
    rid = q(root, "SELECT id FROM member_info WHERE label='Doctor'")[0][0]
    assert re_.values("member_info", rid)["value"] == "Dr Lee"
    assert re_.edit(ADULT, "member_info", "save", rid, {"category": "medical", "label": "Doctor", "value": "Dr Kim"})[0]
    assert re_.edit(ADULT, "member_info", "drop", rid, {})[0] is False, "needs the tick box"
    ok, msg, gone = re_.edit(ADULT, "member_info", "drop", rid, {"sure": "1"})
    assert ok and gone
    blocks = rd.blocks("people", "profiles", D.date.today())
    assert blocks and blocks[0]["table"] == "member_info"


def test_pc_only_not_for_chat_or_sql(root, modules):
    cc = modules("chat_core")
    assert "info_review" in cc.PC_ONLY
    r = run(["data/ask_sql.py", "SELECT * FROM member_info"], root)
    assert r.returncode != 0 and "refused" in (r.stdout + r.stderr)
    r = run(["data/ask_sql.py", "--tables"], root)
    assert "member_info" not in r.stdout
    assert q(root, "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'trg_sync%member_info%'") == [(0,)]


def test_emergency_sheet_and_purge(root, modules):
    ea, es = modules("edit_actions"), modules("emergency_sheet")
    assert ea.member_info_add(ADULT, "Alex", "medical", "Blood type", "O+")[0]
    sheet = es.build(db(root))
    assert "## Critical info by person" in sheet and "Alex - Medical, Blood type: O+" in sheet


# ---- member profile edit (migration 051) -------------------------------------------------------------------------
def test_adults_correct_a_member_and_a_rename_follows_everywhere(root, modules):
    ea = modules("edit_actions")
    with db(root) as con:
        con.execute("INSERT OR IGNORE INTO members(name, role) VALUES ('Mateoo', 'child')")
    assert ea.member_info_add(ADULT, "Mateoo", "school", "Teacher", "Ms Park")[0]
    ok, msg = ea.member_update(ADULT, "Mateoo", school="Lincoln Middle", grade="Grade 6", grad_year="2032", relation="son")
    assert ok, msg
    assert q(root, "SELECT school, grade, grad_year, relation FROM members WHERE name='Mateoo'") == [("Lincoln Middle", "Grade 6", 2032, "son")]
    assert ea.member_update(KID, "Mateoo", school="x")[0] is False, "children cannot edit"
    assert ea.member_update(ADULT, "Mateoo", new_name="Alex")[0] is False, "a name already in the family"
    assert ea.member_update(ADULT, "Mateoo", grad_year="1800")[0] is False
    ok, msg = ea.member_update(ADULT, "Mateoo", new_name="Mateo")
    assert ok and "Mateoo is now Mateo" in msg, msg
    assert q(root, "SELECT COUNT(*) FROM members WHERE name='Mateoo'") == [(0,)]
    assert q(root, "SELECT member FROM member_info WHERE value='Ms Park' AND member LIKE 'Mate%'") == [("Mateo",)], "records follow the new name"
    assert q(root, "SELECT school FROM members WHERE name='Mateo'") == [("Lincoln Middle",)], "the profile stays"
    assert ea.member_update(ADULT, "mateo", new_name="MATEO")[0] is True, "a case-only change is allowed"
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "member_update\tname=Mateo fields=" in log and "Lincoln" not in log, "field names only in the edit log"


def test_family_page_has_an_edit_link_per_person(root, modules):
    re_ = modules("records_edit")
    rid = q(root, "SELECT id FROM members WHERE name='Alex'")[0][0]
    v = re_.values("members", rid)
    assert v["name"] == "Alex" and "school" in v and isinstance(v["ids"], list)
    ok, msg, gone = re_.edit(ADULT, "members", "save", rid, {"name": "Alex", "role": "adult", "birthday": "", "year": "",
                                                              "school": "State College", "grade": "", "grad_year": "", "relation": ""})
    assert ok and not gone, msg
    assert re_.values("members", rid)["school"] == "State College"
