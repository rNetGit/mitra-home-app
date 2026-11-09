"""0.65.0 first-run gaps closed in the browser: make the scheduled jobs run on their own, optional packs, tax papers
(data/task_register.py, admin_actions.tasks_register / packs_set / tax_prep_set, dashboard/connections.py cards)."""
import json

import pytest

from conftest import read_family

ADULT, KID = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}


@pytest.fixture(scope="module")
def A(root, modules):
    return modules("admin_actions")


@pytest.fixture(scope="module")
def TR(root, modules):
    return modules("task_register")


def test_registering_tasks_is_adults_only_and_remembers_the_choice(root, A, TR, monkeypatch):
    assert A.tasks_register(KID)[0] is False
    asked = []
    monkeypatch.setattr(TR, "register", lambda inbox: asked.append(inbox) or (True, [("x", True, "registered")]))
    monkeypatch.delenv("AIFA_DRY_RUN", raising=False)
    ok, msg = A.tasks_register(ADULT, inbox_cycle=True)
    assert ok and asked == [True] and "inbox is checked" in msg
    fam = read_family(root)
    assert fam["tasks_registered"] is True and fam["inbox_cycle"] is True
    assert A.tasks_status() == {"registered": True, "inbox_cycle": True}


def test_a_refused_schedule_says_which_and_does_not_mark_it_done(root, A, TR, monkeypatch):
    fam = read_family(root)
    fam.pop("tasks_registered", None)
    (root / "config" / "family.json").write_text(json.dumps(fam), encoding="utf-8")
    monkeypatch.setattr(TR, "register", lambda inbox: (False, [("Mitra Home Daily Digest", False, "FAILED access denied")]))
    monkeypatch.delenv("AIFA_DRY_RUN", raising=False)
    ok, msg = A.tasks_register(ADULT)
    assert not ok and "Daily Digest" in msg
    assert "tasks_registered" not in read_family(root)


def test_dry_run_touches_nothing(root, A, TR, monkeypatch):
    monkeypatch.setenv("AIFA_DRY_RUN", "1")
    monkeypatch.setattr(TR, "register", lambda inbox: pytest.fail("must not register in test mode"))
    ok, msg = A.tasks_register(ADULT)
    assert ok and "Test mode" in msg


def test_cron_lines_mark_the_install_and_follow_the_profile(root, TR):
    lines = TR.cron_lines(TR.jobs(inbox_cycle=True))
    assert len(lines) == 4 and all(ln.endswith("# MitraHome") for ln in lines)
    assert any("tasks/run_task.py inbox_cycle" in ln for ln in lines)
    assert not any("inbox_cycle" in ln for ln in TR.cron_lines(TR.jobs()))


def test_packs_copy_the_example_once_and_never_overwrite(root, A):
    assert A.packs_set(KID, {"festivals": True})[0] is False
    assert A.packs_set(ADULT, {"nonsense": True})[0] is False
    dst = root / "config" / "festivals.json"
    dst.unlink(missing_ok=True)
    ok, msg = A.packs_set(ADULT, {"festivals": True, "shopping": True})
    assert ok and dst.exists() and "festival calendar" in msg
    assert read_family(root)["packs"]["festivals"] is True
    dst.write_text('{"mine": true}', encoding="utf-8")
    ok, msg = A.packs_set(ADULT, {"festivals": True})
    assert ok and json.loads(dst.read_text(encoding="utf-8")) == {"mine": True}, "a household's own file is kept"
    assert "starter list" not in msg
    assert A.packs_set(ADULT, {"festivals": False})[0] and read_family(root)["packs"]["festivals"] is False
    assert dst.exists(), "switching a pack off removes nothing"


