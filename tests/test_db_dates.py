"""data/db.py, data/dates.py, data/money.py, data/log.py: foreign keys enforced, missing-table vs real errors,
atomic config writes, date edge cases, currency formatting."""
import datetime as dt
import json
import sqlite3

import pytest

from conftest import read_family, write_family


def test_connect_enforces_foreign_keys(root, modules):
    db = modules("db")
    con = db.connect(root / "data" / "family.db")
    try:
        assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO transactions(account_id, txn_date, amount) VALUES (999999, '2026-01-01', -1)")
        con.rollback()
    finally:
        con.close()
    mode = sqlite3.connect(root / "data" / "family.db").execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", "audit A2: WAL (every copy goes through the backup API, see db.py)"


def test_readonly_connection_refuses_writes(root, modules):
    db = modules("db")
    con = db.connect(root / "data" / "family.db", readonly=True)
    try:
        with pytest.raises(sqlite3.OperationalError):
            con.execute("INSERT INTO members(name) VALUES ('x')")
    finally:
        con.close()


def test_open_commits_and_rolls_back(root, modules):
    db = modules("db")
    path = root / "data" / "family.db"
    with db.open(path) as con:
        con.execute("INSERT INTO members(name, role) VALUES ('Txn Ok', 'adult')")
    with pytest.raises(RuntimeError):
        with db.open(path) as con:
            con.execute("INSERT INTO members(name, role) VALUES ('Txn Bad', 'adult')")
            raise RuntimeError("boom")
    names = {n for (n,) in sqlite3.connect(path).execute("select name from members")}
    assert "Txn Ok" in names and "Txn Bad" not in names


def test_rows_skips_only_missing_tables(root, modules):
    db = modules("db")
    con = db.connect(root / "data" / "family.db")
    try:
        assert db.rows(con, "SELECT name FROM no_such_table_zzz") == []
        assert db.rows(con, "SELECT no_such_col FROM members") == []
        with pytest.raises(sqlite3.OperationalError):
            db.rows(con, "SELEC name FROM members")  # a typo is a bug, not an old database
        assert db.one(con, "SELECT count(*) AS n FROM members")["n"] >= 3
    finally:
        con.close()
    assert db.missing(sqlite3.OperationalError("no such table: x"))
    assert not db.missing(sqlite3.OperationalError("database is locked"))
    assert not db.missing(sqlite3.OperationalError("near \"SELEC\": syntax error"))


def test_modules_raise_on_locked_or_broken_sql_not_swallow(root, modules):
    """The narrowed catches: a real OperationalError must surface."""
    life = modules("life")
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DROP VIEW IF EXISTS v_tmp_zz")
    con.execute("CREATE VIEW v_tmp_zz AS SELECT 1 AS x")
    con.commit()
    con.close()
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE life_items (id INTEGER)")  # table exists but has none of the columns -> 'no such column' -> []
    assert life.rows(con, dt.date.today()) == []
    con.close()


def test_write_json_is_atomic_and_refreshes_cache(root, modules):
    config = modules("config")
    fam = read_family(root)
    fam["atomic_marker"] = 1
    config.write_json(root / "config" / "family.json", fam)
    assert config.family()["atomic_marker"] == 1
    assert not list((root / "config").glob("*.tmp"))
    fam.pop("atomic_marker")
    write_family(root, fam)


def test_write_secret_keeps_other_lines_and_restricts_permissions(root, modules):
    import os
    import stat
    config = modules("config")
    f = root / "config" / "secrets.env"
    f.write_text("OTHER=keep\nMITRAHOME_OPENAI_API_KEY=old\n", encoding="utf-8")
    try:
        config.write_secret("MITRAHOME_OPENAI_API_KEY", "new-value")
        txt = f.read_text(encoding="utf-8")
        assert "OTHER=keep" in txt and "MITRAHOME_OPENAI_API_KEY=new-value" in txt and "=old" not in txt
        assert not list((root / "config").glob("secrets.env.tmp"))
        if os.name != "nt":
            assert stat.S_IMODE(f.stat().st_mode) == 0o600
    finally:
        f.unlink(missing_ok=True)


