"""A person's name is a key in many tables: a rename (edit_actions.RENAME_COLUMNS) and a purge (purge.OWNED / SHARED)
must reach every one of them, or a renamed person's rows stop working and a purged person's rows stay behind."""
from conftest import db, q, run

ADULT = {"name": "Alex", "role": "adult"}
# columns that hold a member's name, by column name; a new table with one of these must join both lists
PERSON_COLUMNS = {"member", "person", "who", "owner", "cardholder", "primary_driver", "assigned_driver", "assigned_to",
                  "added_by", "done_by", "undone_by", "decided_by", "created_by", "actor"}
PURGED_APART = {("devices", "member")}  # purge revokes the phone and replaces the name (purge.REVOKED_NAME)


def _person_columns(root):
    con = db(root)
    try:
        tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        return {(t, r[1]) for t in tables for r in con.execute(f"PRAGMA table_info({t})") if r[1] in PERSON_COLUMNS}
    finally:
        con.close()


def test_every_name_column_is_renamed_and_purged(root, modules):
    ea, purge = modules("edit_actions"), modules("purge")
    cols = _person_columns(root)
    assert ("wallet_cards", "member") in cols
    renamed = set(ea.RENAME_COLUMNS)
    purged = {(t, c) for t, c, *_ in purge.OWNED} | set(purge.SHARED) | PURGED_APART
    assert cols - renamed == set(), "add these to edit_actions.RENAME_COLUMNS"
    assert cols - purged == set(), "add these to purge.OWNED (rows go) or purge.SHARED (the name goes)"


def test_a_renamed_persons_wallet_card_and_allowance_follow(root, modules):
    ea = modules("edit_actions")
    with db(root) as con:
        con.execute("INSERT OR IGNORE INTO members(name, role) VALUES ('Robin', 'child')")
        con.execute("INSERT INTO wallet_cards(kind, title, member, number) VALUES ('library', 'Town library', 'Robin', '1234567')")
        con.execute("INSERT INTO budget(category, monthly_limit) VALUES ('allowance:Robin', 20)")
    ok, msg = ea.member_update(ADULT, "Robin", new_name="Robbie")
    assert ok, msg
    assert q(root, "SELECT member FROM wallet_cards WHERE title='Town library'") == [("Robbie",)]
    assert q(root, "SELECT category FROM budget WHERE category LIKE 'allowance:%'") == [("allowance:Robbie",)]


def test_purge_removes_the_persons_wallet_cards_and_keeps_audit_rows(root):
    with db(root) as con:
        con.execute("INSERT OR IGNORE INTO members(name, role) VALUES ('Jordan', 'adult')")
        con.execute("INSERT INTO wallet_cards(kind, title, member, number) VALUES ('membership', 'Gym', 'Jordan', '99887766')")
        con.execute("INSERT INTO wallet_cards(kind, title, member) VALUES ('home', 'Wi-Fi', NULL)")
        rid = con.execute("INSERT INTO audit_runs(started_at, trigger, actor) VALUES ('2026-10-01T09:00:00', 'now', 'Jordan')").lastrowid
        con.execute("INSERT INTO audit_fixes(run_id, action, summary, undo, done_by, done_at) "
                    "VALUES (?, 'categorize', 'x', '{}', 'Jordan', '2026-10-01T09:01:00')", (rid,))
    r = run(["data/purge.py", "person", "Jordan", "--yes"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert q(root, "SELECT COUNT(*) FROM wallet_cards WHERE member='Jordan'") == [(0,)], "full card numbers leave with the person"
    assert q(root, "SELECT COUNT(*) FROM wallet_cards WHERE title='Wi-Fi'") == [(1,)], "household cards stay"
    assert q(root, "SELECT actor FROM audit_runs WHERE id=?", rid) == [(None,)]
    assert q(root, "SELECT done_by FROM audit_fixes WHERE run_id=?", rid) == [("(removed)",)], "a NOT NULL column gets a placeholder"
