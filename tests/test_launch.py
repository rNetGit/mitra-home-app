"""launch.py: the double-click starter. Version gate, environment stamp, fresh-install decision, port choice, command line,
and the wrapper files that call it. Nothing here starts a server or installs packages."""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import DRY, copy_template, imported_from, run

SRC = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _own_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("MITRAHOME_VENV", str(tmp_path / "venv"))


@pytest.fixture()
def launch():
    spec = importlib.util.spec_from_file_location("launch_under_test", SRC / "launch.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_version_gate(launch):
    assert launch.python_ok((3, 12, 0))
    assert launch.python_ok((3, 13, 2))
    assert not launch.python_ok((3, 11, 9))
    assert not launch.python_ok((2, 7, 18))


def test_environment_stamp_follows_requirements(launch, tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    assert launch.needs_install(tmp_path)  # no environment yet
    py = launch.venv_python(tmp_path)
    py.parent.mkdir(parents=True)
    py.write_text("", encoding="utf-8")
    assert launch.needs_install(tmp_path)  # environment but no stamp
    (tmp_path / "venv" / "requirements.sha256").write_text(launch.requirements_hash(tmp_path) + "\n", encoding="utf-8")
    assert not launch.needs_install(tmp_path)
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")  # an update changed it
    assert launch.needs_install(tmp_path)


def test_venv_location(launch, tmp_path, monkeypatch):
    p = launch.venv_python(tmp_path)
    assert p.name == ("python.exe" if os.name == "nt" else "python")
    assert p.parent.parent == tmp_path / "venv"  # MITRAHOME_VENV wins
    monkeypatch.delenv("MITRAHOME_VENV")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    if os.name == "nt":  # short path, outside the app folder: the 260-character limit
        assert launch.venv_dir(tmp_path / "app") == tmp_path / "local" / "MitraHome" / "venv"
        (tmp_path / "local" / "FamilyAgent" / "venv").mkdir(parents=True)  # a PC set up before the rename keeps its copy
        assert launch.venv_dir(tmp_path / "app") == tmp_path / "local" / "FamilyAgent" / "venv"
        (tmp_path / "local" / "MitraHome" / "venv").mkdir(parents=True)
        assert launch.venv_dir(tmp_path / "app") == tmp_path / "local" / "MitraHome" / "venv"
        monkeypatch.setenv("FAMILYAGENT_VENV", str(tmp_path / "old_override"))
        assert launch.venv_dir(tmp_path / "app") == tmp_path / "old_override", "the old variable still works"
    else:
        assert launch.venv_dir(tmp_path / "app") == tmp_path / "app" / ".venv"


def test_fresh_install_decision(launch, tmp_path):
    assert launch.is_fresh_install(tmp_path)
    for marker in ("mitrahome_home.txt", "familyagent_home.txt"):  # the second one: an install from before the rename
        (tmp_path / marker).write_text("../MitraHome_home\n", encoding="utf-8")
        assert not launch.is_fresh_install(tmp_path)
        (tmp_path / marker).unlink()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "family.json").write_text("{}", encoding="utf-8")
    assert not launch.is_fresh_install(tmp_path)  # an older install with its household inside the app
    (tmp_path / "config" / "family.json").unlink()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "family.db").write_bytes(b"")
    assert not launch.is_fresh_install(tmp_path)


def test_port_choice(launch):
    assert launch.pick_port(8603, probe=lambda p: p == 8603, free=lambda p: True) == (8603, True)  # our own app
    # another install's app answers on 8601: leave it alone, take the next free port
    assert launch.pick_port(None, probe=lambda p: p == 8601, free=lambda p: p != 8601 and p != 8602) == (8603, False)
    assert launch.pick_port(8601, probe=lambda p: False, free=lambda p: p >= 8602) == (8602, False)  # record went stale
    assert launch.pick_port(None, probe=lambda p: False, free=lambda p: False) == (None, False)


def test_dashboard_record_round_trip(tmp_path):
    with imported_from(SRC / "data", "dashboard_record") as rec:
        assert rec.read(tmp_path) is None
        rec.write(8502, tmp_path)
        assert rec.read(tmp_path) == {"port": 8502, "pid": os.getpid(), "lan": False}
        rec.write(8502, tmp_path, pid=2**22 - 3)  # a process that is not there
        assert rec.read(tmp_path) is None
        assert rec.read(tmp_path, alive=False)["pid"] == 2**22 - 3
        rec.forget(tmp_path)
        assert rec.read(tmp_path, alive=False) is None
        (tmp_path / ".webapp.json").write_text("not json", encoding="utf-8")
        assert rec.read(tmp_path) is None


