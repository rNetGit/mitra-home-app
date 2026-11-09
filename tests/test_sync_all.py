"""One Sync (data/sync_all.py): which steps a household has, one failing step not stopping the rest, progress and the
last result in logs/sync_all.json, a dead run reported as stopped, and the Sync now button on Today."""
import json
import re
import sys

import pytest

OK = [sys.executable, "-c", "print('3 new')"]
BAD = [sys.executable, "-c", "import sys; print('boom'); sys.exit(2)"]


@pytest.fixture()
def sa(modules):
    return modules("sync_all")


def test_steps_follow_what_the_household_set_up(sa, modules):
    config = modules("config")
    with config.family_edit() as c:
        c.pop("drive_path", None)
        c["gmail"] = {"enabled": False}
        c["mail_folder"] = {"enabled": False}
    assert [k for k, _, _ in sa.steps() if k != "bank"] == []
    with config.family_edit() as c:
        c["drive_path"] = "G:/My Drive/Mitra"
        c["mail_folder"] = {"enabled": True}
    assert [k for k, _, _ in sa.steps() if k != "bank"] == ["drive", "mail"]


def test_a_failing_step_does_not_stop_the_next(sa, monkeypatch):
    monkeypatch.setattr(sa, "steps", lambda: [("a", "Drive", OK), ("b", "Mail", BAD), ("c", "Gmail", OK)])
    assert sa.run() is False
    s = sa.read()
    assert s["running"] is False and s["ok"] is False and s["finished"]
    assert s["lines"][0] == "Drive: 3 new"
    assert s["lines"][1].startswith("Mail: did not finish") and "boom" in s["lines"][1]
    assert s["lines"][2] == "Gmail: 3 new"
    assert sa.recent() is not None


def test_a_dead_run_is_reported_as_stopped(sa):
    sa.STATE.parent.mkdir(parents=True, exist_ok=True)
    sa.STATE.write_text(json.dumps({"running": True, "step": "Bank", "lines": [], "started": "2026-10-24T08:00:00",
                                    "finished": "", "ok": True}), encoding="utf-8")
    s = sa.read()
    assert s["running"] is False and s["ok"] is False and s["lines"][-1] == "Stopped before it finished."


def test_start_says_so_when_there_is_nothing_to_sync(sa, monkeypatch):
    monkeypatch.setattr(sa, "steps", lambda: [])
    ok, msg = sa.start()
    assert ok is False and "Nothing to sync" in msg


pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


def test_sync_now_button_starts_the_run_and_shows_the_result(root, modules, monkeypatch):
    auth, config, sa = modules("auth"), modules("config"), modules("sync_all")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")}]
    fam["drive_path"] = "G:/My Drive/Mitra"
    config.write_json(root / "config" / "family.json", fam)
    started = []
    monkeypatch.setattr(sa, "start", lambda: (started.append(1) or True, "Syncing: google drive inbox."))
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/").text
    assert "Pull the Drive inbox and the mail folder now" in page and '"op": "syncall"' in page
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    r = c.post("/today/act", data={"op": "syncall", "who": ""}, headers={"X-CSRF-Token": token, "HX-Request": "true"})
    assert r.status_code in (200, 204, 303) and started == [1]
    assert "Syncing: google drive inbox." in c.get("/").text
