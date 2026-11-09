"""The test suite never touches this PC's real scheduled tasks (2026-10-15: `onboard.py upgrade` in a test copy moved the
user's tasks to pytest temp folders through task_register.adopt_legacy, which ignored test mode).

Two layers: task_register / autostart / onboard send every schtasks / crontab / launchctl command through
task_register._sched, which runs nothing in test mode (MITRAHOME_NO_SCHEDULER=1); and tests/scheduler_guard, loaded by
every Python the suite starts, blocks those tools outright and fails the test that tried to change a task."""
import json
import subprocess
import sys

import pytest

from conftest import GUARD, SRC, copy_template, imported_from, run


@pytest.fixture
def no_real_run(monkeypatch):
    """subprocess.run fails the test: nothing below may start a process."""
    def refuse(cmd, *a, **k):
        pytest.fail(f"started {cmd}")
    monkeypatch.setattr(subprocess, "run", refuse)


def test_register_adopt_and_remove_run_nothing_in_test_mode(no_real_run, tmp_path):
    with imported_from(SRC / "data", "task_register") as tr:
        ok, rows = tr.register(inbox_cycle=True)
        assert not ok and all("test mode" in detail for _, _, detail in rows)
        assert tr.adopt_legacy() == [], "the upgrade's rename step moves nothing"
        assert tr.remove_windows(root=tmp_path) == []
        assert tr.install_crontab(tr.cron_lines(["daily_digest"]))[0] is False
        assert tr.set_job("daily_digest", True) == (True, "test mode: nothing changed")
        assert tr.job_state("daily_digest") == ("unknown", "")


def test_phone_bot_autostart_runs_nothing_in_test_mode(no_real_run, monkeypatch, tmp_path):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    with imported_from(SRC / "data", "autostart") as a:
        monkeypatch.setattr(a, "supported", lambda: True)
        assert a.status() == ""
        assert a.adopt_legacy() == []


@pytest.mark.parametrize("cmd, kind", [
    (["schtasks", "/create", "/f", "/tn", "Mitra Home Daily Digest", "/tr", "x.bat"], "change"),
    (["C:\\Windows\\System32\\schtasks.exe", "/delete", "/f", "/tn", "x"], "change"),
    (["schtasks", "/change", "/tn", "x", "/disable"], "change"),
    (["schtasks", "/run", "/tn", "x"], "change"),
    (["schtasks", "/query", "/tn", "x", "/xml"], "read"),
    (["crontab", "-"], "change"),
    (["crontab", "-r"], "change"),
    (["crontab", "-l"], "read"),
    (["launchctl", "bootstrap", "gui/501", "x.plist"], "change"),
    (["launchctl", "print", "gui/501/ai.mitrahome.daily_digest"], "read"),
    ("cmd /c schtasks /create /tn x", "change"),
    (["powershell", "-Command", "Register-ScheduledTask -TaskName x"], "change"),
    (["powershell", "-Command", "Get-ScheduledTask"], "read"),
    ([sys.executable, "-c", "print('schtasks /create')"], None),
    (["git", "status"], None),
])
def test_guard_knows_scheduler_commands(cmd, kind):
    with imported_from(GUARD, "sitecustomize") as g:
        assert g.scheduler_call(cmd) == kind


def test_guard_blocks_this_process_and_every_child(tmp_path, monkeypatch):
    """The probes would fail harmlessly even unguarded (no /tr, no such task)."""
    assert getattr(subprocess.Popen, "_mitrahome_scheduler_guard", False), "conftest installs the guard here"
    log = tmp_path / "trip.jsonl"
    monkeypatch.setenv("MITRAHOME_SCHEDULER_TRIPWIRE", str(log))
    r = subprocess.run(["schtasks", "/delete", "/f", "/tn", "Mitra Home Guard Probe (no such task)"], capture_output=True)
    assert r.returncode == 1
    q = subprocess.run(["schtasks", "/query", "/tn", "Mitra Home Daily Digest"], capture_output=True, text=True)
    assert q.returncode == 1 and q.stdout == "", "a question is answered 'not found', and not counted as a change"
    child = ("import subprocess; print(subprocess.run(['schtasks', '/create', '/tn', 'Mitra Home Guard Probe'],"
             " capture_output=True).returncode)")
    c = run(["-c", child], tmp_path, env={"MITRAHOME_SCHEDULER_TRIPWIRE": str(log)})
    assert c.stdout.strip() == "1", c.stderr[-300:]
    seen = [json.loads(x)["cmd"] for x in log.read_text(encoding="utf-8").splitlines()]
    assert [x[:2] for x in seen] == [["schtasks", "/delete"], ["schtasks", "/create"]]


def test_upgrade_in_a_copy_with_test_mode_off_still_touches_nothing(tmp_path):
    """onboard.py upgrade (the step that moved the real tasks) with MITRAHOME_NO_SCHEDULER and AIFA_DRY_RUN cleared:
    only the guard stands between it and the scheduler, and it holds."""
    root = copy_template(tmp_path / "t")
    assert run(["data/migrate.py"], root).returncode == 0
    log = tmp_path / "trip.jsonl"
    r = run(["onboard.py", "upgrade", "--no-doctor"], root,
            env={"MITRAHOME_NO_SCHEDULER": "", "AIFA_DRY_RUN": "", "MITRAHOME_SCHEDULER_TRIPWIRE": str(log)})
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-300:]
    assert not log.exists(), log.read_text(encoding="utf-8")
