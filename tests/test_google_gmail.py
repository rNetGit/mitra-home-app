"""Gmail, read-only (data/google_gmail.py), against a Google stand-in on 127.0.0.1: only the labelled messages are read,
attachments are checked like any upload, mail with no attachment becomes a text file, nothing is read twice, mail that
carries the older Processed label is skipped, the Gmail permission rides on the calendar sign-in without dropping the
others, and subjects or senders never reach the log."""
import base64
import http.server
import json
import threading
import urllib.parse
import urllib.request

import pytest

from conftest import read_family, write_family

CLIENT = {"installed": {"client_id": "test-client.apps.googleusercontent.com", "client_secret": "s"}}
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n" + b"x" * 200


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _msg(mid, sender, subject, parts, labels=("L1",), ms=1760000000000):
    return {"id": mid, "labelIds": list(labels), "internalDate": str(ms),
            "payload": {"mimeType": "multipart/mixed",
                        "headers": [{"name": "From", "value": sender}, {"name": "Subject", "value": subject}],
                        "parts": parts}}


def _file(name, mime, data, att):
    return {"filename": name, "mimeType": mime, "body": {"attachmentId": att, "size": len(data)}}


class FakeGmail:
    def __init__(self):
        self.gets = []
        self.attachments = {"A-pdf": PDF, "A-evil": b"MZ\x90\x00" + b"\x00" * 300, "A-logo": b"\x89PNG\r\n\x1a\n" + b"0" * 50}
        self.messages = {
            "m1": _msg("m1", "Power Co <billing@powerco.example>", "Your October bill", [
                {"mimeType": "text/plain", "body": {"data": _b64(b"Amount due 120.00")}},
                _file("statement oct.pdf", "application/pdf", PDF, "A-pdf"),
                _file("logo.png", "image/png", b"x" * 40, "A-logo"),
                _file("invoice.pdf", "application/pdf", b"MZ" + b"0" * 100, "A-evil")]),
            "m2": _msg("m2", "bank@bank.example", "Statement ready", [
                {"mimeType": "text/plain", "body": {"data": _b64(b"Your statement is ready. Balance due 55.20 by Nov 4.")}}]),
            "m3": _msg("m3", "x@old.example", "Already done", [
                {"mimeType": "text/plain", "body": {"data": _b64(b"Old news that was handled before.")}}],
                labels=("L1", "L2")),
        }
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
                self.rfile.read(int(self.headers["Content-Length"]))
                if not outer.refresh_ok:
                    return self._send(400, {"error": "invalid_grant"})
                self._send(200, {"access_token": "AT-2", "expires_in": 3600})

            def do_GET(self):
                outer.gets.append(self.path)
                if self.headers.get("Authorization") != "Bearer AT-2":
                    return self._send(401, {})
                u = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(u.query)
                if u.path == "/gmail/v1/users/me/labels":
                    return self._send(200, {"labels": [{"id": "L1", "name": "Mitra Home"},
                                                       {"id": "L2", "name": "MitraHome/Processed"},
                                                       {"id": "L9", "name": "Other"}]})
                if u.path == "/gmail/v1/users/me/messages":
                    assert q.get("labelIds") == ["L1"], "only the chosen label is ever listed"
                    return self._send(200, {"messages": [{"id": k} for k in outer.messages]})
                parts = u.path.split("/")
                if len(parts) == 7 and parts[5] == "messages":
                    mid = parts[-1]
                    if mid in outer.messages:
                        return self._send(200, outer.messages[mid])
                if "/attachments/" in u.path:
                    att = u.path.rsplit("/", 1)[1]
                    return self._send(200, {"data": _b64(outer.attachments[att])})
                self._send(404, {})

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def close(self):
        self.srv.shutdown()


@pytest.fixture(scope="module")
def G(root, modules):
    import os
    fake = FakeGmail()
    (root / "config" / "google_client.json").write_text(json.dumps(CLIENT), encoding="utf-8")
    (root / "config" / "secrets.env").write_text("MITRAHOME_GOOGLE_REFRESH_TOKEN=RT-SECRET-1\n", encoding="utf-8")
    fam = read_family(root)
    fam["google_calendar"] = {"enabled": True, "gmail": True, "write": True}
    fam["gmail"] = {"enabled": True, "label": "Mitra Home"}
    write_family(root, fam)
    os.environ["MITRAHOME_GOOGLE_TEST_BASE"] = fake.base
    yield modules("google_gmail"), fake
    os.environ.pop("MITRAHOME_GOOGLE_TEST_BASE", None)
    fake.close()


def _inbox(root):
    return sorted(p.name for p in (root / "inbox").iterdir() if p.is_file() and p.name != ".gitkeep")


def test_dry_run_copies_and_remembers_nothing(root, G):
    mod, fake = G
    r = mod.pull(dry_run=True)
    assert r["files"] == 1 and r["texts"] == 1 and r["skipped"] == 1
    assert _inbox(root) == []
    assert not (root / "config" / "gmail_state.json").exists()


