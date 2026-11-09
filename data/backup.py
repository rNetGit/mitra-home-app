"""Mitra Home backup.

Usage: python data/backup.py [extra_dest ...]
       python data/backup.py open FILE.db.enc    decrypt an encrypted copy kept in backups_pre_upgrade (next to it)

Writes to <project parent>/Mitra-Home-Backup (same drive: protects against mistakes) and to each extra_dest
(a DIFFERENT device: protects against drive loss). Per destination:
  db/family_YYYY-MM-DD_HHMM.db[.enc]   consistent SQLite copy (backup API), keeps newest 14
  archive/ (or archive_enc/)           mirror of archive/, copy-only (never deletes)
  config/  (or config_enc/)            your settings (family.json, contacts, tax_prep ...); never secrets.env
  code/                                small snapshot of data/*.py, schema, CLAUDE.md (no databases)

Encryption: set "backup_encrypt": true in config/family.json and store the passphrase (python onboard.py add backup
does both). Encrypted backups hide file CONTENTS and NAMES (an encrypted manifest maps hidden names back).
Restore with data/restore_backup.py. Without the passphrase an encrypted backup cannot be read.
"""
import json
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import log  # noqa: E402

ROOT = HERE.parent
KEEP = 14
CODE_SUFFIXES = {".py", ".sql", ".md", ".json", ".txt"}


def copy_new(src: Path, dst: Path, accept=lambda p: True):
    n = 0
    for f in src.rglob("*"):
        if not f.is_file() or not accept(f):
            continue
        t = dst / f.relative_to(src)
        if t.exists() and t.stat().st_size == f.stat().st_size and t.stat().st_mtime >= f.stat().st_mtime:
            continue
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, t)
        n += 1
    return n


def sync_encrypted(src: Path, out: Path, fern, salt, accept=lambda p: True):
    """Encrypt new/changed files into out/<hidden name>.enc; names live in out/manifest.enc. Never deletes."""
    import crypto_box as cb
    out.mkdir(parents=True, exist_ok=True)
    mf = out / "manifest.enc"
    manifest = json.loads(cb.decrypt_bytes(mf.read_bytes(), fern)) if mf.exists() else {}
    n = 0
    for f in sorted(src.rglob("*")):
        if not f.is_file() or not accept(f):
            continue
        rel = f.relative_to(src).as_posix()
        name = cb.opaque_name(salt, rel)
        st = f.stat()
        sig = [st.st_size, st.st_mtime_ns]
        if manifest.get(name, {}).get("sig") == sig and (out / name).exists():
            continue
        cb.encrypt_file(f, out / name, fern)
        manifest[name] = {"path": rel, "sig": sig}
        n += 1
    if n or not mf.exists():
        tmp = mf.with_suffix(".part")
        tmp.write_bytes(cb.encrypt_bytes(json.dumps(manifest).encode("utf-8"), fern))
        tmp.replace(mf)
    return n


def open_cipher(dest: Path, passphrase):
    """Create or open the destination's salt + check file; raises if the passphrase does not match."""
    import crypto_box as cb
    salt_f, check_f = dest / "backup.salt", dest / "backup.check"
    if salt_f.exists():
        salt = salt_f.read_bytes()
    else:
        import os
        salt = os.urandom(16)
        salt_f.write_bytes(salt)
    fern = cb.cipher(passphrase, salt)
    if check_f.exists():
        try:
            if cb.decrypt_bytes(check_f.read_bytes(), fern) != cb.CHECK_TEXT:
                raise ValueError
        except Exception:
            raise SystemExit(f"{dest}: wrong backup passphrase for this destination (refusing to mix keys)")
    else:
        check_f.write_bytes(cb.encrypt_bytes(cb.CHECK_TEXT, fern))
    return fern, salt


