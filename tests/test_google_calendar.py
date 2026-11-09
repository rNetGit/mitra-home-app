"""Google Calendar, read-only (data/google_calendar.py), against a Google stand-in on 127.0.0.1: loopback sign-in with
PKCE and a state check, the refresh token only in secrets.env, access tokens by refresh, events parsed (all-day, timed,
cancelled, private), expired sign-in handled, the test-base override refused for any other host, and the CLI."""
import base64
import hashlib
import http.server
import json
import threading
import urllib.parse
import urllib.request

import pytest

from conftest import run

CLIENT = {"installed": {"client_id": "test-client.apps.googleusercontent.com", "client_secret": "test-client-secret",
                        "auth_uri": "x", "token_uri": "x", "redirect_uris": ["http://localhost"]}}


class FakeGoogle:
    def __init__(self):
        self.challenge = None
        self.posts = []
        self.gets = []
        self.refresh_ok = True
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = urllib.parse.parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
                f = {k: v[0] for k, v in body.items()}
                outer.posts.append((self.path, f))
                if self.path == "/revoke":
                    return self._send(200, {})
                if f.get("grant_type") == "authorization_code":
                    want = base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                    if want != outer.challenge or f["code"] != "the-code":
                        return self._send(400, {"error": "invalid_grant"})
                    return self._send(200, {"access_token": "AT-1", "refresh_token": "RT-SECRET-1", "expires_in": 3600})
                if f.get("grant_type") == "refresh_token":
                    if not outer.refresh_ok or f.get("refresh_token") != "RT-SECRET-1":
                        return self._send(400, {"error": "invalid_grant"})
                    return self._send(200, {"access_token": "AT-2", "expires_in": 3600})
                self._send(400, {"error": "unsupported_grant_type"})

            def do_GET(self):
                outer.gets.append((self.path, self.headers.get("Authorization")))
                if self.headers.get("Authorization") != "Bearer AT-2":
                    return self._send(401, {"error": "unauthorized"})
                if self.path.startswith("/calendar/v3/users/me/calendarList"):
                    return self._send(200, {"items": [{"id": "me@example.com", "summary": "Me", "primary": True},
                                                      {"id": "fam123@group.calendar.google.com", "summary": "Family",
                                                       "summaryOverride": "Our family"}]})
                if "/events" in self.path:
                    return self._send(200, {"items": [
                        {"summary": "Dentist  Sam", "start": {"dateTime": "2026-10-12T15:30:00-04:00"},
                         "end": {"dateTime": "2026-10-12T16:15:00-04:00"}},
                        {"summary": "School holiday", "start": {"date": "2026-10-13"}, "end": {"date": "2026-10-14"}},
                        {"summary": "Cancelled thing", "status": "cancelled", "start": {"date": "2026-10-13"}},
                        {"start": {"dateTime": "2026-10-11T09:00:00-04:00"}, "end": {"dateTime": "2026-10-11T10:00:00-04:00"}},
                        {"summary": "Bad\x07date", "start": {"date": "not-a-date"}},
                    ]})
                self._send(404, {})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()


@pytest.fixture(scope="module")
def G(root, modules):
    fake = FakeGoogle()
    (root / "config" / "google_client.json").write_text(json.dumps(CLIENT), encoding="utf-8")
    import os
    os.environ["MITRAHOME_GOOGLE_TEST_BASE"] = fake.base
    yield modules("google_calendar"), fake
    os.environ.pop("MITRAHOME_GOOGLE_TEST_BASE", None)
    fake.close()


