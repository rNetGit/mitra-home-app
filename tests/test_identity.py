"""Row identity for hide/snooze/paid (audit item 14): items are keyed by (table, row id, date), not by their title."""
import datetime as dt
import sqlite3

import pytest

from conftest import SRC, copy_template, db, q, run

TODAY = dt.date.today()


@pytest.fixture
def two_bills(root):
    con = db(root)
    con.execute("DELETE FROM action_state")
    con.execute("DELETE FROM bills")
    due = (TODAY + dt.timedelta(days=3)).isoformat()
    con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('water', 'Town Utilities', 40, ?, 'due')", (due,))
    con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('sewer', 'Town Utilities', 25, ?, 'due')", (due,))
    con.commit()
    ids = [r[0] for r in con.execute("SELECT id FROM bills ORDER BY id")]
    con.close()
    return root, ids, due


def test_items_carry_row_refs_and_stable_keys(two_bills, modules):
    root, ids, due = two_bills
    ai = modules("action_items")
    con = db(root)
    try:
        items = [i for i in ai.collect_items(con, TODAY, 30) if i["kind"] == "Bill"]
    finally:
        con.close()
    assert len(items) == 2, "two bills from one vendor on one day are two items"
    assert {i["ref"] for i in items} == {("bills", ids[0]), ("bills", ids[1])}
    assert {i["key"] for i in items} == {f"bills:{ids[0]}:{due}", f"bills:{ids[1]}:{due}"}
    assert all(len(i["id"]) == 8 and i["id"] != i["key"] for i in items), "people still see an 8-character Id"
    for i in items:
        assert i["ref"] is None or isinstance(i["ref"][1], int)


def test_hidden_item_stays_hidden_after_a_rename(two_bills, modules):
    root, ids, due = two_bills
    ai, st = modules("action_items"), modules("action_state")
    st.set_state(f"bills:{ids[0]}:{due}", "ignored", None, "water")
    con = db(root)
    con.execute("UPDATE bills SET vendor='Town Utilities Inc.', name='water & sewer' WHERE id=?", (ids[0],))
    con.commit()
    try:
        titles = [i["title"] for i in ai.collect_items(con, TODAY, 30) if i["kind"] == "Bill"]
        raw = [i["key"] for i in ai.collect_items(con, TODAY, 30, raw=True) if i["kind"] == "Bill"]
    finally:
        con.close()
    assert titles == ["Town Utilities"], titles
    assert f"bills:{ids[0]}:{due}" in raw, "raw=True lists hidden items too"


def test_each_same_day_bill_can_be_paid_on_its_own(two_bills, modules):
    root, ids, due = two_bills
    da = modules("dashboard_actions")
    assert da.mark_bill_paid("Town Utilities", due, TODAY) is None, "the vendor+date lookup cannot pick between them"
    assert da.mark_bill_paid_by_id(ids[0], TODAY) == ids[0]
    assert q(root, "select status from bills order by id") == [("paid",), ("due",)]
    assert da.mark_bill_paid_by_id(ids[0], TODAY) is None, "already paid"
    assert da.mark_bill_paid_by_id(ids[1], TODAY) == ids[1]
    da.undo_bill_paid(ids[1], due, TODAY)
    assert q(root, "select status from bills where id=?", ids[1]) == [("due",)]


def test_cli_accepts_the_short_id_and_lists_full_keys(two_bills):
    root, ids, due = two_bills
    assert run(["data/make_digest.py"], root).returncode == 0
    out = next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")
    import re
    short = re.findall(r"^\| ([0-9a-f]{8}) \|", out, re.M)
    assert short
    assert run(["data/action_state.py", "done", short[0]], root).returncode == 0
    keys = [r[0] for r in q(root, "select key from action_state")]
    assert len(keys) == 1 and (":" in keys[0] or len(keys[0]) == 8)
    lst = run(["data/action_state.py", "list"], root).stdout
    assert short[0] in lst and keys[0] in lst
    assert run(["data/action_state.py", "reset", keys[0]], root).returncode == 0, "the full key works too"
    assert not q(root, "select 1 from action_state")
    r = run(["data/action_state.py", "done", "zzzzzzzz"], root)
    assert r.returncode != 0 and "no current item" in r.stderr + r.stdout


def test_family_meeting_matches_whole_names_only(root, modules):
    fm = modules("make_family_meeting")
    con = db(root)
    con.execute("INSERT INTO members(name, role) VALUES ('Al', 'adult')")
    con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('auto insurance', 'Allstate', 120, ?, 'due')",
                ((TODAY + dt.timedelta(days=5)).isoformat(),))
    con.execute("INSERT INTO life_items(domain, title, member, due_date, status) VALUES ('chore', 'Rake leaves', 'Al', ?, 'open')",
                ((TODAY + dt.timedelta(days=4)).isoformat(),))
    con.commit()
    try:
        alex = fm.build(con, TODAY, "Alex")
        al = fm.build(con, TODAY, "Al")
    finally:
        con.close()
    assert "Allstate" in alex, "a household bill shows for every adult: 'Al' inside 'Allstate' is not a person"
    assert "Rake leaves" not in alex and "Rake leaves" in al


def test_migration_026_rekeys_legacy_hashes(tmp_path):
    root = copy_template(tmp_path / "t")
    (root / "data" / "migrate_026_action_keys.py").unlink()
    assert run(["data/migrate.py"], root).returncode == 0
    due = (TODAY + dt.timedelta(days=2)).isoformat()
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('gas', 'Gas Co', 30, ?, 'due')", (due,))
    bid = con.execute("select id from bills").fetchone()[0]
    import hashlib
    legacy = hashlib.sha1(f"Bill|Gas Co|{due}".encode()).hexdigest()[:8]
    con.execute("INSERT INTO action_state(key, state) VALUES (?, 'ignored')", (legacy,))
    con.commit()
    con.close()
    (root / "data" / "migrate_026_action_keys.py").write_text((SRC / "data" / "migrate_026_action_keys.py").read_text(encoding="utf-8"), encoding="utf-8")
    r = run(["data/migrate.py"], root)
    assert r.returncode == 0 and "1 hidden item(s) re-keyed" in r.stdout, r.stdout[-400:]
    assert q(root, "select key from action_state") == [(f"bills:{bid}:{due}",)]
