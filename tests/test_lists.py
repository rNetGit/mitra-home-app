"""Shared lists (migration 029 + data/lists.py): the tables and their checks, the CLI, who may do what through
edit_actions (kids: family lists only, add and tick, caps), the edit log without item text, the digest line, the phone
brief (adults-only lists left out), purge clearing names, and the assistant actions."""
import datetime as D
import sqlite3

import pytest

from conftest import db, q, run

ADULT, KID = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}
NOBODY = {"name": "", "role": "limited"}


@pytest.fixture(scope="module")
def L(root, modules):
    return modules("lists")


def _lid(root, name):
    return q(root, "select id from lists where name=?", name)[0][0]


def _iid(root, text):
    return q(root, "select id from list_items where text=? order by id desc", text)[0][0]


def test_migration_tables_checks_and_seed(root, L):
    assert q(root, "select name from schema_migrations where name='migrate_029_lists.py'")
    assert q(root, "select name, kind, audience, status from lists") == [("Groceries", "shopping", "family", "active")]
    r = run(["data/migrate_029_lists.py"], root)
    assert r.returncode == 0 and "1 lists" in r.stdout and "seeded" not in r.stdout, "idempotent, seeds once"
    con = db(root)
    con.execute("PRAGMA foreign_keys=ON")  # as data/db.py connects
    try:
        for sql, args in (("insert into lists(name, kind, created_at) values ('X', 'wishlist', 'now')", ()),
                          ("insert into lists(name, audience, created_at) values ('Y', 'everyone', 'now')", ()),
                          ("insert into lists(name, created_at) values ('groceries', 'now')", ()),
                          ("insert into list_items(list_id, text, added_at) values (?, ?, 'now')", (1, "x" * 121)),
                          ("insert into list_items(list_id, text, status, added_at) values (1, 'milk', 'bought', 'now')", ()),
                          ("insert into list_items(list_id, text, added_at) values (999, 'milk', 'now')", ())):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(sql, args)
    finally:
        con.rollback()
        con.close()


def test_cli_round_trip(root, L):
    ok = lambda *a: run(["data/lists.py", *a], root)  # noqa: E731
    assert ok("add", "groc", "Milk", "--qty", "2").returncode == 0
    assert "already on Groceries" in ok("add", "Groceries", "milk").stdout, "no duplicate open item"
    assert ok("add", "Groceries", "Eggs").returncode == 0
    assert ok("add", "Groceries", "Bread", "--for", "Sam").returncode == 0
    assert ok("add", "Groceries", "Cake", "--for", "Nobody").returncode != 0
    assert ok("add", "Groceries", "card 4111111111111111").returncode != 0, "no full card numbers"
    assert ok("add", "Nope", "x").returncode != 0
    assert ok("new", "Packing for Goa", "--kind", "packing").returncode == 0
    assert ok("new", "packing for goa").returncode != 0, "names are unique (any case)"
    assert ok("new", "Gift ideas", "--adults").returncode == 0
    assert ok("add", "Gift ideas", "Lego set").returncode == 0
    assert ok("done", "Groceries", "mil").returncode == 0
    assert q(root, "select status from list_items where text='Milk'") == [("done",)]
    assert ok("done", "Groceries", "milk").returncode != 0, "nothing open matches any more"
    assert ok("undo", "Groceries", "milk").returncode == 0 and q(root, "select status from list_items where text='Milk'") == [("open",)]
    assert ok("drop", "Groceries", "eggs").returncode == 0
    out = ok("show", "Groceries").stdout
    assert "[ ] Milk (2)" in out and "[ ] Bread - Sam" in out and "Eggs" not in out, out
    assert "[-] Eggs" in ok("show", "Groceries", "--all").stdout
    assert "[adults only]" in ok("show").stdout
    s = ok("summary").stdout
    assert "Groceries: 2 open" in s and "Gift ideas: 1 open" in s and "Packing" not in s, s
    assert ok("archive", "Packing for Goa").returncode == 0
    assert "Packing" not in ok("show").stdout
    assert ok("new", "Packing for Goa", "--kind", "packing").returncode == 0, "an archived list comes back"
    assert q(root, "select count(*) from lists where name='Packing for Goa'") == [(1,)]


def test_items_order_and_ticked_items_fade(root, L):
    lid = _lid(root, "Groceries")
    con = db(root)
    try:
        L.set_status(con, _iid(root, "Milk"), "done", "Alex")
        con.commit()
        today = D.date.today()
        texts = [(i["text"], i["status"]) for i in L.items(con, lid, today)]
        assert texts == [("Bread", "open"), ("Milk", "done")], texts
        assert "Milk" not in [i["text"] for i in L.items(con, lid, today + D.timedelta(days=L.SHOW_DONE_DAYS + 1))]
        assert L.clear_done(con, lid) == 1
        con.commit()
        assert [i["text"] for i in L.items(con, lid, today)] == ["Bread"]
        assert "Milk" in [i["text"] for i in L.items(con, lid, today, all=True)]
        L.set_status(con, _iid(root, "Milk"), "open")
        con.commit()
    finally:
        con.close()


