"""The daily look for new versions (data/update_notice.py): once a day, off = no call, the state file, the Inbox item
(source "update": Update now through maintenance_data.update -> admin_actions, Later = a week), the Today / Brief line
for adults only, the health row after 7 days of failures, the Settings switch, and the daily task step.
updater.check is always a fake: these tests never reach the network."""
import datetime as dt
import io
import json
import re

import pytest

from conftest import db

ADULT = {"name": "Alex", "role": "adult"}
CHILD = {"name": "Sam", "role": "child"}
TODAY = dt.date(2026, 10, 15)


@pytest.fixture()
def un(root, modules, monkeypatch):
    """update_notice of this copy with no state file, the daily look on, and a real updater.check that fails loudly."""
    m = modules("update_notice")
    upd = modules("updater")
    m._file().unlink(missing_ok=True)
    _setting(modules, None)

    def boom(*a, **k):
        raise AssertionError("the network must never be reached in tests")
    monkeypatch.setattr(upd, "latest_release", boom)
    monkeypatch.setattr(upd, "site_release", lambda platform=None: None)  # nor the public site
    monkeypatch.setattr(upd, "current_version", lambda: "1.0.0")
    yield m
    m._file().unlink(missing_ok=True)
    _setting(modules, None)


def _setting(modules, on):
    config = modules("config")
    fam = dict(config.family())
    if on is None:
        fam.pop("updates", None)
    else:
        fam["updates"] = {"daily_check": on}
    config.write_json(modules("paths").CONFIG / "family.json", fam)


class Fake:
    """Stands in for updater.check(quiet=True): counts calls, returns a release or a failure."""

    def __init__(self, version="1.2.0", notes="## Added\n- **Daily** look for [new versions](http://x)\n", fail=False):
        self.calls, self.version, self.notes, self.fail = 0, version, notes, fail

    def __call__(self, quiet=False):
        assert quiet is True
        self.calls += 1
        if self.fail:
            return "1.0.0", None, False
        return "1.0.0", {"version": self.version, "notes": self.notes}, self.version != "1.0.0"


def _proposals(root, source="update"):
    con = db(root)
    try:
        return con.execute("SELECT id, dedupe_key, status, summary, detail, payload, until FROM proposals WHERE source=?",
                           (source,)).fetchall()
    finally:
        con.close()


def _clear_proposals(root):
    con = db(root)
    with con:
        con.execute("DELETE FROM proposals WHERE source='update'")
    con.close()


def test_daily_look_once_a_day_and_state_file(un):
    f = Fake()
    assert un.daily(TODAY, check=f) == "newer"
    assert un.daily(TODAY, check=f) == "done today"
    assert f.calls == 1
    st = json.loads(un._file().read_text(encoding="utf-8"))
    assert st["latest"] == "1.2.0" and st["newer"] is True and st["last_error"] == "" and st["checked_at"].startswith("2026-10-15")
    assert st["notes"] == "Added · Daily look for new versions", st["notes"]  # plain text, links dropped
    assert un.daily(TODAY + dt.timedelta(days=1), check=f) == "newer" and f.calls == 2
    assert un.available() == {"version": "1.2.0", "notes": "Added · Daily look for new versions", "source": "app", "url": ""}


def test_off_means_no_call_and_no_notice(un, modules):
    f = Fake()
    assert un.daily(TODAY, check=f) == "newer"
    _setting(modules, False)
    f2 = Fake()
    assert un.daily(TODAY + dt.timedelta(days=1), check=f2) == "off" and f2.calls == 0
    assert un.available() is None and un.notice(ADULT) is None


def test_up_to_date_and_already_updated(un, modules, monkeypatch):
    assert un.daily(TODAY, check=Fake(version="1.0.0")) == "up to date"
    assert un.available() is None
    un.daily(TODAY + dt.timedelta(days=1), check=Fake(version="1.2.0"))
    monkeypatch.setattr(modules("updater"), "current_version", lambda: "1.2.0")  # the family updated since
    assert un.available() is None


