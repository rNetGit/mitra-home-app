"""Settings > Connections in the web app (data/connections_data.py): AI provider and key, Telegram bot, Google. Adults
only, CSRF like every change, secrets write-only and never sent back, keys / tokens / the Google client file / sign-ins
only from a browser on this PC. No network: Telegram's and the AI's checks are replaced in these tests."""
import json
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

KEY = "sk-test-0123456789abcdefWXYZ"
TOKEN = "123456789:AAtesttokenvalue_ABCDEFGHIJKLMNOPQRS"
CLIENT = {"installed": {"client_id": "test-client.apps.googleusercontent.com", "client_secret": "test-client-secret",
                        "redirect_uris": ["http://localhost"]}}


@pytest.fixture()
def conn(root, modules, monkeypatch):
    """(client, app module, local(on)) with an adult Ann (1234) and a limited Kid (0000) signed in as Ann."""
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    aa = modules("admin_actions")
    monkeypatch.setattr(aa, "test_ai", lambda: (True, "pong"))
    ct = modules("chat_telegram")
    monkeypatch.setattr(ct, "check", lambda tok: (True, "@family_test_bot") if tok == TOKEN else (False, "Telegram said no."))
    modules("connections_data").forget()
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})

    def local(on=True):
        if on:
            monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"})
        else:
            monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"127.0.0.1"})
    local(False)
    return c, app_mod, local


