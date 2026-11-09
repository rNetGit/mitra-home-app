"""Migrations: empty database, idempotence, a schema-only database from before the runner existed, an install
made by an older release, the downgrade guard."""
import shutil
import sqlite3

import pytest

from conftest import DRY, SRC, copy_template, q, read_family, run, write_family


def test_empty_db_migrates_and_is_idempotent(tmp_path):
    root = copy_template(tmp_path / "t")
    r = run(["data/migrate.py"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert q(root, "select value from meta where key='template_version'")[0][0] == (SRC / "VERSION").read_text().strip()
    r = run(["data/migrate.py"], root)
    assert r.returncode == 0 and "applied" not in r.stdout, r.stdout[-200:]
    names = {n for (n,) in q(root, "select name from schema_migrations")}
    assert names == {p.name for p in (root / "data").glob("migrate_*.py")}


def test_schema_only_db_from_before_the_runner_is_adopted(tmp_path):
    """Databases created by plain init_db.py (no schema_migrations table) re-run each idempotent migration once."""
    root = copy_template(tmp_path / "t")
    r = run(["data/init_db.py"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert not sqlite3.connect(root / "data" / "family.db").execute(
        "select 1 from sqlite_master where name='schema_migrations'").fetchone()
    r = run(["data/migrate.py"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert len(q(root, "select name from schema_migrations")) == len(list((root / "data").glob("migrate_*.py")))
    st = run(["data/migrate.py", "status"], root).stdout
    assert "[ ]" not in st


def test_members_sync_seeds_from_config(root):
    assert q(root, "select count(*) from members")[0][0] == 3  # 2 people + the pet (the seeded copy ran members sync)


def test_members_unknown_role_is_refused(tmp_path):
    """A role typo in family.json skips that member (sync still succeeds); `add` with a bad role stores nothing."""
    root = copy_template(tmp_path / "t")
    run(["data/migrate.py"], root)
    fam = read_family(root)
    fam["members"][0]["role"] = "audult"
    bad = fam["members"][0]["name"]
    write_family(root, fam)
    r = run(["data/members.py", "sync"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert "audult" in r.stderr and bad in r.stderr
    assert q(root, "select count(*) from members where name=?", bad)[0][0] == 0
    assert q(root, "select count(*) from members")[0][0] == 2
    r = run(["data/members.py", "add", "Zed", "--role", "kid"], root)
    assert r.returncode != 0 and "kid" in r.stderr
    assert q(root, "select count(*) from members where name='Zed'")[0][0] == 0
    assert run(["data/members.py", "add", "Zed", "--role", "child"], root).returncode == 0
    assert q(root, "select role from members where name='Zed'")[0][0] == "child"


@pytest.fixture
def old_install(tmp_path):
    """A copy whose code predates migration 025 (constraints) and everything after it, migrated and seeded as that
    older release."""
    old = copy_template(tmp_path / "old")
    newest = [m for m in sorted((old / "data").glob("migrate_0*.py")) if m.name >= "migrate_025"]
    held = {m.name: m.read_text(encoding="utf-8") for m in newest}
    for m in newest:
        m.unlink()
    (old / "VERSION").write_text("0.2.0\n", encoding="utf-8")
    assert run(["data/migrate.py"], old).returncode == 0
    run(["data/members.py", "sync"], old)
    run(["data/seed_demo.py"], old)
    return old, held


def test_upgrade_from_an_older_release_applies_only_new_migrations(old_install):
    old, held = old_install
    bills_before = q(old, "select count(*) from bills")[0][0]
    for name, text in held.items():
        (old / "data" / name).write_text(text, encoding="utf-8")  # the new release brings them
    (old / "VERSION").write_text((SRC / "VERSION").read_text(encoding="utf-8"), encoding="utf-8")
    r = run(["onboard.py", "upgrade"], old, env=DRY)
    assert r.returncode == 0, r.stderr[-300:]
    applied = {x[0] for x in q(old, "select name from schema_migrations")}
    assert all(n in applied for n in held)
    assert q(old, "select count(*) from bills")[0][0] == bills_before
    assert q(old, "select count(*) from sqlite_master where name in ('loans','home_office_profile','life_items','action_state')")[0][0] >= 1
    assert list((old / "data" / "backups_pre_upgrade").glob("*.db")), "upgrade backs the database up first"


def test_older_code_refuses_a_newer_database(old_install):
    old, held = old_install
    for name, text in held.items():
        (old / "data" / name).write_text(text, encoding="utf-8")
    (old / "VERSION").write_text((SRC / "VERSION").read_text(encoding="utf-8"), encoding="utf-8")
    assert run(["data/migrate.py"], old).returncode == 0
    (old / "VERSION").write_text("0.1.0\n", encoding="utf-8")
    r = run(["data/migrate.py"], old)
    assert r.returncode != 0 and "newer than the code" in r.stdout + r.stderr


def test_upgrade_keeps_data_and_family_json(tmp_path):
    root = copy_template(tmp_path / "t")
    run(["data/migrate.py"], root)
    run(["data/members.py", "sync"], root)
    run(["data/life.py", "seed"], root)
    before = q(root, "select count(*) from life_items")[0][0]
    fam = read_family(root)
    fam["marker"] = "keep me"
    write_family(root, fam)
    r = run(["onboard.py", "upgrade"], root, env=DRY)
    assert r.returncode == 0, r.stderr[-300:]
    assert q(root, "select count(*) from life_items")[0][0] == before
    assert read_family(root)["marker"] == "keep me"


def test_pre_upgrade_backups_are_not_part_of_the_tree(tmp_path):
    """verify_clean must skip data/backups_pre_upgrade (copies of OLD code kept by the updater)."""
    root = copy_template(tmp_path / "t")
    bk = root / "data" / "backups_pre_upgrade" / "code_0.0.1" / "data"
    bk.mkdir(parents=True)
    (bk / "old.py").write_text("# the user asked for this (2020-01-01)\n", encoding="utf-8")
    r = run(["scripts/verify_clean.py"], root)
    assert r.returncode == 0, r.stdout[-300:]
    shutil.rmtree(bk)


# ---- constraints, snapshot/restore, checksums (migration 025, runner changes)

def test_fresh_db_rejects_bad_dates_and_status(tmp_path):
    root = copy_template(tmp_path / "t")
    assert run(["data/migrate.py"], root).returncode == 0
    con = sqlite3.connect(root / "data" / "family.db")
    for sql in ("INSERT INTO bills(name, due_date) VALUES ('x', '10/15/2026')",
                "INSERT INTO bills(name, due_date, status) VALUES ('x', '2026-10-15', 'unpaid')",
                "INSERT INTO events(name, event_date) VALUES ('x', 'tomorrow')",
                "INSERT INTO life_items(domain, title, status) VALUES ('school', 'x', 'closed')",
                "INSERT INTO loans(name, payoff_date) VALUES ('x', '2026-13-01')",
                "INSERT INTO seasonal_tasks(name, start_md, end_md) VALUES ('x', '1/5', '02-01')"):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(sql)
    con.execute("INSERT INTO bills(name, due_date, status) VALUES ('ok', '2026-10-15', 'due')")
    con.execute("INSERT INTO appointments(person, appt_datetime) VALUES ('a', '2026-10-15T09:30')")
    con.execute("INSERT INTO transactions(txn_date, amount, account_id, ref) VALUES ('2026-10-15', -1, NULL, 'R1')")
    con.execute("INSERT INTO transactions(txn_date, amount, account_id, ref) VALUES ('2026-10-16', -1, NULL, 'R1')")  # NULL account: not a duplicate
    idx = {n for (n,) in con.execute("select name from sqlite_master where type='index'")}
    assert {"idx_bills_status_due", "idx_transactions_date", "idx_documents_type", "idx_life_member", "idx_transactions_acct_ref"} <= idx
    con.close()


def test_old_rows_are_repaired_before_constraints_and_bad_tables_are_skipped(old_install):
    """A pre-025 install with sloppy dates: readable ones become ISO, unreadable optional ones are cleared, a table
    with an unreadable NOT NULL date is left unconstrained and the migration still succeeds."""
    old, held = old_install
    con = sqlite3.connect(old / "data" / "family.db")
    con.execute("INSERT INTO life_items(domain, title, due_date, status) VALUES ('school', 'Slash date', '10/15/2026', 'open')")
    con.execute("INSERT INTO loans(name, payoff_date, status) VALUES ('Vague loan', 'when the kids finish', 'active')")
    con.execute("INSERT INTO seasonal_tasks(name, start_md, end_md) VALUES ('Fine task', '03-01', '03-31')")
    tid = con.execute("select id from seasonal_tasks where name='Fine task'").fetchone()[0]
    con.execute("INSERT INTO seasonal_log(task_id, done_date) VALUES (?, 'whenever')", (tid,))
    con.commit()
    con.close()
    for name, text in held.items():
        (old / "data" / name).write_text(text, encoding="utf-8")
    (old / "VERSION").write_text((SRC / "VERSION").read_text(encoding="utf-8"), encoding="utf-8")
    r = run(["data/migrate.py"], old)
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-300:]
    assert q(old, "select due_date from life_items where title='Slash date'") == [("2026-10-15",)]
    assert q(old, "select payoff_date from loans where name='Vague loan'") == [(None,)]
    assert "seasonal_log" in r.stdout and "unconstrained" not in r.stdout.split("seasonal_log")[0]
    con = sqlite3.connect(old / "data" / "family.db")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO life_items(domain, title, due_date) VALUES ('school', 'x', 'next week')")
    con.execute("INSERT INTO seasonal_log(task_id, done_date) VALUES (?, 'still free text')", (tid,))  # table was skipped
    con.close()
    st = run(["data/migrate.py", "status"], old).stdout
    assert "unconstrained" in st and "seasonal_log" in st
    # fix the rows, re-run the migration script by hand: now the table gets its constraints
    con = sqlite3.connect(old / "data" / "family.db")
    con.execute("UPDATE seasonal_log SET done_date='2026-03-02'")
    con.commit()
    con.close()
    assert run(["data/migrate_025_constraints.py"], old).returncode == 0
    assert "unconstrained" not in run(["data/migrate.py", "status"], old).stdout
    assert q(old, "select count(*) from sqlite_master where type='view'")[0][0] >= 5, "views re-created"


def test_046_impossible_days_are_refused_and_old_ones_moved_to_the_month_end(tmp_path):
    """Pattern-only checks (025) let 2026-02-30 in and the weekly report crashed on it. A copy migrated without 046
    holds such rows; 046 moves them to the last day of the month, keeps time parts, and afterwards the checks refuse
    impossible days (but not a real day with a time, nor Feb 29 in a leap year or as a month-day)."""
    root = copy_template(tmp_path / "t")
    held = (root / "data" / "migrate_046_real_dates.py").read_text(encoding="utf-8")
    (root / "data" / "migrate_046_real_dates.py").unlink()
    assert run(["data/migrate.py"], root).returncode == 0
    con = sqlite3.connect(root / "data" / "family.db")
    # tables whose checks come from 025 / 031 / 032 (bills, events, appointments get theirs from schema.sql)
    con.execute("INSERT INTO life_items(domain, title, due_date, status) VALUES ('school', 'Feb', '2026-02-30', 'open')")
    con.execute("INSERT INTO loans(name, payoff_date, status) VALUES ('Apr', '2026-04-31', 'active')")
    con.execute("INSERT INTO receipts(merchant, receipt_date, total, created_at) VALUES ('Nov', '2026-11-31', 5, '2026-10-15T00:00:00')")
    con.execute("INSERT INTO work_hours(contract_id, work_date, hours) VALUES (1, '2024-02-29', 8)")
    con.execute("INSERT INTO seasonal_tasks(name, start_md, end_md) VALUES ('x', '02-30', '04-31')")
    con.commit()
    con.close()
    (root / "data" / "migrate_046_real_dates.py").write_text(held, encoding="utf-8")
    r = run(["data/migrate.py"], root)
    assert r.returncode == 0, r.stdout[-600:] + r.stderr[-300:]
    assert "not a real day" in r.stdout and "2026-02-28" in r.stdout
    assert q(root, "select due_date from life_items where title='Feb'") == [("2026-02-28",)]
    assert q(root, "select payoff_date from loans where name='Apr'") == [("2026-04-30",)]
    assert q(root, "select receipt_date from receipts where merchant='Nov'") == [("2026-11-30",)]
    assert q(root, "select work_date from work_hours where contract_id=1") == [("2024-02-29",)]
    assert q(root, "select start_md, end_md from seasonal_tasks where name='x'") == [("02-29", "04-30")]
    assert "unconstrained" not in run(["data/migrate.py", "status"], root).stdout
    con = sqlite3.connect(root / "data" / "family.db")
    for sql in ("INSERT INTO bills(name, due_date) VALUES ('x', '2026-02-30')",
                "INSERT INTO events(name, event_date) VALUES ('x', '2023-02-29')",
                "INSERT INTO appointments(person, appt_datetime) VALUES ('a', '2026-04-31T09:00')",
                "INSERT INTO work_hours(contract_id, work_date, hours) VALUES (1, '2026-06-31', 1)",
                "INSERT INTO seasonal_tasks(name, start_md, end_md) VALUES ('x', '13-01', '02-01')"):
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(sql)
    con.execute("INSERT INTO appointments(person, appt_datetime) VALUES ('a', '2026-10-15T09:30')")
    con.execute("INSERT INTO seasonal_tasks(name, start_md, end_md) VALUES ('ok', '02-29', '03-01')")
    assert con.execute("select count(*) from sqlite_master where type='view'").fetchone()[0] >= 5, "views re-created"
    assert con.execute("select count(*) from sqlite_master where type='trigger' and name like 'sync_bills_%'").fetchone()[0] == 3
    con.close()
    # running it again changes nothing
    assert "rebuilt" not in run(["data/migrate_046_real_dates.py"], root).stdout


def test_failed_migration_restores_the_snapshot_and_keeps_the_version(tmp_path):
    root = copy_template(tmp_path / "t")
    assert run(["data/migrate.py"], root).returncode == 0
    ver = q(root, "select value from meta where key='template_version'")[0][0]
    (root / "data" / "migrate_099_boom.py").write_text(
        "import sqlite3, pathlib\nc = sqlite3.connect(pathlib.Path(__file__).with_name('family.db'))\n"
        "c.execute(\"INSERT INTO events(name, event_date) VALUES ('half done', '2030-01-01')\")\nc.commit()\n"
        "raise SystemExit('boom')\n", encoding="utf-8")
    (root / "VERSION").write_text("99.1.0\n", encoding="utf-8")
    r = run(["data/migrate.py"], root)
    assert r.returncode != 0 and "put back" in r.stdout
    assert not q(root, "select 1 from events where name='half done'"), "partial write rolled back with the snapshot"
    assert q(root, "select value from meta where key='template_version'")[0][0] == ver
    assert not q(root, "select 1 from schema_migrations where name='migrate_099_boom.py'")
    assert not (root / "data" / "family.db.migrating").exists()


def test_status_and_verify_report_an_edited_migration(tmp_path):
    root = copy_template(tmp_path / "t")
    assert run(["data/migrate.py"], root).returncode == 0
    assert run(["data/migrate.py", "verify"], root).returncode == 0
    p = root / "data" / "migrate_019_action_state.py"
    p.write_text(p.read_text(encoding="utf-8") + "\n# edited\n", encoding="utf-8")
    assert "changed since applied" in run(["data/migrate.py", "status"], root).stdout
    assert run(["data/migrate.py", "verify"], root).returncode == 1


def test_revised_migration_is_re_recorded_quietly_but_other_edits_are_reported(tmp_path):
    root = copy_template(tmp_path / "t")
    assert run(["data/migrate.py"], root).returncode == 0
    old = "7da6e08808acae7405716a4acc16dc515db128ed125f8a2adac01c29e3936eda"  # 025 as shipped in 0.61.0
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("UPDATE schema_migrations SET checksum=? WHERE name='migrate_025_constraints.py'", (old,))
    con.commit()
    con.close()
    out = run(["data/migrate.py"], root)
    assert out.returncode == 0 and "edited after" not in out.stdout
    assert run(["data/migrate.py", "verify"], root).returncode == 0
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("UPDATE schema_migrations SET checksum=? WHERE name='migrate_025_constraints.py'", ("0" * 64,))
    con.commit()
    con.close()
    assert "edited after" in run(["data/migrate.py"], root).stdout


def test_verify_ignores_line_endings(tmp_path):
    """A Windows checkout rewrites LF as CRLF; that is not an edit."""
    root = copy_template(tmp_path / "t")
    assert run(["data/migrate.py"], root).returncode == 0
    p = root / "data" / "migrate_019_action_state.py"
    p.write_bytes(p.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert run(["data/migrate.py", "verify"], root).returncode == 0


def test_006_creates_tables_without_seeding_a_country_pack(tmp_path):
    root = copy_template(tmp_path / "t")
    assert run(["data/migrate.py"], root).returncode == 0
    assert q(root, "select count(*) from seasonal_tasks")[0][0] == 0
    assert run(["data/seasonal_packs.py", "apply", "uk"], root).returncode == 0
    assert q(root, "select count(*) from seasonal_tasks where pack='uk'")[0][0] > 0


def test_database_from_before_002_still_upgrades(tmp_path):
    """001 used to run schema.sql, whose ref index needs a column only 002 adds."""
    root = copy_template(tmp_path / "t")
    assert run(["data/init_db.py"], root).returncode == 0
    con = sqlite3.connect(root / "data" / "family.db")
    con.executescript("""
        PRAGMA foreign_keys=OFF;
        DROP VIEW v_card_payments; DROP VIEW v_investment_flows; DROP VIEW v_monthly_cashflow;
        DROP TABLE transactions;
        CREATE TABLE transactions (id INTEGER PRIMARY KEY, account_id INTEGER REFERENCES accounts(id), txn_date TEXT NOT NULL,
          description TEXT, amount REAL NOT NULL, category TEXT, document_id INTEGER REFERENCES documents(id));
        """)
    con.commit()
    con.close()
    r = run(["data/migrate.py"], root)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-300:]
    assert {"ref", "payee", "txn_type"} <= {c[1] for c in q(root, "pragma table_info(transactions)")}


def test_the_bank_reference_index_is_tried_again_once_no_reference_repeats(root, modules):
    """Audit D7: 025 skipped idx_transactions_acct_ref while references repeated; every migrate run tries again,
    and repeated references are only reported (a check number can repeat for real), never deleted."""
    mig = modules("migrate")
    con = sqlite3.connect(root / "data" / "family.db")
    try:
        con.execute("DROP INDEX IF EXISTS idx_transactions_acct_ref")
        acct = con.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
        for amt in (-10, -12):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, ref) VALUES (?,?,?,?,?)",
                        (acct, "2026-01-05", "CHECK", amt, "CHK1001"))
        assert mig.ensure_indexes(con) == 1 and mig.repeated_refs(con) == [(acct, "CHK1001", 2)]
        assert not con.execute("SELECT 1 FROM sqlite_master WHERE name='idx_transactions_acct_ref'").fetchone()
        assert con.execute("SELECT COUNT(*) FROM transactions WHERE ref='CHK1001'").fetchone()[0] == 2, "nothing deleted"
        con.execute("DELETE FROM transactions WHERE ref='CHK1001' AND amount=-12")
        assert mig.ensure_indexes(con) == 0
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name='idx_transactions_acct_ref'").fetchone()
    finally:
        con.rollback()
        con.close()
