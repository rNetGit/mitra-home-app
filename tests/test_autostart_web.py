"""The web app can start with this PC: a task that ticks every 5 minutes and runs launch.py (which exits at once while the
app is up), so a tick after it died starts it again. A sign-in trigger needs admin on some PCs; this one does not.
No real scheduler call: autostart._run is replaced by a recorder."""
import os
import subprocess
import sys

import pytest

from conftest import SRC, imported_from


class Recorder:
    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def __call__(self, cmd):
        self.calls.append(cmd)
        bad = self.fail_on is not None and self.fail_on in " ".join(cmd)
        return subprocess.CompletedProcess(cmd, 1 if bad else 0, "", "refused" if bad else "")


@pytest.fixture
def autostart(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with imported_from(SRC / "data", "autostart") as a:
        monkeypatch.setattr(a, "supported", lambda: True)
        monkeypatch.setattr(a, "_remember", lambda *args, **kw: None)
        yield a


def test_web_task_ticks_every_five_minutes_and_runs_the_hidden_launcher(autostart):
    rec = Recorder()
    autostart._run = rec
    ok, msg = autostart.enable("web", start_now=False, lan=True)
    assert ok and "within 5 minutes" in msg
    create = next(c for c in rec.calls if c[:2] == ["schtasks", "/create"])
    assert create[create.index("/tn") + 1] == "Mitra Home Web App"
    assert create[create.index("/sc") + 1:create.index("/sc") + 4] == ["minute", "/mo", "5"], "no sign-in trigger (admin)"
    tr = create[create.index("/tr") + 1]
    assert tr.startswith("wscript.exe //B //Nologo ") and tr.endswith('web_app.vbs" --lan')


def test_web_task_gets_no_time_limit_and_one_copy_at_a_time(autostart):
    rec = Recorder()
    autostart._run = rec
    autostart.enable("web", start_now=False)
    script = next(c for c in rec.calls if c[0] == "powershell")[-1]
    assert "ExecutionTimeLimit = 'PT0S'" in script and "MultipleInstances = 'IgnoreNew'" in script
    assert "'Mitra Home Web App'" in script and "StopIfGoingOnBatteries = $false" in script


def test_web_task_without_lan_has_no_arguments_and_starts_now_on_request(autostart):
    rec = Recorder()
    autostart._run = rec
    autostart.enable("web")
    create = next(c for c in rec.calls if c[:2] == ["schtasks", "/create"])
    assert create[create.index("/tr") + 1].endswith('web_app.vbs"')
    assert ["schtasks", "/run", "/tn", "Mitra Home Web App"] in rec.calls


def test_a_refused_settings_change_is_said_in_the_message(autostart):
    autostart._run = Recorder(fail_on="Set-ScheduledTask")
    ok, msg = autostart.enable("web", start_now=False)
    assert ok and "72 hours" in msg


def test_the_phone_bots_still_start_at_sign_in(autostart):
    rec = Recorder()
    autostart._run = rec
    autostart.enable("telegram", start_now=False)
    create = next(c for c in rec.calls if c[:2] == ["schtasks", "/create"])
    assert create[create.index("/sc") + 1] == "onlogon" and create[create.index("/tr") + 1].endswith('chat_telegram.bat"')
    assert not any(c[0] == "powershell" for c in rec.calls)


def test_startup_folder_fallback_for_the_web_app(autostart, tmp_path, monkeypatch):
    autostart._run = Recorder(fail_on="/create")
    started = []
    monkeypatch.setattr(autostart.subprocess, "Popen", lambda cmd, *a, **k: started.append(cmd))
    ok, msg = autostart.enable("web", start_now=True, lan=True)
    f = autostart._startup_file("Mitra Home Web App")
    assert ok and "not restarted" in msg and f.exists()
    assert f.read_text(encoding="ascii").strip().endswith('web_app.bat" --lan')
    assert started and started[0].endswith('web_app.bat" --lan')


def test_crontab_line_for_the_web_app(autostart):
    line = autostart.crontab_line("web", lan=True)
    assert line.startswith("@reboot cd ") and "launch.py --no-browser --lan" in line and line.endswith("# MitraHome")
    assert "launch.py --no-browser  #" in autostart.crontab_line("web")


def test_launcher_files_exist_and_pass_arguments_through():
    bat = (SRC / "tasks" / "web_app.bat").read_text(encoding="utf-8")
    vbs = (SRC / "tasks" / "web_app.vbs").read_text(encoding="utf-8")
    assert 'launch.py --keep-alive --no-browser %*' in bat and "exit /b %ERRORLEVEL%" in bat
    assert "WScript.Arguments" in vbs and "WScript.Quit" in vbs and ", 0, True)" in vbs


# ---- from the Windows installer: --home and --no-start (installer/MitraHome.iss task "autostart")
def test_installer_call_passes_the_household_folder_and_waits_ten_minutes(autostart, monkeypatch):
    remembered = []
    monkeypatch.setattr(autostart, "_remember", lambda *a, **k: remembered.append(a))
    rec = Recorder()
    autostart._run = rec
    ok, _ = autostart.enable("web", start_now=False, home=r"C:\Users\Me\My Family Data")
    assert ok
    create = next(c for c in rec.calls if c[:2] == ["schtasks", "/create"])
    assert create[create.index("/tr") + 1].endswith(r'web_app.vbs" --home "C:\Users\Me\My Family Data"')
    hhmm = create[create.index("/st") + 1]
    assert len(hhmm) == 5 and hhmm[2] == ":", "the first tick is delayed"
    assert remembered == [], "family.json in the app folder would make a new install look already set up"
    assert not any(c[:2] == ["schtasks", "/run"] for c in rec.calls)


def test_without_home_there_is_no_start_time_and_it_is_remembered(autostart, monkeypatch):
    remembered = []
    monkeypatch.setattr(autostart, "_remember", lambda *a, **k: remembered.append(a))
    rec = Recorder()
    autostart._run = rec
    autostart.enable("web", start_now=False, lan=True)
    create = next(c for c in rec.calls if c[:2] == ["schtasks", "/create"])
    assert "/st" not in create and remembered == [("web", True, True)]


def test_command_line_reads_home_and_no_start(autostart, monkeypatch):
    seen = {}
    monkeypatch.setattr(autostart, "enable", lambda kind, **kw: seen.update(kind=kind, **kw) or (True, "ok"))
    assert autostart.main(["on", "web", "--no-start", "--home", r"C:\A B"]) == 0
    assert seen == {"kind": "web", "start_now": False, "lan": False, "home": r"C:\A B"}
    seen.clear()
    assert autostart.main(["on", "telegram", "--home", r"C:\A B"]) == 0
    assert seen["home"] is None, "--home is for the web app only"


@pytest.mark.skipif(not __import__("sys").platform.startswith("win"), reason="wscript is Windows only")
def test_vbs_quotes_an_argument_that_has_a_space(tmp_path):
    (tmp_path / "tasks").mkdir()
    for n in ("web_app.bat", "web_app.vbs"):
        (tmp_path / "tasks" / n).write_text((SRC / "tasks" / n).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "launch.py").write_text("import sys; print(repr(sys.argv[1:])); sys.exit(4)", encoding="utf-8")
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path / "local")}
    r = subprocess.run(["wscript.exe", "//B", "//Nologo", str(tmp_path / "tasks" / "web_app.vbs"), "--home", r"C:\My Data", "--lan"],
                       timeout=60, env=env)
    assert r.returncode == 4, "the exit code comes back"
    out = (tmp_path / "local" / "MitraHome" / "logs" / "web_autostart.out").read_text()
    assert "['--keep-alive', '--no-browser', '--home', 'C:\\\\My Data', '--lan']" in out