def test_a_failure_is_silent_for_a_week_then_one_health_row(un, modules):
    assert un.daily(TODAY, check=Fake()) == "newer"
    for n in range(1, 9):
        assert un.daily(TODAY + dt.timedelta(days=n), check=Fake(fail=True)) == "failed"
    st = un.state()
    assert st["latest"] == "1.2.0" and st["failing_since"].startswith("2026-10-16") and st["last_error"]
    assert un.health_row(TODAY + dt.timedelta(days=7)) is None  # 6 days of failures
    note = un.health_row(TODAY + dt.timedelta(days=8))
    assert note and note.startswith("could not look for new versions for 7 days")
    health = modules("health")
    rows = [r for r in health.checks(TODAY + dt.timedelta(days=8)) if r["name"] == "New versions"]
    assert rows and rows[0]["status"] == "warn" and rows[0]["here"] == "Settings > Data > Updates"
    assert not [r for r in health.checks(TODAY + dt.timedelta(days=3)) if r["name"] == "New versions"]
    un.daily(TODAY + dt.timedelta(days=9), check=Fake())  # a good look clears it
    assert un.health_row(TODAY + dt.timedelta(days=30)) is None


def test_an_exception_in_the_check_never_escapes(un):
    def broken(quiet=False):
        raise OSError("offline")
    assert un.daily(TODAY, check=broken) == "failed"
    assert un.state()["last_error"] == "OSError"


def test_inbox_item_later_and_update_now(un, root, modules, monkeypatch):
    pr = modules("proposals")
    md = modules("maintenance_data")
    _clear_proposals(root)
    un.daily(TODAY, check=Fake())
    pr.sync(today=TODAY)
    rows = _proposals(root)
    assert len(rows) == 1
    pid, key, status, summary, detail, payload, _ = rows[0]
    assert key == "update:1.2.0" and status == "open" and summary.endswith("1.2.0 is available")
    assert "Daily look" in detail and "data/" not in summary and json.loads(payload) == {"version": "1.2.0"}
    con = db(root)
    assert list(pr.get(con, pid)["options"]) == ["update", "later"]
    con.close()
    pr.sync(today=TODAY)
    assert len(_proposals(root)) == 1  # idempotent

    calls = []
    monkeypatch.setattr(modules("admin_actions"), "update_now", lambda user: (calls.append(user) or (False, "network down")))
    assert pr.decide(CHILD, pid, "update", today=TODAY)[0] is False and not calls
    ok, msg = pr.decide(ADULT, pid, "update", today=TODAY)
    assert ok is False and "did not finish" in msg and calls == [ADULT]
    assert _proposals(root)[0][2] == "open"  # a failed update leaves the item where it was

    ok, msg = pr.decide(ADULT, pid, "later", today=TODAY)
    assert ok and _proposals(root)[0][2] == "snoozed" and _proposals(root)[0][6] == (TODAY + dt.timedelta(days=7)).isoformat()
    pr.restore(ADULT, pid)

    monkeypatch.setattr(modules("admin_actions"), "update_now", lambda user: (True, "ok"))
    ok, msg = pr.decide(ADULT, pid, "update", today=TODAY)
    assert ok and msg.startswith("Updated.") and _proposals(root)[0][2] == "done"
    assert md._UPDATE["newer"] is None  # the Settings card forgets its cached answer, as after Settings > Update
    _clear_proposals(root)


def test_item_expires_after_the_update_and_is_never_offered_in_chat(un, root, modules, monkeypatch):
    pr = modules("proposals")
    _clear_proposals(root)
    un.daily(TODAY, check=Fake())
    pr.sync(today=TODAY)
    assert "update" in modules("chat_core").PC_ONLY
    monkeypatch.setattr(modules("updater"), "current_version", lambda: "1.2.0")
    pr.sync(today=TODAY)
    assert _proposals(root)[0][2] == "expired"
    _clear_proposals(root)


