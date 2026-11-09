"""Versioned migration runner.

  python data/migrate.py            apply every migrate_*.py not yet recorded (creates the DB from schema.sql if missing)
  python data/migrate.py status     list applied / pending migrations, the template version, edited files, unconstrained tables
  python data/migrate.py verify     exit 1 if an applied migration file was edited after it ran
  python data/migrate.py recover    put back the copy left by an update that stopped half way

Applied migrations are recorded in table `schema_migrations` with the SHA-256 of the script that ran. Each migration
runs in its own process against a snapshot: the database file is copied first and put back if the script fails, so a
failed update leaves the data exactly as it was, nothing half-applied, and `meta.template_version` is only written
once every migration succeeded (the downgrade guard can trust it). Existing databases from before this runner simply
re-run each idempotent migration once and are then recorded. `python onboard.py upgrade` backs up first as well.

Numbering: 011 was never shipped; the gap is deliberate and nothing is missing.
"""
import brand
import hashlib
import os
import pathlib
import sqlite3
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
import paths  # noqa: E402
DB = paths.DB
SNAP = paths.DB.with_name("family.db.migrating")
VERSION = (HERE.parent / "VERSION").read_text(encoding="utf-8").strip() if (HERE.parent / "VERSION").exists() else "0"


def _con():
    con = sqlite3.connect(DB)
    con.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT, template_version TEXT)")
    if "checksum" not in {r[1] for r in con.execute("PRAGMA table_info(schema_migrations)")}:
        con.execute("ALTER TABLE schema_migrations ADD COLUMN checksum TEXT")
    con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    con.commit()
    return con


