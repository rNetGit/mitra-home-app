"""Discord adapter (data/chat_discord.py) without discord.py or the live gateway: token shape and REST check against
a local stand-in for discord.com, Public Bot warning, token never sent elsewhere or shown in errors, invite link with
the minimum permission, slash commands mapped to chat_core text, DM vs server rules (server = no money even for
adults), plain words in DMs, onboarding add-on wired and documented."""
import datetime as D
import http.server
import json
import os
import threading

import pytest

from conftest import SRC, db, run

TOKEN = "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.GabCdE.abcdefghijklmnopqrstuvwxyz0123456789AB"


class FakeDiscord:
    def __init__(self):
        self.public, self.auth = False, []
        state = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                state.auth.append(self.headers.get("Authorization"))
                if self.headers.get("Authorization") != f"Bot {TOKEN}":
                    return self._send(401, {"message": "401: Unauthorized"})
                if self.path == "/users/@me":
                    return self._send(200, {"id": "42", "username": "OurMitra Home", "bot": True})
                if self.path == "/oauth2/applications/@me":
                    return self._send(200, {"id": "4242", "bot_public": state.public})
                return self._send(404, {})

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"


@pytest.fixture(scope="module")
def dc(root):
    f = FakeDiscord()
    saved = {k: os.environ.get(k) for k in ("MITRAHOME_DISCORD_TOKEN", "MITRAHOME_DISCORD_API")}
    os.environ.update({"MITRAHOME_DISCORD_TOKEN": TOKEN, "MITRAHOME_DISCORD_API": f.base})
    yield f
    f.srv.shutdown()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="module")
def Dm(root, modules, dc):
    return modules("chat_discord")


@pytest.fixture(scope="module")
def C(root, modules):
    return modules("chat_core")


@pytest.fixture(scope="module")
def dbp(root):
    return root / "data" / "family.db"


def _link(C, dbp, name, uid):
    con = C._con(dbp)
    try:
        code, *_ = C.invite(con, name, platform="discord")
    finally:
        con.close()
    assert "linked" in C.handle("discord", str(uid), f"/start {code}", db=dbp)


@pytest.fixture(scope="module")
def bill(root):
    c = db(root)
    c.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Internet','NetCo',79.99,?, 'due')",
              ((D.date.today() + D.timedelta(days=1)).isoformat(),))
    c.commit()
    c.close()


@pytest.mark.parametrize("tok,ok", [(TOKEN, True), ("", False), ("abc.def", False), ("123456789:AAHtelegramstyletoken", False)])
def test_token_shape(Dm, tok, ok):
    assert Dm.valid_token_shape(tok) is ok


def test_check_ok_bad_and_public_warning(Dm, dc):
    ok, name, app = Dm.check()
    assert ok and name == "OurMitra Home" and app == "4242"
    assert dc.auth[-1] == f"Bot {TOKEN}"
    dc.public = True
    ok, name, _ = Dm.check()
    assert ok and "Public Bot" in name
    dc.public = False
    bad = "MTk5OTk5OTk5OTk5OTk5OTk5OQ.GabCdE.zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
    ok, msg, app = Dm.check(bad)
    assert not ok and "401" in msg and bad not in msg and app is None


def test_api_base_refuses_other_hosts(Dm, monkeypatch):
    for bad in ("https://evil.example.com/api", "http://discord.com/api/v10", "http://10.0.0.5:80"):
        monkeypatch.setenv("MITRAHOME_DISCORD_API", bad)
        with pytest.raises(Dm.DiscordError):
            Dm.api_base()


def test_network_error_hides_token(Dm, monkeypatch):
    monkeypatch.setenv("MITRAHOME_DISCORD_API", "http://127.0.0.1:1")
    with pytest.raises(Dm.DiscordError) as e:
        Dm.rest("/users/@me", TOKEN, timeout=2)
    assert TOKEN not in str(e.value)