def test_notice_is_for_adults_only_and_follows_the_inbox_item(un, root, modules):
    pr = modules("proposals")
    _clear_proposals(root)
    un.daily(TODAY, check=Fake())
    assert un.notice(CHILD) is None and un.notice({"name": "G", "role": "limited"}) is None and un.notice(None) is None
    assert un.notice(ADULT)["text"].endswith("1.2.0 is available.")
    pr.sync(today=TODAY)
    pid = _proposals(root)[0][0]
    pr.decide(ADULT, pid, "later", today=TODAY)
    con = db(root)
    try:
        assert un.notice(ADULT, con) is None  # snoozed: no line either
    finally:
        con.close()
    _clear_proposals(root)


def test_settings_switch_is_adults_only_and_audited(un, modules):
    aa = modules("admin_actions")
    assert aa.update_check_set(CHILD, False)[0] is False
    assert un.enabled() is True
    ok, msg = aa.update_check_set(ADULT, False)
    assert ok and un.enabled() is False
    assert any(r["what"] == "update_check_set" and r["detail"] == "off" for r in aa.what_changed())
    assert aa.update_check_set(ADULT, True)[0] and un.enabled() is True
    d = modules("maintenance_data").daily_check()
    assert d["on"] is True and d["host"] == "api.github.com"


def test_daily_task_runs_the_look_before_the_inbox_and_ignores_its_failure(un, modules, monkeypatch):
    rt = modules("run_task")
    cmds = []

    def fake_run(cmd, lf, timeout=1800):
        cmds.append([str(c) for c in cmd])
        return "update_notice.py" not in " ".join(str(c) for c in cmd)  # the look fails; the task must not
    monkeypatch.setattr(rt, "run", fake_run)
    monkeypatch.setattr(rt, "claude_bin", lambda: None)
    monkeypatch.setattr(rt, "bank_sync", lambda lf: True)
    assert rt.daily_digest(io.StringIO()) is True
    names = [" ".join(c[1:3]) for c in cmds]
    look = names.index("data/update_notice.py daily")
    assert look < names.index("data/proposals.py sync")


def test_web_updates_card_switch_and_today_line(un, root, modules):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    sessions = modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    _clear_proposals(root)
    un.daily(TODAY, check=Fake())
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    try:
        assert c.post("/login", data={"name": "Ann", "pin": "1234"}).status_code == 303
        home = c.get("/").text
        assert "1.2.0 is available." in home
        token = re.search(r'name="csrf-token" content="([^"]+)"', home).group(1)
        page = c.get("/settings?group=data").text
        assert "Check for new versions every day" in page and "api.github.com" in page and "Update to 1.2.0" in page
        assert "About " in page and "data-about" in page and "rnetgit.github.io/mitra-home/install.html" in page and "rnetgit.github.io/mitra-home/source.html" in page
        r = c.post("/settings/update", data={"op": "daily"}, headers={"X-CSRF-Token": token})  # unticked = off
        assert r.status_code == 200 and un.enabled() is False
        assert "1.2.0 is available." not in c.get("/").text
        c.post("/settings/update", data={"op": "daily", "on": "1"}, headers={"X-CSRF-Token": token})
        assert un.enabled() is True
        un.daily(TODAY + dt.timedelta(days=3), check=Fake(fail=True), site=FakeSite())  # only the public site answers
        modules("proposals").sync()
        home = c.get("/").text
        assert "1.3.0 is available." in home and "site</a>" in home and "Download it from the" in home
        page = c.get("/settings?group=data").text
        assert "Open the download page for 1.3.0" in page and "Update to 1.3.0" not in page
        c.post("/logout", headers={"X-CSRF-Token": token})
        c.cookies.clear()
        assert c.post("/login", data={"name": "Kid", "pin": "0000"}).status_code == 303
        assert "is available." not in c.get("/").text
    finally:
        sessions.clear()
        _clear_proposals(root)