def checksum(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _matches(path, recorded):
    """True when the file is what ran, ignoring line endings (Windows checkouts rewrite LF as CRLF)."""
    raw = pathlib.Path(path).read_bytes()
    lf = raw.replace(b"\r\n", b"\n")
    return recorded in {hashlib.sha256(v).hexdigest() for v in (raw, lf, lf.replace(b"\n", b"\r\n"))}


# Migrations changed on purpose after they shipped: name -> SHA-256 of every earlier version (LF and CRLF form).
# A database that recorded one of these gets the current checksum quietly; any other mismatch is still reported.
REVISED = {
    "migrate_025_constraints.py": {
        "e8bc9df127a02872af1072116b81238a52225db5f9fbb4063aa924b885674dda",  # 0.15.0 (LF)
        "6fd73844b29bcc4b553e7e9d0a5ec347d400ba8986e11d0ee7ef5a68bdb96866",  # 0.15.0 (CRLF)
        "7da6e08808acae7405716a4acc16dc515db128ed125f8a2adac01c29e3936eda",  # 0.61.0 (LF)
        "f16448d0cd8d1e6492b0964e8f6238825cd1b189533e53edee5dc5a6a84783ec",  # 0.61.0 (CRLF)
    },
}


def refresh_revised(con):
    """Re-record the checksum of a revised migration whose stored checksum is a known earlier version."""
    for name, sum_ in con.execute("SELECT name, checksum FROM schema_migrations").fetchall():
        p = HERE / name
        if sum_ in REVISED.get(name, ()) and p.exists():
            con.execute("UPDATE schema_migrations SET checksum=? WHERE name=?", (checksum(p), name))
    con.commit()


def pending(con):
    done = {r[0] for r in con.execute("SELECT name FROM schema_migrations")}
    return [p for p in sorted(HERE.glob("migrate_*.py")) if p.name not in done]


def edited(con):
    """Applied migrations whose file no longer matches the recorded checksum."""
    out = []
    for name, sum_ in con.execute("SELECT name, checksum FROM schema_migrations"):
        p = HERE / name
        if sum_ and p.exists() and not _matches(p, sum_):
            out.append(name)
    return out


def unconstrained(con):
    """Tables migration 025 could not rebuild (rows it could not repair); see migrate_025_constraints.py."""
    try:
        sys.path.insert(0, str(HERE))
        import migrate_025_constraints as m25
    except ImportError:
        return []
    have = {r[0]: r[1] or "" for r in con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")}
    return [t for t in m25.SPEC if t in have and f"ck_{t}_" not in have[t]]


REF_INDEX = ("CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_acct_ref ON transactions(account_id, ref) "
             "WHERE ref IS NOT NULL AND ref != ''")


def ensure_indexes(con):
    """Audit D7: migration 025 skipped the unique (account, ref) index while two lines of one account shared a bank
    reference, and never tried again. Every migrate run (each update, and `python data/migrate.py`) tries again:
    created once no pair repeats; otherwise -> how many pairs repeat (they are left alone: a reference column can be a check number or a
    row number that repeats for real, so nothing is deleted)."""
    if not con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='transactions'").fetchone():
        return 0
    if con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_transactions_acct_ref'").fetchone():
        return 0
    dup = con.execute("SELECT COUNT(*) FROM (SELECT account_id, ref FROM transactions WHERE ref IS NOT NULL AND ref != '' "
                      "GROUP BY account_id, ref HAVING COUNT(*) > 1)").fetchone()[0]
    if not dup:
        con.execute(REF_INDEX)
    return dup


def repeated_refs(con, limit=20):
    """[(account_id, ref, count)] of bank references shared by more than one line of an account (for status)."""
    try:
        return con.execute("SELECT account_id, ref, COUNT(*) FROM transactions WHERE ref IS NOT NULL AND ref != '' "
                           "GROUP BY account_id, ref HAVING COUNT(*) > 1 ORDER BY account_id, ref LIMIT ?", (limit,)).fetchall()
    except sqlite3.OperationalError:
        return []


def _log():
    sys.path.insert(0, str(HERE))
    import log
    return log.get("migrate")


def _v(s):
    import re
    return tuple(int(x) for x in re.findall(r"\d+", str(s))[:3])


def _snapshot():
    src = sqlite3.connect(DB)
    try:
        dst = sqlite3.connect(SNAP)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _restore():
    for side in ("-journal", "-wal", "-shm"):
        p = DB.with_name(DB.name + side)
        if p.exists():
            p.unlink()
    os.replace(SNAP, DB)


STALE_SNAP = ("A database update stopped half way last time (the PC switched off or the window was closed). The copy "
              "from before it is kept as {snap}. Nothing was changed now. Put that copy back with: python data/migrate.py "
              "recover   (then start again).")


def recover():
    """Put the copy from before a migration that never finished back in place; the half-updated file is kept aside."""
    if not SNAP.exists():
        print("Nothing to recover: no half-finished database update.")
        return True
    if DB.exists():
        aside = DB.with_name("family.db.half-updated")
        aside.unlink(missing_ok=True)
        os.replace(DB, aside)
        print(f"  the half-updated database is kept as {aside.name}")
    _restore()
    print("  the database from before the update is back; run python onboard.py upgrade (or start the app) again")
    _log().warning("recovered the snapshot left by an unfinished migration")
    return True


def run():
    if SNAP.exists():  # a migration crashed (only one runs at a time: joblock): its snapshot is the good copy
        print(STALE_SNAP.format(snap=SNAP))
        return False
    if DB.exists():
        con0 = sqlite3.connect(DB)
        try:
            row = con0.execute("SELECT value FROM meta WHERE key='template_version'").fetchone()
            if row and _v(row[0]) > _v(VERSION):
                print(f"This database was last migrated by {brand.PRODUCT} {row[0]}, newer than the code ({VERSION}). "
                      "Update the code (python onboard.py update) instead of running older code on newer data.")
                return False
        except sqlite3.OperationalError:
            pass
        finally:
            con0.close()
    fresh = not DB.exists()
    if not fresh:
        con0 = sqlite3.connect(DB)
        fresh = not con0.execute("SELECT 1 FROM sqlite_master WHERE name='documents'").fetchone()
        con0.close()
    if fresh:
        r = subprocess.run([sys.executable, str(HERE / "init_db.py")], cwd=HERE.parent, capture_output=True, text=True)
        if r.returncode:
            print(r.stderr)
            return False
    con = _con()
    refresh_revised(con)
    for name in edited(con):
        print(f"  note: {name} was edited after it was applied (python data/migrate.py verify)")
    todo = pending(con)
    con.close()
    ok = True
    for mig in todo:
        _snapshot()
        r = subprocess.run([sys.executable, str(mig)], cwd=HERE.parent, capture_output=True, text=True)
        if r.returncode:
            print(f"  {mig.name}: FAILED\n{r.stderr[-600:]}")
            _restore()
            print(f"  {mig.name}: database put back as it was before this migration")
            _log().error("failed %s; database restored from snapshot", mig.name)
            ok = False
            break
        SNAP.unlink()
        con = _con()
        con.execute("INSERT OR REPLACE INTO schema_migrations(name, applied_at, template_version, checksum) "
                    "VALUES (?, strftime('%Y-%m-%dT%H:%M:%S','now','localtime'), ?, ?)", (mig.name, VERSION, checksum(mig)))
        con.commit()
        con.close()
        out = r.stdout.strip().splitlines()
        print(f"  {mig.name}: applied" + ("\n    " + "\n    ".join(out[-6:]) if out else ""))
        _log().info("applied %s (template %s)", mig.name, VERSION)
    if ok:
        con = _con()
        con.execute("INSERT OR REPLACE INTO meta VALUES ('template_version', ?)", (VERSION,))
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_log'").fetchone():
            import sync_data  # any table rebuild (a migration re-run by hand included) loses its triggers: restore them
            sync_data.ensure_triggers(con)
        dup = ensure_indexes(con)
        con.commit()
        if dup:
            print(f"  note: {dup} bank reference(s) repeat within an account, so duplicate imports are caught by the "
                  "import check only (python data/migrate.py status lists them)")
        for t in unconstrained(con):
            print(f"  note: table {t} still runs without its CHECK constraints (python data/migrate.py status)")
        con.close()
    return ok


def status():
    con = _con()
    refresh_revised(con)
    done = {r[0]: r[1] for r in con.execute("SELECT name, applied_at FROM schema_migrations")}
    changed = set(edited(con))
    print(f"template version {VERSION}")
    for p in sorted(HERE.glob("migrate_*.py")):
        flag = "  (changed since applied)" if p.name in changed else ""
        print(f"  [{'x' if p.name in done else ' '}] {p.name}  {done.get(p.name, 'pending')}{flag}")
    un = unconstrained(con)
    if un:
        print("unconstrained tables (rows migration 025 could not repair; fix them, then run: "
              "python data/migrate_025_constraints.py and python data/migrate_046_real_dates.py): " + ", ".join(un))
    rep = repeated_refs(con)
    if rep:
        print("missing index idx_transactions_acct_ref: these bank references repeat within an account (the same line "
              "imported twice? remove the extra copy from Settings > Data > Data check; the next start creates it):")
        for acct, ref, n in rep:
            print(f"  account {acct}  ref {ref}  x{n}")
    con.close()


def verify():
    con = _con()
    refresh_revised(con)
    bad = edited(con)
    con.close()
    for name in bad:
        print(f"  {name}: edited after it was applied")
    print("ok" if not bad else f"{len(bad)} migration file(s) differ from what ran on this database")
    return not bad


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "status":
        status()
    elif cmd == "verify":
        sys.exit(0 if verify() else 1)
    elif cmd == "recover":
        sys.exit(0 if recover() else 1)
    else:
        import joblock
        try:
            with joblock.maintenance(wait_jobs=120):
                ok = run()
        except joblock.Busy as e:
            print("Another update or restore is running; try again when it has finished." if str(e) == joblock.MAINTENANCE
                  else f"A {str(e).replace('_', ' ')} run did not finish within two minutes; nothing was changed.")
            ok = False
        sys.exit(0 if ok else 1)