def test_health_probe_is_false_when_nothing_listens(launch):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert launch.healthy(port, timeout=0.5) is False


def test_check_flag_changes_nothing(tmp_path):
    r = subprocess.run([sys.executable, str(SRC / "launch.py"), "--check"], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Python ok" in r.stdout


def test_wrappers_call_launch_and_have_the_right_line_endings():
    bat = (SRC / "Start Mitra Home.bat").read_bytes()
    assert b"launch.py" in bat and b"python.org/downloads" in bat
    assert b"\r\n" in bat and b"\n" not in bat.replace(b"\r\n", b"")  # cmd.exe needs CRLF (labels break with LF)
    cmd = (SRC / "Start Mitra Home.command").read_bytes()
    assert cmd.startswith(b"#!/usr/bin/env sh") and b"launch.py" in cmd and b"\r" not in cmd


def test_task_wrappers_prefer_the_environment():
    for f in (SRC / "tasks").glob("*.bat"):
        t = f.read_text(encoding="utf-8")
        assert r".venv\Scripts\python.exe" in t and r"%LOCALAPPDATA%\MitraHome\venv\Scripts\python.exe" in t, f.name
        assert t.index("FamilyAgent\\venv") < t.index("MitraHome\\venv"), "the new environment wins when both exist"
        assert '"%PY%"' in t, f.name


def test_updater_and_git_leave_the_environment_alone():
    # a subprocess: importing data/updater.py here would leave it bound to the real checkout for later tests
    code = "import sys; sys.path.insert(0, 'data'); import updater; print(updater.protected('.venv/Lib/site-packages/x.py'))"
    r = subprocess.run([sys.executable, "-c", code], cwd=SRC, capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "True", r.stdout + r.stderr
    ignore = (SRC / ".gitignore").read_text(encoding="utf-8")
    assert ".venv/" in ignore and ".webapp.json" in ignore


def test_lan_needs_a_pin_and_binds_all_addresses(launch, tmp_path):
    import json
    assert not launch.pins_set(tmp_path)  # nothing set up
    (tmp_path / "config").mkdir()
    fam = tmp_path / "config" / "family.json"
    fam.write_text(json.dumps({"members": [{"name": "A"}]}), encoding="utf-8")
    assert not launch.pins_set(tmp_path)
    fam.write_text(json.dumps({"dashboard_users": [{"name": "A", "role": "adult"}]}), encoding="utf-8")
    assert not launch.pins_set(tmp_path), "a user without a PIN hash does not count"
    fam.write_text(json.dumps({"dashboard_users": [{"name": "A", "role": "adult", "pin_hash": "pbkdf2$1$aa$bb"}]}), encoding="utf-8")
    assert launch.pins_set(tmp_path)
    assert launch.web_cmd(tmp_path / "py", 8601, root=tmp_path, lan=True)[-1] == "--lan"
    assert "--lan" not in launch.web_cmd(tmp_path / "py", 8601, root=tmp_path)


def test_lan_without_a_pin_starts_for_this_pc_only(launch, tmp_path, monkeypatch, capsys):
    """Audit M4: the phones starter no longer dead-ends on a first run; it starts without --lan and says why."""
    seen = []
    monkeypatch.setattr(launch, "pins_set", lambda root=None: False)
    monkeypatch.setattr(launch, "pick_port", lambda *a, **k: (8601, False))
    monkeypatch.setattr(launch, "ensure_venv", lambda: tmp_path / "py")
    monkeypatch.setattr(launch, "is_fresh_install", lambda: False)

    def stop(py, port, root=None, lan=False):
        seen.append(lan)
        raise RuntimeError("stop before starting")
    monkeypatch.setattr(launch, "web_cmd", stop)
    with pytest.raises(RuntimeError):
        launch.main(["--lan"])
    out = capsys.readouterr().out
    assert seen == [False] and "PIN" in out and "this PC only" in out


def _family(tmp_path, data):
    import json
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config" / "family.json").write_text(json.dumps(data), encoding="utf-8")


def test_phones_are_on_unless_switched_off_and_the_starter_flags_win(launch, tmp_path):
    """0.135: every start follows Settings > Phones > Connection (family.json phones.lan); on by default."""
    assert launch.phones_on(tmp_path), "no household yet: on (still needs a PIN before it opens)"
    _family(tmp_path, {"members": []})
    assert launch.phones_on(tmp_path) and launch.want_lan([], tmp_path) == (True, False)
    _family(tmp_path, {"phones": {"lan": False}})
    assert not launch.phones_on(tmp_path) and launch.want_lan([], tmp_path) == (False, False)
    assert launch.want_lan(["--lan"], tmp_path) == (True, True), "--lan opens it even when switched off"
    _family(tmp_path, {"phones": {"lan": True}})
    assert launch.want_lan(["--pc-only", "--lan"], tmp_path) == (False, True), "--pc-only wins"


def test_the_setting_without_a_pin_starts_for_this_pc_and_says_why(launch, tmp_path, monkeypatch, capsys):
    seen = []
    monkeypatch.setattr(launch, "want_lan", lambda argv, root=None: (True, False))
    monkeypatch.setattr(launch, "pins_set", lambda root=None: False)
    monkeypatch.setattr(launch, "pick_port", lambda *a, **k: (8601, False))
    monkeypatch.setattr(launch, "ensure_venv", lambda: tmp_path / "py")
    monkeypatch.setattr(launch, "is_fresh_install", lambda: False)

    def stop(py, port, root=None, lan=False):
        seen.append(lan)
        raise RuntimeError("stop before starting")
    monkeypatch.setattr(launch, "web_cmd", stop)
    with pytest.raises(RuntimeError):
        launch.main([])
    out = capsys.readouterr().out
    assert seen == [False] and "once an adult has a PIN" in out


def test_a_running_pc_only_app_is_reopened_and_points_at_restart(launch, monkeypatch, capsys):
    """The 5-minute start task and a double-click no longer fail when the app runs for this PC only and the setting
    wants phones: they open it and say where to restart it."""
    opened = []
    monkeypatch.setattr(launch, "want_lan", lambda argv, root=None: (True, False))
    monkeypatch.setattr(launch, "pins_set", lambda root=None: True)
    monkeypatch.setattr(launch.dashboard_record, "read", lambda *a, **k: {"port": 8601, "pid": 1, "lan": False})
    monkeypatch.setattr(launch, "pick_port", lambda *a, **k: (8601, True))
    monkeypatch.setattr(launch.webbrowser, "open", opened.append)
    assert launch.main([]) == 0
    assert opened == ["http://127.0.0.1:8601"] and "Restart for phones" in capsys.readouterr().out
    monkeypatch.setattr(launch, "want_lan", lambda argv, root=None: (True, True))
    assert launch.main(["--lan", "--no-browser"]) == 1, "an explicit --lan still says to close it first"


def test_the_installer_follows_the_setting_and_keeps_a_this_pc_only_entry():
    iss = (SRC / "installer" / "MitraHome.iss").read_text(encoding="utf-8")
    icons = [x for x in iss.splitlines() if x.startswith('Name: "{auto')]
    main = next(x for x in icons if x.startswith('Name: "{autoprograms}\\Mitra Home";'))
    assert "--lan" not in main and "--pc-only" not in main, "the main entry follows Settings > Phones"
    assert any("(this PC only)" in x and "--pc-only" in x for x in icons)
    assert not any("--lan" in x for x in icons), "no entry needs --lan any more"


def test_lan_help_names_the_https_phone_url_and_the_private_firewall_rule(launch):
    text = " ".join(launch.lan_help("192.168.1.20", 8501, fp="ab" * 32))
    assert "https://192.168.1.20:8601" in text and "profile=private" in text and "localport=8601" in text
    assert "http://192.168.1.20" not in text and "AB:AB:AB" in text


def test_lan_help_in_a_container_names_the_server_and_has_no_windows_lines(launch, monkeypatch):
    monkeypatch.setenv("MITRAHOME_CONTAINER", "1")
    text = " ".join(launch.lan_help("172.18.0.2", 8601, fp="ab" * 32))
    assert "https://<server-address>:8701" in text and "AB:AB:AB" in text
    assert "Windows" not in text and "netsh" not in text and "this PC" not in text


def test_phone_starters_pass_lan():
    assert b"launch.py --lan" in (SRC / "Start Mitra Home for phones.bat").read_bytes()
    assert b"launch.py --lan" in (SRC / "Start Mitra Home for phones.command").read_bytes()
    assert b"%*" in (SRC / "Start Mitra Home.bat").read_bytes()


def test_web_command_line(launch, tmp_path):
    cmd = launch.web_cmd(tmp_path / "py", 8602, root=tmp_path)
    assert cmd == [str(tmp_path / "py"), str(tmp_path / "data" / "web_app.py"), "--port", "8602"]  # this PC only
    assert launch.web_cmd(tmp_path / "py", 8601, root=tmp_path, lan=True)[-1] == "--lan"
    assert launch.PORTS[0] == 8601 and 8501 not in launch.PORTS


def test_the_record_is_the_web_apps(tmp_path):
    with imported_from(SRC / "data", "dashboard_record") as rec:
        assert rec.NAME == rec.WEB_NAME == ".webapp.json"
        rec.write(8601, tmp_path)
        assert rec.read(tmp_path)["port"] == 8601 and (tmp_path / ".webapp.json").exists()
        rec.forget(tmp_path)
        assert rec.read(tmp_path, alive=False) is None


def test_web_needs_a_pin_for_lan(launch, tmp_path, monkeypatch, capsys):
    """A brand-new install may start the web app (its first run is there); phones wait until a PIN exists."""
    monkeypatch.setattr(launch, "pick_port", lambda *a, **k: (None, False))  # stop after the PIN check
    monkeypatch.setattr(launch, "pins_set", lambda root=None: False)
    assert launch.main(["--web", "--lan"]) == 1
    out = capsys.readouterr().out
    assert "PIN" in out and "this PC only" in out and "No free port" in out


def test_web_probe_uses_the_health_route(launch):
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    assert launch.healthy(port, timeout=0.5) is False


class _Proc:
    pid = 4242

    def __init__(self):
        self.stopped = False

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.stopped = True




def test_home_arg_names_the_household_folder_only_when_given(launch, tmp_path):
    assert launch.home_arg([]) is None
    assert launch.home_arg(["--home"]) is None
    assert launch.home_arg(["--lan", "--home", str(tmp_path / "H")]) == tmp_path / "H"


def test_pip_tries_the_shipped_wheels_before_the_internet(launch, tmp_path):
    cmds = launch.pip_cmds("py", root=tmp_path, wheels=tmp_path / "w")
    assert len(cmds) == 2 and cmds[0][-3:] == ["--no-index", "--find-links", str(tmp_path / "w")]
    assert "--no-index" not in cmds[1]
    assert launch.pip_cmds("py", root=tmp_path) == [cmds[1]]


def test_fresh_install_uses_the_home_the_installer_passed(launch, tmp_path, monkeypatch):
    import types
    seen = []
    monkeypatch.setitem(sys.modules, "onboard", types.SimpleNamespace(set_home=seen.append))
    launch.make_household_folder(tmp_path / "Documents" / "MitraHome_home")
    assert seen == [tmp_path / "Documents" / "MitraHome_home"]


def test_starters_prefer_the_installers_python():
    for name in ("Start Mitra Home.bat", "Start Mitra Home for phones.bat"):
        text = (SRC / name).read_text(encoding="utf-8")
        assert text.index(r"MitraHome\runtime\python.exe") < text.index('for %%C in')


def test_a_half_finished_update_is_finished_on_the_next_start(tmp_path):
    """0.109.1's zip updater could stop after copying the code, before the database step: the next start applies the
    waiting migrations (with a backup first) before the app opens; with nothing waiting it does nothing."""
    import sqlite3
    app = copy_template(tmp_path / "app")
    assert run(["data/migrate.py"], app).returncode == 0
    con = sqlite3.connect(app / "data" / "family.db")
    con.execute("DELETE FROM schema_migrations WHERE name = 'migrate_052_home_contacts.py'")
    con.commit()
    con.close()
    probe = "import sys, launch; print(launch.pending_migrations()); sys.exit(0 if launch.finish_update(sys.executable) else 1)"
    r = run(["-c", probe], app, env=DRY)
    assert r.returncode == 0, (r.stdout + r.stderr)[-600:]
    assert "migrate_052_home_contacts.py" in r.stdout and "Finishing the last update" in r.stdout
    assert list((app / "data" / "backups_pre_upgrade").glob("family_*.db")), "database backed up first"
    r = run(["-c", probe], app, env=DRY)
    assert r.returncode == 0 and r.stdout.startswith("[]") and "Finishing" not in r.stdout


def test_a_failed_finish_stops_the_start(launch, tmp_path, monkeypatch):
    monkeypatch.setattr(launch, "pending_migrations", lambda root=None: ["migrate_999_x.py"])
    seen = []
    ok = launch.finish_update("py", root=tmp_path, run=lambda cmd, **k: seen.append(cmd) or subprocess.CompletedProcess(cmd, 1))
    assert ok is False and seen[0][-2:] == ["upgrade", "--no-doctor"]
    monkeypatch.setattr(launch, "pending_migrations", lambda root=None: [])
    assert launch.finish_update("py", root=tmp_path, run=lambda *a, **k: pytest.fail("nothing to do")) is True


def test_the_installer_prepares_python_and_starts_with_no_window():
    """0.137: the installer makes the environment from its shipped wheels while it installs, its shortcuts start the
    app with pythonw.exe --quiet (no console window), it stops a running app before replacing files and the
    uninstaller stops it too; the last page names the app, household and backup folders."""
    iss = (SRC / "installer" / "MitraHome.iss").read_text(encoding="utf-8")
    starts = [x for x in iss.splitlines() if x.startswith(("Name: \"{auto", "Filename:")) and "launch.py\"\" --" in x
              and "--prepare" not in x and "--stop" not in x]
    assert len(starts) == 4 and all('"{#Pyw}"' in x and "--quiet" in x for x in starts)
    run_part = iss.split("[Run]", 1)[1].split("[UninstallRun]", 1)[0]
    assert run_part.index("--prepare") < run_part.index("autostart.py") < run_part.index("--quiet")
    assert '"{#Py}"; Parameters: """{app}\\launch.py"" --prepare"; WorkingDir: "{app}"; Flags: runhidden' in run_part
    assert "--stop" in iss.split("[UninstallRun]", 1)[1].split("[UninstallDelete]", 1)[0]
    assert "StopRunningApp();" in iss and "taskkill.exe" in iss
    assert "wpFinished" in iss and "Mitra-Home-Backup" in iss


def test_a_quiet_start_has_no_window_and_runs_on(launch, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(launch, "ROOT", tmp_path)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    assert launch.step_opts() == {} and launch.app_opts() == {}, "a start in a window keeps its output there"
    launch.go_quiet()
    try:
        steps, app = launch.step_opts(), launch.app_opts()
        if os.name == "nt":
            assert steps["creationflags"] == launch.NO_WINDOW
            assert app["creationflags"] == launch.NO_WINDOW | launch.NEW_GROUP
        assert steps["stdout"] is sys.stdout and steps["stdin"] == subprocess.DEVNULL
        assert Path(app["stdout"].name).name == "web_app.out"
        app["stdout"].close()
        launch.say("  hello")
        sys.stdout.flush()
        assert "hello" in (launch.launcher_logs() / "launch.log").read_text(encoding="utf-8")
    finally:
        sys.stdout.close()


def test_the_keep_alive_task_leaves_a_stopped_app_alone_until_a_start_by_hand(launch, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(launch, "ROOT", tmp_path)
    monkeypatch.setattr(launch, "boot_time", lambda: 1000.0)
    note = launch.stop_note()
    assert note == tmp_path / ".stopped", "per app folder: a Stop in one install never holds another"
    note.write_text("x", encoding="utf-8")
    os.utime(note, (2000, 2000))
    assert launch.stopped_on_purpose()
    started = []
    monkeypatch.setattr(launch, "pick_port", lambda *a, **k: started.append(1) or (None, False))
    assert launch.main(["--keep-alive", "--no-browser"]) == 0 and not started and note.exists()
    os.utime(note, (500, 500))
    assert not launch.stopped_on_purpose(), "the PC restarted since"
    os.utime(note, (2000, 2000))
    assert launch.main(["--no-browser"]) == 1 and started and not note.exists(), "a start by hand removes the note"


def test_stop_ends_only_this_folders_own_app(launch, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(launch.dashboard_record, "read", lambda root=None, **k: None)
    assert launch.stop(tmp_path, run=lambda *a, **k: calls.append(a)) is False and not calls
    monkeypatch.setattr(launch.dashboard_record, "read", lambda root=None, **k: {"port": 8601, "pid": 4242, "lan": False})
    forgot = []
    monkeypatch.setattr(launch.dashboard_record, "forget", lambda root=None, **k: forgot.append(root))
    if os.name == "nt":
        assert launch.stop(tmp_path, run=lambda cmd, **k: calls.append(cmd)) is True
        assert calls == [["taskkill", "/PID", "4242", "/T", "/F"]] and forgot == [tmp_path]


def test_prepare_only_makes_the_environment(launch, monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    monkeypatch.setattr(sys, "stderr", sys.stderr)
    made, started = [], []
    monkeypatch.setattr(launch, "ensure_venv", lambda: made.append(1) or Path("py"))
    monkeypatch.setattr(launch, "pick_port", lambda *a, **k: started.append(1) or (None, False))
    try:
        assert launch.main(["--prepare"]) == 0 and made and not started and launch.QUIET
    finally:
        sys.stdout.close()
