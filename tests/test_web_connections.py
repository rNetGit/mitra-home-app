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


def test_bank_sync_page_token_only_from_this_pc_accounts_find_pull_forget(conn, root, modules, monkeypatch):
    """Settings > Bank sync (SimpleFIN, its own page since the Settings redesign): the token box only on this PC, ticked
    accounts grouped by bank, Find new accounts, Pull now, Forget with a tick box; the access URL never comes back; a
    limited person gets 403. Connections no longer carries it."""
    import test_bank_sync as tb
    c, _, local = conn
    bs = modules("bank_sync")
    bs.forget()
    tb.fake_http(monkeypatch, bs)
    t = _token(c)
    assert 'id="conn-bank"' not in c.get("/settings?group=connections").text, "bank sync left Connections"

    def page():
        return c.get("/settings?group=bank").text

    p = page()
    assert "Bank sync (SimpleFIN)" in p and 'name="token"' not in p and "only on this PC" in p, "a phone gets no token box"
    assert "Connect your banks" in p and "Find new accounts" not in p
    _post(c, "/settings/bank", t, op="token", token=tb.TOKEN)
    assert "only on this PC" in page() and not bs.configured()
    local()
    assert 'name="token"' in page()
    _post(c, "/settings/bank", t, op="token", token="nope")
    assert "not a SimpleFIN setup token" in page()
    r = _post(c, "/settings/bank", t, op="token", token=tb.TOKEN)
    assert r.headers["hx-redirect"] == "/settings?group=bank"
    p = page()
    assert "Connected to SimpleFIN: 2 account(s)" in p and "Everyday Checking" in p and "x4477" in p and "Pull now" in p
    assert "Find new accounts" in p and '<h3 class="bbank">Test Bank' in p
    assert 'data-check-all="1">Select all' in p and 'data-check-all="0">Unselect all' in p
    assert tb.ACCESS not in p and "sfsecret" not in p
    _post(c, "/settings/bank", t, op="pull")
    assert "tick at least one account" in page()
    r = c.post("/settings/bank", data={"op": "pick", "acct": ["ACT-chk", "bogus"]}, headers={"X-CSRF-Token": t})
    assert r.headers["hx-redirect"] == "/settings?group=bank"
    p = page()
    assert "1 account(s) will be pulled" in p and 'value="ACT-chk" checked' in p and "New</span>" not in p
    # a bank linked later at SimpleFIN: Find new accounts lists it as New, imports nothing
    more = tb.ACCOUNTS + [{"id": "ACT-sav", "name": "High Yield Savings ...5050", "currency": "USD", "balance": "10.00",
                           "balance-date": tb.ACCOUNTS[0]["balance-date"], "org": {"name": "Other Bank"}, "transactions": []}]
    calls = tb.fake_http(monkeypatch, bs, accounts=more)
    _post(c, "/settings/bank", t, op="refresh")
    p = page()
    assert "Found 1 new account(s)" in p and "High Yield Savings" in p and '<span class="devpill p-info">New</span>' in p
    assert calls and "balances-only=1" in calls[-1][1], "Find new accounts asks for balances only"
    _post(c, "/settings/bank", t, op="refresh")
    assert "No new accounts" in page()
    tb.fake_http(monkeypatch, bs)
    _post(c, "/settings/bank", t, op="pull")
    p = page()
    assert "Pulled 2 new transaction(s)" in p and "Last good pull" in p and "in Money: Everyday Checking" in p
    _post(c, "/settings/bank", t, op="forget")
    assert "Tick the box" in page() and bs.configured()
    _post(c, "/settings/bank", t, op="forget", sure="1")
    p = page()
    assert "forgotten" in p and not bs.configured() and 'name="token"' in p
    _post(c, "/settings/bank", t, op="explode")
    assert "cannot be done here" in page()
    log = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "bank_setup" in log and "bank_pull" in log and "bank_refresh" in log and "bank_forget" in log and "sfsecret" not in log
    assert c.post("/settings/bank", data={"op": "pull"}).status_code == 403, "CSRF"
    c.cookies.clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    assert _post(c, "/settings/bank", t, op="pull").status_code == 403
    assert "Bank sync" not in c.get("/").text