def _secrets(root):
    f = root / "config" / "secrets.env"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def test_sign_in_uses_pkce_state_and_keeps_the_token_in_secrets_only(root, G):
    mod, fake = G
    seen = {}

    def browser(url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        seen.update({k: v[0] for k, v in q.items()})
        fake.challenge = seen["code_challenge"]
        bad = f"{seen['redirect_uri']}/?code=evil&state=WRONG"
        try:
            urllib.request.urlopen(bad, timeout=5)  # a wrong state is refused and ignored
        except Exception:
            pass
        urllib.request.urlopen(f"{seen['redirect_uri']}/?code=the-code&state={seen['state']}", timeout=5).read()

    out = []
    assert mod.authorize(browser=browser, timeout=20, say=out.append) is True
    assert seen["code_challenge_method"] == "S256" and seen["response_type"] == "code"
    assert seen["redirect_uri"].startswith("http://127.0.0.1:") and seen["access_type"] == "offline"
    assert set(seen["scope"].split()) == set(mod.SCOPES), "read-only scopes, nothing more"
    assert all(s.endswith(".readonly") for s in mod.SCOPES)
    assert "RT-SECRET-1" in _secrets(root)
    fam = (root / "config" / "family.json").read_text(encoding="utf-8")
    assert "RT-SECRET-1" not in fam and "RT-SECRET-1" not in " ".join(out)


def test_status_never_prints_the_token(root, G):
    r = run(["data/google_calendar.py", "status"], root, env={"MITRAHOME_GOOGLE_TEST_BASE": G[1].base})
    assert r.returncode == 0 and "signed in:         yes" in r.stdout and "RT-SECRET" not in r.stdout + r.stderr


def test_events_are_parsed_and_sorted(root, G):
    mod, fake = G
    import datetime as D
    ev = mod.events(days=7, today=D.date(2026, 10, 11), cals=["primary"])
    assert [(e["date"], e["time"], e["title"], e["all_day"]) for e in ev] == [
        ("2026-10-11", "09:00", "(busy)", False),
        ("2026-10-12", "15:30", "Dentist Sam", False),
        ("2026-10-13", "", "School holiday", True)]
    assert any(p.startswith("/calendar/v3/calendars/primary/events") and "singleEvents=true" in p for p, _ in fake.gets)
    assert all(a == "Bearer AT-2" for _, a in fake.gets), "an access token from the refresh token"
    sent = [f for path, f in fake.posts if f.get("grant_type") == "refresh_token"]
    assert sent and sent[-1]["refresh_token"] == "RT-SECRET-1"


def test_calendar_list_uses_the_display_name(G):
    mod, _ = G
    cals = mod.calendars()
    assert {"id": "fam123@group.calendar.google.com", "name": "Our family", "primary": False} in cals
    assert cals[0]["primary"] is True


def test_expired_sign_in_gives_one_clear_instruction(G):
    mod, fake = G
    fake.refresh_ok = False
    try:
        with pytest.raises(mod.AuthError) as e:
            mod.events(days=3)
        assert "Settings > Connections > Google Calendar" in str(e.value) and "RT-SECRET" not in str(e.value)
        assert "Publish app" not in str(e.value), "signed in today: no Testing hint"
    finally:
        fake.refresh_ok = True


def test_refused_a_week_after_sign_in_points_at_testing_status(root, G):
    mod, fake = G
    import datetime as D
    fam_file = root / "config" / "family.json"
    keep = fam_file.read_text(encoding="utf-8")
    fam = json.loads(keep)
    assert fam["google_calendar"]["signed_in"] == D.date.today().isoformat(), "sign-in date is remembered"
    fam["google_calendar"]["signed_in"] = (D.date.today() - D.timedelta(days=8)).isoformat()
    fam_file.write_text(json.dumps(fam), encoding="utf-8")
    fake.refresh_ok = False
    try:
        with pytest.raises(mod.AuthError) as e:
            mod.events(days=3)
        assert "'Testing'" in str(e.value) and "Publish app" in str(e.value)
    finally:
        fake.refresh_ok = True
        fam_file.write_text(keep, encoding="utf-8")


def test_other_hosts_are_refused_and_a_web_client_file_is_not_accepted(root, G, monkeypatch, tmp_path):
    mod, _ = G
    monkeypatch.setenv("MITRAHOME_GOOGLE_TEST_BASE", "https://evil.example.com")
    with pytest.raises(mod.CalendarError):
        mod.endpoints()
    monkeypatch.setenv("MITRAHOME_GOOGLE_TEST_BASE", G[1].base)
    web = tmp_path / "web.json"
    web.write_text(json.dumps({"web": {"client_id": "x"}}), encoding="utf-8")
    with pytest.raises(mod.CalendarError) as e:
        mod.load_client(web)
    assert "Desktop app" in str(e.value)


def test_revoke_forgets_the_token_here(root, G):
    mod, fake = G
    assert mod.revoke() is True
    assert mod.refresh_token() == ""
    assert any(p == "/revoke" and f.get("token") == "RT-SECRET-1" for p, f in fake.posts)
    assert "RT-SECRET-1" not in _secrets(root)


def test_wizard_checks_the_client_file_and_never_saves_in_dry_run(root, G, tmp_path):
    import os
    import subprocess
    import sys
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(CLIENT), encoding="utf-8")
    bad.write_text(json.dumps({"web": {"client_id": "x"}}), encoding="utf-8")
    saved = root / "config" / "google_client.json"
    keep = saved.read_text(encoding="utf-8")
    saved.unlink()
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    env["AIFA_DRY_RUN"] = "1"
    try:
        r = subprocess.run([sys.executable, "onboard.py", "add", "calendar"], cwd=root, capture_output=True, text=True, timeout=120,
                           env=env, input="y\ny\ny\ny\ny\ny\n" + str(bad) + "\n")
        assert "Desktop app" in r.stdout and "not complete" in r.stdout and not saved.exists()
        r = subprocess.run([sys.executable, "onboard.py", "add", "calendar"], cwd=root, capture_output=True, text=True, timeout=120,
                           env=env, input="y\ny\ny\ny\ny\ny\n" + str(good) + "\n")
        assert "Dry run: client file checked, not saved" in r.stdout and not saved.exists()
    finally:
        saved.write_text(keep, encoding="utf-8")


def test_disconnect_then_sign_in_again_turns_it_back_on_and_a_pick_keeps_the_rest(root, G, modules):
    from conftest import read_family
    mod, fake = G
    aa = modules("admin_actions")
    adult = {"name": "Alex", "role": "adult"}
    assert aa.google_disconnect(adult)[0]
    assert read_family(root)["google_calendar"]["enabled"] is False

    def browser(url):
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
        fake.challenge = q["code_challenge"]
        urllib.request.urlopen(f"{q['redirect_uri']}/?code=the-code&state={q['state']}", timeout=5).read()

    assert mod.authorize(browser=browser, timeout=20, say=lambda *_: None, write=True) is True
    import datetime as D
    gc = read_family(root)["google_calendar"]
    assert gc["enabled"] is True and gc["write"] is True and gc["signed_in"] == D.date.today().isoformat()
    assert aa.google_pick(adult, ["fam123@group.calendar.google.com"])[0]
    gc = read_family(root)["google_calendar"]
    assert gc["calendars"] == ["fam123@group.calendar.google.com"] and gc["enabled"] is True
    assert gc["write"] is True and gc["signed_in"] == D.date.today().isoformat(), "a pick keeps the write flag and date"