def test_invite_url_minimum_permission(Dm):
    u = Dm.invite_url("4242")
    assert "client_id=4242" in u and "permissions=2048" in u and "applications.commands" in u and "administrator" not in u


def test_slash_mapping(Dm):
    assert Dm.as_text("due") == "/due"
    assert Dm.as_text("start", "12345678") == "/start 12345678"
    assert Dm.as_text("rm") == ""
    assert set(Dm.COMMANDS) == {"due", "week", "whoami", "unlink", "help", "start", "find", "ask", "inbox", "ok", "no"}
    assert Dm.as_text("ok", "12 2") == "/ok 12 2"


def test_strangers_and_bots_silent(Dm, dbp):
    assert Dm.reply_for(555, "/due", is_dm=True, db=dbp) is None
    assert Dm.reply_for(555, "/due", is_dm=True, is_bot=True, db=dbp) is None
    assert Dm.reply_for(555, "", is_dm=True, db=dbp) is None


def test_code_only_in_dm(Dm, C, dbp):
    con = C._con(dbp)
    try:
        code, *_ = C.invite(con, "Alex", platform="discord")
    finally:
        con.close()
    assert "private chat" in Dm.reply_for(601, Dm.as_text("start", code), is_dm=False, db=dbp)
    assert "linked" in Dm.reply_for(601, Dm.as_text("start", code), is_dm=True, db=dbp)


def test_adult_money_only_in_dm(Dm, C, dbp, bill):
    _link(C, dbp, "Alex", 602)
    dm = Dm.reply_for(602, "due", is_dm=True, db=dbp)  # plain word in a DM
    srv = Dm.reply_for(602, "/due", is_dm=False, db=dbp)
    assert "NetCo" in dm and "$79.99" in dm
    assert "NetCo" not in srv and "$" not in srv


def test_kid_no_money_anywhere(Dm, C, dbp, bill):
    _link(C, dbp, "Sam", 603)
    for t, dm in (("due", True), ("/due", False), ("/week", True)):
        r = Dm.reply_for(603, t, is_dm=dm, db=dbp)
        assert "NetCo" not in r and "$" not in r


def test_telegram_link_does_not_work_on_discord(Dm, C, dbp):
    con = C._con(dbp)
    try:
        code, *_ = C.invite(con, "Alex", platform="telegram")
    finally:
        con.close()
    assert "did not work" in Dm.reply_for(604, f"/start {code}", is_dm=True, db=dbp)


def test_reply_length_capped(Dm, C, dbp, root, monkeypatch):
    _link(C, dbp, "Alex", 605)
    monkeypatch.setattr(C, "handle", lambda *a, **k: "x" * 5000)
    assert len(Dm.reply_for(605, "/due", is_dm=True, db=dbp)) == Dm.MAX_REPLY


def test_cli_check_without_token(root):
    r = run(["data/chat_discord.py", "check"], root, env={"MITRAHOME_DISCORD_TOKEN": ""})
    assert r.returncode == 1 and "onboard.py add discord" in r.stdout


def test_cli_check_prints_invite(root, dc):
    r = run(["data/chat_discord.py", "invite-url"], root,
            env={"MITRAHOME_DISCORD_TOKEN": TOKEN, "MITRAHOME_DISCORD_API": dc.base})
    assert r.returncode == 0 and "client_id=4242" in r.stdout and TOKEN not in r.stdout


def test_onboarding_wired_and_documented():
    ob = (SRC / "onboard.py").read_text(encoding="utf-8")
    assert '"discord": ("Discord bot' in ob and "def add_discord" in ob and '"Mitra Home Discord Bot"' in ob
    assert (SRC / "tasks" / "chat_discord.bat").exists()
    assert 'chat = ["discord.py' in (SRC / "pyproject.toml").read_text(encoding="utf-8")
    doc = (SRC / "docs" / "CHAT.md").read_text(encoding="utf-8")
    for must in ("python onboard.py add discord", "Public Bot", "Privileged Gateway Intent", "Reset Token",
                 "direct message", "discord.py"):
        assert must in doc
