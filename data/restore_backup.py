"""Restore or verify a Mitra Home backup (encrypted or plain).

  python data/restore_backup.py SRC --verify              decrypt the newest database snapshot to a temp file and check it
  python data/restore_backup.py SRC OUT [--db NAME]       restore database, archive and config into a NEW folder OUT
  python data/restore_backup.py live SRC NAME [--wait PID] [--relaunch PORT] [--by WHO]
                                                          replace THIS install's database with snapshot NAME (Settings >
                                                          Data > Restore from backup runs this after closing the dashboard)

SRC is a backup destination folder (the one that contains db/). OUT must not exist or must be empty; nothing in your live
project is touched. Afterwards copy OUT/data/family.db, OUT/archive and OUT/config into a fresh install and run
`python onboard.py upgrade`. Encrypted backups need the passphrase (MITRAHOME_BACKUP_PASSPHRASE, config/secrets.env, or a prompt).

`live` is the in-place restore: it waits for the dashboard (PID) to close, stops the phone bot, checks the snapshot, keeps
a copy of today's database in Mitra-Home-Backup/before_restore/, swaps the database in, brings back archive and config
files that are missing here (nothing present is overwritten; secrets are never in a backup), applies database updates,
writes logs/restore_result.json, then starts the bot and the dashboard again.
"""
import datetime as dt
import getpass
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import brand  # noqa: E402
import crypto_box as cb  # noqa: E402

LOGS = paths.LOGS
RESULT = LOGS / "restore_result.json"
BEFORE_KEEP = 5


def destinations():
    """Backup folders this install writes to: next to the project, plus backup_dest. -> [(label, Path)]."""
    import config
    out = [("on this PC", paths.BACKUPS)]
    other = (config.family().get("backup_dest") or "").strip()
    if other:
        out.append(("second backup place", Path(other)))
    return out


def _before_dir():
    return paths.BACKUPS / "before_restore"


def snapshots():
    """Every database snapshot found, newest first, plus the copies kept just before a restore (to undo one).
    -> [{src, name, where, when, encrypted}]."""
    out = []
    places = [(where, src / "db", src, "%Y-%m-%d_%H%M") for where, src in destinations()]
    places.append(("copy from just before a restore", _before_dir(), _before_dir(), "%Y-%m-%d_%H%M%S"))
    for where, folder, src, fmt in places:
        try:
            files = list(folder.glob("family_*.db*"))
        except OSError:
            continue
        for p in files:
            if p.suffix not in (".db", ".enc"):
                continue
            try:
                when = dt.datetime.strptime(p.name[len("family_"):].split(".")[0], fmt)
            except ValueError:
                continue
            out.append({"src": str(src), "name": p.name, "where": where, "when": when, "encrypted": p.suffix == ".enc"})
    return sorted(out, key=lambda x: (x["when"], x["where"] == "on this PC"), reverse=True)


def newest_db(src: Path, db_name=None):
    folder = src / "db" if (src / "db").is_dir() else src  # before_restore/ holds its copies directly
    cands = sorted(folder.glob("family_*.db*"))
    if db_name:
        cands = [c for c in cands if c.name == db_name]
    if not cands:
        raise SystemExit(f"no database snapshot found in {src / 'db'}")
    return cands[-1]


def cipher_for(src: Path, passphrase=None, ask=True):
    salt_f = src / "backup.salt"
    if not salt_f.exists():
        return None
    pw = passphrase or cb.load_passphrase() or (getpass.getpass("Backup passphrase: ") if ask else "")
    if not pw:
        raise SystemExit("this backup is encrypted and needs its passphrase")
    f = cb.cipher(pw, salt_f.read_bytes())
    try:
        if cb.decrypt_bytes((src / "backup.check").read_bytes(), f) != cb.CHECK_TEXT:
            raise ValueError
    except Exception:
        raise SystemExit("wrong passphrase for this backup")
    return f


