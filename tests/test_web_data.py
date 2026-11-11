"""Settings > Data in the web app (data/maintenance_data.py): back up, export download, restore (check, start, the web
app closing and coming back), running on its own, updates, the full check, the change log. Adults only, CSRF on every
change. Nothing slow or outward runs here: the backup, export, updater, restore process and doctor are replaced."""
import datetime as dt
import re
import zipfile

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def data(root, modules, monkeypatch):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    md = modules("maintenance_data")
    md._UPDATE.update(at=0.0, newer=None, error="")
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/settings?group=data").text).group(1)
    return c, t, md


def _post(c, path, csrf, **d):
    return c.post(path, data=d, headers={"X-CSRF-Token": csrf})


def _page(c):
    return c.get("/settings?group=data").text


def test_data_group_backup_export_and_download(data, modules, monkeypatch):
    c, t, md = data
    page = _page(c)
    for words in ("Back up now", "Restore from backup", "Runs on its own", "Check for updates", "Run full check"):
        assert words in page, words
    assert "classic" not in page.lower()
    aa = modules("admin_actions")
    monkeypatch.setattr(aa, "backup_now", lambda user: (True, "snapshot written"))
    r = _post(c, "/settings/backup", t)
    assert r.headers["hx-redirect"] == "/settings?group=data" and "Backup done." in _page(c)
    paths = modules("paths")
    paths.EXPORTS.mkdir(parents=True, exist_ok=True)
    z = paths.EXPORTS / "familyagent_export_test.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("members.csv", "name\nAlex\n")
    monkeypatch.setattr(aa, "export_now", lambda user: (True, "Exported 3 tables.", z))
    _post(c, "/settings/export", t)
    page = _page(c)
    assert "Exported 3 tables." in page and 'href="/settings/export/familyagent_export_test.zip"' in page
    r = c.get("/settings/export/familyagent_export_test.zip")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and "attachment" in r.headers["content-disposition"]
    for bad in ("..%2Fconfig%2Ffamily.json", "family.db", "nothere.zip", "..%5Cx.zip"):
        assert c.get(f"/settings/export/{bad}").status_code == 404, bad


def test_restore_check_and_start_close_the_web_app(data, modules, monkeypatch):
    c, t, md = data
    assert "No backups yet" in _page(c)
    rb = modules("restore_backup")
    snap = {"src": "D:/backups", "name": "family_2026-10-01_120000.db", "when": dt.datetime(2026, 10, 1, 12), "where": "this PC",
            "encrypted": False}
    monkeypatch.setattr(rb, "snapshots", lambda: [snap])
    monkeypatch.setattr(rb, "check", lambda src, name, pw=None: (True, "The backup is good."))
    started, closed = [], []
    monkeypatch.setattr(rb, "start_live", lambda *a, **k: started.append((a, k)))
    monkeypatch.setattr(md, "close_soon", lambda seconds=2.0: closed.append(seconds))
    assert "Thu 01 Oct 2026" in _page(c)
    _post(c, "/settings/backup/restore", t, op="check", snap="0")
    assert "The backup is good." in _page(c)
    _post(c, "/settings/backup/restore", t, op="start", snap="0")
    assert "Tick the box" in _page(c) and not started
    r = _post(c, "/settings/backup/restore", t, op="start", snap="0", sure="1")
    assert "only on this PC" in _page(c) and not started and not closed, "never from a phone on the Wi-Fi (S5)"
    app_mod = modules("webapp.app")
    monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"})
    _post(c, "/settings/backup/restore", t, op="start", snap="7", sure="1")
    assert "no longer there" in _page(c) and not started
    monkeypatch.setenv("MITRAHOME_WEB_PORT", "8605")
    r = _post(c, "/settings/backup/restore", t, op="start", snap="0", sure="1")
    assert r.status_code == 200 and "data-wait-back" in r.text and closed
    (args, kw), = started
    assert args[:2] == ("D:/backups", "family_2026-10-01_120000.db") and kw["web"] is True and kw["port"] == 8605
    assert _post(c, "/settings/backup/restore", t, op="explode").status_code == 400


def test_restore_live_starts_the_web_app_again(root, modules, monkeypatch):
    rb = modules("restore_backup")
    again = []
    monkeypatch.setattr(rb, "relaunch_web", lambda port, lan=False: again.append((port, lan)))
    res = rb.restore_live(str(root / "no_such_backup"), "family_x.db", relaunch="8601", web=True, lan=True)
    assert res["ok"] is False and again == [("8601", True)]