@pytest.mark.parametrize("v,exp", [("2026-02-28", dt.date(2026, 2, 28)), ("2026-02-28T10:00:00", dt.date(2026, 2, 28)),
                                   ("tomorrow", None), ("", None), (None, None), ("2026-13-01", None), (20260101, dt.date(2026, 1, 1))])
def test_parse(modules, v, exp):
    assert modules("dates").parse(v) == exp


def test_add_months_and_next_annual(modules):
    d = modules("dates")
    assert d.add_months(dt.date(2027, 1, 31), 1) == dt.date(2027, 2, 28)
    assert d.add_months(dt.date(2028, 1, 31), 1) == dt.date(2028, 2, 29)
    assert d.add_months(dt.date(2026, 11, 30), 3) == dt.date(2027, 2, 28)
    assert d.add_months(dt.date(2026, 3, 31), -1) == dt.date(2026, 2, 28)
    assert d.next_annual("02-29", dt.date(2027, 1, 1)) == dt.date(2027, 2, 28)
    assert d.next_annual("02-29", dt.date(2028, 1, 1)) == dt.date(2028, 2, 29)
    assert d.next_annual("12-31", dt.date(2026, 12, 31)) == dt.date(2026, 12, 31)
    assert d.next_annual("01-01", dt.date(2026, 12, 31)) == dt.date(2027, 1, 1)
    assert d.next_annual("13-01", dt.date(2026, 1, 1)) is None and d.next_annual("", dt.date(2026, 1, 1)) is None
    assert d.valid_md("02-29") and not d.valid_md("02-30") and not d.valid_md("x")


def test_money_follows_family_currency(root, modules):
    money = modules("money")
    assert money.fmt(1234.5) == "$1,234.50" and money.fmt(-20, 0) == "-$20" and money.fmt(None) == "$0.00"
    fam = read_family(root)
    fam["currency"] = "GBP"
    write_family(root, fam)
    try:
        assert money.fmt(3) == "£3.00"
        assert money.fmt(3, code="XYZ") == "XYZ 3.00"
    finally:
        fam["currency"] = "USD"
        write_family(root, fam)


def test_logger_writes_to_logs_without_duplicates(root, modules):
    log = modules("log")
    L = log.get("test")
    L.info("hello from the test logger ZZLOG")
    L2 = log.get("test")
    L2.info("second ZZLOG")
    for h in L.handlers + logging_root(log).handlers:
        h.flush()
    txt = (root / "logs" / "mitrahome.log").read_text(encoding="utf-8")
    assert txt.count("ZZLOG") == 2 and "mitrahome.test" in txt


def logging_root(log):
    import logging
    return logging.getLogger("mitrahome")


def test_digest_runs_after_the_shared_helper_change(root):
    from conftest import run
    r = run(["data/make_digest.py"], root)
    assert r.returncode == 0, r.stderr[-400:]
    assert json.loads((root / "config" / "family.json").read_text())["family_name"] == "Test"


def test_database_runs_in_wal_and_readers_do_not_wait_for_a_writer(modules, tmp_path):
    """Audit A2: the first read-write connection switches the file to WAL; a reader sees the last commit while a
    write is open; checkpoint() folds the side file into the .db (before a plain copy)."""
    db = modules("db")
    p = tmp_path / "w.db"
    con = db.connect(p)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    con.execute("BEGIN IMMEDIATE")
    con.execute("INSERT INTO t VALUES (2)")
    ro = db.connect(p, readonly=True, timeout=1)
    assert ro.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 1, "the reader did not wait for the open write"
    con.commit()
    assert ro.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    ro.close()
    con.close()
    db.checkpoint(p)
    assert not (tmp_path / "w.db-wal").exists() or (tmp_path / "w.db-wal").stat().st_size == 0
    assert db.connect(p, readonly=True).execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