def restore_db(src, out_file, fern, db_name=None):
    dbf = newest_db(src, db_name)
    if dbf.suffix == ".enc":
        if fern is None:
            raise SystemExit("encrypted snapshot but no backup.salt found")
        cb.decrypt_file(dbf, out_file, fern)
    else:
        shutil.copy2(dbf, out_file)
    con = sqlite3.connect(out_file)
    ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    tables = con.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]
    if ok:  # a restored copy is a new copy: paired phones take a full copy again (data/sync_data.py epoch, audit M9)
        try:
            con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('sync_epoch', ?)", (secrets.token_hex(4),))
            con.commit()
        except sqlite3.OperationalError:
            pass  # an old backup without `meta`: migrate.py makes it; the first pull then sets an epoch
    con.close()
    return dbf.name, ok, tables


def restore_tree(src: Path, enc_dir: str, plain_dir: str, out_dir: Path, fern, only_missing=False):
    """Copy a backed-up folder into out_dir. only_missing: files already in out_dir are left as they are."""
    n = 0
    if fern is not None and (src / enc_dir / "manifest.enc").exists():
        manifest = json.loads(cb.decrypt_bytes((src / enc_dir / "manifest.enc").read_bytes(), fern))
        for name, meta in manifest.items():
            target = (out_dir / meta["path"]).resolve()
            if out_dir.resolve() not in target.parents:
                continue  # manifest path escaping the target folder: skip
            if only_missing and target.exists():
                continue
            if (src / enc_dir / name).exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                cb.decrypt_file(src / enc_dir / name, target, fern)
                n += 1
    elif (src / plain_dir).exists():
        if not only_missing:
            shutil.copytree(src / plain_dir, out_dir, dirs_exist_ok=True)
            return sum(1 for p in out_dir.rglob("*") if p.is_file())
        for p in (src / plain_dir).rglob("*"):
            t = out_dir / p.relative_to(src / plain_dir)
            if p.is_file() and not t.exists():
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, t)
                n += 1
    return n


def _plain(msg):
    return {"wrong passphrase for this backup": "That passphrase does not open this backup.",
            "this backup is encrypted and needs its passphrase": "This backup is locked. Type its passphrase."}.get(msg, msg)


def _fern_for(src, name, passphrase):
    """The key for snapshot NAME: required for a locked (.enc) one; for a plain one taken before encryption was turned
    on, used only if the passphrase is at hand (for papers backed up locked), never asked for."""
    if name.endswith(".enc"):
        return cipher_for(src, passphrase, ask=False)
    try:
        return cipher_for(src, passphrase, ask=False)
    except SystemExit:
        return None


def check(src, name, passphrase=None):
    """Open one snapshot in a temp folder and check it. -> (ok, message). Never touches the live database."""
    try:
        fern = _fern_for(Path(src), name, passphrase)
        with tempfile.TemporaryDirectory() as td:
            _, ok, tables = restore_db(Path(src), Path(td) / "check.db", fern, name)
    except SystemExit as e:
        return False, _plain(str(e))
    except Exception as e:  # noqa: BLE001 (a damaged file must come back as a sentence)
        return False, f"This backup could not be read ({type(e).__name__})."
    if not ok or not tables:
        return False, "This backup is damaged and cannot be used."
    return True, f"This backup is readable ({tables} tables)."


# ---------- live restore (Settings > Data > Restore from backup)
def _alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _wait(pred, seconds, step=0.5):
    end = time.time() + seconds
    while time.time() < end:
        if pred():
            return True
        time.sleep(step)
    return pred()


def _detached():
    if os.name == "nt":
        return {"creationflags": 0x08000000 | 0x00000200}  # no console window, own process group
    return {"start_new_session": True}


def relaunch_web(port, lan=False):
    """Start the web app again on the port it had (and on the home Wi-Fi when it was), so the open tab comes back."""
    LOGS.mkdir(exist_ok=True)
    logf = open(LOGS / "webapp_restart.log", "a", encoding="utf-8")  # noqa: SIM115 (the child keeps it)
    subprocess.Popen([sys.executable, str(HERE / "web_app.py"), "--port", str(int(port))] + (["--lan"] if lan else []),
                     cwd=ROOT, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, **_detached())


