"""One way to open data/family.db (standard library only).

    import db
    con = db.connect()                  # read-write, foreign keys enforced
    con = db.connect(readonly=True)     # read-only URI connection (reports, dashboard)
    with db.open() as con: ...          # commits on success, rolls back on error, always closes
    rows = db.rows(con, "SELECT ...")   # list of dicts; [] only when the table/column is not migrated yet

Every connection turns `PRAGMA foreign_keys` on, so a transaction cannot point at an account or document that
does not exist. The first read-write connection to a file switches it to WAL (audit A2): readers (the web app, phones,
reports) no longer wait for a writer (the inbox task, a sync), and a writer no longer waits for them. The setting lives
in the file. Every copy of the database goes through SQLite's backup API (backup.py, migrate snapshot, restore, purge,
export), which reads the -wal side file too; the two places that swap the file itself (migrate recover, live restore)
delete the old -wal / -shm first, and `checkpoint()` folds the side file into the .db before a plain file copy.

`missing(e)` tells a "table/column not created yet" OperationalError (fine to ignore on an old database) from a
real problem (locked database, disk full, SQL typo), which must surface.
"""
import contextlib
import pathlib
import sqlite3
import time

HERE = pathlib.Path(__file__).resolve().parent
import paths  # noqa: E402
DB = paths.DB
_MISSING = ("no such table", "no such column", "no such view")
_WAL = set()  # files this process already saw in WAL mode


def _wait_for_maintenance(timeout):
    """An update, restore or migration in another process replaces or rebuilds the file: wait for it, then give up with
    the same error a locked database gives (shown as "busy, try again"). Its own processes are let through."""
    import joblock
    if not joblock.maintenance_running():
        return
    end = time.time() + timeout
    while time.time() < end:
        time.sleep(0.25)
        if not joblock.maintenance_running():
            return
    raise sqlite3.OperationalError("database is locked (an update or restore is running)")


def _rollback_hot_journal(p, timeout):
    """A crash in the middle of a write leaves a hot journal that only a read-write connection may roll back; until
    then every read-only connection fails with "attempt to write a readonly database". Open one read-write, once."""
    rw = sqlite3.connect(p, timeout=timeout)
    try:
        rw.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    finally:
        rw.close()


def connect(path=None, readonly=False, row=False, timeout=10.0):
    p = pathlib.Path(path) if path else DB
    _wait_for_maintenance(timeout)
    if readonly:
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=timeout)
        try:
            con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
        except sqlite3.OperationalError as e:
            if "readonly" not in str(e).lower():
                raise
            con.close()
            _rollback_hot_journal(p, timeout)
            con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=timeout)
    else:
        con = sqlite3.connect(p, timeout=timeout)
        _wal(con, p)
    con.execute("PRAGMA foreign_keys = ON")
    if row:
        con.row_factory = sqlite3.Row
    return con


def _wal(con, p):
    """Switch the file to WAL once (a no-op when it already is). Another connection holding the file keeps the old mode
    for now (SQLite answers with the mode it kept, no error); the next connection tries again."""
    key = str(p)
    if key in _WAL:
        return
    try:
        mode = con.execute("PRAGMA journal_mode=WAL").fetchone()[0]
    except sqlite3.OperationalError:
        return
    if str(mode).lower() == "wal":
        _WAL.add(key)


def checkpoint(path=None):
    """Fold the -wal side file into the .db (before a plain file copy, a move to another folder or a swap)."""
    p = pathlib.Path(path) if path else DB
    if not p.exists():
        return
    con = sqlite3.connect(p, timeout=10)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        con.close()


@contextlib.contextmanager
def open(path=None, readonly=False, row=False):  # noqa: A001 (mirrors the built-in on purpose)
    con = connect(path, readonly=readonly, row=row)
    try:
        yield con
        if not readonly:
            con.commit()
    except BaseException:
        if not readonly:
            con.rollback()
        raise
    finally:
        con.close()


def missing(e):
    """True when an OperationalError means the schema is older than the code (table or column not there yet)."""
    s = str(e).lower()
    return any(m in s for m in _MISSING)


def rows(con, sql, params=()):
    """Rows as dicts. Returns [] when the table or column is not migrated yet; any other error is raised."""
    cur = con.cursor()
    try:
        cur.execute(sql, params)
    except sqlite3.OperationalError as e:
        if missing(e):
            _log().debug("skipped (not migrated yet): %s", e)
            return []
        raise
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def one(con, sql, params=()):
    r = rows(con, sql, params)
    return r[0] if r else None


def _log():
    import log
    return log.get("db")
