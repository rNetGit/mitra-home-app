"""0.57.0 Settings > Data > Restore from backup (data/restore_backup.py live mode) and the phone bot's "Start with this PC"
toggle (data/autostart.py): the restore keeps a copy of today's data, swaps the database in, brings back only missing
papers, refuses a wrong passphrase without touching anything; the toggle registers and removes the sign-in start."""
import importlib
import json

import pytest

from conftest import db, q, read_family, run, write_family

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}
PW = "correct horse battery staple"


@pytest.fixture(scope="module")
def rb(modules):
    return importlib.import_module("restore_backup")


def _marker(root, name):
    con = db(root)
    con.execute("insert into bills(name, vendor, amount, due_date) values (?, 'ZXQRESTORE', 1, '2099-01-01')", (name,))
    con.commit()
    con.close()


def _bills(root):
    return {r[0] for r in q(root, "select name from bills where vendor='ZXQRESTORE'")}


def _backup(root, encrypt=False, env=None):
    fam = read_family(root)
    fam["backup_encrypt"] = encrypt
    write_family(root, fam)
    r = run(["data/backup.py"], root, env=env)
    assert r.returncode == 0, r.stderr[-300:] + r.stdout[-300:]


def test_restore_puts_the_backup_back_and_keeps_todays_copy(root, rb):
    arc = root / "archive" / "2026" / "bills"
    arc.mkdir(parents=True, exist_ok=True)
    (arc / "kept.txt").write_text("as backed up", encoding="utf-8")
    (arc / "lost.txt").write_text("will be lost", encoding="utf-8")
    _marker(root, "Before backup")
    _backup(root)
    snaps = rb.snapshots()
    assert snaps and snaps[0]["where"] == "on this PC" and not snaps[0]["encrypted"]
    s = snaps[0]
    ok, msg = rb.check(s["src"], s["name"])
    assert ok and "readable" in msg

    _marker(root, "After backup")
    (arc / "lost.txt").unlink()
    (arc / "kept.txt").write_text("changed since", encoding="utf-8")
    res = rb.restore_live(s["src"], s["name"], by="Alex", bot_wait=1)
    assert res["ok"], res
    assert _bills(root) == {"Before backup"}, "entries made after the backup are replaced"
    assert (arc / "lost.txt").read_text(encoding="utf-8") == "will be lost", "a missing paper comes back"
    assert (arc / "kept.txt").read_text(encoding="utf-8") == "changed since", "papers that are here are not overwritten"
    kept = res["kept"]
    assert kept and "before_restore" in kept
    import sqlite3
    con = sqlite3.connect(kept)
    assert {r[0] for r in con.execute("select name from bills where vendor='ZXQRESTORE'")} == {"Before backup", "After backup"}
    con.close()
    assert json.loads((root / "logs" / "restore_result.json").read_text(encoding="utf-8"))["ok"] is True
    assert rb.last_result()["snapshot"] == s["name"] and "Restored the backup from" in rb.last_result()["message"]
    assert "restore\tsnapshot=" in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert not (root / "data" / "family.db.restoring").exists()

    undo = next(x for x in rb.snapshots() if x["where"] == "copy from just before a restore")
    assert rb.restore_live(undo["src"], undo["name"], bot_wait=1)["ok"]
    assert _bills(root) == {"Before backup", "After backup"}, "the copy kept before a restore undoes it"


def test_a_locked_backup_needs_its_passphrase_and_a_wrong_one_changes_nothing(root, rb):
    pytest.importorskip("cryptography")
    _backup(root, encrypt=True, env={"MITRAHOME_BACKUP_PASSPHRASE": PW})
    s = next(x for x in rb.snapshots() if x["encrypted"])
    ok, msg = rb.check(s["src"], s["name"], "totally wrong")
    assert not ok and msg == "That passphrase does not open this backup."
    assert rb.check(s["src"], s["name"], PW)[0]
    _marker(root, "Stays")
    res = rb.restore_live(s["src"], s["name"], passphrase="totally wrong", bot_wait=1)
    assert not res["ok"] and "passphrase" in res["message"] and "Stays" in _bills(root), "nothing changed"
    res = rb.restore_live(s["src"], s["name"], passphrase=PW, bot_wait=1)
    assert res["ok"], res
    assert "Stays" not in _bills(root)
    fam = read_family(root)
    fam["backup_encrypt"] = False
    write_family(root, fam)