def backup_to(dest: Path, encrypt=False, passphrase=""):
    dest.mkdir(parents=True, exist_ok=True)
    dbdir = dest / "db"
    dbdir.mkdir(exist_ok=True)
    stamp = f"{datetime.now():%Y-%m-%d_%H%M}"
    fern = salt = None
    if encrypt:
        fern, salt = open_cipher(dest, passphrase)
    with tempfile.TemporaryDirectory() as td:
        snap = Path(td) / "snap.db"
        import db
        src = db.connect(paths.DB, readonly=True)  # also gets past a hot journal left by a crash
        s2 = sqlite3.connect(snap)
        with s2:
            src.backup(s2)
        src.close()
        s2.close()
        if encrypt:
            import crypto_box as cb
            out = dbdir / f"family_{stamp}.db.enc"
            cb.encrypt_file(snap, out, fern)
        else:
            out = dbdir / f"family_{stamp}.db"
            shutil.copy2(snap, out)
    for pat in ("family_*.db", "family_*.db.enc"):
        for old in sorted(dbdir.glob(pat))[:-KEEP]:
            old.unlink()  # prune old DB snapshots only
    arch = paths.ARCHIVE
    cfg_files = lambda p: p.name != "secrets.env" and not p.name.endswith(".example.json") and p.suffix in (".json",)
    if encrypt:
        na = sync_encrypted(arch, dest / "archive_enc", fern, salt, lambda p: p.name != ".gitkeep") if arch.exists() else 0
        nc = sync_encrypted(paths.CONFIG, dest / "config_enc", fern, salt, cfg_files) if (paths.CONFIG).exists() else 0
    else:
        na = copy_new(arch, dest / "archive") if arch.exists() else 0
        nc = copy_new(paths.CONFIG, dest / "config", cfg_files) if (paths.CONFIG).exists() else 0
    nd = copy_new(ROOT / "data", dest / "code", lambda p: p.suffix in CODE_SUFFIXES
                  and "backups_pre_upgrade" not in p.parts and "__pycache__" not in p.parts)
    shutil.copy2(ROOT / "CLAUDE.md", dest / "code" / "CLAUDE.md") if (dest / "code").exists() else None
    msg = f"{dest}: db={out.name} archive+{na} config+{nc} code+{nd}" + (" [encrypted]" if encrypt else "")
    log.get("backup").info(msg)
    print(msg)


def seal_copy(plain):
    """A database copy kept on this PC (before an update, before a purge): encrypted in place when the family encrypts
    its backups and the passphrase is on this PC (audit D4: they held removed people's rows in the clear) -> the path
    kept. No encryption set up, no passphrase or no cryptography -> the plain copy stays, as before."""
    plain = Path(plain)
    try:
        if not config.family().get("backup_encrypt"):
            return plain
        import crypto_box as cb
        pw = cb.load_passphrase()
        if not pw:
            return plain
        cb.available()
        fern, _ = open_cipher(plain.parent, pw)
        enc = plain.with_name(plain.name + ".enc")
        cb.encrypt_file(plain, enc, fern)
        plain.unlink()
        return enc
    except (Exception, SystemExit) as e:  # noqa: BLE001 (never lose the copy over its encryption)
        log.get("backup").warning("kept a plain copy %s: %s", plain.name, e)
        return plain


def open_copy(enc):
    """Decrypt FILE.db.enc (a sealed copy) to FILE.db next to it with the passphrase on this PC -> the plain path."""
    import crypto_box as cb
    enc = Path(enc)
    pw = cb.load_passphrase()
    if not pw:
        raise SystemExit("no backup passphrase on this PC (MITRAHOME_BACKUP_PASSPHRASE or config/secrets.env)")
    fern, _ = open_cipher(enc.parent, pw)
    out = enc.with_name(enc.name[:-4]) if enc.name.endswith(".enc") else enc.with_name(enc.name + ".db")
    cb.decrypt_file(enc, out, fern)
    return out


if __name__ == "__main__":
    if sys.argv[1:2] == ["open"]:
        if len(sys.argv) != 3:
            sys.exit("usage: python data/backup.py open FILE.db.enc")
        print(f"decrypted to {open_copy(sys.argv[2])}")
        sys.exit(0)
    fam = config.family()
    encrypt = bool(fam.get("backup_encrypt"))
    pw = ""
    if encrypt:
        import crypto_box as cb
        pw = cb.load_passphrase()
        if not pw:
            sys.exit("backup_encrypt is on but no passphrase found (MITRAHOME_BACKUP_PASSPHRASE or config/secrets.env)")
        try:
            cb.available()
        except cb.CryptoUnavailable as e:
            sys.exit(str(e))
    dests = [paths.BACKUPS] + [Path(a) for a in sys.argv[1:]]
    for d in dests:
        if any(d.resolve() == b.resolve() or b.resolve() in d.resolve().parents for b in (ROOT, paths.HOME)):
            sys.exit(f"refusing: backup dest inside the app or household folder: {d}")
    import joblock
    failed = False
    try:
        with joblock.job("backup"):
            for d in dests:
                try:
                    backup_to(d, encrypt, pw)
                except (OSError, sqlite3.Error) as e:
                    log.get("backup").error("FAILED %s: %s", d, e)
                    print(f"FAILED {d}: {e}")
                    failed = True
    except joblock.Busy as e:
        sys.exit("an update or restore is running; back up again when it has finished" if str(e) == joblock.MAINTENANCE
                 else "another backup is running")
    sys.exit(1 if failed else 0)