def test_settings_form_redraws_in_place_on_its_own_tab(conn, modules):
    """A form sent by HTMX from its own Settings page gets the page back to swap into <main> (scroll and tab kept, the
    result as a toast); from another page, or without HTMX, it still gets HX-Redirect."""
    c, _, local = conn
    local()
    t = _token(c)
    h = {"X-CSRF-Token": t, "HX-Request": "true",
         "HX-Current-URL": "http://127.0.0.1:8601/settings?group=connections&tab=calendars"}
    r = c.post("/settings/feeds", data={"op": "remove", "id": "nope"}, headers=h)
    assert r.status_code == 200 and "hx-redirect" not in r.headers
    assert r.headers["hx-retarget"] == "main" and r.headers["hx-reselect"] == "main"
    assert r.headers["hx-reswap"].startswith("outerHTML show:none")
    assert 'class="stoast' in r.text and "data-toast" in r.text
    assert 'id="sp-calendars" role="tabpanel"' in r.text and 'id="sp-ai" role="tabpanel" aria-labelledby="st-ai" hidden' in r.text
    assert 'data-stab="calendars" aria-selected="true"' in r.text, "the tab the form was sent from stays open"
    h["HX-Current-URL"] = "http://127.0.0.1:8601/settings?group=data"
    r = c.post("/settings/feeds", data={"op": "remove", "id": "nope"}, headers=h)
    assert r.headers["hx-redirect"] == "/settings?group=connections"
    page = c.get("/settings?group=connections").text
    for k in ("ai", "bot", "google", "mail", "calendars"):
        assert f'data-stab="{k}"' in page and f'id="sp-{k}"' in page
    assert 'id="sp-bot" role="tabpanel" aria-labelledby="st-bot" hidden' in page, "one tab at a time, AI first"
    page = c.get("/settings?group=data&tab=backups").text
    assert 'id="sp-backups" role="tabpanel" aria-labelledby="st-backups">' in page and "Settings history" in page


def test_settings_change_keeps_a_copy_first_and_puts_it_back(conn, root, modules):
    """Before a change in Settings the settings files are copied (only when they changed since the newest copy);
    Settings > Data > Backups > Settings history puts one back, after copying the files of right now."""
    import json as _json
    c, _, local = conn
    sh = modules("settings_history")
    import shutil
    shutil.rmtree(sh.home(), ignore_errors=True)
    t = _token(c)
    before = (root / "config" / "family.json").read_text(encoding="utf-8")
    _post(c, "/settings/agent", t, name="Robo", tone="brief", brief_time="07:00", weekly_day="SUN", weekly_time="18:00")
    first = sh.listing()
    assert len(first) == 1 and first[0]["who"] == "Ann" and first[0]["what"] == "Home Profile"
    assert _json.loads((sh.home() / first[0]["name"] / "family.json").read_text(encoding="utf-8")) == _json.loads(before)
    assert "secrets.env" not in [p.name for p in (sh.home() / first[0]["name"]).iterdir()]
    _post(c, "/settings/audit", t)
    assert len(sh.listing()) == 1, "a check changes no settings: no copy"
    page = c.get("/settings?group=data&tab=backups").text
    assert first[0]["name"] in page and "Put back" in page
    _post(c, "/settings/history/restore", t, name=first[0]["name"])
    assert "Tick the box" in c.get("/settings?group=data").text
    _post(c, "/settings/history/restore", t, name="../../etc", sure="1")
    assert "not in the settings history" in c.get("/settings?group=data").text
    _post(c, "/settings/history/restore", t, name=first[0]["name"], sure="1")
    assert "Settings put back" in c.get("/settings?group=data").text
    assert _json.loads((root / "config" / "family.json").read_text(encoding="utf-8")) == _json.loads(before)
    assert len(sh.listing()) == 2 and sh.listing()[0]["what"].startswith("before putting back"), "now is kept first"
    assert "settings_restore" in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    c.cookies.clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    assert _post(c, "/settings/history/restore", t, name=first[0]["name"], sure="1").status_code == 403