def test_edit_actions_permissions(root, L, modules):
    ea = modules("edit_actions")
    groc, gifts = _lid(root, "Groceries"), _lid(root, "Gift ideas")
    ok, msg = ea.list_item_add(KID, groc, "Apples")
    assert ok and "Apples" in msg
    assert q(root, "select added_by from list_items where text='Apples'") == [("Sam",)]
    assert not ea.list_item_add(KID, gifts, "Bike")[0], "kids never touch adults-only lists"
    assert not ea.list_item_add(KID, groc, "Chips", who="Alex")[0], "kids cannot put a name on an item"
    assert not ea.list_item_add(NOBODY, groc, "Chips")[0], "a limited user must be signed in"
    lego = _iid(root, "Lego set")
    assert not ea.list_item_tick(KID, lego)[0]
    apples = _iid(root, "Apples")
    assert ea.list_item_tick(KID, apples)[0]
    ok, msg = ea.list_item_tick(ADULT, apples)
    assert ok and "already ticked" in msg, "a second tick is not an error"
    assert q(root, "select status, done_by from list_items where id=?", apples) == [("done", "Sam")]
    assert ea.list_item_tick(KID, apples, done=False)[0] and q(root, "select status from list_items where id=?", apples) == [("open",)]
    assert not ea.list_item_drop(KID, apples)[0] and not ea.list_new(KID, "Kid list")[0] and not ea.list_archive(KID, groc)[0]
    assert ea.list_item_drop(ADULT, apples)[0]
    assert not ea.list_item_tick(KID, apples)[0], "a dropped item cannot be ticked"
    assert ea.list_clear(KID, groc)[0]
    assert not ea.list_new(ADULT, "")[0] and not ea.list_new(ADULT, "Toys", kind="wishlist")[0]
    assert ea.list_new(ADULT, "Saturday jobs")[0]
    assert not ea.list_new(ADULT, "saturday JOBS")[0]
    jobs = _lid(root, "Saturday jobs")
    for n in range(L.MAX_OPEN_PER_PERSON):
        assert ea.list_item_add(KID, jobs, f"job {n}")[0]
    ok, msg = ea.list_item_add(KID, jobs, "one too many")
    assert not ok and str(L.MAX_OPEN_PER_PERSON) in msg
    assert ea.list_item_add(ADULT, jobs, "Mow the lawn", qty="1", who="Sam")[0], "adults have no cap"
    assert ea.list_archive(ADULT, jobs)[0] and not ea.list_item_add(ADULT, jobs, "x")[0], "archived lists are closed"
    elog = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    for action in ("list_item_add", "list_item_tick", "list_item_untick", "list_item_drop", "list_new", "list_archive"):
        assert action in elog, action
    assert "Apples" not in elog and "Mow" not in elog and "Saturday" not in elog, "ids only, never the text"


def test_digest_line_and_phone_brief(root, L):
    assert run(["data/make_digest.py"], root).returncode == 0
    digest = next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")
    assert "## Lists" in digest and "Groceries: 2 to do" in digest, digest.split("## Lists")[-1][:200]
    r = run(["data/lists.py", "brief"], root)
    assert r.returncode == 0
    md = (root / "brief" / "lists.md").read_text(encoding="utf-8")
    assert "## Groceries" in md and "- [ ] Milk (2)" in md and "- [ ] Bread - Sam" in md
    assert "Gift ideas" not in md and "Lego" not in md, "adults-only lists never go to the phone"
    con = db(root)
    try:
        for (iid,) in con.execute("select id from list_items where status='open'").fetchall():
            L.set_status(con, iid, "done")
        con.commit()
    finally:
        con.close()
    assert "nothing open" in run(["data/lists.py", "brief"], root).stdout
    assert not (root / "brief" / "lists.md").exists(), "a stale phone copy is removed"


def test_assistant_catalog_runs_lists(root, modules):
    asst = modules("assistant")
    for name in ("list_add", "list_done", "list_show"):
        assert name in asst.CATALOG
    argv = asst.CATALOG["list_add"][3]({"list": "Groceries", "item": "Tea", "qty": "1 box"})
    assert argv[-5:] == ["add", "Groceries", "Tea", "--qty", "1 box"]
    assert run(argv[1:], root).returncode == 0 and q(root, "select qty from list_items where text='Tea'") == [("1 box",)]


def test_purge_person_clears_names_keeps_items(root):
    r = run(["data/purge.py", "person", "Sam", "--yes"], root)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    assert not q(root, "select count(*) from list_items where 'Sam' in (added_by, done_by, assigned_to)")[0][0]
    assert q(root, "select count(*) from list_items where text='Bread'")[0][0] == 1, "shared list rows stay"