def test_tax_names_only(root, A):
    assert A.tax_prep_set(KID, "Chase")[0] is False
    assert A.tax_prep_set(ADULT, "Chase, 123456789012")[0] is False
    assert A.tax_prep_set(ADULT, "Account 1234-5678-90")[0] is False
    assert A.tax_prep_set(ADULT, "x" * 90)[0] is False
    assert not (root / "config" / "tax_prep.json").exists() or "123456789012" not in (root / "config" / "tax_prep.json").read_text(encoding="utf-8")
    ok, _ = A.tax_prep_set(ADULT, "Chase, Credit Union X\nFidelity", "State Dept of Revenue", "%UNIVERSITY BURSAR%")
    assert ok
    saved = json.loads((root / "config" / "tax_prep.json").read_text(encoding="utf-8"))
    assert saved["payers"] == ["Chase", "Credit Union X", "Fidelity"]
    assert saved["state_tax_keywords"] == ["State Dept of Revenue"]
    assert saved["education_payee_patterns"] == ["%UNIVERSITY BURSAR%"]
    audit = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "Chase" not in audit, "the audit line holds counts, not names"




def test_uninstall_removes_only_this_installs_tasks(TR, monkeypatch, tmp_path):
    calls = []

    class R:
        def __init__(self, rc, out=""):
            self.returncode, self.stdout = rc, out

    def run(cmd, **_):
        calls.append(cmd)
        if cmd[1] == "/query":
            mine = cmd[3] == TR.TASKS[0][0]
            folder = tmp_path / "tasks" if mine else "D:/other/tasks"
            return R(0, f"<Command>{folder}/daily_digest.bat</Command>")
        return R(0)

    monkeypatch.setattr(TR, "_sched", run)  # the scheduler runner (test mode refuses the real one)
    assert TR.remove_windows(root=tmp_path) == [TR.TASKS[0][0]]
    assert [c[-1] for c in calls if c[1] == "/delete"] == [TR.TASKS[0][0]]


class _R:
    def __init__(self, rc=0, out="", err=""):
        self.returncode, self.stdout, self.stderr = rc, out, err


def _scheduler(root, tasks):
    """A fake schtasks: `tasks` = {task name: command} is the scheduler's state; returns (runner, calls)."""
    calls = []

    def run(cmd, **_):
        calls.append(cmd)
        if cmd[0] == "powershell":  # the battery / missed-start settings after a create (test_task_battery.py)
            return _R(0)
        if cmd[1] == "/query":
            cmd_line = tasks.get(cmd[3])
            return _R(0, f"<Task><Command>{cmd_line}</Command></Task>") if cmd_line else _R(1)
        if cmd[1] == "/create":
            tasks[cmd[cmd.index("/tn") + 1]] = cmd[cmd.index("/tr") + 1]
            return _R(0)
        if cmd[1] == "/delete":
            tasks.pop(cmd[-1], None)
            return _R(0)
        return _R(1)
    return run, calls


@pytest.mark.skipif(__import__("platform").system() != "Windows", reason="Task Scheduler")
def test_one_job_on_off_and_its_state(root, TR):
    name = TR.ALL["weekly_backup"][0]
    tasks = {}
    run, calls = _scheduler(root, tasks)
    assert TR.job_state("weekly_backup", run, root) == ("off", "")
    assert TR.set_job("weekly_backup", True, run, root) == (True, "")
    assert "weekly_backup.bat" in tasks[name] and str(root) in tasks[name]
    assert TR.job_state("weekly_backup", run, root)[0] == "on"
    assert TR.set_job("weekly_backup", False, run, root)[0] and name not in tasks
    tasks[name] = "D:/other/tasks/weekly_backup.bat"
    assert TR.job_state("weekly_backup", run, root) == ("elsewhere", "D:/other/tasks/weekly_backup.bat")
    ok, msg = TR.set_job("weekly_backup", False, run, root)
    assert not ok and "another copy" in msg and tasks[name].startswith("D:/other"), "another copy's task is left alone"
    tasks[name] = f'"{root / "tasks" / "weekly_backup.bat"}"'
    paused = lambda cmd, **k: _R(0, f"<Command>{tasks[name]}</Command><Enabled>false</Enabled>")  # noqa: E731
    assert TR.job_state("weekly_backup", paused, root)[0] == "paused"
    assert TR.job_state("weekly_backup") == ("unknown", ""), "the test suite never asks the real scheduler"
    assert TR.set_job("weekly_backup", True)[1].startswith("test mode")