class FakeSite:
    """Stands in for updater.site_release(): the newest public release with an installer for this system."""

    def __init__(self, version="1.3.0", notes="Remote and office days on the Calendar"):
        self.calls, self.version, self.notes = 0, version, notes

    def __call__(self, platform=None):
        self.calls += 1
        return {"version": self.version, "tag": f"mitra-home-{self.version}", "notes": self.notes,
                "url": "https://rnetgit.github.io/mitra-home/install.html"}


def test_a_pc_that_cannot_read_the_app_repo_hears_about_a_public_release(un, root, modules):
    site = FakeSite()
    assert un.daily(TODAY, check=Fake(fail=True), site=site) == "newer" and site.calls == 1
    st = un.state()
    assert (st["latest"], st["source"], st["url"], st["last_error"], st["failing_since"]) ==         ("1.3.0", "site", "https://rnetgit.github.io/mitra-home/install.html", "", "")
    a = un.available()
    assert a["source"] == "site" and a["url"].endswith("install.html")
    n = un.notice(ADULT)
    assert n["href"].endswith("install.html") and "1.3.0 is available" in n["text"]
    assert un.notice(CHILD) is None
    modules("proposals").sync()
    (row,) = _proposals(root)
    assert row[3].endswith("1.3.0 is available") and "Download the new installer" in row[4]
    pl = json.loads(row[5])
    assert pl["source"] == "site" and pl["fix_link"]["href"].endswith("install.html")
    con = db(root)
    item = next(i for i in modules("proposals").items(con) if i["source"] == "update")
    con.close()
    assert list(item["options"]) == ["later"], "a site notice cannot start an update by itself"


def test_the_app_repo_wins_and_the_site_is_not_asked(un):
    site = FakeSite()
    assert un.daily(TODAY, check=Fake(), site=site) == "newer" and site.calls == 0
    st = un.state()
    assert st["source"] == "app" and st["url"] == ""
    assert un.notice(ADULT)["href"] == ""


def test_a_site_release_not_newer_than_this_install_is_quiet(un):
    assert un.daily(TODAY, check=Fake(fail=True), site=FakeSite(version="1.0.0")) == "up to date"
    assert un.available() is None


def test_nothing_anywhere_is_still_a_silent_failure(un):
    assert un.daily(TODAY, check=Fake(fail=True), site=lambda platform=None: None) == "failed"
    assert un.state()["failing_since"]


def test_site_release_picks_the_newest_release_with_an_installer_for_this_system(modules, monkeypatch):
    upd = modules("updater")
    rels = [
        {"tag_name": "mitra-home-0.139.0", "assets": [{"name": "MitraHome-Setup-0.139.0.exe"}], "body": "win only"},
        {"tag_name": "mitra-home-0.138.0", "assets": [{"name": "MitraHome-Setup-0.138.0.exe"}, {"name": "MitraHome-0.138.0-mac-arm64.dmg"}], "body": "both"},
        {"tag_name": "mitra-home-0.140.0", "assets": [{"name": "MitraHome-Setup-0.140.0.exe"}], "draft": True},
        {"tag_name": "not-a-version", "assets": [{"name": "x.exe"}]},
    ]

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(rels).encode()

    monkeypatch.setattr(upd._OPENER, "open", lambda req, timeout=10: R())
    assert upd.site_release("win32")["version"] == "0.139.0"
    assert upd.site_release("darwin")["version"] == "0.138.0", "no Mac installer in 0.139.0: not offered to a Mac"
    assert upd.site_release("linux") is None
    assert upd.site_release("win32")["url"] == "https://rnetgit.github.io/mitra-home/install.html"

    def boom(req, timeout=10):
        raise OSError("offline")
    monkeypatch.setattr(upd._OPENER, "open", boom)
    assert upd.site_release("win32") is None
