"""House maintenance contacts (migration 052, home_contacts.py): adults keep the plumber, furnace company, garage ...;
last job also comes from the upkeep log; PC only (ask_sql refuses it); the emergency sheet lists the ones to use again."""
import datetime as D

import pytest

from conftest import db, q, run

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


def test_adults_add_change_use_and_remove_contacts(root, modules):
    ea = modules("edit_actions")
    ok, msg = ea.home_contact_add(ADULT, name="Acme Plumbing", trade="plumbing", phone="(555) 123-4567 ext 2",
                                  email="office@acme.example", website="acme.example", notes="Fixed the kitchen drain, $180")
    assert ok, msg
    rid = q(root, "SELECT id FROM home_contacts WHERE name='Acme Plumbing'")[0][0]
    assert q(root, "SELECT trade, phone, website, last_used FROM home_contacts WHERE id=?", rid) == \
        [("plumbing", "(555) 123-4567 ext 2", "https://acme.example", None)]
    assert ea.home_contact_add(KID, name="Joe", trade="handyman")[0] is False, "children cannot add"
    assert ea.home_contact_add(ADULT, name="Acme Plumbing", trade="plumbing")[0] is False, "duplicate"
    assert ea.home_contact_add(ADULT, name="Acme Plumbing", trade="heating_cooling")[0] is True, "same firm, other trade"
    assert ea.home_contact_add(ADULT, name="X", trade="bogus")[0] is False
    assert ea.home_contact_add(ADULT, name="X", trade="other", phone="call me")[0] is False
    assert ea.home_contact_add(ADULT, name="X", trade="other", email="nope")[0] is False
    assert ea.home_contact_add(ADULT, name="X", trade="other", website="javascript:alert(1)")[0] is False
    assert ea.home_contact_add(ADULT, name="X", trade="other", rating="9")[0] is False
    assert ea.home_contact_add(ADULT, name="X", trade="other", notes="acct 123456789012")[0] is False, "no full numbers in notes"

    ok, msg = ea.home_contact_update(ADULT, rid, rating="5", again="1", email="")
    assert ok, msg
    assert q(root, "SELECT rating, again, email, phone FROM home_contacts WHERE id=?", rid) == [(5, 1, None, "(555) 123-4567 ext 2")]
    assert ea.home_contact_update(KID, rid, rating="1")[0] is False
    assert ea.home_contact_used(ADULT, rid)[0] is True
    assert q(root, "SELECT last_used FROM home_contacts WHERE id=?", rid) == [(D.date.today().isoformat(),)]
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "home_contact_add\tid=" in log and "555" not in log and "acme.example" not in log, "ids only in the edit log"
    assert ea.home_contact_drop(KID, rid)[0] is False
    assert ea.home_contact_drop(ADULT, rid)[0] is True
    assert ea.home_contact_drop(ADULT, rid)[0] is False, "already gone"
    assert ea.home_contact_add(ADULT, name="Acme Plumbing", trade="plumbing")[0] is True, "a removed one can come back"


def test_last_job_follows_the_upkeep_log(root, modules):
    ea, rd = modules("edit_actions"), modules("records_data")
    assert ea.home_contact_add(ADULT, name="Warm Air Co", trade="heating_cooling", last_used="2024-01-10")[0]
    item = q(root, "SELECT id FROM recurring_items LIMIT 1")
    if not item:
        pytest.skip("demo seed has no recurring item")
    with db(root) as con:
        con.execute("INSERT INTO recurring_log(item_id, done_date, provider) VALUES (?, '2025-11-02', 'warm air co ')", (item[0][0],))
    blocks = rd.blocks("home", "contacts", D.date.today())
    assert blocks and blocks[0]["table"] == "home_contacts"
    row = next(r for r in blocks[0]["rows"] if "Warm Air Co" in r["cells"])
    assert "Nov 2, 2025" in row["cells"]  # PC tables show short dates


def test_records_forms_sheet_and_privacy(root, modules):
    re_, R = modules("records_edit"), modules("records")
    assert ("home", "contacts") in re_.EDIT_PARTS and re_.add_tables(("home", "contacts")) == ("home_contacts",)
    form = {k: "" for k in modules("edit_actions").CONTACT_FIELDS}
    ok, msg = re_.add(ADULT, ("home", "contacts"), {**form, "table": "home_contacts", "name": "Garage Doors R Us",
                                                     "trade": "garage_door", "phone": "555 222 3333"})
    assert ok, msg
    rid = q(root, "SELECT id FROM home_contacts WHERE name='Garage Doors R Us'")[0][0]
    v = re_.values("home_contacts", rid)
    assert v["phone"] == "555 222 3333" and v["last_job"] == ""
    ok, msg, _ = re_.edit(ADULT, "home_contacts", "save", rid, {**v, "notes": "Spring replaced", "again": "0"})
    assert ok, msg
    assert q(root, "SELECT notes, again, phone FROM home_contacts WHERE id=?", rid) == [("Spring replaced", 0, "555 222 3333")]
    assert re_.edit(ADULT, "home_contacts", "drop", rid, {})[0] is False, "needs the tick box"
    assert R.where("home_contacts", {})[0] == "home"
    assert any(h["table"] == "home_contacts" for h in R.search(db(root), "garage"))

    es = modules("emergency_sheet")
    modules("edit_actions").home_contact_add(ADULT, name="Bright Sparks", trade="electrical", phone="555 444 1212")
    sheet = es.build(db(root))
    assert "Bright Sparks" in sheet and "Garage Doors R Us" not in sheet, "the sheet leaves out 'would not use again'"

    r = run(["data/ask_sql.py", "SELECT phone FROM home_contacts"], root)
    assert r.returncode != 0 and "refused" in (r.stdout + r.stderr)