def test_tasks_updates_and_full_check(data, modules, monkeypatch):
    c, t, md = data
    aa = modules("admin_actions")
    seen = []
    monkeypatch.setattr(aa, "tasks_register", lambda user, inbox=False: (seen.append(inbox) or (True, "Registered.")))
    _post(c, "/settings/tasks", t, inbox="1")
    assert seen == [True] and "Registered." in _page(c)
    upd = modules("updater")
    monkeypatch.setattr(upd, "check", lambda quiet=True: ("0.1", {"version": "9.9.9"}, True))
    _post(c, "/settings/update", t, op="check")
    page = _page(c)
    assert "9.9.9 is available" in page and "Update to 9.9.9" in page
    monkeypatch.setattr(aa, "update_now", lambda user: (True, "done"))
    rb = modules("restore_backup")
    again, closed = [], []
    monkeypatch.setattr(rb, "start_relaunch", lambda port, lan=False: again.append((port, lan)))
    monkeypatch.setattr(md, "close_soon", lambda seconds=2.0: closed.append(seconds))
    monkeypatch.setenv("MITRAHOME_WEB_PORT", "8605")
    r = _post(c, "/settings/update", t, op="go")
    assert "starts again with the new version" in r.text and "data-wait-back" in r.text and "<h2>Update</h2>" in r.text
    assert again == [(8605, False)] and closed, "S6: the app starts again on its own port with the new code"
    monkeypatch.setattr(aa, "update_now", lambda user: (False, "signature bad"))
    _post(c, "/settings/update", t, op="go")
    assert "did not finish" in _page(c) and len(again) == 1, "a failed update keeps the running app"
    monkeypatch.setattr(md, "full_check", lambda: ["[x] database", "[!] <b>tasks</b>", "12/13 checks passed"])
    r = _post(c, "/settings/doctor", t)
    assert "[x] database" in r.text and "&lt;b&gt;tasks" in r.text
    assert _post(c, "/settings/update", t, op="nope").status_code == 400


def test_data_actions_need_an_adult(data):
    c, _, _ = data
    c.cookies.clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    for path, d in (("/settings/backup", {}), ("/settings/export", {}), ("/settings/backup/restore", {"op": "check"}),
                    ("/settings/tasks", {}), ("/settings/update", {"op": "check"}), ("/settings/doctor", {})):
        assert _post(c, path, t, **d).status_code == 403, path
    assert c.get("/settings/export/x.zip").status_code == 403


def test_runs_on_its_own_card_switch_and_time(data, modules, monkeypatch):
    c, t, md = data
    page = _page(c)
    for words in ("Daily brief", "Weekly digest and family meeting", "Weekly backup", "Inbox check", 'role="switch"',
                  "Change time", "Last run:"):
        assert words in page, words
    aa = modules("admin_actions")
    seen = []
    monkeypatch.setattr(aa, "task_set", lambda user, job, on: seen.append((job, on)) or (True, "Weekly backup is off."))
    _post(c, "/settings/tasks/job", t, job="weekly_backup")
    _post(c, "/settings/tasks/job", t, job="daily_digest", on="1")
    assert seen == [("weekly_backup", False), ("daily_digest", True)] and "Weekly backup is off." in _page(c)
    monkeypatch.setattr(aa, "task_time", lambda user, job, day, time_: seen.append((job, day, time_)) or (True, "moved"))
    _post(c, "/settings/tasks/time", t, job="weekly_backup", day="SAT", time="08:15")
    assert seen[-1] == ("weekly_backup", "SAT", "08:15")
    c.cookies.clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    kt = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    assert _post(c, "/settings/tasks/job", kt, job="daily_digest").status_code == 403
    assert _post(c, "/settings/tasks/time", kt, job="daily_digest", time="06:00").status_code == 403


def test_relaunch_waits_for_the_old_app_then_starts_the_new_one(modules, monkeypatch):
    rb = modules("restore_backup")
    started = []
    monkeypatch.setattr(rb, "relaunch_web", lambda port, lan=False: started.append((port, lan)))
    alive = iter([True, True, False])
    monkeypatch.setattr(rb, "_alive", lambda pid: next(alive))
    monkeypatch.setattr(rb.time, "sleep", lambda s: None)
    assert rb.relaunch_after("123", "8601", lan=True) and started == [("8601", True)]
    monkeypatch.setattr(rb, "_alive", lambda pid: True)
    monkeypatch.setattr(rb, "_wait", lambda pred, seconds, step=0.5: False)
    assert not rb.relaunch_after("123", "8601") and len(started) == 1, "never two apps on one port"


def test_a_container_never_installs_an_update_from_inside(data, modules, monkeypatch):
    c, t, md = data
    aa = modules("admin_actions")
    monkeypatch.setenv("MITRAHOME_CONTAINER", "1")
    upd = modules("updater")
    monkeypatch.setattr(upd, "check", lambda quiet=True: ("0.1", {"version": "9.9.9"}, True))
    _post(c, "/settings/update", t, op="check")
    page = _page(c)
    assert "9.9.9 is available" in page and "Update to 9.9.9" not in page
    assert "docker compose build" in page and "replacing the image" in page

    def boom(*a, **k):
        raise AssertionError("an update must not run inside a container")
    monkeypatch.setattr(aa.subprocess, "run", boom)
    again = []
    monkeypatch.setattr(modules("restore_backup"), "start_relaunch", lambda port, lan=False: again.append(port))
    _post(c, "/settings/update", t, op="go")
    assert "did not finish" in _page(c) and "docker compose build" in _page(c) and not again


def test_onboard_update_refuses_in_a_container():
    import os
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, str(root / "onboard.py"), "update", "--yes"], cwd=root, capture_output=True, text=True,
                       timeout=60, stdin=subprocess.DEVNULL, env={**os.environ, "MITRAHOME_CONTAINER": "1"})
    assert r.returncode == 1 and "docker compose build" in r.stdout