def last_result():
    try:
        return json.loads(RESULT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _keep_before(live_db):
    """A plain copy of today's database (WAL included) in Mitra-Home-Backup/before_restore. -> Path or None."""
    if not live_db.exists():
        return None
    d = _before_dir()
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"family_{dt.datetime.now():%Y-%m-%d_%H%M%S}.db"
    src = sqlite3.connect(live_db, timeout=15)
    dst = sqlite3.connect(out)
    with dst:
        src.backup(dst)
    src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    src.close()
    dst.close()
    for old in sorted(d.glob("family_*.db"))[:-BEFORE_KEEP]:
        old.unlink(missing_ok=True)
    return out


def made_by_newer(db_file):
    """The version that last migrated `db_file` when it is newer than this code (it would refuse to migrate it, and
    older code must not run on newer data), else ''."""
    import migrate
    try:
        con = sqlite3.connect(db_file)
        try:
            row = con.execute("SELECT value FROM meta WHERE key='template_version'").fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return ""
    return str(row[0]) if row and row[0] and migrate._v(row[0]) > migrate._v(migrate.VERSION) else ""


def restore_live(src, name, passphrase=None, wait_pid=None, relaunch=None, by="local", bot_wait=90, web=True, lan=False):
    """Replace this install's database with snapshot NAME from SRC. -> result dict (also in logs/restore_result.json)."""
    import admin_actions as aa
    res = {"at": dt.datetime.now().isoformat(timespec="seconds"), "snapshot": name, "ok": False, "message": "", "kept": ""}
    bot_was = False
    try:
        if wait_pid and not _wait(lambda: not _alive(wait_pid), 60):
            raise RuntimeError("The app did not close, so nothing was changed.")
        if aa.bot_running():
            bot_was = True
            LOGS.mkdir(exist_ok=True)
            aa.BOT_STOP.write_text(res["at"], encoding="utf-8")
            if not _wait(lambda: not aa.BOT_PID.exists(), bot_wait):
                raise RuntimeError("The phone bot did not stop, so nothing was changed. Stop it in Settings and try again.")
        srcp = Path(src)
        try:
            fern = _fern_for(srcp, name, passphrase)
        except SystemExit as e:
            raise RuntimeError(_plain(str(e))) from None
        live = paths.DB
        tmp = paths.DB.with_name("family.db.restoring")
        tmp.unlink(missing_ok=True)
        try:
            _, ok, tables = restore_db(srcp, tmp, fern, name)
        except SystemExit as e:
            raise RuntimeError(_plain(str(e))) from None
        if not ok or not tables:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("That backup is damaged, so nothing was changed.")
        newer = made_by_newer(tmp)
        if newer:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"That backup was made by a newer {brand.PRODUCT} ({newer}) than this PC runs. Update this "
                               "PC first (Settings > Data > Updates), then restore. Nothing was changed.")
        import joblock
        try:
            hold = joblock.maintenance(wait_jobs=120)  # running jobs finish first; new ones skip their turn until done
            hold.__enter__()
        except joblock.Busy:
            tmp.unlink(missing_ok=True)
            raise RuntimeError("A scheduled job (inbox, bank sync or backup) is still running, or another update or "
                               "restore is, so nothing was changed. Try again in a few minutes.") from None
        try:
            try:
                kept = _keep_before(live)
                for side in ("-wal", "-shm", "-journal"):
                    Path(str(live) + side).unlink(missing_ok=True)
                os.replace(tmp, live)
            except (OSError, sqlite3.Error):
                tmp.unlink(missing_ok=True)
                raise RuntimeError("Something else is using the database, so nothing was changed. Try again in a few "
                                   "minutes.") from None
            res["kept"] = str(kept) if kept else ""
            res["ok"] = True
            na = restore_tree(srcp, "archive_enc", "archive", paths.ARCHIVE, fern, only_missing=True)
            nc = restore_tree(srcp, "config_enc", "config", paths.CONFIG, fern, only_missing=True)
            m = subprocess.run([sys.executable, str(HERE / "migrate.py")], cwd=ROOT, capture_output=True, text=True,
                               timeout=600)
        finally:
            hold.__exit__(None, None, None)
        stamp = name[len("family_"):].split(".")[0]
        res["message"] = (f"Restored the backup from {stamp[:10]} {stamp[11:13]}:{stamp[13:15]}. "
                          + (f"{na} filed paper(s) that were missing came back. " if na else "")
                          + (f"{nc} settings file(s) that were missing came back. " if nc else "")
                          + ("" if m.returncode == 0 else "Database updates did not finish: open Settings > Data > Health check.")).strip()
    except RuntimeError as e:
        res["message"] = str(e)
    except Exception as e:  # noqa: BLE001 (the result must still be written and the app reopened)
        res["message"] = (f"The restore stopped part way ({type(e).__name__}). " + ("The database was restored; check Settings > "
                          "Data > Health check." if res["ok"] else "Nothing was changed."))
    LOGS.mkdir(exist_ok=True)
    RESULT.write_text(json.dumps(res, indent=1), encoding="utf-8")
    aa._audit({"name": by}, "restore", f"snapshot={name} ok={res['ok']}")
    if bot_was:
        aa.bot_start({"name": by, "role": "adult"})
    if relaunch:
        relaunch_web(relaunch, lan)
    return res


