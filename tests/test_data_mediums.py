"""Data-layer fixes from the 2026-10-14 audit: phone-sync triggers survive a by-hand re-run of migration 025 (M10),
family category rules beat starter rules and an edit takes effect (M13), a locked database is an error instead of
"no members" (M16). Purge (M11, M12) is covered in test_devices.py."""
import json
import sqlite3

import pytest

from conftest import db, q, run


def _sync_triggers(root):
    return sorted(n for (n,) in q(root, "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'sync_%'"))


def test_rerunning_025_keeps_the_phone_sync_triggers(root, modules):
    # a household where 025 once left `bills` without its constraints (bad rows), fixed later, then 025 run by hand
    con = db(root)
    con.execute("PRAGMA legacy_alter_table=ON")
    views = con.execute("SELECT name, sql FROM sqlite_master WHERE type='view'").fetchall()
    for name, _ in views:
        con.execute(f"DROP VIEW {name}")
    con.execute("CREATE TABLE _plain_bills AS SELECT * FROM bills")
    con.execute("DROP TABLE bills")
    con.execute("ALTER TABLE _plain_bills RENAME TO bills")
    for _, sql in views:
        con.execute(sql)
    modules("sync_data").ensure_triggers(con)
    con.commit()
    con.close()
    before = _sync_triggers(root)
    assert "sync_bills_i" in before, "migration 044 made the triggers"
    r = run(["data/migrate_025_constraints.py"], root)
    assert r.returncode == 0, r.stderr[-400:]
    assert _sync_triggers(root) == before
    r = run(["data/migrate.py"], root)
    assert r.returncode == 0 and _sync_triggers(root) == before


def test_family_rules_win_over_starter_rules_and_an_edit_takes_effect(root):
    con = db(root)
    aid = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Rules Test', 'checking', '8080')").lastrowid
    tid = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2026-02-03', "
                      "'COSTCO WHSE 0042', -80)", (aid,)).lastrowid
    con.commit()
    con.close()
    rules = root / "config" / "category_rules.json"
    saved = rules.read_text(encoding="utf-8") if rules.exists() else None
    try:
        for cat in ("groceries", "bulk buys"):
            rules.write_text(json.dumps([["COSTCO%", cat, "spend", "Costco"]]), encoding="utf-8")
            con = db(root)
            con.execute("UPDATE transactions SET txn_type=NULL, category=NULL WHERE id=?", (tid,))
            con.commit()
            con.close()
            r = run(["data/apply_rules.py"], root)
            assert r.returncode == 0, r.stderr[-300:]
            assert q(root, "SELECT category FROM transactions WHERE id=?", tid) == [(cat,)], cat
        pri = dict(q(root, "SELECT pattern, priority FROM category_rules WHERE pattern IN ('COSTCO%', 'WALMART%')"))
        assert pri["COSTCO%"] < 100 <= 1000 <= pri["WALMART%"], pri
    finally:
        if saved is None:
            rules.unlink(missing_ok=True)
        else:
            rules.write_text(saved, encoding="utf-8")
        con = db(root)
        con.execute("DELETE FROM transactions WHERE account_id=?", (aid,))
        con.execute("DELETE FROM accounts WHERE id=?", (aid,))
        con.commit()
        con.close()


class _Con:
    def __init__(self, msg):
        self.msg = msg

    def execute(self, *a):
        raise sqlite3.OperationalError(self.msg)


def test_a_locked_database_is_not_read_as_no_members(modules):
    td = modules("today_data")
    assert td.members(_Con("no such table: members")) == []
    with pytest.raises(sqlite3.OperationalError):
        td.members(_Con("database is locked"))