def test_installer_has_the_autostart_checkbox_and_runs_it_before_starting_the_app():
    iss = (SRC / "installer" / "MitraHome.iss").read_text(encoding="utf-8")
    assert 'Name: "autostart"' in iss and "GroupDescription: \"Startup:\"" in iss
    line = next(x for x in iss.splitlines() if "autostart.py" in x and x.startswith("Filename"))
    assert "on web --no-start --home" in line and "Tasks: autostart" in line and "runhidden" in line
    assert iss.index("autostart.py") < iss.index("Start Mitra Home now"), "registered before the first start"
    assert "unchecked" not in line and 'Name: "autostart"' in iss and "Flags: unchecked" not in iss.split('Name: "autostart"')[1].splitlines()[0]


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="the task wrapper is a Windows .bat")
def test_first_start_by_the_task_can_move_the_app_folders_logs(tmp_path):
    """0.130.2: the .bat wrote its output to <app>/logs/web_autostart.out. On a fresh install the task's first start runs
    launch.py -> onboard.set_home, which moves the app folder's logs into the household folder; the file held open by the
    redirect made that fail (WinError 32), so every tick exited 1 and the household was never made. The stub launch.py
    here moves <app>/logs the way set_home does; it must work, and the output must be outside the app folder."""
    app = tmp_path / "app"
    (app / "tasks").mkdir(parents=True)
    (app / "logs").mkdir()  # a fresh install's app folder already has one (the installer's earlier steps, caches)
    (app / "tasks" / "web_app.bat").write_text((SRC / "tasks" / "web_app.bat").read_text(encoding="utf-8"), encoding="utf-8")
    (app / "launch.py").write_text("\n".join([
        "import os, sys",
        "p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')",
        "os.rename(p, p + '_moved')",
        "print('moved the logs folder')",
    ]), encoding="utf-8")
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path / "local"),
           "PATH": os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", "")}
    r = subprocess.run(["cmd", "/c", str(app / "tasks" / "web_app.bat"), "--home", "x"], timeout=60, env=env)
    assert r.returncode == 0, "set_home's move of the app folder's logs works while the wrapper runs"
    assert (app / "logs_moved").is_dir()
    out = tmp_path / "local" / "MitraHome" / "logs" / "web_autostart.out"
    assert "moved the logs folder" in out.read_text()
    assert not list(app.rglob("web_autostart.out")), "no output file inside the app folder"