def start_live(src, name, passphrase=None, by="local", port=8601, web=True, lan=False):
    """Run restore_live in a separate process that outlives this one (the dashboard or web app closes itself next)."""
    env = dict(os.environ)
    if passphrase:
        env["MITRAHOME_BACKUP_PASSPHRASE"] = passphrase  # environment, never the command line
    LOGS.mkdir(exist_ok=True)
    logf = open(LOGS / "restore.log", "a", encoding="utf-8")  # noqa: SIM115 (the child keeps it)
    subprocess.Popen([sys.executable, str(HERE / "restore_backup.py"), "live", str(src), name, "--wait", str(os.getpid()),
                      "--relaunch", str(int(port)), "--by", by] + (["--web"] if web else []) + (["--lan"] if lan else []),
                     cwd=ROOT, env=env, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
                     **_detached())


def start_relaunch(port=8601, lan=False):
    """After an update from Settings: a separate process waits for this web app to exit, then starts it again on the
    same port, so the new code runs (the old process kept serving and imported new modules lazily)."""
    LOGS.mkdir(exist_ok=True)
    logf = open(LOGS / "webapp_restart.log", "a", encoding="utf-8")  # noqa: SIM115 (the child keeps it)
    subprocess.Popen([sys.executable, str(HERE / "restore_backup.py"), "relaunch", "--wait", str(os.getpid()),
                      "--relaunch", str(int(port))] + (["--lan"] if lan else []),
                     cwd=ROOT, stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, **_detached())


def relaunch_after(wait_pid, port, lan=False):
    """-> True once the old app closed and the new one was started."""
    if not _wait(lambda: not _alive(wait_pid), 60):
        print("The app did not close; start it again by hand to use the new version.")
        return False
    relaunch_web(port, lan)
    return True


def _opt(flag):
    i = sys.argv.index(flag) if flag in sys.argv else -1
    return sys.argv[i + 1] if 0 <= i < len(sys.argv) - 1 else None


def main():
    if sys.argv[1:2] == ["relaunch"]:
        sys.exit(0 if relaunch_after(_opt("--wait"), _opt("--relaunch") or 8601, "--lan" in sys.argv) else 1)
    if sys.argv[1:2] == ["live"]:
        if len(sys.argv) < 4:
            raise SystemExit(__doc__)
        res = restore_live(sys.argv[2], sys.argv[3], wait_pid=_opt("--wait"), relaunch=_opt("--relaunch"),
                           by=_opt("--by") or "local", web="--web" in sys.argv, lan="--lan" in sys.argv)
        print(res["message"])
        sys.exit(0 if res["ok"] else 1)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    src = Path(args[0])
    fern = cipher_for(src)
    db_name = _opt("--db")
    if "--verify" in sys.argv:
        with tempfile.TemporaryDirectory() as td:
            name, ok, tables = restore_db(src, Path(td) / "check.db", fern, db_name)
        print(f"{name}: integrity {'ok' if ok else 'FAILED'}, {tables} tables" + (" (decrypted)" if fern else ""))
        sys.exit(0 if ok else 1)
    if len(args) < 2:
        raise SystemExit("need OUT folder (or --verify)")
    out = Path(args[1])
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; choose a new folder")
    (out / "data").mkdir(parents=True, exist_ok=True)
    name, ok, tables = restore_db(src, out / "data" / "family.db", fern, db_name)
    na = restore_tree(src, "archive_enc", "archive", out / "archive", fern)
    nc = restore_tree(src, "config_enc", "config", out / "config", fern)
    print(f"restored {name} (integrity {'ok' if ok else 'FAILED'}), {na} archive file(s), {nc} config file(s) into {out}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
