"""The first run in the web app (data/setup_data.py, /setup): a new install opens the setup, every step is checked in
plain language, PINs never reach the draft, "Set everything up" builds the household through setup_interview.finish,
and the open-on-this-PC session ends once someone has a PIN. Also: the first PIN set from Settings in open mode."""
import importlib
import json
import re

import pytest

from conftest import bind, copy_template, q

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

PIN, KID_PIN = "4821", "1357"


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    """A template copy with NO family set up and no database, and the web app bound to it."""
    r = copy_template(tmp_path_factory.mktemp("ws") / "t")
    for f in ("config/family.json", "data/family.db"):
        (r / f).unlink(missing_ok=True)
    bind(r)
    app_mod = importlib.import_module("webapp.app")
    importlib.import_module("webapp.sessions").clear()
    app_mod.LOCAL_HOSTS = app_mod.LOCAL_HOSTS | {"testclient"}  # open mode (no PIN yet) is for the PC's own browser
    return r, TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)


def _csrf(html):
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def _step(c, token, step, op="next", **data):
    return c.post("/setup", data={"op": op, "step": str(step), **data}, headers={"X-CSRF-Token": token})


def test_new_install_walks_through_setup_and_ends_open_mode(fresh):
    root, c = fresh
    r = c.get("/chat")
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    r = c.get("/setup")
    assert r.status_code == 200 and "Welcome to" in r.text and "Step 1 of 6" in r.text and "Get started" in r.text
    assert "fa_session" in r.headers.get("set-cookie", ""), "open on this PC: the page hands out a session for its token"
    token = _csrf(r.text)
    assert token
    assert c.post("/setup", data={"op": "next", "step": "0"}).status_code == 403, "no token, no change"
    assert "accept the rules" in _step(c, token, 0).text
    r = _step(c, token, 0, accept="1")
    assert "Step 2 of 6" in r.text and "Who lives with you, and where?" in r.text
    family = dict(family_name="The <b>Web</b> family", country="US", place="Austin", state="TX", climate="mild", currency="usd")
    people = dict(people="Alex, adult, March 14 1980\nSam", name_1="Sam", role_1="child", papers="Alexander Q Web")
    # every step on the screen is still checked, each with its own sentence; a refused screen keeps what was typed
    r = _step(c, token, 1, **{**family, **people, "family_name": "  "})
    assert "Give the family a name" in r.text and "Step 2 of 6" in r.text and "Austin" in r.text
    assert "three-letter" in _step(c, token, 1, **{**family, **people, "currency": "DOLLARS"}).text
    assert "Add at least one adult" in _step(c, token, 1, **{**family, "people": "Sam, child"}).text
    r = _step(c, token, 1, op="check", **{**family, "people": "Alex, adult, March 14 1980\nSam"})
    assert "Here is what I understood" in r.text and 'name="role_1"' in r.text and "March 14, 1980" in r.text
    assert "Step 2 of 6" in r.text, "checking the people does not move on"
    r = _step(c, token, 1, **family, **people)
    assert "Step 3 of 6" in r.text and "Your answers so far" in r.text
    r = _step(c, token, 2, op="goto", to="1")  # "Change" in Your answers so far
    assert "Step 2 of 6" in r.text and "How to fill it in" in r.text
    assert "Step 2 of 6" in _step(c, token, 1, op="goto", to="4").text, "never jumps ahead of the screen you are on"
    assert "Step 3 of 6" in _step(c, token, 1, **family, **people).text
    home = dict(tenure="own", cars="2019 Honda CR-V", trad_0="1", trad_2="1", trad_other="Hindu (Telugu)", lookup="1")
    assert "short name" in _step(c, token, 2, **{**home, "trad_other": "http://x.example"}).text
    assert "make and model" in _step(c, token, 2, **{**home, "cars": "Honda"}).text
    r = _step(c, token, 2, **home)
    assert "Step 4 of 6" in r.text and "Hindu, Christian, Hindu (Telugu)" in r.text
    assert "Read your papers" in r.text and "How your privacy is protected" in r.text and "What an AI does here" in r.text,         "the AI has a screen of its own that says what it does and how the privacy is kept"
    assert 'hx-post="/settings/ai"' in r.text and "Without one:" in r.text
    r = _step(c, token, 3)  # Continue with No AI
    assert "Step 5 of 6" in r.text and "Who signs in?" in r.text
    assert "4 to 64 characters" in _step(c, token, 4, on="1", pin_Alex="12").text
    r = _step(c, token, 4, on="1", pin_Alex=PIN, pin_Sam=KID_PIN)
    assert "Step 6 of 6" in r.text and "Set everything up" in r.text and "&lt;b&gt;Web&lt;/b&gt;" in r.text
    assert "What happens next" in r.text and "<dt>Cars</dt><dd>2019 Honda CR-V</dd>" in r.text and "<dt>PINs</dt>" in r.text
    assert "<dt>AI</dt>" in r.text, "the summary names the AI choice"
    assert r.text.count('"op": "goto"') == 4, "a Change button for every finished screen"
    draft = (root / "config" / "setup_draft.json").read_text(encoding="utf-8")
    assert PIN not in draft and KID_PIN not in draft
    assert "Saved" in _step(c, token, 5, op="later").text
    r = c.post("/setup/finish", headers={"X-CSRF-Token": token})
    assert r.headers.get("hx-redirect") == "/setup/done", r.text[:300]
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    assert fam["family_name"] == "The <b>Web</b> family" and fam["household"]["tenure"] == "own"
    assert [(m["name"], m["role"]) for m in fam["members"]] == [("Alex", "adult"), ("Sam", "child")]
    assert fam["traditions"] == ["Hindu", "Christian", "Hindu (Telugu)"] and fam["traditions_lookup"] is True
    assert {u["name"]: u["role"] for u in fam["dashboard_users"]} == {"Alex": "adult", "Sam": "limited"}
    assert PIN not in json.dumps(fam) and fam["privacy"]["paper_names"] == ["Alexander Q Web"]
    assert q(root, "select make, model from vehicles") == [("Honda", "CR-V")]
    assert not (root / "config" / "setup_draft.json").exists()
    r = c.get("/setup/done")
    assert r.status_code == 200 and "You are set up" in r.text and 'href="/login"' in r.text, "PINs on: sign in next"
    assert c.get("/chat").status_code == 303 and c.get("/chat").headers["location"] == "/login", "open session ended"
    assert c.post("/setup/finish", headers={"X-CSRF-Token": token}).status_code == 403
    # a re-run from Settings: adults only, prefilled, and Cancel leaves everything as it was
    assert c.post("/login", data={"name": "Sam", "pin": KID_PIN}).status_code == 303
    assert c.get("/setup").status_code == 403
    c.cookies.clear()
    assert c.post("/login", data={"name": "Alex", "pin": PIN}).status_code == 303
    r = c.get("/setup")
    assert r.status_code == 200 and "Setting up" in r.text and "Cancel and go back" in r.text
    assert 'href="/setup"' in c.get("/settings?group=household").text
    token = _csrf(r.text)
    _step(c, token, 0, accept="1")
    r = c.post("/setup/cancel", headers={"X-CSRF-Token": token})
    assert r.headers["hx-redirect"] == "/settings?group=household"
    assert not (root / "config" / "setup_draft.json").exists()


