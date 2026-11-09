"""Update, restore and migrate hold one maintenance lock: jobs wait or skip, pages wait, a crashed migration's snapshot
is never thrown away, a read-only connection gets past a hot journal, and a failed household move changes nothing."""
import os
import shutil
import sqlite3
import time

import pytest

from conftest import DRY, clone, run


def _foreign(jl, name):
    """A lock held by another live process (this test's parent)."""
    p = jl.lock_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"{os.getppid()} {int(time.time())}\n", encoding="utf-8")
    return p


def test_jobs_refuse_while_another_process_runs_maintenance(root, modules):
    jl = modules("joblock")
    p = _foreign(jl, jl.MAINTENANCE)
    try:
        assert jl.maintenance_running()
        with pytest.raises(jl.Busy, match=jl.MAINTENANCE):
            with jl.job("bank_sync"):
                pass
    finally:
        p.unlink(missing_ok=True)
    with jl.job("bank_sync"):
        assert jl.is_held("bank_sync")
    assert not jl.is_held("bank_sync")


def test_maintenance_waits_for_running_jobs_and_is_reentrant(root, modules):
    jl = modules("joblock")
    p = _foreign(jl, "intake")
    try:
        with pytest.raises(jl.Busy, match="intake"):
            with jl.maintenance(wait_jobs=0.2):
                pass
        assert not jl.is_held(jl.MAINTENANCE), "nothing left behind"
    finally:
        p.unlink(missing_ok=True)
    with jl.maintenance(wait_jobs=0):
        assert os.environ.get(jl.ENV) == "1" and not jl.maintenance_running(), "its own processes are let through"
        with jl.maintenance():  # a migration started by the update
            pass
        assert jl.is_held(jl.MAINTENANCE)
    assert os.environ.get(jl.ENV) is None and not jl.is_held(jl.MAINTENANCE)


def test_a_fresh_empty_lock_file_is_not_taken_over(root, modules):
    jl = modules("joblock")
    p = jl.lock_path("unit2")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("", encoding="utf-8")  # its owner is between creating and writing it
    try:
        with pytest.raises(jl.Busy):
            with jl.held("unit2"):
                pass
        old = time.time() - 60
        os.utime(p, (old, old))
        with jl.held("unit2"):
            pass
    finally:
        p.unlink(missing_ok=True)


def test_pages_wait_for_maintenance_then_say_locked(root, modules):
    jl, db = modules("joblock"), modules("db")
    p = _foreign(jl, jl.MAINTENANCE)
    try:
        t0 = time.time()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            db.connect(timeout=0.3)
        assert time.time() - t0 >= 0.25
    finally:
        p.unlink(missing_ok=True)
    db.connect().close()


def test_scheduled_tasks_skip_their_turn_during_maintenance(root, modules):
    jl, paths = modules("joblock"), modules("paths")
    p = _foreign(jl, jl.MAINTENANCE)
    try:
        r = run(["tasks/run_task.py", "inbox_sweep"], root, env=DRY)
        assert r.returncode == 0, r.stderr[-300:]
        log = (paths.LOGS / "mitrahome.log").read_text(encoding="utf-8", errors="replace")
        assert "inbox_sweep: skipped, an update or restore is running" in log
    finally:
        p.unlink(missing_ok=True)


def test_a_crashed_migration_snapshot_is_kept_and_can_be_put_back(golden, tmp_path):
    r0 = clone(golden, tmp_path / "t")
    dbf = r0 / "data" / "family.db"
    snap = dbf.with_name("family.db.migrating")
    shutil.copy2(dbf, snap)  # the copy from before a migration that never finished
    con = sqlite3.connect(dbf)
    con.execute("CREATE TABLE half_done(x)")
    con.commit()
    con.close()
    r = run(["data/migrate.py"], r0, env=DRY)
    assert r.returncode == 1 and "stopped half way" in r.stdout and snap.exists()
    r = run(["data/migrate.py", "recover"], r0, env=DRY)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not snap.exists() and dbf.with_name("family.db.half-updated").exists()
    assert not sqlite3.connect(dbf).execute("SELECT 1 FROM sqlite_master WHERE name='half_done'").fetchone()
    assert run(["data/migrate.py"], r0, env=DRY).returncode == 0