def test_only_adults_restore_and_the_passphrase_never_goes_on_a_command_line(root, rb, modules, monkeypatch):
    md = importlib.import_module("maintenance_data")
    i = next(k for k, x in enumerate(rb.snapshots()) if not x["encrypted"])
    s = rb.snapshots()[i]
    assert md.restore_start(KID, i, "", 8601)[0] is False
    assert md.restore_start(ADULT, 999, "", 8601)[1] == "That backup is no longer there."
    seen = {}

    class FakePopen:
        def __init__(self, args, **kw):
            seen["args"], seen["env"] = args, kw.get("env") or {}

    monkeypatch.setattr(rb.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(rb, "check", lambda src, name, pw=None: (True, "ok"))
    ok, msg = md.restore_start(ADULT, i, "my secret phrase", 8601)
    assert ok and "comes back by itself" in msg
    assert "my secret phrase" not in " ".join(seen["args"]) and seen["env"]["MITRAHOME_BACKUP_PASSPHRASE"] == "my secret phrase"
    assert seen["args"][2:4] == ["live", s["src"]] and "--wait" in seen["args"] and "--relaunch" in seen["args"]
    assert "--web" in seen["args"], "the web app is started again, never a dashboard that no longer exists"


def test_start_with_this_pc_registers_and_removes_the_sign_in_start(root, modules, monkeypatch, tmp_path):
    A = importlib.import_module("autostart")
    aa = importlib.import_module("admin_actions")
    monkeypatch.setattr(A, "supported", lambda: True)
    monkeypatch.setenv("APPDATA", str(tmp_path))
    tasks = set()

    class R:
        def __init__(self, rc):
            self.returncode, self.stdout, self.stderr = rc, "", "Access is denied." if rc else ""

    def fake_run(cmd, **kw):
        verb, name = cmd[1], cmd[cmd.index("/tn") + 1]
        if verb == "/query":
            return R(0 if name in tasks else 1)
        if verb == "/create":
            if allow:
                tasks.add(name)
            return R(0 if allow else 1)
        if verb == "/delete":
            tasks.discard(name)
        return R(0)

    monkeypatch.setattr(A, "_run", fake_run)
    monkeypatch.setattr(A.subprocess, "Popen", lambda *a, **k: None)
    allow = True
    assert aa.bot_autostart(KID, True)[0] is False
    ok, msg = aa.bot_autostart(ADULT, True)
    assert ok and "sign in" in msg and A.status() == "task"
    assert read_family(root)["chat"]["telegram"]["task_registered"] is True
    ok, _ = aa.bot_autostart(ADULT, False)
    assert ok and A.status() == "" and read_family(root)["chat"]["telegram"]["task_registered"] is False
    allow = False  # this PC refuses logon tasks: the Startup folder does it instead
    ok, _ = aa.bot_autostart(ADULT, True)
    launcher = tmp_path / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / "Mitra Home Telegram Bot.cmd"
    assert ok and A.status() == "startup" and launcher.exists() and "chat_telegram.bat" in launcher.read_text(encoding="ascii")
    ok, _ = aa.bot_autostart(ADULT, False)
    assert ok and not launcher.exists() and A.status() == ""
    assert "bot_autostart\ton=True" in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")




def test_a_backup_from_a_newer_version_is_refused_before_anything_changes(root, rb, tmp_path):
    """Audit test gap: older code must not swap in (and then fail to migrate) a database a newer version wrote."""
    import shutil
    import sqlite3
    src = tmp_path / "newer"
    src.mkdir()
    snap = src / "family_2026-10-15_0303.db"
    shutil.copy2(root / "data" / "family.db", snap)
    con = sqlite3.connect(snap)
    con.execute("INSERT OR REPLACE INTO meta VALUES ('template_version', '99.0.0')")
    con.commit()
    con.close()
    assert rb.made_by_newer(snap) == "99.0.0"
    _marker(root, "Still here")
    res = rb.restore_live(str(src), snap.name, bot_wait=1)
    assert not res["ok"] and "newer" in res["message"] and "Nothing was changed" in res["message"]
    assert "Still here" in _bills(root) and not (root / "data" / "family.db.restoring").exists()