def test_first_pin_from_settings_in_open_mode(root, modules, monkeypatch):
    """An install with nobody holding a PIN: Settings > Agent can set the first one, which ends the open session."""
    config = modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"})  # open mode is for the PC's own browser
    fam = dict(config.family())
    fam.pop("dashboard_users", None)
    config.write_json(root / "config" / "family.json", fam)
    started = []
    monkeypatch.setattr(modules("restore_backup"), "start_relaunch", lambda port, lan=False: started.append((port, lan)))
    monkeypatch.setattr(modules("maintenance_data"), "close_soon", lambda seconds=2.0: None)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    r = c.get("/settings?group=agent")
    assert r.status_code == 200 and "Sign-in PINs" in r.text
    token = _csrf(r.text)
    r = c.post("/settings/pin", data={"who": "Alex", "pin": PIN, "again": PIN, "current": ""},
               headers={"X-CSRF-Token": token})
    assert started == [(8601, True)], "the first PIN opens the app to phones: no second restart step"
    assert 'data-wait-back="/login?pin=changed"' in r.text and "phones and walls" in r.text, r.text[:300]
    users = config.family().get("dashboard_users") or json.loads((root / "config" / "family.json").read_text())["dashboard_users"]
    assert [u["name"] for u in users] == ["Alex"]
    assert c.get("/settings").status_code == 303, "the open session ended with the first PIN"


def test_first_pin_with_phones_switched_off_only_signs_in_again(root, modules, monkeypatch):
    config = modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"})
    fam = dict(config.family())
    fam.pop("dashboard_users", None)
    fam["phones"] = {"lan": False}
    config.write_json(root / "config" / "family.json", fam)
    started = []
    monkeypatch.setattr(modules("restore_backup"), "start_relaunch", lambda port, lan=False: started.append((port, lan)))
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    token = _csrf(c.get("/settings?group=agent").text)
    r = c.post("/settings/pin", data={"who": "Alex", "pin": PIN, "again": PIN, "current": ""},
               headers={"X-CSRF-Token": token})
    assert not started and r.headers.get("hx-redirect") == "/login?pin=changed"


def test_a_draft_from_the_ten_step_setup_resumes_on_the_right_screen(modules):
    sd = modules("setup_data")
    si = modules("setup_interview")
    assert [s for _, secs in sd.SCREENS for s in secs if s != "AI"] + ["AI"] != [] and \
        sorted(s for _, secs in sd.SCREENS for s in secs) == sorted(si.SECTIONS), "every step is on exactly one screen"
    names = si.SECTIONS
    assert sd.screen_of_step(names.index("Welcome")) == 0
    assert sd.screen_of_step(names.index("AI")) == 1, "the AI is optional: an old draft does not resume on its screen"
    assert sd.screen_of_step(names.index("People")) == 1 and sd.screen_of_step(names.index("Traditions")) == 1
    assert sd.screen_of_step(names.index("Home")) == 2 and sd.screen_of_step(names.index("Cars")) == 2
    assert sd.screen_of_step(names.index("Logins")) == 4 and sd.screen_of_step(names.index("Finish")) == 5
