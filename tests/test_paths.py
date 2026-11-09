"""The household folder (data/paths.py): inside the app folder by default for a template copy, or a folder of its own
named in mitrahome_home.txt (familyagent_home.txt before the rename); `onboard.py home` moves a household there and every script finds it again."""
import json
import os
import subprocess
import sys

import pytest

from conftest import DRY, copy_template, imported_from, q, run, seed


def _guard(root, payload):
    return subprocess.run([sys.executable, str(root / "scripts" / "guard_tool.py")], cwd=root, capture_output=True,
                          text=True, input=json.dumps(payload))


@pytest.fixture
def root(tmp_path):
    r = copy_template(tmp_path / "app")
    seed(r)
    return r


def test_inside_the_app_folder_without_a_marker(root):
    out = run(["data/paths.py"], root).stdout
    assert "(inside the app folder)" in out
    assert str(root / "data" / "family.db") in out and str(root / "inbox") in out


def test_home_moves_the_household_and_every_script_finds_it(root, tmp_path):
    (root / "inbox" / "note.txt").write_text("x", encoding="utf-8")
    before = q(root, "SELECT COUNT(*) FROM members")[0][0]
    home = tmp_path / "MitraHome_home"
    r = run(["onboard.py", "home", str(home)], root, env=DRY)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (root / "mitrahome_home.txt").read_text(encoding="utf-8").strip() == str(home)
    assert (home / "family.db").is_file() and not (root / "data" / "family.db").exists()
    assert (home / "config" / "family.json").is_file() and not (root / "config" / "family.json").exists()
    assert (home / "inbox" / "note.txt").is_file() and not (root / "inbox" / "note.txt").exists()
    for d in ("archive", "brief", "reports", "exports", "logs"):
        assert (home / d).is_dir()
    assert (root / "config" / "family.example.json").is_file(), "shipped examples are code and stay in the app folder"
    assert not list((home / "config").glob("*.example.json"))
    out = run(["data/paths.py"], root).stdout
    assert str(home / "family.db") in out and "(inside the app folder)" not in out
    # scripts, the database helper and the config loader follow the marker
    r = run(["data/members.py", "list"], root)
    assert r.returncode == 0 and "Alex" in r.stdout, r.stdout + r.stderr
    r = run(["data/health.py"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    r = run(["onboard.py", "doctor"], root, env=DRY)
    assert "household folder (separate from the app)" in r.stdout
    import sqlite3
    con = sqlite3.connect(home / "family.db")
    assert con.execute("SELECT COUNT(*) FROM members").fetchone()[0] == before
    con.close()
    # the agents' settings: the folder is reachable and writable only where documents go
    local = json.loads((root / ".claude" / "settings.local.json").read_text(encoding="utf-8"))["permissions"]
    assert str(home) in local["additionalDirectories"]
    assert any(a.startswith("Write(//") and a.endswith("/archive/**)") for a in local["allow"])
    assert not any("config/secrets" in a for a in local["allow"])
    # the guard hook: writes under the household folder's archive are fine, elsewhere in it are not
    assert _guard(root, {"tool_name": "Write", "tool_input": {"file_path": str(home / "archive" / "2026" / "bills" / "a.pdf")}}).returncode == 0
    assert _guard(root, {"tool_name": "Write", "tool_input": {"file_path": str(home / "config" / "family.json")}}).returncode == 2
    assert _guard(root, {"tool_name": "Write", "tool_input": {"file_path": str(tmp_path / "elsewhere.txt")}}).returncode == 2
    mv = f'mv "{home / "inbox" / "a.pdf"}" "{home / "archive" / "2026" / "bills" / "a.pdf"}"'
    assert _guard(root, {"tool_name": "Bash", "tool_input": {"command": mv}}).returncode == 0
    # and back inside the app folder
    r = run(["onboard.py", "home", "--inside"], root, env=DRY)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not (root / "mitrahome_home.txt").exists() and (root / "data" / "family.db").is_file()
    assert (root / "inbox" / "note.txt").is_file() and not (home / "family.db").exists()
    assert not (root / ".claude" / "settings.local.json").exists()


def test_home_refuses_a_folder_inside_the_app(root):
    r = run(["onboard.py", "home", str(root / "sub")], root, env=DRY)
    assert r.returncode != 0 and "outside the app folder" in (r.stdout + r.stderr)
    assert not (root / "mitrahome_home.txt").exists()


def test_update_keeps_the_marker_and_the_household_folder(root, tmp_path):
    with imported_from(root / "data", "updater") as updater:
        assert updater.protected("mitrahome_home.txt") and updater.protected("familyagent_home.txt")
        assert updater.protected("config/family.json") and not updater.protected("data/paths.py")


def test_an_install_from_before_the_rename_keeps_its_household(root, tmp_path):
    """familyagent_home.txt still names the household; the next `onboard.py home` writes the new marker only."""
    home = tmp_path / "FamilyAgent_home"
    assert run(["onboard.py", "home", str(home)], root, env=DRY).returncode == 0
    (root / "mitrahome_home.txt").rename(root / "familyagent_home.txt")  # as an older version left it
    out = run(["data/paths.py"], root).stdout
    assert str(home / "family.db") in out and "(inside the app folder)" not in out
    r = run(["data/members.py", "list"], root)
    assert r.returncode == 0 and "Alex" in r.stdout, r.stdout + r.stderr
    assert _guard(root, {"tool_name": "Write", "tool_input": {"file_path": str(home / "archive" / "a.pdf")}}).returncode == 0
    assert _guard(root, {"tool_name": "Write", "tool_input": {"file_path": str(home / "config" / "family.json")}}).returncode == 2
    new_home = tmp_path / "MitraHome_home"
    assert run(["onboard.py", "home", str(new_home)], root, env=DRY).returncode == 0
    assert not (root / "familyagent_home.txt").exists()
    assert (root / "mitrahome_home.txt").read_text(encoding="utf-8").strip() == str(new_home)
    assert (new_home / "family.db").is_file()


def test_a_failed_move_puts_everything_back_and_keeps_the_pointer(root, tmp_path):
    """D12: the pointer is written only after every file moved; a move that fails half-way is undone."""
    (root / "inbox" / "note.txt").write_text("x", encoding="utf-8")
    home = tmp_path / "Elsewhere"
    driver = tmp_path / "drive.py"
    driver.write_text(
        "import shutil, sys\n"
        f"sys.path[:0] = [{str(root)!r}, {str(root / 'data')!r}]\n"
        "import onboard\n"
        "real, n = shutil.move, [0]\n"
        "def flaky(a, b):\n"
        "    n[0] += 1\n"
        "    if n[0] == 3:\n"
        "        raise PermissionError('file is open in another program')\n"
        "    return real(a, b)\n"
        "shutil.move = flaky\n"
        "try:\n"
        f"    onboard.set_home({str(home)!r})\n"
        "except SystemExit as e:\n"
        "    print('STOPPED', e)\n", encoding="utf-8")
    r = subprocess.run([sys.executable, str(driver)], cwd=root, capture_output=True, text=True, env={**os.environ, **DRY})
    assert "STOPPED The household folder was not moved" in r.stdout, r.stdout + r.stderr[-500:]
    assert not (root / "mitrahome_home.txt").exists(), "the pointer was not written"
    assert (root / "data" / "family.db").is_file() and (root / "inbox" / "note.txt").is_file()
    assert (root / "config" / "family.json").is_file()
    assert not [p for p in home.rglob("*") if p.is_file()], "nothing is left half-way in the new folder"
