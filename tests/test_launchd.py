"""macOS scheduling: LaunchAgents instead of cron (task_register), tested with a fake launchctl / crontab."""
import pathlib
import plistlib
import types


class FakeRun:
    """Records commands; `loaded` = labels launchctl knows; `crontab` = the user's crontab text."""
    def __init__(self, crontab=""):
        self.calls, self.loaded, self.crontab = [], set(), crontab

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        out, rc = "", 0
        if cmd[:2] == ["launchctl", "bootstrap"]:
            self.loaded.add(plistlib.loads(pathlib.Path(cmd[3]).read_bytes())["Label"])
        elif cmd[:2] == ["launchctl", "bootout"]:
            self.loaded.discard(cmd[2].split("/", 2)[2])
        elif cmd[:2] == ["launchctl", "print"]:
            rc = 0 if cmd[2].split("/", 2)[2] in self.loaded else 113
        elif cmd == ["crontab", "-l"]:
            out = self.crontab
        elif cmd == ["crontab", "-"]:
            self.crontab = kw.get("input", "")
        return types.SimpleNamespace(returncode=rc, stdout=out, stderr="")


def _mac(modules, monkeypatch):
    tr = modules("task_register")
    monkeypatch.setattr(tr.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(tr.os, "getuid", lambda: 501, raising=False)
    return tr


def test_cron_schedules_become_launchd_keys(modules):
    tr = modules("task_register")
    assert tr.launchd_when("0 7 * * *") == {"StartCalendarInterval": {"Minute": 0, "Hour": 7}}
    assert tr.launchd_when("0 18 * * 0") == {"StartCalendarInterval": {"Minute": 0, "Hour": 18, "Weekday": 0}}
    assert tr.launchd_when("30 9 * * 1,4")["StartCalendarInterval"] == [{"Minute": 30, "Hour": 9, "Weekday": 1},
                                                                       {"Minute": 30, "Hour": 9, "Weekday": 4}]
    assert tr.launchd_when("*/15 * * * *") == {"StartInterval": 900}
    assert tr.launchd_when("0 */2 * * *") == {"StartInterval": 7200}


def test_register_writes_agents_loads_them_and_drops_old_cron(modules, monkeypatch, tmp_path):
    tr = _mac(modules, monkeypatch)
    root = tmp_path / "app"
    run = FakeRun(crontab="0 1 * * * echo mine\n0 7 * * * cd '/x' && python tasks/run_task.py daily_digest  # MitraHome\n")
    ok, rows = tr.register_mac(run=run, root=root, home=tmp_path)
    assert ok and [r[0] for r in rows] == ["ai.mitrahome.daily-digest", "ai.mitrahome.weekly-digest", "ai.mitrahome.weekly-backup"]
    d = plistlib.loads((tmp_path / "Library/LaunchAgents/ai.mitrahome.daily-digest.plist").read_bytes())
    assert d["ProgramArguments"][1:] == [str(root / "tasks" / "run_task.py"), "daily_digest"]
    assert d["WorkingDirectory"] == str(root) and "StartCalendarInterval" in d and d["RunAtLoad"] is False
    assert ["launchctl", "bootstrap", "gui/501", str(tmp_path / "Library/LaunchAgents/ai.mitrahome.daily-digest.plist")] in run.calls
    assert run.crontab == "0 1 * * * echo mine\n", "our old cron lines go, the family's own stay"


def test_state_switch_and_remove_respect_other_installs(modules, monkeypatch, tmp_path):
    tr = _mac(modules, monkeypatch)
    root, other = tmp_path / "app", tmp_path / "other"
    run = FakeRun()
    assert tr.mac_state("weekly_backup", run, root, tmp_path) == ("off", "")
    tr.mac_on("weekly_backup", run, root, tmp_path)
    assert tr.mac_state("weekly_backup", run, root, tmp_path)[0] == "on"
    run.loaded.clear()
    assert tr.mac_state("weekly_backup", run, root, tmp_path)[0] == "paused", "file there, launchd does not know it"
    assert tr.mac_state("weekly_backup", run, other, tmp_path) == ("elsewhere", str(root))
    tr.mac_on("daily_digest", run, other, tmp_path)
    assert tr.remove_mac(root, run, tmp_path) == ["ai.mitrahome.weekly-backup"]
    assert (tmp_path / "Library/LaunchAgents/ai.mitrahome.daily-digest.plist").exists(), "another install's agent stays"


def test_set_job_and_job_state_use_launchd_on_a_mac(modules, monkeypatch, tmp_path):
    tr = _mac(modules, monkeypatch)
    monkeypatch.setattr(tr, "agents_dir", lambda home=None: tmp_path / "LA")
    run = FakeRun()
    root = tmp_path / "app"
    assert tr.set_job("weekly_digest", True, run, root) == (True, "")
    assert tr.job_state("weekly_digest", run, root)[0] == "on"
    assert tr.set_job("weekly_digest", False, run, root) == (True, "")
    assert tr.job_state("weekly_digest", run, root) == ("off", "")
    assert not any(c[0] == "crontab" for c in run.calls), "a Mac never touches crontab for one job"