def test_pull_files_good_attachments_and_text_only_mail(root, G):
    mod, fake = G
    r = mod.pull()
    names = _inbox(root)
    assert r["messages"] == 2 and r["files"] == 1 and r["texts"] == 1 and r["skipped"] == 1
    assert any(n.endswith("_gmail_powerco.example_statement oct.pdf") for n in names), names
    assert any(n.endswith("_gmail_bank.example_Statement-ready.txt") for n in names), names
    assert not any("logo" in n or "invoice" in n for n in names), "tiny logo and a program named .pdf are refused"
    txt = next(root / "inbox" / n for n in names if n.endswith(".txt"))
    body = txt.read_text(encoding="utf-8")
    assert "bank.example" in body and "55.20" in body
    assert not any("old.example" in n for n in names), "mail already labelled Processed is skipped"
    log_text = (root / "logs" / "mitrahome.log").read_text(encoding="utf-8") if (root / "logs" / "mitrahome.log").exists() else ""
    assert "Your October bill" not in log_text and "powerco" not in log_text


def test_nothing_is_copied_twice(root, G):
    mod, fake = G
    before = _inbox(root)
    r = mod.pull()
    assert r["messages"] == 0 and r["files"] == 0 and r["texts"] == 0
    assert _inbox(root) == before
    state = json.loads((root / "config" / "gmail_state.json").read_text(encoding="utf-8"))
    assert set(state["done"]) == {"m1", "m2", "m3"}
    assert "October" not in json.dumps(state) and "powerco" not in json.dumps(state)


def test_a_missing_label_and_a_missing_permission_say_what_to_do(root, G):
    mod, fake = G
    fam = read_family(root)
    keep = json.loads(json.dumps(fam))
    try:
        fam["gmail"]["label"] = "Nope"
        write_family(root, fam)
        with pytest.raises(mod.GmailError) as e:
            mod.pull(dry_run=True)
        assert "Nope" in str(e.value)
        fam["google_calendar"]["gmail"] = False
        write_family(root, fam)
        with pytest.raises(mod.gc.AuthError) as e2:
            mod.pull(dry_run=True)
        assert "RT-SECRET" not in str(e2.value)
    finally:
        write_family(root, keep)


def test_expired_sign_in_is_an_auth_error(G):
    mod, fake = G
    fake.refresh_ok = False
    try:
        with pytest.raises(mod.gc.AuthError):
            mod.labels()
    finally:
        fake.refresh_ok = True


def test_sign_in_adds_gmail_and_keeps_the_calendar_write_permission(root, G, modules):
    mod, fake = G
    gc = modules("google_calendar")
    seen = {}

    def browser(url):
        q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).items()}
        seen.update(q)
        urllib.request.urlopen(f"{q['redirect_uri']}/?code=c&state={q['state']}", timeout=5).read()

    fam = read_family(root)
    keep = json.loads(json.dumps(fam))
    fam["google_calendar"] = {"enabled": True, "write": True}
    write_family(root, fam)
    import os
    import http.server as hs

    class H(hs.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            data = json.dumps({"access_token": "AT-1", "refresh_token": "RT-NEW",
                               "scope": " ".join(seen["scope"].split())}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    srv = hs.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["MITRAHOME_GOOGLE_TEST_BASE"] = f"http://127.0.0.1:{srv.server_port}"
    try:
        gc.authorize(browser=browser, timeout=20, say=lambda *_: None, gmail=True)
        scopes = set(seen["scope"].split())
        assert gc.GMAIL_SCOPE in scopes and gc.WRITE_SCOPE in scopes and set(gc.SCOPES) <= scopes
        assert read_family(root)["google_calendar"]["gmail"] is True
        gc.authorize(browser=browser, timeout=20, say=lambda *_: None)
        assert gc.GMAIL_SCOPE in set(seen["scope"].split()), "signing in again does not drop the Gmail permission"
    finally:
        srv.shutdown()
        os.environ["MITRAHOME_GOOGLE_TEST_BASE"] = fake.base
        write_family(root, keep)


def test_only_one_readonly_gmail_scope(G):
    mod, _ = G
    assert mod.SCOPE.endswith("gmail.readonly") and mod.SCOPE == mod.gc.GMAIL_SCOPE


def test_dashboard_actions_are_adults_only(root, G, modules):
    aa = modules("admin_actions")
    kid = {"name": "Sam", "role": "limited"}
    for fn, args in ((aa.gmail_sign_in, ()), (aa.gmail_settings, (True, "Mitra Home")), (aa.gmail_pull_now, ())):
        assert fn(kid, *args)[0] is False
    adult = {"name": "Alex", "role": "adult"}
    assert aa.gmail_settings(adult, False, "Bills")[0]
    assert read_family(root)["gmail"] == {"enabled": False, "label": "Bills"}
    assert aa.gmail_settings(adult, True, "Mitra Home")[0]