def test_a_read_only_connection_gets_past_a_hot_journal(root, modules, tmp_path):
    db = modules("db")
    a = tmp_path / "a.db"
    con = sqlite3.connect(a)
    con.execute("CREATE TABLE t(x TEXT)")
    con.executemany("INSERT INTO t VALUES (?)", [("x" * 500,)] * 4000)
    con.commit()
    con.execute("PRAGMA cache_size=5")
    con.execute("BEGIN IMMEDIATE")
    con.execute("UPDATE t SET x = ?", ("y" * 500,))  # spills pages: a journal that would be hot after a crash
    crashed = tmp_path / "crashed"
    crashed.mkdir()
    shutil.copy2(a, crashed / "a.db")
    shutil.copy2(str(a) + "-journal", crashed / "a.db-journal")
    con.rollback()
    con.close()
    ro = db.connect(crashed / "a.db", readonly=True)
    try:
        assert ro.execute("SELECT COUNT(*) FROM t WHERE x LIKE 'x%'").fetchone()[0] == 4000, "rolled back"
    finally:
        ro.close()


def test_a_failed_household_move_changes_nothing(golden, tmp_path):
    r0 = clone(golden, tmp_path / "t")
    (r0 / "inbox").mkdir(exist_ok=True)
    (r0 / "inbox" / "waiting.pdf").write_bytes(b"%PDF-1.4 test")
    home = tmp_path / "home"
    home.mkdir()
    (home / "inbox").write_text("a file where the inbox folder should go", encoding="utf-8")
    r = run(["onboard.py", "home", str(home)], r0, env=DRY)
    assert r.returncode != 0 and "was not moved" in (r.stdout + r.stderr)
    assert not (r0 / "mitrahome_home.txt").exists(), "the pointer is written only after everything moved"
    assert (r0 / "data" / "family.db").exists() and not (home / "family.db").exists(), "the database came back"
    assert (r0 / "inbox" / "waiting.pdf").exists()


def test_an_update_keeps_only_the_newest_automatic_copies(golden, tmp_path):
    """Audit D4: backups_pre_upgrade kept every copy for good; now the newest 5 database and 3 code copies stay, and
    copies saved there by hand under another name are never touched."""
    r0 = clone(golden, tmp_path / "t")
    bk = r0 / "data" / "backups_pre_upgrade"
    bk.mkdir(parents=True, exist_ok=True)
    for d in range(1, 9):
        (bk / f"family_2026-01-0{d}_120000.db").write_bytes(b"x")
    for v, d in (("0.99.0", "20260101"), ("0.100.0", "20260102"), ("0.101.0", "20260103"), ("0.117.3", "20260104")):
        (bk / f"code_{v}_{d}_120000").mkdir()
    (bk / "family_before_move.db").write_bytes(b"mine")
    driver = tmp_path / "prune.py"  # in its own process: importing onboard puts the copy's data/ on sys.path
    driver.write_text("\n".join(["import sys", f"sys.path.insert(0, {str(r0)!r})", "import onboard",
                                 f"print('REMOVED', onboard.prune_pre_upgrade({str(bk)!r}))", ""]), encoding="utf-8")
    r = run([str(driver)], r0, env=DRY)
    assert "REMOVED 4" in r.stdout, r.stdout + r.stderr[-400:]
    left = sorted(p.name for p in bk.iterdir())
    assert "family_before_move.db" in left
    assert [n for n in left if n.startswith("family_2026")] == [f"family_2026-01-0{d}_120000.db" for d in range(4, 9)]
    assert [n for n in left if n.startswith("code_")] == ["code_0.100.0_20260102_120000", "code_0.101.0_20260103_120000",
                                                          "code_0.117.3_20260104_120000"]
