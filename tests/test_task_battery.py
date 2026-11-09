"""Scheduled tasks run on a laptop on battery (2026-10-17: the Inbox Cycle skipped its 6:20 PM run on a laptop at 17%
because `schtasks /create` leaves Task Scheduler's DisallowStartIfOnBatteries / StopIfGoingOnBatteries on). Every place
that creates a task asks for the battery and missed-start settings right after it, through the same runner."""
import platform
import subprocess

import pytest

from conftest import GUARD, imported_from


class R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


@pytest.fixture(scope="module")
def TR(root, modules):
    return modules("task_register")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(platform, "system", lambda: "Windows")


def asks_for_laptop_settings(cmd, name):
    script = cmd[-1]
    return (cmd[0] == "powershell" and f"-TaskName '{name}'" in script and "Set-ScheduledTask" in script
            and "$s.DisallowStartIfOnBatteries = $false" in script and "$s.StopIfGoingOnBatteries = $false" in script
            and "$s.StartWhenAvailable = $true" in script)


def test_create_sets_battery_and_wake_after_the_task_and_keeps_the_schedule(TR, root):
    calls = []
    ok, msg = TR.create_windows("Mitra Home Weekly Digest", "weekly_digest", ["/sc", "weekly", "/d", "SUN", "/st", "18:00"],
                                run=lambda c, **k: calls.append(c) or R(), root=root)
    assert (ok, msg) == (True, "")
    assert calls[0][:5] == ["schtasks", "/create", "/f", "/tn", "Mitra Home Weekly Digest"]
    assert calls[0][-6:] == ["/sc", "weekly", "/d", "SUN", "/st", "18:00"], "the schedule is unchanged"
    assert str(root / "tasks" / "weekly_digest.bat") in calls[0][6]
    assert len(calls) == 2 and asks_for_laptop_settings(calls[1], "Mitra Home Weekly Digest")


def test_a_refused_task_asks_for_nothing_more_and_refused_settings_still_register(TR):
    calls = []
    assert TR.create_windows("X", "daily_digest", ["/sc", "daily"], run=lambda c, **k: calls.append(c) or R(1, err="Access is denied.")) \
        == (False, "Access is denied.")
    assert len(calls) == 1
    answers = iter([R(), R(1, err="Get-ScheduledTask : not found")])
    ok, msg = TR.create_windows("X", "daily_digest", ["/sc", "daily"], run=lambda c, **k: next(answers))
    assert ok and "mains power" in msg and "not found" in msg


def test_a_quote_in_the_name_cannot_break_out_of_the_powershell_string(TR):
    assert "-TaskName 'O''Brien Daily'" in TR.laptop_settings_cmd("O'Brien Daily")[-1]


def test_the_settings_command_is_a_scheduler_change_for_the_guard(TR):
    with imported_from(GUARD, "sitecustomize") as guard:
        assert guard.scheduler_call(TR.laptop_settings_cmd("Mitra Home Daily Digest")) == "change"


def test_register_and_adopt_legacy_ask_for_it_for_every_task(TR, windows, monkeypatch):
    calls = []
    monkeypatch.setattr(TR, "_sched", lambda c, **k: calls.append(c) or R(1 if c[1] == "/query" else 0))
    ok, rows = TR.register_windows(inbox_cycle=True)
    assert ok and [n for n, _, _ in rows] == [t[0] for t in TR.TASKS + [TR.INBOX_TASK]]
    for name, _, _ in rows:
        assert any(asks_for_laptop_settings(c, name) for c in calls), name
    calls.clear()
    monkeypatch.setattr(TR, "_sched", lambda c, **k: calls.append(c) or R())  # every pre-rename task exists
    moved = TR.adopt_legacy()
    assert moved == [t[0] for t in TR.TASKS + [TR.INBOX_TASK, TR.SWEEP_TASK]]
    for name in moved:
        assert any(asks_for_laptop_settings(c, name) for c in calls), name


def test_switching_one_job_on_asks_for_it(TR, windows, root):
    calls = []
    ok, msg = TR.set_job("inbox_cycle", True, run=lambda c, **k: calls.append(c) or R(), root=root)
    assert (ok, msg) == (True, "")
    assert calls[0][1] == "/create" and calls[0][-4:] == ["/sc", "hourly", "/mo", "2"]
    assert asks_for_laptop_settings(calls[1], TR.INBOX_TASK[0])


def test_a_new_time_in_the_profile_asks_for_it(root, modules, windows):
    P = modules("agent_profile")
    calls = []
    here = f"<Command>{root / 'tasks' / 'daily_digest.bat'}</Command>"
    assert P.reschedule("daily_digest", run=lambda c, **k: calls.append(c) or R(0, here)) is True
    assert calls[1][1] == "/create" and calls[1][-2:] == ["/st", P.get()["brief_time"]]
    assert asks_for_laptop_settings(calls[2], P.TASK_NAMES["daily_digest"])


def test_the_wizards_drive_sweep_task_asks_for_it(root, modules, windows, monkeypatch):
    modules("task_register")
    with imported_from(root, "onboard") as onboard:
        calls = []
        monkeypatch.setattr(onboard.task_register, "_sched", lambda c, **k: calls.append(c) or R(1 if c[1] == "/query" else 0))
        assert onboard.register_sweep() is True
        assert calls[0][-4:] == ["/sc", "minute", "/mo", "15"]
        assert asks_for_laptop_settings(calls[1], onboard.task_register.SWEEP_TASK[0])


def test_the_suite_still_never_reaches_the_real_scheduler(TR, windows, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("started a process"))
    assert TR.create_windows("Mitra Home Daily Digest", "daily_digest", ["/sc", "daily"])[0] is False