def _token(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/settings?group=connections").text).group(1)


def _post(c, path, csrf, **data):
    return c.post(path, data=data, headers={"X-CSRF-Token": csrf})


def _flash(c):
    return c.get("/settings?group=connections").text


def test_ai_key_only_from_this_pc_and_never_shown(conn, root, modules):
    c, _, local = conn
    t = _token(c)
    page = c.get("/settings?group=connections").text
    assert 'name="key"' not in page and "only on this PC" in page, "a phone gets no key box"
    assert "Recommended: an OpenRouter key" in page and 'href="https://openrouter.ai/settings/keys"' in page, "how to get a key"
    assert '<details class="rblock fold ai-guide">' in page, "folded in Settings"
    assert "key named Mitra Home" in page, "the brand fills in"
    r = _post(c, "/settings/ai", t, provider="anthropic", key=KEY, consent="1")
    assert r.headers["hx-redirect"] == "/settings?group=connections"
    assert "only on this PC" in _flash(c)
    assert (modules("config").family().get("ai") or {}).get("provider") != "anthropic"
    local()
    assert 'name="key"' in c.get("/settings?group=connections").text
    _post(c, "/settings/ai", t, provider="anthropic", key=KEY)
    assert "Tick the box" in _flash(c), "consent is required for a keyed provider"
    _post(c, "/settings/ai", t, provider="anthropic", key=KEY, consent="1")
    page = _flash(c)
    assert "Saved: Anthropic" in page and "Test call: pong" in page
    assert KEY not in page and KEY[-4:] in page, "only the last four characters come back"
    assert (modules("config").family().get("ai") or {})["provider"] == "anthropic"
    assert "ai-guide" not in c.get("/settings?group=connections").text, "no guide once a key is saved"
    assert KEY not in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    _post(c, "/settings/ai/test", t)
    assert "Test call: pong" in _flash(c)
    _post(c, "/settings/ai", t, provider="none")
    assert "Saved: No AI" in _flash(c)



def test_ai_signed_in_cli_choices(conn, modules, monkeypatch):
    """The Claude CLI can be chosen here: found on this PC first, consent ticked, scheduled runs a choice of their own;
    no test call on Save (a CLI can take a minute), the Test button does it. Codex and Gemini CLIs are not offered (audit
    2026-10-28: Codex's read-only sandbox still reads any file)."""
    c, _, _ = conn
    aa, config = modules("admin_actions"), modules("config")
    t = _token(c)
    page = c.get("/settings?group=connections").text
    assert 'value="claude_cli"' in page and 'value="codex_cli"' not in page and 'value="gemini_cli"' not in page
    assert "<code>claude</code> was not found" in page or "Found <code>claude</code>" in page
    _post(c, "/settings/ai", t, provider="codex_cli", consent="1")
    assert (config.family().get("ai") or {}).get("provider") != "codex_cli", "Codex cannot be picked from a phone or a form"
    found = {}
    monkeypatch.setattr(aa, "cli_found", lambda p: found.get(p, ""))
    _post(c, "/settings/ai", t, provider="claude_cli", consent="1")
    assert "was not found on this PC" in _flash(c)
    assert (config.family().get("ai") or {}).get("provider") != "claude_cli"
    found["claude_cli"] = "/usr/local/bin/claude"
    _post(c, "/settings/ai", t, provider="claude_cli")
    assert "Tick the box" in _flash(c), "consent is required: the text goes to Anthropic"
    _post(c, "/settings/ai", t, provider="claude_cli", consent="1", unattended="1")
    page = _flash(c)
    assert "Saved: Your Claude plan" in page and "Press Test the AI now" in page and "Test call" not in page
    ai = config.family()["ai"]
    assert ai["provider"] == "claude_cli" and ai["allow_unattended_cli"] is True
    assert "Found <code>claude</code>" in page and "Test the AI now" in page
    assert re.search(r'name="unattended" value="1" checked', page)
    _post(c, "/settings/ai", t, provider="claude_cli", consent="1")
    assert config.family()["ai"]["allow_unattended_cli"] is False, "unticked = scheduled runs off again"
    _post(c, "/settings/ai/test", t)
    assert "Test call: pong" in _flash(c)


def test_ai_provider_set_outside_settings_is_shown_and_kept(conn, root, modules):
    """gemini_cli (python onboard.py only) shows as the current choice, not as the list's first entry, and Save keeps it."""
    c, _, _ = conn
    config = modules("config")
    fam = dict(config.family())
    fam["ai"] = {**(fam.get("ai") or {}), "provider": "gemini_cli", "model": ""}
    config.write_json(root / "config" / "family.json", fam)
    t = _token(c)
    page = c.get("/settings?group=connections").text
    assert re.search(r'<option value="gemini_cli" selected[^>]*>gemini_cli \(set outside this screen\)', page)
    assert not re.search(r'<option value="claude_code" selected', page)
    _post(c, "/settings/ai", t, provider="gemini_cli")
    assert "Saved: gemini_cli" in _flash(c)
    assert config.family()["ai"]["provider"] == "gemini_cli"
    _post(c, "/settings/ai", t, provider="fake")
    assert "Pick one of the providers" in _flash(c), "only the current provider may be kept"


def test_telegram_token_codes_and_unknown_ops(conn, root, modules):
    c, _, local = conn
    t = _token(c)
    _post(c, "/settings/telegram", t, op="token", token=TOKEN)
    assert "only on this PC" in _flash(c)
    local()
    _post(c, "/settings/telegram", t, op="token", token="nope")
    assert "Telegram said no." in _flash(c)
    _post(c, "/settings/telegram", t, op="token", token=TOKEN)
    page = _flash(c)
    assert "@family_test_bot" in page and TOKEN not in page and "Make a one-time code" in page
    _post(c, "/settings/telegram", t, op="code", who="Alex")
    assert "/start " in _flash(c)
    _post(c, "/settings/telegram", t, op="stop")
    assert "Stop requested" in _flash(c) and (root / "logs" / "telegram_bot.stop").exists()
    _post(c, "/settings/telegram", t, op="explode")
    assert "cannot be done here" in _flash(c)


def test_google_client_file_and_guards(conn, root, modules):
    c, _, local = conn
    t = _token(c)
    up = lambda body: c.post("/settings/google/client", content=body, headers={"X-CSRF-Token": t})  # noqa: E731
    assert up(json.dumps(CLIENT).encode()).json()["ok"] is False, "not from a phone"
    local()
    assert c.post("/settings/google/client", content=b"{}").status_code == 403, "CSRF"
    assert up(b"x" * 100_001).status_code == 413
    assert "not the .json" in up(b"\xff\xfe").json()["message"]
    assert "Desktop-app" in up(json.dumps({"web": {"client_id": "x"}}).encode()).json()["message"]
    r = up(json.dumps(CLIENT).encode())
    assert r.json()["ok"] is True
    assert "Sign in to Google" in _flash(c)
    local(False)
    _post(c, "/settings/google", t, op="sign_in")
    assert "only on this PC" in _flash(c)
    for op, words in (("sync_settings", "Pick how far ahead"), ("disconnect", "Tick the box"), ("sync_remove", "Tick the box"),
                      ("nuke", "cannot be done here")):
        _post(c, "/settings/google", t, op=op, horizon="7", reminder_days="1")
        assert words in _flash(c), op


def test_connections_need_an_adult(conn):
    c, _, _ = conn
    c.cookies.clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    for path, data in (("/settings/ai", {"provider": "none"}), ("/settings/telegram", {"op": "stop"}),
                       ("/settings/google", {"op": "disconnect", "sure": "1"}), ("/settings/ai/test", {})):
        assert _post(c, path, t, **data).status_code == 403, path
    assert c.post("/settings/google/client", content=b"{}", headers={"X-CSRF-Token": t}).status_code == 403
    assert c.get("/settings/google/preview").status_code == 403


def test_setup_ai_step_shows_the_ai_form(conn, modules):
    c, _, local = conn
    local()
    si, sd = modules("setup_interview"), modules("setup_data")
    a = si.defaults()
    a["screen"] = next(i for i, (_, secs) in enumerate(sd.SCREENS) if "AI" in secs)  # the AI screen ("Read your papers")
    si.save_draft(a)
    r = c.get("/setup")
    assert r.status_code == 200 and 'hx-post="/settings/ai"' in r.text and '"from": "setup"' in r.text
    assert '<details class="rblock fold ai-guide" open>' in r.text, "the first run shows how to get a key, open"
    assert r.text.index("ai-guide") < r.text.index('hx-post="/settings/ai"'), "the steps come before the form"
    t = re.search(r'name="csrf-token" content="([^"]+)"', r.text).group(1)
    r = _post(c, "/settings/ai", t, provider="none", **{"from": "setup"})
    assert r.headers["hx-redirect"] == "/setup"
    assert "Saved: No AI" in c.get("/setup").text
    si.clear_draft()


def test_bank_sync_card_token_only_from_this_pc_accounts_pull_forget(conn, root, modules, monkeypatch):
    """Settings > Connections > Bank sync (SimpleFIN): the token box only on this PC, ticked accounts, Pull now, Forget
    with a tick box; the access URL never comes back; a limited person gets 403."""
    import test_bank_sync as tb
    c, _, local = conn
    bs = modules("bank_sync")
    bs.forget()
    tb.fake_http(monkeypatch, bs)
    t = _token(c)
    page = c.get("/settings?group=connections").text
    assert "Bank sync (SimpleFIN)" in page and 'name="token"' not in page.split('id="conn-bank"')[1]
    assert "only on this PC" in page.split('id="conn-bank"')[1], "a phone gets no token box"
    _post(c, "/settings/bank", t, op="token", token=tb.TOKEN)
    assert "only on this PC" in _flash(c) and not bs.configured()
    local()
    page = c.get("/settings?group=connections").text
    assert 'name="token"' in page.split('id="conn-bank"')[1]
    _post(c, "/settings/bank", t, op="token", token="nope")
    assert "not a SimpleFIN setup token" in _flash(c)
    _post(c, "/settings/bank", t, op="token", token=tb.TOKEN)
    page = _flash(c)
    assert "Connected to SimpleFIN: 2 account(s)" in page and "Everyday Checking x4477" in page and "Pull now" in page
    bank_card = page.split('id="conn-bank"')[1]
    assert 'data-check-all="1">Select all' in bank_card and 'data-check-all="0">Unselect all' in bank_card
    assert tb.ACCESS not in page and "sfsecret" not in page
    _post(c, "/settings/bank", t, op="pull")
    assert "tick at least one account" in _flash(c)
    r = c.post("/settings/bank", data={"op": "pick", "acct": ["ACT-chk", "bogus"]}, headers={"X-CSRF-Token": t})
    assert r.headers["hx-redirect"] == "/settings?group=connections"
    page = _flash(c)
    assert "1 account(s) will be pulled" in page and 'value="ACT-chk" checked' in page
    _post(c, "/settings/bank", t, op="pull")
    page = _flash(c)
    assert "Pulled 2 new transaction(s)" in page and "Last good pull" in page
    _post(c, "/settings/bank", t, op="forget")
    assert "Tick the box" in _flash(c) and bs.configured()
    _post(c, "/settings/bank", t, op="forget", sure="1")
    page = _flash(c)
    assert "forgotten" in page and not bs.configured() and 'name="token"' in page.split('id="conn-bank"')[1]
    _post(c, "/settings/bank", t, op="explode")
    assert "cannot be done here" in _flash(c)
    log = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "bank_setup" in log and "bank_pull" in log and "bank_forget" in log and "sfsecret" not in log
    assert c.post("/settings/bank", data={"op": "pull"}).status_code == 403, "CSRF"
    c.cookies.clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    assert _post(c, "/settings/bank", t, op="pull").status_code == 403
    assert "Bank sync" not in c.get("/").text
