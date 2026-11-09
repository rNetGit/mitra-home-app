"""Backups: plain copy, encrypted (FAB1) round trip through restore, wrong passphrase, incremental second run."""
import sqlite3

import pytest

from conftest import db, read_family, run, write_family

PW = {"MITRAHOME_BACKUP_PASSPHRASE": "correct horse battery staple"}
BAD = {"MITRAHOME_BACKUP_PASSPHRASE": "totally wrong passphrase"}


@pytest.fixture(scope="module")
def marked(root):
    con = db(root)
    con.execute("insert into bills(name, vendor, amount, due_date) values ('Marker bill','ZXQMARKERVENDOR',12.5,'2099-01-01')")
    con.commit()
    con.close()
    arc = root / "archive" / "2026" / "bills"
    arc.mkdir(parents=True, exist_ok=True)
    (arc / "2026-01-01_zxqmarkervendor_bill.txt").write_text("ZXQ-SECRET-CONTENT", encoding="utf-8")
    (root / "config" / "secrets.env").write_text("MITRAHOME_BACKUP_PASSPHRASE=in-file-passphrase\n", encoding="utf-8")
    yield root
    (root / "config" / "secrets.env").unlink(missing_ok=True)


def _encrypt(root, on):
    fam = read_family(root)
    fam["backup_encrypt"] = on
    write_family(root, fam)


def test_plain_backup(marked, tmp_path):
    _encrypt(marked, False)
    plain = tmp_path / "plainbk"
    r = run(["data/backup.py", str(plain)], marked)
    assert r.returncode == 0, r.stderr[-200:] + r.stdout[-200:]
    dbs = list(plain.rglob("*.db"))
    assert dbs and all(x.parent.name == "db" for x in dbs)
    assert (plain / "config" / "family.json").exists()
    assert not list(plain.rglob("secrets.env"))
    assert not list(plain.rglob("backups_pre_upgrade"))


def test_backup_refuses_destination_inside_the_project(marked):
    assert run(["data/backup.py", str(marked / "archive" / "bk")], marked).returncode != 0


@pytest.fixture(scope="module")
def encrypted(marked, tmp_path_factory):
    pytest.importorskip("cryptography")
    _encrypt(marked, True)
    enc = tmp_path_factory.mktemp("enc") / "encbk"
    r = run(["data/backup.py", str(enc)], marked, env=PW)
    assert r.returncode == 0, r.stderr[-300:] + r.stdout[-300:]
    yield enc
    _encrypt(marked, False)


def test_encrypted_backup_has_no_plaintext(encrypted):
    blob = b"".join(x.read_bytes() for x in encrypted.rglob("*") if x.is_file())
    names = " ".join(str(x.relative_to(encrypted)).lower() for x in encrypted.rglob("*"))
    assert b"ZXQMARKERVENDOR" not in blob and b"zxqmarkervendor" not in blob.lower()
    assert b"ZXQ-SECRET-CONTENT" not in blob and "zxqmarkervendor" not in names
    assert b"agent@example.com" not in blob and b"Biscuit" not in blob
    assert all(not x.read_bytes().startswith(b"SQLite format") for x in (encrypted / "db").glob("*"))
    assert not (encrypted / "archive_enc" / "2026").exists() and (encrypted / "archive_enc" / "manifest.enc").exists()
    assert b"in-file-passphrase" not in blob and b"correct horse" not in blob


def test_restore_round_trip(marked, encrypted, tmp_path):
    r = run(["data/restore_backup.py", str(encrypted), "--verify"], marked, env=PW)
    assert r.returncode == 0 and "integrity ok" in r.stdout, r.stdout[-200:] + r.stderr[-200:]
    out = tmp_path / "restored"
    r = run(["data/restore_backup.py", str(encrypted), str(out)], marked, env=PW)
    assert r.returncode == 0, r.stdout[-200:] + r.stderr[-300:]
    rdb = sqlite3.connect(out / "data" / "family.db")
    assert rdb.execute("select count(*) from bills where vendor='ZXQMARKERVENDOR'").fetchone()[0] == 1
    rdb.close()
    ra = out / "archive" / "2026" / "bills" / "2026-01-01_zxqmarkervendor_bill.txt"
    assert ra.exists() and ra.read_text(encoding="utf-8") == "ZXQ-SECRET-CONTENT"
    assert (out / "config" / "family.json").exists()
    assert run(["data/restore_backup.py", str(encrypted), str(out)], marked, env=PW).returncode != 0, "non-empty folder refused"


def test_wrong_passphrase(marked, encrypted):
    assert run(["data/restore_backup.py", str(encrypted), "--verify"], marked, env=BAD).returncode != 0
    assert run(["data/backup.py", str(encrypted)], marked, env=BAD).returncode != 0


def test_second_encrypted_backup_is_incremental(marked, encrypted):
    r = run(["data/backup.py", str(encrypted)], marked, env=PW)
    assert r.returncode == 0 and "archive+0" in r.stdout, r.stdout[-300:]


def test_encrypt_on_without_passphrase_fails_clearly(marked, tmp_path):
    _encrypt(marked, True)
    (marked / "config" / "secrets.env").unlink(missing_ok=True)
    env = {"MITRAHOME_BACKUP_PASSPHRASE": ""}
    r = run(["data/backup.py", str(tmp_path / "nopw")], marked, env=env)
    assert r.returncode != 0 and "passphrase" in (r.stderr + r.stdout).lower()
    _encrypt(marked, False)


def test_kept_copies_are_sealed_when_backups_are_encrypted(marked, modules, tmp_path, monkeypatch):
    """Audit D4: a copy kept before an update or a purge is encrypted like the backups; `backup.py open` reads it."""
    monkeypatch.setenv("MITRAHOME_BACKUP_PASSPHRASE", "seal test passphrase")
    d = tmp_path / "pre"
    d.mkdir()
    plain = d / "family_2026-10-18_101010.db"
    con = sqlite3.connect(plain)
    con.execute("CREATE TABLE t(x)")
    con.execute("INSERT INTO t VALUES ('ZXQ-KEPT-ROW')")
    con.commit()
    con.close()
    _encrypt(marked, True)
    try:
        bk = modules("backup")  # bound after the settings change (modules() starts with fresh caches)
        modules("crypto_box")
        out = bk.seal_copy(plain)
        assert out.name.endswith(".db.enc") and not plain.exists() and b"ZXQ-KEPT-ROW" not in out.read_bytes()
        back = bk.open_copy(out)
        assert back == plain and sqlite3.connect(back).execute("SELECT x FROM t").fetchone()[0] == "ZXQ-KEPT-ROW"
    finally:
        _encrypt(marked, False)
    other = d / "family_2026-10-18_111111.db"
    sqlite3.connect(other).close()
    assert modules("backup").seal_copy(other) == other, "no encryption set up: the plain copy stays"


def test_purge_copies_keeps_the_newest_purge_snapshot(marked, modules):
    purge, paths = modules("purge"), modules("paths")
    d = paths.PRE_UPGRADE
    d.mkdir(parents=True, exist_ok=True)
    names = ["family_2026-01-01_000000.db", "family_before_purge_20260101_000000.db", "family_before_purge_20260201_000000.db.enc"]
    for n in names:
        (d / n).write_bytes(b"x")
    purge.purge_copies(False)
    assert all((d / n).exists() for n in names), "dry run changes nothing"
    purge.purge_copies(True)
    assert [p.name for p in d.iterdir() if p.name.startswith("family_")] == ["family_before_purge_20260201_000000.db.enc"]
