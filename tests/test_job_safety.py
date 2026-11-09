"""Jobs that move papers or change many rows: one inbox run at a time, a paper whose record never commits goes back to
the inbox, database errors say what happened (BUSY only when the database is locked), duplicate charges with a receipt
each can be removed, and pets never get a PIN."""
import os
import sqlite3

import pytest

from conftest import db, q, read_family, write_family

ADULT = {"name": "Alex", "role": "adult"}


def test_a_job_lock_is_held_once_and_a_dead_owner_is_taken_over(root, modules):
    jl = modules("joblock")
    with jl.held("unit"):
        with pytest.raises(jl.Busy):
            with jl.held("unit"):
                pass
    assert not jl.lock_path("unit").exists(), "released"
    jl.lock_path("unit").write_text("999999999 1\n", encoding="utf-8")  # a process that is long gone
    with jl.held("unit"):
        assert jl.lock_path("unit").read_text(encoding="utf-8").split()[0] == str(os.getpid())


def test_a_second_inbox_run_waits_and_leaves_the_files(root, modules, capsys):
    ai, jl, paths = modules("ai_intake"), modules("joblock"), modules("paths")
    paths.INBOX.mkdir(exist_ok=True)
    f = paths.INBOX / "waiting.txt"
    f.write_text("a bill", encoding="utf-8")
    try:
        with jl.held("intake"):
            assert ai.run() == 0
        assert f.exists() and "another filing run" in capsys.readouterr().out
    finally:
        f.unlink(missing_ok=True)


def test_a_paper_whose_record_never_commits_goes_back_to_the_inbox(root, modules, monkeypatch):
    ai, paths = modules("ai_intake"), modules("paths")
    paths.INBOX.mkdir(exist_ok=True)
    f = paths.INBOX / "power-bill.txt"
    f.write_text("Acme Power bill", encoding="utf-8")
    before = q(root, "SELECT COUNT(*) FROM documents")

    def busy_after_filing(con, f, local=False, step=None):
        ai.file_document(con, f, "bill", "Acme Power", "2026-10-01", 12.5, "2026-10-20", "test")
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ai, "process_file", busy_after_filing)
    try:
        assert ai.run() == 1, "skipped files make the run report it"
        assert f.exists(), "back in the inbox for the next run"
        assert not list((paths.ARCHIVE / "2026").rglob("*acme*power*")), "nothing left in the archive"
        assert q(root, "SELECT COUNT(*) FROM documents") == before
    finally:
        f.unlink(missing_ok=True)


def test_a_paper_whose_record_was_committed_stays_filed(root, modules, monkeypatch):
    ai, paths = modules("ai_intake"), modules("paths")
    paths.INBOX.mkdir(exist_ok=True)
    f = paths.INBOX / "phone-bill.txt"
    f.write_text("Acme Mobile bill", encoding="utf-8")
    before = q(root, "SELECT COUNT(*) FROM documents")

    def fails_after_commit(con, f, local=False, step=None):  # like the phone bill and PayPal routes
        ai.file_document(con, f, "bill", "Acme Mobile", "2026-10-02", 40, "2026-10-21", "test")
        con.commit()
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ai, "process_file", fails_after_commit)
    try:
        ai.run()
        assert not f.exists(), "not put back: the next run would file it twice"
        assert q(root, "SELECT COUNT(*) FROM documents")[0][0] == before[0][0] + 1
        assert list((paths.ARCHIVE / "2026").rglob("*acme*mobile*")), "the paper stays with its record"
    finally:
        f.unlink(missing_ok=True)


def test_database_errors_say_what_happened(root, modules):
    ea = modules("edit_actions")

    @ea.edits
    def raises(e):
        raise e

    assert raises(sqlite3.OperationalError("database is locked")) == (False, ea.BUSY)
    assert raises(sqlite3.IntegrityError("UNIQUE constraint failed: receipts.transaction_id")) == (False, ea.CLASH)
    assert raises(sqlite3.OperationalError("disk I/O error")) == (False, ea.FAILED)
    assert "receipts.transaction_id" in (root / "logs" / "mitrahome.log").read_text(encoding="utf-8")


def test_duplicate_charges_with_a_receipt_each_can_be_removed(root, modules):
    af = modules("audit_fix")
    con = db(root)
    try:
        acct = con.execute("SELECT id FROM accounts LIMIT 1").fetchone()[0]
        a = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2026-09-03', 'CAFE', -4.5)", (acct,)).lastrowid
        b = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2026-09-03', 'CAFE', -4.5)", (acct,)).lastrowid
        for t in (a, b):
            con.execute("INSERT INTO receipts(merchant, receipt_date, total, transaction_id, created_at) VALUES ('Cafe', '2026-09-03', 4.5, ?, '2026-09-04T10:00:00')", (t,))
        con.commit()
        undo = af.remove_rows(con, "transactions", a, [b])
        con.commit()
        assert undo
        assert con.execute("SELECT COUNT(*) FROM transactions WHERE id=?", (b,)).fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM receipts WHERE transaction_id=?", (a,)).fetchone()[0] == 1
        assert con.execute("SELECT COUNT(*) FROM receipts WHERE merchant='Cafe' AND transaction_id IS NULL").fetchone()[0] == 1
    finally:
        con.close()


def test_pets_never_get_a_pin(root, modules):
    aa, auth = modules("admin_actions"), modules("auth")
    assert "Biscuit" not in [p["name"] for p in aa.pin_people()]
    assert aa.pin_set(ADULT, "Biscuit", "1234", "1234")[0] is False
    fam = read_family(root)
    saved = dict(fam)
    fam["dashboard_users"] = [{"name": "Biscuit", "role": "limited", "pin_hash": auth.hash_pin("1234")}]
    write_family(root, fam)
    try:
        assert auth.users() == [] and auth.login("Biscuit", "1234") is None, "a PIN given to a pet earlier no longer signs in"
    finally:
        write_family(root, saved)


def test_long_running_processes_log_to_their_own_file(modules, root):
    """S7: the web app and the phone bots write logs/mitrahome-<process>.log; a refused rotation keeps the line."""
    import logging
    log = modules("log")
    base = logging.getLogger("mitrahome")
    log.use("web")
    try:
        log.get("t").warning("from the web app")
        h = base.handlers[0]
        h.flush()
        assert "from the web app" in (root / "logs" / "mitrahome-web.log").read_text(encoding="utf-8")
        real = h.rotate

        def refused(src, dst):
            raise PermissionError("held open by another process")
        h.rotate = refused
        h.maxBytes = 1  # every record wants a rotation now
        log.get("t").warning("still written")
        h.flush()
        assert "still written" in (root / "logs" / "mitrahome-web.log").read_text(encoding="utf-8")
        h.rotate = real
        try:
            log.use("../escape")
            raise AssertionError("a path is not a process name")
        except ValueError:
            pass
    finally:
        log.FILE = log.paths.LOGS / "mitrahome.log"
        log._ready = False
        for x in list(base.handlers):
            base.removeHandler(x)
            x.close()