def test_cron_one_job_on_and_off(root, TR, monkeypatch):
    monkeypatch.setattr(TR.platform, "system", lambda: "Linux")
    tab = ["0 5 * * * other-job"]

    def run(cmd, **kw):
        if cmd == ["crontab", "-l"]:
            return _R(0, "\n".join(tab) + "\n")
        tab[:] = [ln for ln in kw["input"].splitlines() if ln]
        return _R(0)
    assert TR.job_state("daily_digest", run, root)[0] == "off"
    assert TR.set_job("daily_digest", True, run, root)[0]
    assert TR.job_state("daily_digest", run, root) == ("on", "crontab") and tab[0] == "0 5 * * * other-job"
    assert TR.set_job("daily_digest", False, run, root)[0] and tab == ["0 5 * * * other-job"]


def test_switching_a_job_off_is_remembered_and_not_asked_for(root, A, modules, monkeypatch):
    hb = modules("heartbeat")
    TR = modules("task_register")
    assert A.task_set(KID, "daily_digest", False)[0] is False
    monkeypatch.setattr(TR, "set_job", lambda job, on, run=None: (True, ""))
    monkeypatch.delenv("AIFA_DRY_RUN", raising=False)
    fam = read_family(root)
    fam["tasks_registered"] = True
    (root / "config" / "family.json").write_text(json.dumps(fam), encoding="utf-8")
    ok, msg = A.task_set(ADULT, "weekly_backup", False)
    assert ok and "is off" in msg and read_family(root)["tasks_off"] == ["weekly_backup"]
    assert "weekly_backup" not in [t for t, _ in hb.stale()], "a job switched off is not expected to run"
    assert read_family(root)["tasks_registered"] is True, "the other jobs still run"
    assert A.task_set(ADULT, "weekly_backup", True)[0] and read_family(root)["tasks_off"] == []
    assert A.task_set(ADULT, "inbox_cycle", True)[0] and read_family(root)["inbox_cycle"] is True
    assert A.task_set(ADULT, "nope", True) == (False, "Unknown job.")
    monkeypatch.setattr(TR, "set_job", lambda job, on, run=None: (False, "Access is denied."))
    ok, msg = A.task_set(ADULT, "daily_digest", True)
    assert not ok and "Access is denied" in msg


def test_changing_a_time_saves_the_profile(root, A, modules):
    P = modules("agent_profile")
    assert A.task_time(KID, "weekly_backup", "SAT", "08:15")[0] is False
    ok, msg = A.task_time(ADULT, "weekly_backup", "SAT", "08:15")
    assert ok and "Saturdays at 08:15" in msg
    assert P.get()["backup_day"] == "SAT" and P.schtasks_args("weekly_backup")[-3:] == ["SAT", "/st", "08:15"]
    assert A.task_time(ADULT, "daily_digest", "", "25:00")[0] is False
    assert A.task_time(ADULT, "inbox_cycle", "", "08:00")[0] is False
    A.task_time(ADULT, "weekly_backup", "SUN", "09:00")


def test_job_rows_show_state_when_and_last_run(root, A, modules):
    import datetime as dt
    hb = modules("heartbeat")
    hb.record("daily_digest", True)
    hb.record("weekly_digest", False, "a step failed")
    rows = {r["job"]: r for r in A.task_jobs(cfg={})}
    assert list(rows) == ["daily_digest", "weekly_digest", "weekly_backup", "inbox_cycle"], "no drop box without Drive"
    assert rows["daily_digest"]["last"]["text"].startswith("Today") and rows["daily_digest"]["last"]["ok"]
    assert rows["weekly_digest"]["last"]["ok"] is False and "a step failed" in rows["weekly_digest"]["last"]["note"]
    assert rows["weekly_backup"]["last"] is None and rows["weekly_backup"]["day"] == "SUN"
    assert rows["inbox_cycle"]["when"] == "Every two hours" and rows["inbox_cycle"]["time"] is None
    assert rows["daily_digest"]["state"] == "unknown"
    assert "inbox_sweep" in [r["job"] for r in A.task_jobs(cfg={"sweep_registered": True})]
    old = {"ok": True, "at": (dt.datetime(2026, 10, 15, 9, 0)).isoformat()}
    assert A._last_run(old, now=dt.datetime(2026, 10, 16, 8)) ["text"] == "Yesterday 09:00"
    assert A._last_run(old, now=dt.datetime(2026, 10, 20, 8))["text"] == "Oct 15 09:00"
