"""Web app (data/webapp): sign-in, sessions, CSRF, role checks, headers, Finance numbers, PWA files."""
import datetime as dt
import html
import re
import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def web(root, modules):
    """(client, auth module, sessions module) on this copy, with an adult (Ann) and a limited user (Kid)."""
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    sessions = modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)  # an earlier test's lock must not leak into this one
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    (root / "config").mkdir(exist_ok=True)
    config.write_json(root / "config" / "family.json", fam)
    config._cache.clear() if hasattr(config, "_cache") else None
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    yield c, auth, sessions
    sessions.clear()


def _login(c, name="Ann", pin="1234"):
    return c.post("/login", data={"name": name, "pin": pin})


def _csrf(c):
    html = c.get("/").text
    return re.search(r'name="csrf-token" content="([^"]+)"', html).group(1)


def test_pages_need_a_session(web):
    c, _, _ = web
    r = c.get("/money")
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert c.get("/").status_code == 303


def test_wrong_pin_then_right_pin(web):
    c, _, _ = web
    assert _login(c, pin="9999").status_code == 401
    r = _login(c)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert c.get("/money").status_code == 200


def test_pin_check_runs_off_the_event_loop(web, monkeypatch):
    """S8: checking a PIN (200,000 PBKDF2 rounds) runs in a worker thread, so other requests are not held up."""
    import asyncio
    c, auth, _ = web
    seen = []
    real = auth.login

    def spy(*a):
        try:
            asyncio.get_running_loop()
            seen.append("loop")
        except RuntimeError:
            seen.append("thread")
        return real(*a)
    monkeypatch.setattr(auth, "login", spy)
    assert _login(c).status_code == 303
    assert seen == ["thread"]


def test_unknown_name_is_refused_without_a_new_throttle_entry(web, root):
    c, auth, _ = web
    assert _login(c, name="Mallory").status_code == 401
    assert _login(c, name="Eve").status_code == 401
    keys = set(auth._throttle_load())
    assert keys <= {"?", "*", "@testclient"}, "one entry per device at most, never one per typed name"


def test_five_wrong_pins_lock_the_name(web):
    c, _, _ = web
    for _ in range(5):
        _login(c, pin="bad")
    assert _login(c).status_code == 429  # even the right PIN waits


def test_limited_user_cannot_open_finance(web):
    c, _, _ = web
    assert _login(c, "Kid", "0000").status_code == 303
    assert c.get("/money").status_code == 403
    assert c.get("/money/trends").status_code == 403
    assert c.get("/settings").status_code == 403


def test_session_ends_when_the_pin_changes_or_the_person_is_removed(web, root, modules):
    c, auth, _ = web
    config = modules("config")
    assert _login(c).status_code == 303
    assert c.get("/money").status_code == 200
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("9999")}, fam["dashboard_users"][1]]
    config.write_json(root / "config" / "family.json", fam)
    config._cache.clear() if hasattr(config, "_cache") else None
    assert c.get("/money").status_code == 303  # old session is gone: back to sign-in


def test_demoted_person_loses_finance_at_once(web, root, modules):
    c, auth, _ = web
    config = modules("config")
    assert _login(c).status_code == 303
    fam = dict(config.family())
    users = [dict(u) for u in fam["dashboard_users"]]
    users[0]["role"] = "limited"
    fam["dashboard_users"] = users
    config.write_json(root / "config" / "family.json", fam)
    config._cache.clear() if hasattr(config, "_cache") else None
    assert c.get("/money").status_code == 403


def test_post_needs_the_csrf_token(web):
    c, _, _ = web
    _login(c)
    assert c.post("/theme", data={"mode": "dark"}).status_code == 403
    token = _csrf(c)
    assert c.post("/theme", data={"mode": "dark"}, headers={"X-CSRF-Token": "nope"}).status_code == 403
    assert c.post("/theme", data={"mode": "dark"}, headers={"X-CSRF-Token": token}).status_code == 204
    assert c.post("/theme", data={"mode": "pink"}, headers={"X-CSRF-Token": token}).status_code == 400


def test_cross_site_post_is_refused(web):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    r = c.post("/theme", data={"mode": "dark"}, headers={"X-CSRF-Token": token, "Origin": "http://evil.example"})
    assert r.status_code == 403


def test_logout_ends_the_session(web):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    r = c.post("/logout", headers={"X-CSRF-Token": token})
    assert r.status_code == 204 and r.headers["HX-Redirect"] == "/login"
    c.cookies.clear()
    assert c.get("/money").status_code == 303


def test_a_forged_or_old_cookie_is_not_a_session(web):
    c, _, sessions = web
    c.cookies.set("fa_session", "x" * 43)
    assert c.get("/money").status_code == 303
    tok = sessions.create({"name": "Ann", "role": "adult"}, now=1000)
    assert sessions.get(tok, now=1000 + sessions.IDLE + 1) is None


def test_host_header_must_be_local(web):
    c, _, _ = web
    assert c.get("/healthz", headers={"Host": "evil.example"}).status_code == 400
    assert c.get("/healthz", headers={"Host": "localhost:8601"}).status_code == 200
    assert c.get("/healthz", headers={"Host": "192.168.1.20:8601"}).status_code == 200


def test_security_headers_and_no_store(web):
    c, _, _ = web
    r = _login(c)
    r = c.get("/money")
    h = r.headers
    assert "script-src 'self'" in h["content-security-policy"] and "unsafe-inline" not in h["content-security-policy"]
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "no-store"
    assert "<script>" not in r.text.replace('<script type="application/json"', "")  # no inline script


def test_referrer_policy_lets_browsers_send_a_real_origin(web):
    # "no-referrer" makes browsers send "Origin: null" on same-origin form POSTs, which same_origin() refuses
    c, _, _ = web
    assert c.get("/login").headers["referrer-policy"] == "same-origin"


def test_finance_numbers_match_trends(web, root, modules):
    c, _, _ = web
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM transactions")
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Chk', 'checking', '9999')")
    acct = con.execute("SELECT id FROM accounts WHERE name='Chk'").fetchone()[0]
    con.executemany("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) VALUES (?,?,?,?,?,?)",
                    [(acct, "2026-09-01", "PAYROLL", 5000.0, "salary", "income"),
                     (acct, "2026-09-03", "RENT", -1500.0, "housing", "spend")])
    con.commit()
    con.close()
    _login(c)
    html = c.get("/money?months=6").text
    assert "$5,000" in html and "$1,500" in html and "$3,500" in html


def test_pwa_files(web, root):
    c, _, _ = web
    m = c.get("/manifest.webmanifest")
    assert m.status_code == 200 and m.json()["display"] == "standalone"
    sw = c.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["service-worker-allowed"] == "/"
    ver = (root / "VERSION").read_text(encoding="utf-8").strip()
    assert "__VERSION__" not in sw.text and f"'{ver}'" in sw.text  # a new release = a new worker and a new cache
    _login(c)
    page = c.get("/").text
    assert f'/static/app.css?v={ver}"' in page and f'/static/app.js?v={ver}"' in page
    assert c.get("/static/icon-192.png").status_code == 200
    assert "--accent" in c.get("/tokens.css").text
    assert '[data-theme="dark"]{color-scheme:dark;' in c.get("/tokens.css").text
    off = c.get("/offline")
    assert off.status_code == 200 and "csrf-token" not in off.text


def test_web_app_does_not_start_with_database_updates_waiting(root, modules, capsys):
    """Audit A10: new code on an old database is refused at start (launch.py / onboard upgrade apply them first)."""
    web_app = modules("web_app")
    assert web_app.waiting_updates() == []
    extra = root / "data" / "migrate_999_waiting_test.py"
    extra.write_text("def run(con):\n    pass\n", encoding="utf-8")
    try:
        assert web_app.waiting_updates() == ["migrate_999_waiting_test.py"]
        assert web_app.main([]) == 3
        assert "database update(s) are waiting" in capsys.readouterr().out
    finally:
        extra.unlink()


def test_lan_refused_without_a_pin(root, modules):
    web_app, config = modules("web_app"), modules("config")
    fam = dict(config.family())
    fam.pop("dashboard_users", None)
    fam.pop("dashboard_pin", None)
    config.write_json(root / "config" / "family.json", fam)
    assert web_app.main(["--lan"]) == 2


# ---- Brief --------------------------------------------------------------------------------------------------------
def _vals(html):
    """Every hx-vals JSON object on the page, as dicts."""
    import html as _h
    import json
    return [json.loads(_h.unescape(m)) for m in re.findall(r"hx-vals='([^']*)'", html)]


def _post(c, path, token, **data):
    return c.post(path, data=data, headers={"X-CSRF-Token": token})


def test_today_rows_need_an_adult_and_a_token_and_to_do_redirects(web):
    c, _, _ = web
    assert c.get("/brief", follow_redirects=False).headers["location"] == "/"
    _login(c, "Kid", "0000")
    assert c.post("/today/act", data={"op": "hide", "key": "x"}).status_code == 403
    assert c.post("/today/doc", data={"kind": "emergency"}).status_code == 403
    c.cookies.clear()
    _login(c)
    assert c.post("/today/act", data={"op": "hide", "key": "x"}).status_code == 403  # no CSRF token
    r = c.get("/brief?who=Sam%20X", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/?who=Sam%20X", "an old To do link lands on Today, same person"
    assert c.get("/brief/body").status_code == 404


def _today_act(c, token, **data):
    r = _post(c, "/today/act", token, **data)
    assert r.status_code == 200 and r.headers["HX-Redirect"].startswith("/")
    return c.get(r.headers["HX-Redirect"]).text


def test_today_hide_snooze_and_unknown_key(web):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    assert "no longer on the list" in _today_act(c, token, op="snooze", key="alert:nope:1", days="7")
    keys = [v["key"] for v in _vals(c.get("/").text) if v.get("op") == "snooze"]
    assert keys, "the demo household has something coming up"
    key = keys[0]
    page = _today_act(c, token, op="snooze", key=key, days="7")
    assert "Hidden for 7 days" in page and f'"key": "{key}"' not in html.unescape(page)
    page = _today_act(c, token, op="snooze", key=key, days="9999")
    assert "no longer on the list" in page  # already hidden: nothing to act on, and no odd length is taken


def test_today_paid_then_undo(web):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/").text
    # a bill row is the one whose Done button is labelled Paid
    paid = re.findall(r"hx-vals='([^']*)'\s+aria-label=\"Paid: [^\"]*\">Paid</button>", page)
    assert paid, "the demo household has an open bill"
    import json
    vals = json.loads(html.unescape(paid[0]))
    page = _today_act(c, token, **vals)
    assert "as paid" in page and 'hx-post="/today/undo"' in page
    undo = [v for v in _vals(page) if "bill" in v][0]
    r = _post(c, "/today/undo", token, **undo)
    assert "Put back on the list" in c.get(r.headers["HX-Redirect"]).text
    assert _post(c, "/today/undo", token, bill="x", due="nope").status_code == 400


def test_today_documents_kinds_are_fixed(web):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    assert 'hx-post="/today/doc"' in c.get("/").text
    assert _post(c, "/today/doc", token, kind="../../etc/passwd").status_code == 404
    r = _post(c, "/today/doc", token, kind="emergency")
    assert r.status_code == 200 and 'href="/brief/doc/emergency"' in r.text and "<html" not in r.text
    assert "Where things are" in r.text and 'data-download-post="/brief/doc/emergency/sealed"' in r.text
    assert "data-print-list" in _post(c, "/today/doc", token, kind="this_week").text


def test_emergency_where_things_are_and_the_sealed_copy(web, modules):
    import base64
    import json
    import re as _re
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    r = _post(c, "/today/emergency/where", token, will="Top drawer of the desk, blue folder", passwords="Aunt Mary")
    assert r.status_code == 200 and "Saved." in r.text
    assert "The will and power of attorney: Top drawer of the desk, blue folder" in r.text
    assert "Who can open the password manager (a name, never the password): Aunt Mary" in r.text
    fam = json.loads((modules("paths").CONFIG / "family.json").read_text(encoding="utf-8"))
    assert fam["emergency"]["where"] == {"will": "Top drawer of the desk, blue folder", "passwords": "Aunt Mary"}
    for bad in ("password is hunter2", "PIN: 4821", "account 1234567890"):
        r = _post(c, "/today/emergency/where", token, safe=bad)
        assert "never a password" in r.text, bad
    assert "safe" not in json.loads((modules("paths").CONFIG / "family.json").read_text(encoding="utf-8"))["emergency"]["where"]
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert "emergency_where_set\tfields=will,passwords" in log and "Aunt Mary" not in log
    # the sealed copy: refused without a good passphrase; else one HTML file the passphrase opens
    assert _post(c, "/brief/doc/emergency/sealed", token, passphrase="short", again="short").status_code == 400
    assert _post(c, "/brief/doc/emergency/sealed", token, passphrase="correct horse", again="correct house").status_code == 400
    r = _post(c, "/brief/doc/emergency/sealed", token, passphrase="correct horse battery", again="correct horse battery")
    assert r.status_code == 200 and "emergency_sheet_sealed.html" in r.headers["content-disposition"]
    assert "Aunt Mary" not in r.text and "correct horse" not in r.text, "nothing readable without the passphrase"
    data = json.loads(_re.search(r"var D = (\{.*?\});", r.text).group(1))
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    key = PBKDF2HMAC(hashes.SHA256(), 32, base64.b64decode(data["salt"]), data["iter"]).derive(b"correct horse battery")
    plain = AESGCM(key).decrypt(base64.b64decode(data["iv"]), base64.b64decode(data["ct"]), None).decode()
    assert plain.startswith("# Emergency sheet") and "Aunt Mary" in plain
    assert c.post("/brief/doc/emergency/sealed", data={"passphrase": "x" * 12, "again": "x" * 12}).status_code == 403


def test_briefing_markdown_is_rendered_and_escaped(modules):
    app_mod = modules("webapp.app")
    out = app_mod.render_md("# Week\n\n| A | B |\n|---|---|\n| <script>x</script> | [go](javascript:alert(1)) |\n")
    assert "<h1>" in out and "<table>" in out
    assert "<script>" not in out and "&lt;script&gt;" in out
    assert "javascript:" not in out
    code = app_mod.render_md("Files under `archive/2026/<category>` and `<b>x</b>`")
    assert "<code>archive/2026/&lt;category&gt;</code>" in code and "&amp;lt;" not in code and "<b>" not in code


# ---- Inbox ------------------------------------------------------------------------------------------------------
def _add_proposal(modules, key, source="statement", kind="decision", summary="A statement is missing"):
    paths = modules("paths")
    con = sqlite3.connect(paths.DB)
    try:
        with con:
            con.execute("INSERT OR REPLACE INTO proposals(dedupe_key, source, kind, summary, detail, payload) "
                        "VALUES (?,?,?,?,?,?)", (key, source, kind, summary, "", "{}"))
            return con.execute("SELECT id FROM proposals WHERE dedupe_key=?", (key,)).fetchone()[0]
    finally:
        con.close()


def test_inbox_needs_an_adult_and_a_token(web):
    c, _, _ = web
    assert c.get("/add").status_code == 303
    assert c.post("/inbox/upload", content=b"%PDF-1.4 x", headers={"X-Filename": "a.pdf"}).status_code == 403
    _login(c, "Kid", "0000")
    assert c.get("/add").status_code == 403 and c.get("/inbox/body").status_code == 403
    token = _csrf(c)
    r = c.post("/inbox/upload", content=b"%PDF-1.4 x", headers={"X-Filename": "a.pdf", "X-CSRF-Token": token})
    assert r.status_code == 403  # a limited person may not add files
    assert _post(c, "/inbox/decide", token, id="1", option="dismiss").status_code == 403
    c.cookies.clear()
    _login(c)
    assert c.post("/inbox/decide", data={"id": "1", "option": "dismiss"}).status_code == 403  # no CSRF token
    r = c.get("/inbox?view=files")
    assert r.status_code == 303 and r.headers["location"] == "/add?view=files", "the Inbox lives on Add"
    r = c.get("/add?view=files")
    assert r.status_code == 200 and "Drop files here" in r.text and "<h1>Add</h1>" in r.text
    tiles = r.text.split('class="addtiles"', 1)[1].split("</nav>", 1)[0]
    assert tiles.count('class="addtile"') == 11 and 'href="/records?domain=people&amp;section=people#add-members"' in tiles
    assert 'id="add-members"' in c.get("/records?domain=people&section=people").text, "the tile opens that form"
    assert c.get("/inbox/progress").status_code == 200
    for v in ("all", "files", "money", "family", "decisions", "questions", "nonsense"):
        assert c.get(f"/inbox/body?view={v}").status_code == 200


def test_inbox_upload_checks(web, modules):
    c, _, _ = web
    _login(c)
    h = {"X-CSRF-Token": _csrf(c)}
    paths = modules("paths")

    def up(name, body):
        import urllib.parse
        return c.post("/inbox/upload", content=body, headers={**h, "X-Filename": urllib.parse.quote(name)})
    r = up("../../evil dir/Water bill.PDF", b"%PDF-1.4 hello")
    assert r.status_code == 200 and r.json()["ok"], r.text
    saved = r.json()["message"].removeprefix("Saved as ")
    assert (paths.INBOX / saved).read_bytes() == b"%PDF-1.4 hello"
    assert saved == "Water bill.pdf" and not (paths.INBOX.parent / "evil dir").exists()
    again = up("Water bill.pdf", b"%PDF-1.4 other")  # never overwrites
    assert again.json()["message"].endswith("Water bill_2.pdf")
    assert up("run.exe", b"MZ\x90\x00").status_code == 400  # type not accepted
    assert up("page.pdf", b"<html><script>x</script>").status_code == 400  # content must match the name
    assert up("empty.pdf", b"").status_code == 400
    r = up("big.pdf", b"%PDF" + b"0" * (25 * 1024 * 1024))
    assert r.status_code == 413


def test_inbox_decide_runs_the_fixed_handler(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    pid = _add_proposal(modules, "statement:test-web-1")
    html = c.get("/inbox/body").text
    assert "A statement is missing" in html
    r = _post(c, "/inbox/decide", token, id="99999", option="dismiss")
    assert "no longer on the list" in r.text
    r = _post(c, "/inbox/decide", token, id=str(pid), option="format_disk")  # not one of the card's choices
    assert "not available" in r.text
    r = _post(c, "/inbox/decide", token, id=str(pid), option="dismiss")
    assert "Dismissed" in r.text and "A statement is missing" not in r.text
    r = _post(c, "/inbox/decide", token, id=str(pid), option="dismiss")  # already handled
    assert "already handled" in r.text


def test_inbox_filing_form_needs_its_answers(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    pid = _add_proposal(modules, "review:test-web-2", source="review", kind="file", summary="A paper to file")
    html = c.get("/inbox/body").text
    assert 'name="vendor"' in html and 'name="type"' in html
    r = _post(c, "/inbox/decide", token, id=str(pid), option="file", type="not_a_type", vendor="", date="2026-01-01")
    assert "Please fill in" in r.text  # a bad type is dropped, a blank sender is refused


# ---- Chat -------------------------------------------------------------------------------------------------------
def _nonce(html):
    m = re.search(r'"nonce": "([^"]+)"', html)
    return m.group(1) if m else None


def test_chat_needs_an_adult_and_a_token(web):
    c, _, _ = web
    assert c.get("/chat").status_code == 303
    _login(c, "Kid", "0000")
    assert c.get("/chat").status_code == 403 and c.get("/chat/body").status_code == 403
    token = _csrf(c)
    assert _post(c, "/chat/say", token, text="what do we owe").status_code == 403
    assert _post(c, "/chat/chip", token, key="owe").status_code == 403
    c.cookies.clear()
    _login(c)
    assert c.post("/chat/say", data={"text": "hello"}).status_code == 403  # no CSRF token
    r = c.get("/chat")
    assert r.status_code == 200 and "What is due this week?" in r.text and 'href="/chat"' in r.text


def test_chat_chips_answer_from_the_records_without_ai(web, modules, monkeypatch):
    c, _, _ = web
    cd = modules("chat_data")
    monkeypatch.setattr(cd, "ai_ready", lambda: False)
    _login(c)
    token = _csrf(c)
    r = _post(c, "/chat/chip", token, key="owe")
    assert r.status_code == 200 and "What do we owe?" in r.text and ("bill" in r.text.lower())
    before = r.text.count('class="msg user"')
    r = _post(c, "/chat/chip", token, key="format_disk")  # not a chip on offer: nothing is said or done
    assert r.text.count('class="msg user"') == before
    r = _post(c, "/chat/say", token, text="zzqx nothing matches this")
    assert "I found nothing with those words" in r.text
    _sql(modules, "INSERT INTO bills(name, vendor, frequency, amount, due_date, status) VALUES ('Zorbo Electric', 'Zorbo Power', 'monthly', 80, '2030-01-05', 'due')")
    r = _post(c, "/chat/say", token, text="zorbo power")  # a bill, not a paper or a list item
    assert "Here is what I found" in r.text and "Record: " in r.text and "Zorbo" in r.text
    r = _post(c, "/chat/clear", token)
    assert 'class="msg' not in r.text


def test_chat_change_runs_only_with_the_cards_nonce(web, modules, monkeypatch):
    c, _, _ = web
    cd = modules("chat_data")
    monkeypatch.setattr(cd, "ai_ready", lambda: True)
    monkeypatch.setattr(cd, "describe_pending", lambda pend, today: ["Add a dentist visit"])
    writes = [("life_add", {"title": "Dentist", "kind": "medical"})]
    answer = ("Sure <script>alert(1)</script> see [this](https://evil.example/?d=secret) "
              "![x](https://evil.example/p.png)")
    monkeypatch.setattr(cd.aa, "ask", lambda user, text, history=None: {
        "lines": [answer], "answer": answer, "needs_confirm": True, "writes": writes, "refs": [], "ok": True})
    made = []
    monkeypatch.setattr(cd.aa, "confirm", lambda user, w: made.append(list(w)) or {"lines": ["Saved."], "refs": [], "ok": True})
    _login(c)
    token = _csrf(c)
    r = _post(c, "/chat/say", token, text="add a dentist visit")
    assert "Yes, save it" in r.text and "Add a dentist visit" in r.text
    assert "<script>alert" not in r.text and "evil.example" not in r.text and "<img" not in r.text
    nonce = _nonce(r.text)
    assert nonce
    r = _post(c, "/chat/answer", token, nonce="wrong", yes="1",
              writes='[["purge", {"all": true}]]')  # the browser cannot hand in changes, or guess the card
    assert made == [] and "Yes, save it" in r.text
    r = _post(c, "/chat/answer", token, nonce=nonce, yes="1")
    assert made == [[("life_add", {"title": "Dentist", "kind": "medical"})]] and "Saved." in r.text
    _post(c, "/chat/answer", token, nonce=nonce, yes="1")  # a second click runs nothing
    assert len(made) == 1
    r = _post(c, "/chat/say", token, text="and again")
    _post(c, "/chat/answer", token, nonce=_nonce(r.text), yes="0")
    assert len(made) == 1


def test_chat_questions_are_capped_per_hour(web, modules, monkeypatch):
    c, _, _ = web
    cd = modules("chat_data")
    monkeypatch.setattr(cd, "ai_ready", lambda: True)
    monkeypatch.setattr(cd, "ASK_PER_HOUR", 2)
    asked = []
    monkeypatch.setattr(cd.aa, "ask", lambda user, text, history=None: asked.append(text) or {
        "lines": ["ok"], "answer": "ok", "needs_confirm": False, "writes": [], "refs": [], "ok": True})
    _login(c)
    token = _csrf(c)
    for q in ("one", "two", "three"):
        r = _post(c, "/chat/say", token, text=q)
    assert asked == ["one", "two"] and "questions this hour" in r.text


def test_chat_answers_keep_no_links_or_images(modules):
    app_mod = modules("webapp.app")
    out = app_mod.render_md("Pay [here](https://x.example/pay) ![t](https://x.example/t.png) **now**", links=False)
    assert "<a" not in out and "<img" not in out and "x.example" not in out
    assert "here" in out


# ---- Calendar -----------------------------------------------------------------------------------------------------
def _add_bill(modules, vendor, due):
    con = sqlite3.connect(modules("paths").DB)
    try:
        with con:
            con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES (?,?,?,?,'due')",
                        ("Test bill", vendor, 12.5, due))
    finally:
        con.close()


def test_calendar_needs_an_adult(web):
    c, _, _ = web
    assert c.get("/calendar").status_code == 303
    _login(c, "Kid", "0000")
    for path in ("/calendar", "/calendar/body", "/calendar/google"):
        assert c.get(path).status_code == 403
    c.cookies.clear()
    _login(c)
    r = c.get("/calendar")
    assert r.status_code == 200 and 'href="/calendar"' in r.text and "/p/calendar" not in r.text


def test_calendar_views_and_bad_parameters(web):
    import datetime as dt
    c, _, _ = web
    _login(c)
    for v in ("week", "month", "year", "nonsense"):
        for ref in ("", "2026-02-29", "9999-01-01", "<script>", "2026-03-15"):
            r = c.get(f"/calendar/body?view={v}&ref={ref}")
            assert r.status_code == 200 and "<script>" not in r.text
    today = dt.date.today()
    week = c.get("/calendar/body?view=x&ref=bad").text  # a rolling week from today
    assert f"{today:%b} {today.day} to " in week and f"ref={(today + dt.timedelta(days=7)).isoformat()}" in week
    r = c.get("/calendar/body?view=month&ref=2026-03-15")
    assert "March 2026" in r.text and "ref=2026-02-01" in r.text and "ref=2026-04-01" in r.text  # Prev / Next
    assert "2027" in c.get("/calendar/body?view=year&ref=2026-06-01").text  # Next year link


def test_calendar_shows_records_escaped(web, modules):
    c, _, _ = web
    _login(c)
    _add_bill(modules, "<img src=x onerror=alert(1)>Power", "2026-05-14")
    for v in ("week", "month", "year"):
        r = c.get(f"/calendar/body?view={v}&ref=2026-05-14")
        assert "<img src=x" not in r.text
        assert "&lt;img src=x onerror=alert(1)&gt;Power" in r.text
    assert "k-bill" in c.get("/calendar/body?view=week&ref=2026-05-14").text
    css = c.get("/tokens.css").text
    assert ".k-bill{--k:#c0392b}" in css
    week = c.get("/calendar/body?view=week&ref=2026-05-14").text
    card = week.split('class="story deck calc"')[1].split('<p class="shint"')[0]
    assert card.count('class="slide ') == 3 and "<img src=x" not in card and ">Bill<" in card
    assert ' style="' not in card and 'class="k-bill"' in card, "glance: kind bars coloured by class, no inline styles"
    assert 'class="story' not in c.get("/calendar/body?view=year&ref=2026-05-14").text, "no glance card on the year view"


def test_calendar_glance_counts_kinds_people_and_big_dates(modules):
    import datetime as dt
    cd = modules("calendar_data")
    d = dt.date(2026, 5, 11)
    cells = [{"date": d, "things": [("Bill", "Power $80"), ("Class", "Swim (Mia)"), ("Birthday", "Mia's birthday")]},
             {"date": d + dt.timedelta(days=1), "things": [("Class", "Swim (Mia)"), ("Holiday", "Memorial Day")]},
             {"date": d + dt.timedelta(days=2), "things": []}]
    g = cd.glance(cells, d + dt.timedelta(days=1), names=["Mia", "Leo"])
    assert g["total"] == 5 and g["upcoming"] == 2 and g["kinds"][0] == {"kind": "Class", "n": 2, "cls": "k-class"}
    assert [(p["name"], p["n"]) for p in g["people"]] == [("Mia", 3), ("Everyone", 2)]
    assert g["busiest"] == {"date": d, "n": 3}
    assert [t for _, _, t in g["big"]] == ["Memorial Day", "Mia's birthday"], "upcoming big dates first, then past ones"


def test_calendar_google_off_ok_and_error(web, modules, monkeypatch):
    import datetime as dt
    c, _, _ = web
    _login(c)
    gc, cd = modules("google_calendar"), modules("calendar_data")
    cd._cache.clear()
    monkeypatch.setattr(gc, "status", lambda: {"enabled": False, "signed_in": False})
    assert "Not connected" in c.get("/calendar/google").text
    monkeypatch.setattr(gc, "status", lambda: {"enabled": True, "signed_in": True})
    calls = []

    def events(days, today):
        calls.append(days)
        return [{"date": today.isoformat(), "time": "", "end": "", "all_day": True, "title": "<b>Dentist</b>"}]
    monkeypatch.setattr(gc, "events", events)
    r = c.get("/calendar/google?days=999")
    assert "&lt;b&gt;Dentist&lt;/b&gt;" in r.text and calls == [14]  # odd look-ahead falls back to 14
    c.get("/calendar/google?days=14")
    assert calls == [14]  # cached for five minutes

    def broken(days, today):
        raise gc.CalendarError("Sign in to Google again.")
    monkeypatch.setattr(gc, "events", broken)
    assert "Sign in to Google again." in c.get("/calendar/google?days=7").text
    assert cd.google(7, dt.date.today())[0] == "error"


# ---- Notes -------------------------------------------------------------------------------------------------------
def _add_saved(modules, title, audience="family", owner=None, url=None, kind="note"):
    S = modules("saved")
    con = sqlite3.connect(modules("paths").DB)
    try:
        with con:
            return S.add(con, title, url=url, kind=kind, audience=audience, owner=owner)[0]
    finally:
        con.close()


def test_notes_needs_an_adult_and_a_token(web):
    c, _, _ = web
    assert c.get("/notes").status_code == 303 and c.get("/notes/body").status_code == 303
    _login(c, "Kid", "0000")
    assert c.get("/notes").status_code == 403 and c.get("/notes/body").status_code == 403
    token = _csrf(c)
    assert _post(c, "/notes/add", token, title="Hi").status_code == 403
    assert _post(c, "/notes/act", token, id="1", op="pin").status_code == 403
    c.cookies.clear()
    _login(c)
    r = c.get("/notes")
    assert r.status_code == 200 and 'href="/notes"' in r.text and "/p/notes" not in r.text
    assert c.post("/notes/add", data={"title": "Hi"}).status_code == 403  # no CSRF token


def test_notes_add_escapes_and_cleans_links(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    r = _post(c, "/notes/add", token, title="<img src=x onerror=alert(1)>Pizza", url="https://example.com/menu?utm_source=x&a=1",
              new_kind="place", note="<b>best</b> crust", new_tags="food, goa", audience="family")
    assert r.status_code == 200 and r.headers.get("x-saved") == "1"
    assert "<img src=x" not in r.text and "&lt;img src=x onerror=alert(1)&gt;Pizza" in r.text
    assert "&lt;b&gt;best&lt;/b&gt; crust" in r.text and "#goa" in r.text
    assert 'href="https://example.com/menu?a=1"' in r.text and 'rel="noopener noreferrer nofollow"' in r.text
    for bad in ("javascript:alert(1)", "data:text/html,hi", "file:///C:/x"):
        r = _post(c, "/notes/add", token, title="Bad link", url=bad)
        assert r.status_code == 200 and "x-saved" not in r.headers and 'class="alert"' in r.text
        assert bad not in r.text
    r = _post(c, "/notes/add", token, title="", url="")
    assert "x-saved" not in r.headers and 'class="alert"' in r.text
    r = _post(c, "/notes/add", token, title="Odd", audience="everyone")
    assert "Choose who sees it." in r.text
    r = _post(c, "/notes/add", token, title="Deal", until="soon")
    assert "not a date" in r.text


def test_notes_keep_other_peoples_private_items_hidden(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    theirs = _add_saved(modules, "Bob secret", audience="private", owner="Bob")
    mine = _add_saved(modules, "Ann secret", audience="private", owner="Ann")
    _add_saved(modules, "Adults plan", audience="adults")
    body = c.get("/notes/body?all=1").text
    assert "Bob secret" not in body and "Ann secret" in body and "Adults plan" in body
    for op in ("pin", "archive", "tags"):
        r = _post(c, "/notes/act", token, id=str(theirs), op=op, tags="x")
        assert "no longer exists" in r.text and "Bob secret" not in r.text
    assert "Pinned" in _post(c, "/notes/act", token, id=str(mine), op="pin").text


def test_notes_actions_and_filters(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    a = _add_saved(modules, "Voice cloning repo", kind="repo")
    _add_saved(modules, "Goa beach shack", kind="place")
    assert _post(c, "/notes/act", token, id=str(a), op="drop").status_code == 400
    assert "no longer exists" in _post(c, "/notes/act", token, id="abc", op="pin").text
    r = _post(c, "/notes/act", token, id=str(a), op="tags", tags="ai, tools")
    assert "Tags: ai, tools" in r.text
    def card(html):
        return html.split("Voice cloning repo</h2>")[0].rsplit("<article", 1)[1]
    assert "ncard pinned" in card(_post(c, "/notes/act", token, id=str(a), op="pin").text), "pinned: gradient card"
    assert "ncard pinned" not in card(_post(c, "/notes/act", token, id=str(a), op="unpin").text)
    r = c.get("/notes/body?tag=ai")
    assert "Voice cloning repo" in r.text and "Goa beach shack" not in r.text
    r = c.get("/notes/body?kind=place&q=beach")
    assert "Goa beach shack" in r.text and "Voice cloning repo" not in r.text
    page = c.get("/notes").text  # kind chips with counts, extra filters folded
    import re
    assert re.search(r'name="kind" value="place"\s*>\s*<span>Places <small>\d+</small>', page), page[page.find("nkinds"):][:600]
    assert 'class="nmore"' in page
    assert 'class="nmenu"' in c.get("/notes/body").text  # unpinned rows: actions behind the ... menu
    r = c.get("/notes/body?kind=<script>&tag=nope&who=Nobody")  # unknown choices are ignored, not used
    assert "Goa beach shack" in r.text and "Voice cloning repo" in r.text and "<script>" not in r.text
    r = _post(c, "/notes/act", token, id=str(a), op="archive", q="voice")  # the filter comes back with the list
    assert "Archived" in r.text and "Voice cloning repo" not in r.text.split("</p>", 1)[1]
    assert "Voice cloning repo" in c.get("/notes/body?all=1").text


# ---- Records -----------------------------------------------------------------------------------------------------
def _sql(modules, sql, *params):
    con = sqlite3.connect(modules("paths").DB)
    try:
        with con:
            return con.execute(sql, params).lastrowid
    finally:
        con.close()


def test_records_needs_an_adult(web):
    c, _, _ = web
    assert c.get("/records").status_code == 303 and c.get("/records/paper/1").status_code == 303
    _login(c, "Kid", "0000")
    assert c.get("/records").status_code == 403 and c.get("/records/paper/1").status_code == 403
    assert c.get("/records?ref=members:1").status_code == 403
    c.cookies.clear()
    _login(c)
    r = c.get("/records")
    assert r.status_code == 303 and r.headers["location"] == "/family", "the Records home is Family now"
    r = c.get("/family")
    assert 'action="/records"' in r.text and 'aria-label="Family"' in r.text and "/p/records" not in r.text


def test_records_lists_detail_and_search_are_escaped(web, modules):
    c, _, _ = web
    _login(c)
    lid = _sql(modules, "INSERT INTO life_items (domain, member, title, status) VALUES ('school', 'Sam', ?, 'open')",
               "<script>alert(1)</script>Recital")
    r = c.get("/records?domain=people&section=life")
    assert r.status_code == 200 and "<script>alert(1)" not in r.text and "&lt;script&gt;alert(1)&lt;/script&gt;Recital" in r.text
    assert f'href="/records?ref=life_items%3A{lid}"' in r.text
    r = c.get(f"/records?ref=life_items:{lid}")
    assert "<script>alert(1)" not in r.text and "Show all life items" in r.text and "classic" not in r.text.lower()
    r = c.get("/records?q=recital")
    assert "1 found for" in r.text and f"life_items%3A{lid}" in r.text
    assert "Search: every record" in r.text and "People · People" not in r.text  # hits can be from any area
    r = c.get("/records?q=<b>zzqq</b>")
    assert "Nothing found" in r.text and "<b>zzqq" not in r.text
    assert "does not point to a record" in c.get("/records?ref=sqlite_master:1").text
    assert "does not point to a record" in c.get("/records?ref=members:1;DROP").text
    r = c.get("/family")  # Family's chips open every area
    assert 'href="/records?domain=people"' in r.text and 'href="/records?domain=papers"' in r.text and 'href="/wallet"' in r.text
    r = c.get("/records?domain=people&section=life")
    assert "rlist fl-phone" in r.text and "Recital" in r.text and "<h1>Family</h1>" in r.text
    assert 'class="pchip on" aria-current="true">People</a>' in r.text
    r = c.get("/records?domain=nowhere&section=<x>")  # unknown choices fall back to People
    assert r.status_code == 200 and "<x>" not in r.text
    r = c.get("/records?domain=money&section=bills")  # Finance parts open in the web app's Finance page
    assert r.status_code == 303 and r.headers["location"] == "/money?part=bills"
    assert c.get("/records?domain=money&section=evil").headers["location"] == "/money?part=home"


def test_records_home_needs_a_look_and_phone_rows(web, modules):
    c, _, _ = web
    _login(c)
    lid = _sql(modules, "INSERT INTO life_items (domain, member, title, status, due_date) VALUES ('school', 'Sam', "
               "'Permission slip', 'open', '2000-01-05')")
    r = c.get("/family")
    assert "Needs a look" in r.text and "Sam: Permission slip was due" in r.text
    assert f'href="/records?ref=life_items%3A{lid}"' in r.text
    r = c.get("/records?domain=people&section=life")
    assert "overdue" in r.text and 'class="chip-s t-bad"' in r.text
    r = c.get(f"/records?ref=life_items:{lid}")
    assert "<h1>Permission slip" in r.text and 'class="fback" href="/records?domain=people&amp;section=life"' in r.text


def test_records_keep_private_saved_items_private(web, modules):
    c, _, _ = web
    _login(c)
    theirs = _add_saved(modules, "Bob zebra secret", audience="private", owner="Bob")
    r = c.get(f"/records?ref=saved_items:{theirs}")
    assert "Bob zebra secret" not in r.text and "not there any more, or it is private" in r.text
    assert "Bob zebra secret" not in c.get("/records?q=zebra").text


def test_records_paper_download_stays_inside_the_archive(web, modules, root):
    c, _, _ = web
    _login(c)
    paths = modules("paths")
    f = paths.ARCHIVE / "2026" / "bills" / "2026-01-02_power_bill.pdf"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(b"%PDF-1.4 test")
    good = _sql(modules, "INSERT INTO documents (filed_path, doc_type, vendor, doc_date) VALUES (?, 'bill', 'Power', '2026-01-02')",
                str(f.relative_to(paths.HOME)))
    bad = _sql(modules, "INSERT INTO documents (filed_path, doc_type, vendor, doc_date) VALUES (?, 'bill', 'Evil', '2026-01-03')",
               "../config/family.json")
    r = c.get(f"/records?ref=documents:{good}")
    assert f'href="/records/paper/{good}"' in r.text
    r = c.get(f"/records/paper/{good}")
    assert r.status_code == 200 and r.content == b"%PDF-1.4 test"
    assert r.headers["content-type"] == "application/octet-stream" and "attachment" in r.headers["content-disposition"]
    assert r.headers["cache-control"] == "no-store"
    assert c.get(f"/records/paper/{bad}").status_code == 404
    assert f"/records/paper/{bad}" not in c.get(f"/records?ref=documents:{bad}").text
    assert c.get("/records/paper/999999").status_code == 404
    assert c.get("/records/paper/abc").status_code == 422


def _one(modules, sql, *params):
    con = sqlite3.connect(modules("paths").DB)
    try:
        return con.execute(sql, params).fetchone()
    finally:
        con.close()


def test_records_edits_need_an_adult_and_a_token(web, modules):
    c, _, _ = web
    lid = _sql(modules, "INSERT INTO life_items (domain, member, title, status) VALUES ('school', 'Sam', 'Recital', 'open')")
    _login(c, "Kid", "0000")
    token = _csrf(c)
    assert _post(c, "/records/edit", token, table="life_items", id=str(lid), op="drop", sure="1").status_code == 403
    assert _post(c, "/records/add", token, part="people/life", domain="school", title="x").status_code == 403
    c.cookies.clear()
    _login(c)
    assert c.post("/records/edit", data={"table": "life_items", "id": str(lid), "op": "drop", "sure": "1"}).status_code == 403
    token = _csrf(c)
    for bad in ({"table": "documents", "op": "save"}, {"table": "life_items", "op": "delete"}, {"table": "sqlite_master", "op": "save"}):
        assert _post(c, "/records/edit", token, id=str(lid), **bad).status_code == 400
    assert _post(c, "/records/add", token, part="money/bills", title="x").status_code == 400
    assert _one(modules, "SELECT status FROM life_items WHERE id=?", lid)[0] == "open"


def test_records_life_item_add_change_done_remove(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    r = c.get("/records?domain=people&section=life")
    assert "Add an item" in r.text and 'id="radd-life_items"' in r.text and "Open a row to change it here" in r.text
    r = _post(c, "/records/add", token, part="people/life", domain="medical", who="Sam", title="<b>Dentist</b>", due="2030-01-05",
              every="6", amount="0", provider="Dr Lee")
    assert r.status_code == 200 and r.headers["hx-redirect"] == "/records?domain=people&section=life"
    lid, member, recur, amount = _one(modules, "SELECT id, member, recur_months, amount FROM life_items WHERE title='<b>Dentist</b>'")
    assert (member, recur, amount) == ("Sam", 6, None)
    page = c.get("/records?domain=people&section=life").text
    assert "Added" in page and "<b>Dentist</b>" not in page  # flash shown once, escaped
    assert "Added" not in c.get("/records?domain=people&section=life").text
    r = _post(c, "/records/add", token, part="people/life", domain="medical", who="Nobody", title="Kept typed")
    assert r.status_code == 200 and "hx-redirect" not in r.headers and 'class="alert"' in r.text and 'value="Kept typed"' in r.text
    det = c.get(f"/records?ref=life_items:{lid}").text
    assert 'id="redit"' in det and "Mark done" in det and "Change it in the classic dashboard" not in det
    r = _post(c, "/records/edit", token, table="life_items", id=str(lid), op="save", title="Dentist", who="household", due="",
              every="0", amount="25", provider="")
    assert r.headers["hx-redirect"] == f"/records?ref=life_items%3A{lid}"
    assert _one(modules, "SELECT title, member, due_date, recur_months, amount, provider FROM life_items WHERE id=?", lid) == \
        ("Dentist", None, None, None, 25.0, None)
    r = _post(c, "/records/edit", token, table="life_items", id=str(lid), op="save", title="", who="household")
    assert "hx-redirect" not in r.headers and 'class="alert"' in r.text
    r = _post(c, "/records/edit", token, table="life_items", id=str(lid), op="drop")
    assert "Tick" in r.text and _one(modules, "SELECT status FROM life_items WHERE id=?", lid)[0] == "open"
    r = _post(c, "/records/edit", token, table="life_items", id=str(lid), op="done")
    assert r.headers["hx-redirect"] == "/records?domain=people&section=life"  # a one-off is finished: back to the list
    assert _one(modules, "SELECT status FROM life_items WHERE id=?", lid)[0] == "done"
    assert 'id="redit"' not in c.get(f"/records?ref=life_items:{lid}").text  # finished items are not changed here
    r = _post(c, "/records/edit", token, table="life_items", id=str(lid), op="save", title="Again")
    assert r.headers["hx-redirect"] == "/records?domain=people&section=life"
    assert "already finished" in c.get("/records?domain=people&section=life").text
    rid = _sql(modules, "INSERT INTO life_items (domain, title, status, due_date, recur_months) VALUES ('chore', 'Gutters', 'open', "
               "'2026-01-01', 12)")
    r = _post(c, "/records/edit", token, table="life_items", id=str(rid), op="done")
    assert r.headers["hx-redirect"] == f"/records?ref=life_items%3A{rid}"  # a repeating one moves to its next date
    _post(c, "/records/edit", token, table="life_items", id=str(rid), op="drop", sure="1")
    assert _one(modules, "SELECT status FROM life_items WHERE id=?", rid)[0] == "dropped"
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert f"life_drop\tid={rid}" in log and "\tAnn\t" in log


def test_records_people_and_checkups(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    sid = _one(modules, "SELECT id FROM members WHERE name='Sam'")[0]
    det = c.get(f"/records?ref=members:{sid}").text
    assert "Edit " in det and "fix a typo" in det and 'value="09-02"' in det
    r = _post(c, "/records/edit", token, table="members", id=str(sid), op="save", role="child", birthday="13-40", year="")
    assert 'class="alert"' in r.text and 'value="13-40"' in r.text
    _post(c, "/records/edit", token, table="members", id=str(sid), op="save", role="child", birthday="09-03", year="2015")
    assert _one(modules, "SELECT birth_month_day, birth_year FROM members WHERE id=?", sid) == ("09-03", 2015)
    r = _post(c, "/records/edit", token, table="members", id=str(sid), op="save", role="boss", birthday="", year="")
    assert 'class="alert"' in r.text and _one(modules, "SELECT role FROM members WHERE id=?", sid)[0] == "child"
    r = _post(c, "/records/add", token, part="people/people", name="Rex", role="pet", birthday="", year="")
    assert r.headers["hx-redirect"] == "/records?domain=people&section=people"
    assert _one(modules, "SELECT role FROM members WHERE name='Rex'")[0] == "pet"
    assert "already in the family" in _post(c, "/records/add", token, part="people/people", name="rex", role="pet").text
    cid = _sql(modules, "INSERT INTO recurring_items (name, category, who, interval_months, active) VALUES "
               "('Eye exam', 'Health', 'Sam', 12, 1)")
    det = c.get(f"/records?ref=recurring_items:{cid}").text
    assert "Record it as done" in det
    assert "future" in _post(c, "/records/edit", token, table="recurring_items", id=str(cid), op="done", when="2999-01-01").text
    r = _post(c, "/records/edit", token, table="recurring_items", id=str(cid), op="done", when="2026-02-03", provider="Vision Co")
    assert r.headers["hx-redirect"] == f"/records?ref=recurring_items%3A{cid}"
    assert _one(modules, "SELECT last_done, provider FROM recurring_items WHERE id=?", cid) == ("2026-02-03", "Vision Co")


def test_records_bill_paid_and_undo(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    bid = _sql(modules, "INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Water', 'City Water', 40, '2026-01-10', 'due')")
    assert "Open a row to change it here" in c.get("/money?part=bills&month=2026-01").text
    det = c.get(f"/records?ref=bills:{bid}").text
    assert "Mark it paid" in det and "Change it in the classic dashboard" not in det
    assert "Money · Bills" in det and 'href="/records?domain=people"' not in det  # no Records lists under a Finance row
    assert "future" in _post(c, "/records/edit", token, table="bills", id=str(bid), op="paid", when="2999-01-01").text
    assert "not marked paid" in _post(c, "/records/edit", token, table="bills", id=str(bid), op="unpaid").text
    r = _post(c, "/records/edit", token, table="bills", id=str(bid), op="paid", when="2026-01-09")
    assert r.headers["hx-redirect"] == f"/records?ref=bills%3A{bid}"
    assert _one(modules, "SELECT status, paid_date FROM bills WHERE id=?", bid) == ("paid", "2026-01-09")
    det = c.get(f"/records?ref=bills:{bid}").text
    assert "Marked City Water as paid." in det and "Mark as not paid" in det
    assert "not open any more" in _post(c, "/records/edit", token, table="bills", id=str(bid), op="paid").text
    _post(c, "/records/edit", token, table="bills", id=str(bid), op="unpaid")
    assert _one(modules, "SELECT status, paid_date FROM bills WHERE id=?", bid) == ("overdue", None)
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert f"bill_paid\tid={bid}" in log and f"bill_unpaid\tid={bid}" in log


def test_records_subscription_add_decide_and_tracking(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/money?part=subs").text
    assert "Add a subscription" in page and 'id="radd-subscriptions"' in page
    r = _post(c, "/records/add", token, part="money/subs", name="Streamly", amount="12.99", frequency="fortnightly")
    assert "hx-redirect" not in r.headers and 'class="alert"' in r.text and 'value="Streamly"' in r.text
    r = _post(c, "/records/add", token, part="money/subs", name="Streamly", amount="12.99", frequency="monthly", renew="")
    assert r.headers["hx-redirect"] == "/money?part=subs"
    assert "Added Streamly." in c.get("/money?part=subs").text
    sid, active = _one(modules, "SELECT id, active FROM subscriptions WHERE name='Streamly'")
    det = c.get(f"/records?ref=subscriptions:{sid}").text
    assert "Save decision" in det and "Stop tracking it" in det
    assert 'class="alert"' in _post(c, "/records/edit", token, table="subscriptions", id=str(sid), op="decide", decision="maybe").text
    r = _post(c, "/records/edit", token, table="subscriptions", id=str(sid), op="decide", decision="cancel", note="kids stopped")
    assert r.headers["hx-redirect"] == f"/records?ref=subscriptions%3A{sid}"
    _post(c, "/records/edit", token, table="subscriptions", id=str(sid), op="decide", decision="cancelled", note="done online")
    dec, rv, notes = _one(modules, "SELECT decision, reviewed_on, notes FROM subscriptions WHERE id=?", sid)
    assert dec == "cancelled" and rv == dt.date.today().isoformat() and notes == "kids stopped | done online"
    _post(c, "/records/edit", token, table="subscriptions", id=str(sid), op="active")
    assert _one(modules, "SELECT active FROM subscriptions WHERE id=?", sid)[0] == 0
    assert "Track it again" in c.get(f"/records?ref=subscriptions:{sid}").text


def test_records_receipt_add_link_ignore_unlink(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    aid = _sql(modules, "INSERT INTO accounts(name, type, last4) VALUES ('Visa', 'credit', '1111')")
    tid = _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
               aid, "2026-03-05", "CORNER HARDWARE", -23.45)
    other = _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                 aid, "2026-03-05", "GAS STATION", -60.0)
    assert "Add a receipt by hand" in c.get("/money?part=receipts").text
    r = _post(c, "/records/add", token, part="money/receipts", merchant="Bakery", date="2026-03-04", total="7.10", last4="")
    assert r.headers["hx-redirect"] == "/money?part=receipts"
    rid = _one(modules, "SELECT id FROM receipts WHERE merchant='Bakery'")[0]
    det = c.get(f"/records?ref=receipts:{rid}").text
    assert "No charge with this amount yet" in det and "No charge expected" in det
    assert "Pick one of the charges" in _post(c, "/records/edit", token, table="receipts", id=str(rid), op="link", txn=str(other)).text
    _post(c, "/records/edit", token, table="receipts", id=str(rid), op="ignore")
    assert _one(modules, "SELECT status FROM receipts WHERE id=?", rid)[0] == "ignored"
    assert "has changed" in _post(c, "/records/edit", token, table="receipts", id=str(rid), op="ignore").text
    assert "Wait for a charge again" in c.get(f"/records?ref=receipts:{rid}").text
    _post(c, "/records/edit", token, table="receipts", id=str(rid), op="unlink")
    assert _one(modules, "SELECT status FROM receipts WHERE id=?", rid)[0] == "open"
    # a receipt the matcher left open (the charge is a few days off and the name differs): link it by hand
    hid = _sql(modules, "INSERT INTO receipts(merchant, receipt_date, total, status, created_at) VALUES ('Hardware', '2026-03-03', 23.45, 'open', '2026-03-03')")
    det = c.get(f"/records?ref=receipts:{hid}").text
    assert f'value="{tid}"' in det and f'value="{other}"' not in det
    r = _post(c, "/records/edit", token, table="receipts", id=str(hid), op="link", txn=str(tid))
    assert r.headers["hx-redirect"] == f"/records?ref=receipts%3A{hid}"
    assert _one(modules, "SELECT status, transaction_id FROM receipts WHERE id=?", hid) == ("matched", tid)
    assert "Wrong charge? Unlink" in c.get(f"/records?ref=receipts:{hid}").text
    _post(c, "/records/edit", token, table="receipts", id=str(hid), op="unlink")
    assert _one(modules, "SELECT status, transaction_id FROM receipts WHERE id=?", hid) == ("open", None)


def test_finance_budget_lines_set_change_remove(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/money?part=budget").text
    assert "Set or remove a budget line" in page and 'id="radd-budget"' in page and 'id="radd-loans"' in page
    r = _post(c, "/records/add", token, part="money/budget", table="budget", category="Groceries", limit="-5")
    assert "hx-redirect" not in r.headers and 'class="alert"' in r.text and 'value="Groceries"' in r.text
    r = _post(c, "/records/add", token, part="money/budget", table="budget", category="Groceries", limit="600")
    assert r.headers["hx-redirect"] == "/money?part=budget"
    _post(c, "/records/add", token, part="money/budget", table="budget", category="Groceries", limit="650")
    assert _one(modules, "SELECT monthly_limit FROM budget WHERE category='Groceries'") == (650.0,)
    assert '<option value="Groceries">' in c.get("/money?part=budget").text
    assert "no such budget line" in _post(c, "/records/add", token, part="money/budget", table="budget", category="Fun",
                                          remove="1").text
    _post(c, "/records/add", token, part="money/budget", table="budget", category="Groceries", limit="", remove="1")
    assert _one(modules, "SELECT COUNT(*) FROM budget WHERE category='Groceries'") == (0,)
    assert _post(c, "/records/add", token, part="money/budget", table="members", name="X").status_code == 400
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert "budget_set\tcategory=Groceries" in log and "budget_delete\tcategory=Groceries" in log


def test_finance_loan_add_update_paid_off(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    r = _post(c, "/records/add", token, part="money/budget", table="loans", name="Car", kind="boat")
    assert 'class="alert"' in r.text and 'value="Car"' in r.text
    r = _post(c, "/records/add", token, part="money/budget", table="loans", name="Car", kind="auto", lender="CU",
              balance="12000", rate="5.5", payment="400", payoff="")
    assert r.headers["hx-redirect"] == "/money?part=budget"
    lid = _one(modules, "SELECT id FROM loans WHERE name='Car'")[0]
    assert f"loans%3A{lid}" in c.get("/money?part=budget").text
    det = c.get(f"/records?ref=loans:{lid}").text
    assert "Update it" in det and 'value="12000"' in det and "Yes, it is paid off" in det
    r = _post(c, "/records/edit", token, table="loans", id=str(lid), op="save", balance="11500", rate="", payment="",
              payoff="2029-06-01")
    assert r.headers["hx-redirect"] == f"/records?ref=loans%3A{lid}"
    assert _one(modules, "SELECT balance, balance_date, rate_pct, payoff_date FROM loans WHERE id=?", lid) == (
        11500.0, dt.date.today().isoformat(), 5.5, "2029-06-01")
    assert 'class="alert"' in _post(c, "/records/edit", token, table="loans", id=str(lid), op="save", rate="101").text
    assert "Tick" in _post(c, "/records/edit", token, table="loans", id=str(lid), op="status").text
    r = _post(c, "/records/edit", token, table="loans", id=str(lid), op="status", sure="1")
    assert r.headers["hx-redirect"] == "/money?part=budget"
    assert _one(modules, "SELECT status FROM loans WHERE id=?", lid) == ("paid_off",)
    assert "make it active again" in c.get(f"/records?ref=loans:{lid}").text
    _post(c, "/records/edit", token, table="loans", id=str(lid), op="status")
    assert _one(modules, "SELECT status FROM loans WHERE id=?", lid) == ("active",)


def test_finance_account_add_last4_only(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    assert 'id="radd-accounts"' in c.get("/money?part=accounts").text
    r = _post(c, "/records/add", token, part="money/accounts", name="Joint checking", kind="checking",
              last4="123456789", owner="")
    assert "exactly four digits" in r.text and "hx-redirect" not in r.headers
    r = _post(c, "/records/add", token, part="money/accounts", name="Joint checking", kind="checking", last4="6789",
              owner="Ann")
    assert r.headers["hx-redirect"] == "/money?part=accounts"
    assert _one(modules, "SELECT type, last4, owner FROM accounts WHERE name='Joint checking'") == ("checking", "6789", "Ann")
    assert "already ends in 6789" in _post(c, "/records/add", token, part="money/accounts", name="Other", kind="savings",
                                           last4="6789").text
    assert "Account Joint checking added." in c.get("/money?part=accounts").text


def test_records_inventory_add_change_dispose(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/records?domain=home&section=inventory").text
    assert "Add a thing to the inventory" in page and 'id="radd-home_assets"' in page and "Open a row to change it here" in page
    r = _post(c, "/records/add", token, part="home/inventory", name="Fridge", category="spaceship")
    assert 'class="alert"' in r.text and 'value="Fridge"' in r.text
    r = _post(c, "/records/add", token, part="home/inventory", name="Fridge", category="appliance", brand_model="LG X1",
              location="kitchen", purchase_date="2024-05-01", price="1299", warranty_years="2", serial_last4="", notes="")
    assert r.headers["hx-redirect"] == "/records?domain=home&section=inventory"
    aid = _one(modules, "SELECT id FROM home_assets WHERE name='Fridge'")[0]
    det = c.get(f"/records?ref=home_assets:{aid}").text
    assert "Change it" in det and 'value="LG X1"' in det and "Yes, it is gone" in det
    assert "already exists" in _post(c, "/records/add", token, part="home/inventory", name="fridge").text
    r = _post(c, "/records/edit", token, table="home_assets", id=str(aid), op="save", name="Fridge", category="appliance",
              brand_model="LG X1", location="garage", purchase_date="2024-05-01", price="", warranty_end="2026-05-01",
              warranty_years="2", store="Costco", serial_last4="7K2Q", notes="")
    assert r.headers["hx-redirect"] == f"/records?ref=home_assets%3A{aid}"
    assert _one(modules, "SELECT location, price, store, serial_last4 FROM home_assets WHERE id=?", aid) == (
        "garage", None, "Costco", "7K2Q")
    assert "letters and digits only" in _post(c, "/records/edit", token, table="home_assets", id=str(aid), op="save",
                                              name="Fridge", serial_last4="7-2Q").text
    assert "Tick" in _post(c, "/records/edit", token, table="home_assets", id=str(aid), op="dispose", how="sold").text
    r = _post(c, "/records/edit", token, table="home_assets", id=str(aid), op="dispose", how="sold", when="2026-01-02", sure="1")
    assert r.headers["hx-redirect"] == "/records?domain=home&section=inventory"
    assert _one(modules, "SELECT status, disposed_date FROM home_assets WHERE id=?", aid) == ("sold", "2026-01-02")
    assert "Yes, it is gone" not in c.get(f"/records?ref=home_assets:{aid}").text
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert f"asset_add\tid={aid}" in log and f"asset_update\tid={aid}" in log and f"asset_dispose\tid={aid}" in log


def test_records_seasonal_job_done(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    tid = _sql(modules, "INSERT INTO seasonal_tasks(name, category, start_md, end_md) VALUES ('Clean gutters', 'Home', "
                        "'10-01', '11-30')")
    page = c.get("/records?domain=home&section=upkeep").text
    assert "Seasonal jobs" in page and f"seasonal_tasks%3A{tid}" in page and "Oct 1 to Nov 30" in page
    today = dt.date.today()
    future = (today + dt.timedelta(days=3)).isoformat()
    assert "future" in _post(c, "/records/edit", token, table="seasonal_tasks", id=str(tid), op="done", when=future).text
    r = _post(c, "/records/edit", token, table="seasonal_tasks", id=str(tid), op="done", when=today.isoformat(), place="")
    assert r.headers["hx-redirect"] == f"/records?ref=seasonal_tasks%3A{tid}"
    assert _one(modules, "SELECT COUNT(*) FROM seasonal_log WHERE task_id=?", tid) == (1,)
    assert f"last {today.isoformat()}" in c.get(f"/records?ref=seasonal_tasks:{tid}").text


def test_records_vehicle_add_and_service(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/records?domain=vehicles&section=vehicles").text
    assert "Add a vehicle" in page and 'id="radd-vehicles"' in page and "Open a row to change it here" in page
    assert 'class="alert"' in _post(c, "/records/add", token, part="vehicles/vehicles", make="Kia", model="Soul", year="1800").text
    r = _post(c, "/records/add", token, part="vehicles/vehicles", make="Kia", model="Soul", year="2019")
    assert r.headers["hx-redirect"] == "/records?domain=vehicles&section=vehicles"
    vid = _one(modules, "SELECT id FROM vehicles WHERE make='Kia' AND model='Soul'")[0]
    _post(c, "/records/add", token, part="vehicles/vehicles", make="kia", model="soul", year="2019")
    assert _one(modules, "SELECT COUNT(*) FROM vehicles WHERE make='Kia' COLLATE NOCASE AND model='Soul' COLLATE NOCASE") == (1,)
    det = c.get(f"/records?ref=vehicles:{vid}").text
    assert "Log a service" in det and 'value="oil_change"' in det
    future = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    assert "today or earlier" in _post(c, "/records/edit", token, table="vehicles", id=str(vid), op="service",
                                       kind="tires", when=future).text
    assert 'class="alert"' in _post(c, "/records/edit", token, table="vehicles", id=str(vid), op="service", kind="wax").text
    r = _post(c, "/records/edit", token, table="vehicles", id=str(vid), op="service", kind="oil_change", when="2026-02-01",
              odometer="41200", cost="59.99", vendor="Quick Lube")
    assert r.headers["hx-redirect"] == f"/records?ref=vehicles%3A{vid}"
    assert _one(modules, "SELECT kind, log_date, odometer, cost, vendor FROM vehicle_log WHERE vehicle_id=?", vid) == (
        "oil_change", "2026-02-01", 41200, 59.99, "Quick Lube")
    assert "last 41200" in c.get(f"/records?ref=vehicles:{vid}").text
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert f"vehicle_add\tid={vid}" in log and "vehicle_service\tid=" in log


def test_records_id_document_add_and_renew(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/records?domain=papers&section=ids").text
    assert "Add an ID document" in page and 'id="radd-id_documents"' in page and 'value="passport"' in page
    assert "not a family member" in _post(c, "/records/add", token, part="papers/ids", person="Nobody", doc_type="passport",
                                           expires="2031-04-01").text
    assert "letters and digits" in _post(c, "/records/add", token, part="papers/ids", person="Sam", doc_type="passport",
                                         expires="2031-04-01", last4="12-4").text
    r = _post(c, "/records/add", token, part="papers/ids", person="Sam", doc_type="passport", expires="2031-04-01", last4="A123")
    assert r.headers["hx-redirect"] == "/records?domain=papers&section=ids"
    did = _one(modules, "SELECT id FROM id_documents WHERE person='Sam' AND doc_type='passport'")[0]
    det = c.get(f"/records?ref=id_documents:{did}").text
    assert "Renewed? New expiry" in det and 'value="2031-04-01"' in det
    r = _post(c, "/records/edit", token, table="id_documents", id=str(did), op="save", expires="2041-04-01", last4="")
    assert r.headers["hx-redirect"] == f"/records?ref=id_documents%3A{did}"
    assert _one(modules, "SELECT expires, number_last4 FROM id_documents WHERE id=?", did) == ("2041-04-01", "A123")
    assert 'class="alert"' in _post(c, "/records/edit", token, table="id_documents", id=str(did), op="save", expires="soon").text
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert f"id_doc_set\tid={did} type=passport" in log


def test_records_list_board(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    assert 'id="radd-lists"' in c.get("/records?domain=home&section=lists").text
    r = _post(c, "/records/add", token, part="home/lists", name="Camping", kind="packing", adults="1")
    assert r.headers["hx-redirect"] == "/records?domain=home&section=lists"
    lid, aud = _one(modules, "SELECT id, audience FROM lists WHERE name='Camping'")
    assert aud == "adults"
    base = {"table": "lists", "id": str(lid)}
    r = _post(c, "/records/edit", token, **base, op="item_add", text="<b>Tent</b>", qty="1", who="Sam")
    assert r.headers["hx-redirect"] == f"/records?ref=lists%3A{lid}"
    _post(c, "/records/edit", token, **base, op="item_add", text="Stove", qty="", who="")
    tent = _one(modules, "SELECT id FROM list_items WHERE list_id=? AND text LIKE '%Tent%'", lid)[0]
    det = c.get(f"/records?ref=lists:{lid}").text
    assert "&lt;b&gt;Tent&lt;/b&gt;" in det and "<b>Tent</b>" not in det and "Add to the list" in det and "adults only" in det
    # Share the list: the open items as plain text (escaped in the attribute), and Print the list
    assert 'data-share="Camping\n- &lt;b&gt;Tent&lt;/b&gt; · 1\n- Stove"' in det and 'data-share-title="Camping"' in det
    assert "data-print-list" in det and 'class="print-list"' in det
    _post(c, "/records/edit", token, **base, op="tick", item=str(tent))
    assert 'data-share="Camping\n- Stove"' in c.get(f"/records?ref=lists:{lid}").text, "ticked items are not shared"
    assert _one(modules, "SELECT status FROM list_items WHERE id=?", tent) == ("done",)
    det = c.get(f"/records?ref=lists:{lid}").text
    assert "Untick &lt;b&gt;Tent" in det and f'"item": "{tent}"' in det
    _post(c, "/records/edit", token, **base, op="untick", item=str(tent))
    assert _one(modules, "SELECT status FROM list_items WHERE id=?", tent) == ("open",)
    other = _sql(modules, "INSERT INTO lists(name, kind, audience, status, created_at) VALUES ('Other', 'todo', 'family', "
                          "'active', '2026-01-01')")
    oid = _sql(modules, "INSERT INTO list_items(list_id, text, status, added_at) VALUES (?, 'x', 'open', '2026-01-01')", other)
    assert "not on this list" in _post(c, "/records/edit", token, **base, op="drop", item=str(oid)).text
    _post(c, "/records/edit", token, **base, op="tick", item=str(tent))
    _post(c, "/records/edit", token, **base, op="clear")
    assert _one(modules, "SELECT cleared_at IS NOT NULL FROM list_items WHERE id=?", tent) == (1,)
    assert f'"item": "{tent}"' not in c.get(f"/records?ref=lists:{lid}").text
    stove = _one(modules, "SELECT id FROM list_items WHERE list_id=? AND text='Stove'", lid)[0]
    _post(c, "/records/edit", token, **base, op="drop", item=str(stove))
    assert _one(modules, "SELECT status FROM list_items WHERE id=?", stove) == ("dropped",)
    assert "Tick" in _post(c, "/records/edit", token, **base, op="archive").text
    r = _post(c, "/records/edit", token, **base, op="archive", sure="1")
    assert r.headers["hx-redirect"] == "/records?domain=home&section=lists"
    assert _one(modules, "SELECT status FROM lists WHERE id=?", lid) == ("archived",)
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert f"list_new\tid={lid}" in log and f"list_item_tick\tlist={lid}" in log and f"list_archive\tid={lid}" in log


def test_records_meals_plan_recipe_shop(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/records?domain=home&section=meals").text
    assert 'id="radd-meal_plan"' in page and 'id="radd-recipes"' in page and 'id="radd-meal_shop"' in page
    long = "\n".join(f"{i} cup thing{i}" for i in range(60))  # longer than one short field: kept whole
    r = _post(c, "/records/add", token, part="home/meals", table="recipes", name="Big soup", ingredients=long, servings="4")
    assert r.headers["hx-redirect"] == "/records?domain=home&section=meals"
    rid = _one(modules, "SELECT id FROM recipes WHERE name='Big soup'")[0]
    assert _one(modules, "SELECT COUNT(*) FROM recipe_ingredients WHERE recipe_id=?", rid) == (60,)
    day = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    assert 'class="alert"' in _post(c, "/records/add", token, part="home/meals", table="meal_plan", day=day, slot="brunch",
                                    what="Big soup").text
    _post(c, "/records/add", token, part="home/meals", table="meal_plan", day=day, slot="dinner", what="Big soup")
    mid = _one(modules, "SELECT id FROM meal_plan WHERE day=? AND slot='dinner'", day)[0]
    r = _post(c, "/records/add", token, part="home/meals", table="meal_shop", start="", end="", list_name="Groceries")
    assert r.headers["hx-redirect"] == "/records?domain=home&section=meals"
    assert _one(modules, "SELECT COUNT(*) FROM list_items i JOIN lists l ON l.id=i.list_id WHERE l.name='Groceries' "
                         "AND i.text LIKE 'thing%'")[0] > 0
    assert "Take it off the plan" in c.get(f"/records?ref=meal_plan:{mid}").text
    r = _post(c, "/records/edit", token, table="meal_plan", id=str(mid), op="clear")
    assert r.headers["hx-redirect"] == "/records?domain=home&section=meals"
    assert _one(modules, "SELECT COUNT(*) FROM meal_plan WHERE id=?", mid) == (0,)
    assert "Tick" in _post(c, "/records/edit", token, table="recipes", id=str(rid), op="archive").text
    _post(c, "/records/edit", token, table="recipes", id=str(rid), op="archive", sure="1")
    assert _one(modules, "SELECT status FROM recipes WHERE id=?", rid) == ("archived",)


# ---- Settings ----------------------------------------------------------------------------------------------------
def test_settings_groups_render_for_adults_only(web, modules):
    c, _, _ = web
    assert c.get("/settings").status_code == 303
    _login(c, "Kid", "0000")
    assert c.get("/settings?group=agent").status_code == 403
    c.post("/logout", headers={"x-csrf-token": _csrf(c)})
    _login(c)
    for g, words in (("household", "How complete is your profile"), ("agent", "Sign-in PINs"),
                     ("connections", "Phone bot (Telegram)"), ("data", "Health check"), ("evil", "Needs a look"), ("", "Ask me the next question")):
        r = c.get(f"/settings?group={g}")
        assert r.status_code == 200 and words in r.text, g
    assert 'href="/settings"' in c.get("/").text  # the rail links here now, not to the classic page
    r = c.get("/settings")  # the home: profile hero, one lane per group, back link + chips inside a group
    assert 'href="/settings?group=data"' in r.text and 'class="fhero g-over shero"' in r.text
    r = c.get("/settings?group=agent")
    assert 'class="fback" href="/settings"' in r.text and 'class="fchips"' in r.text and 'details class="card sfold" open' in r.text
    r = c.get("/settings/calendar.ics")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar") and "BEGIN:VCALENDAR" in r.text


def test_settings_agent_profile_papers_and_restore(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    moved = []
    ap = modules("agent_profile")
    ap.reschedule = lambda job, profile=None, run=None: moved.append(job)  # never touch this PC's real scheduled tasks
    body = "name=Mitra&tone=warm&brief_time=06%3A30&weekly_day=SAT&weekly_time=17%3A00&watch=bills&watch=renewals&approvers=Alex"
    r = c.post("/settings/agent", content=body, headers={"x-csrf-token": token,
                                                         "content-type": "application/x-www-form-urlencoded"})
    assert r.headers["hx-redirect"] == "/settings?group=agent"
    p = ap.get()
    assert (p["tone"], p["brief_time"], p["weekly_day"], p["watch"], p["approvers"]) == (
        "warm", "06:30", "SAT", ["bills", "renewals"], ["Alex"])
    assert sorted(moved) == ["daily_digest", "weekly_digest"]
    assert "Saved." in c.get("/settings?group=agent").text
    r = _post(c, "/settings/agent", token, name="", tone="warm", brief_time="25:00", weekly_day="SAT", weekly_time="17:00")
    assert 'class="alert"' in c.get("/settings?group=agent").text and ap.get()["brief_time"] == "06:30"
    r = _post(c, "/settings/papers", token, names="Annabel Q Example\nSamuel Example")
    assert r.headers["hx-redirect"] == "/settings?group=household"
    assert modules("config").family()["privacy"]["paper_names"] == ["Annabel Q Example", "Samuel Example"]
    audit = (modules("paths").LOGS / "admin_audit.log").read_text(encoding="utf-8")
    assert "paper_names\t2 name(s)" in audit and "Annabel" not in audit and "agent_profile\tsaved" in audit
    da = modules("dashboard_actions")
    da.hide("bill:99", "<b>Water</b>", "ignore", None, dt.date.today())
    page = c.get("/settings?group=agent").text
    assert "&lt;b&gt;Water&lt;/b&gt;" in page and "<b>Water</b>" not in page
    _post(c, "/settings/restore", token, key="bill:1")
    assert "not hidden" in c.get("/settings?group=agent").text
    _post(c, "/settings/restore", token, key="bill:99")
    assert "shows on Today again" in c.get("/settings?group=agent").text
    con = sqlite3.connect(modules("paths").DB)
    assert con.execute("SELECT COUNT(*) FROM action_state WHERE key='bill:99'").fetchone()[0] == 0
    con.close()


def test_settings_pins(web, modules):
    c, auth, _ = web
    _login(c)
    token = _csrf(c)
    assert "Your own current PIN" not in c.get("/settings?group=agent").text, "the old PIN is not asked"
    _post(c, "/settings/pin", token, who="Nobody", pin="2468", again="2468", current="1234")
    assert "Choose a person" in c.get("/settings?group=agent").text
    _post(c, "/settings/pin", token, who="Alex", pin="2468", again="2486", current="1234")
    assert "not the same" in c.get("/settings?group=agent").text
    r = _post(c, "/settings/pin", token, who="Alex", pin="2468", again="2468", current="1234")
    assert r.headers["hx-redirect"] == "/settings?group=agent"
    page = c.get("/settings?group=agent").text
    assert "Alex signs in with this PIN" in page and "2468" not in page
    assert auth.login("Alex", "2468")
    audit = (modules("paths").LOGS / "admin_audit.log").read_text(encoding="utf-8")
    assert "pin_set\tAlex" in audit and "2468" not in audit
    c.post("/logout", headers={"x-csrf-token": token})
    _login(c, "Alex", "2468")
    token = _csrf(c)
    r = _post(c, "/settings/pin", token, who="Alex", pin="5678", again="5678", current="2468")
    assert r.headers["hx-redirect"] == "/login?pin=changed"  # own PIN: the session ended
    assert c.get("/settings").status_code == 303
    assert "Sign in with the new one" in c.get("/login?pin=changed").text
    assert _login(c, "Alex", "5678").status_code == 303


def test_settings_answer_next_goes_to_the_inbox(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/settings?group=household").text
    if "Ask me the next question" not in page:
        return  # the seeded profile has nothing left to ask
    r = _post(c, "/settings/next", token)
    assert r.headers["hx-redirect"] == "/add"


# ---- Finance parts -----------------------------------------------------------------------------------------------
def test_finance_parts_need_an_adult(web):
    c, _, _ = web
    assert c.get("/money?part=bills").status_code == 303
    _login(c, "Kid", "0000")
    for p in ("bills", "subs", "accounts", "tax"):
        assert c.get(f"/money?part={p}").status_code == 403


def test_every_finance_part_opens(web, modules):
    c, _, _ = web
    _login(c)
    fd = modules("finance_data")
    for p, _title in fd.parts():
        r = c.get(f"/money?part={p}")
        assert r.status_code == 200, p
        assert 'aria-current="true">' + _title + "</a>" in r.text, p
    r = c.get("/money?part=<script>")  # unknown part: the Money overview
    assert r.status_code == 200 and "<script>" not in r.text and "what is still to come" in r.text
    assert r.text.count('class="flane"') == 3 and "Pay" in r.text and "Keep" in r.text and "Look back" in r.text
    assert 'class="fparts"' not in r.text, "R1: each lane carries its own parts, no second list of them"
    for gone in ("cards", "cashflow"):  # R3 / R4: merged into the Ledger and Trends; old links land on the overview
        r = c.get(f"/money?part={gone}")
        assert r.status_code == 200 and "what is still to come" in r.text, gone


def test_finance_bills_filters_links_and_escaping(web, modules):
    c, _, _ = web
    _login(c)
    import datetime as dt
    month = dt.date.today().strftime("%Y-%m")
    bid = _sql(modules, "INSERT INTO bills(name, vendor, amount, due_date, status) VALUES (?,?,?,?,'due')",
               "<b>Water</b> bill", "City", 41.25, month + "-28")
    r = c.get(f"/money?part=bills&month={month}")
    assert f'href="/records?ref=bills%3A{bid}"' in r.text
    assert "<b>Water" not in r.text and "&lt;b&gt;Water&lt;/b&gt; bill" in r.text and "Utilities" in r.text
    r = c.get(f"/money?part=bills&month={month}&q=water")
    assert f"bills%3A{bid}" in r.text
    r = c.get(f"/money?part=bills&month={month}&q=zzqq")
    assert f"bills%3A{bid}" not in r.text and "No bills match." in r.text
    r = c.get("/money?part=bills&month=1999-13&q=<i>x</i>")  # bad month: this month; words escaped
    assert r.status_code == 200 and f'value="{month}" selected' in r.text and "<i>x</i>" not in r.text
    r = c.get(f"/records?ref=bills:{bid}")  # a Finance row opens in Records, "Show all" goes back to Finance
    assert 'href="/money?part=bills"' in r.text


def test_every_finance_view_builds(modules):
    """Every part builds on the demo data without an error, and each row has one cell per column."""
    import datetime as dt
    fd = modules("finance_data")
    for p, _ in fd.parts():
        v = fd.view(p, dt.date.today(), {})
        assert set(v) >= {"tiles", "notes", "blocks", "md", "filters"}, p
        for b in v["blocks"]:
            assert all(len(r["cells"]) == len(b["cols"]) for r in b["rows"]), (p, b["heading"])
    assert fd.part_of("evil") == "home" and fd.part_of("bills") == "bills"
    o = fd.overview(dt.date.today())
    assert [l["group"] for l in o["lanes"]] == ["Pay", "Keep", "Look back"] and all(l["first"] for l in o["lanes"])
    row = fd.list_row(["name", "vendor", "amount", "due_date", "status"],
                      {"name": "Water", "vendor": "Water", "amount": 41.25, "due_date": "2020-03-04", "status": "overdue"},
                      {"amount"})
    assert row == {"title": "Water", "amount": "$41.25", "pill": "overdue", "tone": "bad", "meta": "Mar 4, 2020"}
    b = fd.block("x", [{"id": 1, "name": "Water", "due_date": "2020-03-04", "status": "overdue"}], "", "bills")
    assert b["rows"][0]["cells"] == ["Water", "Mar 4, 2020", "overdue"]  # PC table: short date
    assert b["rows"][0]["pills"] == {2: "bad"}  # and the status as a pill
    assert fd.month_arg("2026-13", ["2026-13"], "x") == "x"
    assert fd.bill_category("Electric bill") == "Utilities"


def test_ledger_takes_over_the_cards_page(web, modules):
    """R4: what Money > Cards showed lives in the Ledger: one card's lines (Account), spending per card member, and the
    uncategorized card merchants with the Remember form, which goes back to the same Ledger filters."""
    c, _, _ = web
    _login(c)
    aid = _sql(modules, "INSERT INTO accounts(name, type, last4, owner) VALUES ('Test Card', 'credit', '4242', 'Ann')")
    tid = _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount, category, cardholder) "
                        "VALUES (?,?,?,?,?,?)", aid, "2026-03-14", "<img src=x>CAFE", -18.4, "Dining", "Ann")
    _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount, cardholder) VALUES (?,?,?,?,?)",
         aid, "2026-03-15", "MYSTERY SHOP 88", -60.0, "Bo")
    q = f"/money?part=ledger&from=2026-03-01&to=2026-03-31&account={aid}"
    r = c.get(q)
    assert f"/money/txn/{tid}" in r.text and "<img src=x>" not in r.text and "MYSTERY SHOP" in r.text
    assert "By card member" in r.text and "Ann" in r.text and "Bo" in r.text
    r = c.get(q + "&cat=__none__")
    assert "Uncategorized merchants" in r.text and "MYSTERY SHOP" in r.text and 'name="back" value="ledger"' in r.text
    token = _csrf(c)
    r = _post(c, "/money/rule", token, pattern="MYSTERY SHOP", category="Gifts", back="ledger", account=str(aid),
              cat="__none__", **{"from": "2026-03-01", "to": "2026-03-31"})
    assert r.headers["hx-redirect"] == f"/money?part=ledger&from=2026-03-01&to=2026-03-31&account={aid}&cat=__none__"
    assert _one(modules, "SELECT category FROM transactions WHERE description LIKE 'MYSTERY SHOP%'") == ("gifts",)
    assert c.get("/money/download?part=cards&month=2026-03").status_code == 404, "the Ledger's CSV replaces it"


def test_kid_page_shows_own_items_family_lists_and_no_money(web, modules):
    c, _, _ = web
    soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    mine = _sql(modules, "INSERT INTO life_items(domain, member, title, due_date) VALUES ('school', 'Kid', 'Book report', ?)", soon)
    other = _sql(modules, "INSERT INTO life_items(domain, member, title, due_date) VALUES ('school', 'Ann', 'Ann thing', ?)", soon)
    _sql(modules, "INSERT INTO life_items(domain, member, title, due_date, amount) VALUES ('medical', 'Kid', 'Dentist', ?, 90)", soon)
    fam = _sql(modules, "INSERT INTO lists(name, kind, audience, status, created_at) VALUES ('Picnic', 'packing', 'family', "
                        "'active', '2026-01-01')")
    adl = _sql(modules, "INSERT INTO lists(name, kind, audience, status, created_at) VALUES ('Secret gifts', 'todo', 'adults', "
                        "'active', '2026-01-01')")
    hid = _sql(modules, "INSERT INTO list_items(list_id, text, status, added_at) VALUES (?, 'Bike', 'open', '2026-01-01')", adl)
    _login(c, "Kid", "0000")
    r = c.get("/")
    assert r.status_code == 200 and "Hi Kid" in r.text and "Book report" in r.text and "Picnic" in r.text
    assert "Secret gifts" not in r.text and "Ann thing" not in r.text and "classic" not in r.text.lower()
    assert 'href="/money"' not in r.text and "$" not in r.text
    token = _csrf(c)
    r = _post(c, "/me", token, op="add", list=str(fam), text="<i>Sandwiches</i>")
    assert r.headers["hx-redirect"] == "/"
    page = c.get("/").text
    assert "Added" in page and "&lt;i&gt;Sandwiches&lt;/i&gt;" in page and "<i>Sandwiches</i>" not in page
    item = _one(modules, "SELECT id, added_by FROM list_items WHERE list_id=?", fam)
    assert item[1] == "Kid"
    _post(c, "/me", token, op="tick", item=str(item[0]))
    assert _one(modules, "SELECT status FROM list_items WHERE id=?", item[0]) == ("done",)
    assert "Untick &lt;i&gt;Sandwiches" in c.get("/").text
    _post(c, "/me", token, op="clear", list=str(fam))
    assert _one(modules, "SELECT cleared_at IS NOT NULL FROM list_items WHERE id=?", item[0]) == (1,)
    # never an adults-only list, never someone else's item, never an unknown op
    _post(c, "/me", token, op="tick", item=str(hid))
    assert _one(modules, "SELECT status FROM list_items WHERE id=?", hid) == ("open",)
    assert "for adults" in c.get("/").text
    _post(c, "/me", token, op="add", list=str(adl), text="peek")
    assert _one(modules, "SELECT COUNT(*) FROM list_items WHERE list_id=?", adl) == (1,)
    _post(c, "/me", token, op="done", item=str(other))
    assert _one(modules, "SELECT status FROM life_items WHERE id=?", other) == ("open",)
    _post(c, "/me", token, op="drop", item=str(item[0]))
    assert "cannot be done here" in c.get("/").text
    _post(c, "/me", token, op="done", item=str(mine))
    assert _one(modules, "SELECT status FROM life_items WHERE id=?", mine) == ("done",)
    # saved links: family only, a link must be http(s)
    _post(c, "/me", token, op="save", title="Science fair ideas", url="https://example.org/sci", note="for May")
    _post(c, "/me", token, op="save", title="Bad", url="javascript:alert(1)")
    page = c.get("/?q=science").text
    assert 'href="https://example.org/sci"' in page and 'rel="noopener noreferrer nofollow"' in page
    assert "javascript:" not in page
    assert _one(modules, "SELECT audience, owner FROM saved_items WHERE title='Science fair ideas'") == ("family", "Kid")
    # every adult page stays shut, and the page needs the token
    assert c.get("/brief", follow_redirects=False).headers["location"] == "/"
    for path in ("/money", "/records", "/settings", "/chat", "/add", "/notes", "/calendar"):
        r = c.get(path)
        assert r.status_code == 403 and "Back to my page" in r.text, path
    assert c.post("/me", data={"op": "done", "item": str(mine)}).status_code == 403


def test_kid_page_shows_own_jobs_ticks_them_and_never_money(web, modules):
    c, _, _ = web
    days = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
    today, other_day = days[dt.date.today().weekday()], days[(dt.date.today().weekday() + 1) % 7]
    for t in ("routine_done", "routines"):
        _sql(modules, f"DELETE FROM {t}")

    def job(member, part, title, stars=1, weekdays=""):
        return _sql(modules, "INSERT INTO routines(member, part, title, icon, stars, weekdays, sort, created_at) "
                             "VALUES (?,?,?,'star',?,?,1,'2026-01-01T00:00:00')", member, part, title, stars, weekdays)

    bed = job("Kid", "morning", "Make the bed", 2, today)
    job("Kid", "evening", "Pack the school bag")
    job("Kid", "afternoon", "Practise piano", 1, other_day)  # not on today
    sams = job("Sam", "morning", "Feed Biscuit", 3)
    _login(c, "Kid", "0000")
    page = c.get("/").text
    assert "My jobs today" in page and "Make the bed" in page and "Pack the school bag" in page
    assert page.index("Morning") < page.index("Make the bed") < page.index("Evening") < page.index("Pack the school bag")
    assert "Practise piano" not in page and "After school" not in page, "a job not on today, an empty part"
    assert "Feed Biscuit" not in page, "only the signed-in child's own jobs"
    assert "0 of 2 done" in page and "0 stars this week" in page
    assert "$" not in page and "¢" not in page and "allowance" not in page.lower()
    token = _csrf(c)
    r = _post(c, "/me", token, op="job", job=str(bed), done="1")
    assert r.headers["hx-redirect"] == "/"
    assert _one(modules, "SELECT done_by, stars FROM routine_done WHERE routine_id=?", bed) == ("Kid", 2)
    page = c.get("/").text
    assert "done." in page and "1 of 2 done" in page and "2 stars this week" in page and "Untick Make the bed" in page
    assert "$" not in page
    _post(c, "/me", token, op="job", job=str(bed), done="0")
    assert _one(modules, "SELECT COUNT(*) FROM routine_done WHERE routine_id=?", bed) == (0,)
    assert "back on the list" in c.get("/").text
    # another child's job, a job gone, a bad id: refused, nothing written
    _post(c, "/me", token, op="job", job=str(sams), done="1")
    assert _one(modules, "SELECT COUNT(*) FROM routine_done WHERE routine_id=?", sams) == (0,)
    assert "only that child" in c.get("/").text
    for bad in ("999999", "1;DROP", ""):
        _post(c, "/me", token, op="job", job=bad, done="1")
        assert 'class="alert"' in c.get("/").text, bad
    assert _one(modules, "SELECT COUNT(*) FROM routine_done") == (0,)
    # no jobs today = no block
    _sql(modules, "UPDATE routines SET status='dropped' WHERE member='Kid'")
    assert "My jobs today" not in c.get("/").text


def test_kid_page_needs_sign_in(web):
    c, _, _ = web
    assert c.get("/").status_code == 303
    assert c.post("/me", data={"op": "add"}).status_code == 403  # no session = no CSRF token


def test_web_charts_leave_gaps_for_months_without_statements(web, root, modules):
    c, _, _ = web
    from test_trends import _fill
    _fill(root)
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("DELETE FROM transactions WHERE txn_date < '2026-06-01' AND txn_date >= '2026-02-01'")
    con.commit()
    con.close()
    assert c.post("/login", data={"name": "Ann", "pin": "1234"}).status_code == 303
    html = c.get("/money/trends?months=12").text
    have = len(re.findall(r'<rect class="inc"', html))
    assert 0 < have < 12  # only months with statements get bars: no zero bars for the empty ones
    assert re.search(r"[A-Z][a-z]{2} 2026 to [A-Z][a-z]{2} 2026: no statements", html)  # the empty run is one line


def test_inbox_folds_a_crowd_of_the_same_kind_of_card(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    ids = [_add_proposal(modules, f"statement:fold-{i}", summary=f"Statement {i} missing") for i in range(5)]
    _add_proposal(modules, "renewal:lonely", source="renewal", summary="A policy renews")
    html = c.get("/inbox/body?view=money").text
    assert html.count('<details class="igroup"') == 1 and "Statements not seen" in html
    assert "A policy renews" not in html  # another category
    assert '<details class="igroup" open' not in html  # folded until a person opens it
    r = _post(c, "/inbox/decide", token, id=str(ids[0]), option="dismiss", open="statement", view="money")
    assert '<details class="igroup" open' in r.text  # the group they are working in stays open
    for i in ids[1:3]:
        _post(c, "/inbox/decide", token, id=str(i), option="dismiss", open="statement", view="money")
    assert 'class="igroup"' not in c.get("/inbox/body?view=money").text  # two left: plain cards again


def _fresh_inbox(modules):
    """No open proposals, nothing waiting in inbox/, no progress file: earlier tests in this module share the copy."""
    paths = modules("paths")
    con = sqlite3.connect(paths.DB)
    with con:
        con.execute("DELETE FROM proposals")
    con.close()
    paths.INBOX.mkdir(parents=True, exist_ok=True)
    for f in paths.INBOX.iterdir():
        if f.is_file() and f.name != ".gitkeep":
            f.unlink()
    (paths.LOGS / "intake_progress.json").unlink(missing_ok=True)


def test_inbox_groups_cards_by_category(web, modules):
    c, _, _ = web
    _login(c)
    _fresh_inbox(modules)
    for i in range(5):
        _add_proposal(modules, f"recurring:r{i}", source="recurring", summary=f"Shop {i} charged monthly")
    _add_proposal(modules, "renewal:p1", source="renewal", summary="A policy renews")
    _add_proposal(modules, "undated:u1", source="undated", kind="question", summary="When was the checkup")
    _add_proposal(modules, "mystery:m1", source="mystery", summary="Something new")
    html = c.get("/inbox/body").text
    heads = re.findall(r'<h2 id="isec-([a-z]+)"', html)
    assert heads == ["money", "renewals", "family", "other"]  # page order, empty categories left out
    assert html.count("Shop ") == 3 and "Show all 5 in Money" in html  # All shows a preview of each
    assert 'hx-get="/inbox/body?view=calendar"' not in html  # no chip for an empty category
    money = c.get("/inbox/body?view=money").text
    assert money.count("Shop ") == 5 and "A policy renews" not in money and "Back to everything" in money
    assert re.search(r'class="icat on" aria-current="true">\s*Money <span class="n">5</span>', money)


def test_inbox_progress_panel_follows_the_run(web, modules):
    c, _, _ = web
    _login(c)
    _fresh_inbox(modules)
    paths, prog, inbox_data = modules("paths"), modules("intake_progress"), modules("inbox_data")
    paths.INBOX.mkdir(parents=True, exist_ok=True)
    (paths.INBOX / "late.pdf").write_bytes(b"%PDF-1.4 x")
    run = prog.Run(["a.pdf", "b.jpg", "c.pdf"])
    run.step("a.pdf", "checking")
    run.done("a.pdf", "filed", "archive/2026/bills/2026-10-01_power_bill.pdf")
    run.step("b.jpg", "sorting")
    p = inbox_data.progress()
    assert p["state"] == "running" and p["poll"] and p["total"] == 4 and p["done"] == 1
    assert p["title"] == "Reading 2 of 4: b.jpg"
    rows = {r["name"]: r for r in p["rows"]}
    assert rows["a.pdf"]["line"] == "Filed as 2026-10-01_power_bill.pdf" and rows["a.pdf"]["tone"] == "ok"
    assert rows["b.jpg"]["step"] == 3 and rows["b.jpg"]["label"] == "Sorting"
    assert rows["late.pdf"]["label"] == "In line"  # dropped after the run began
    r = c.get("/inbox/progress")
    assert 'hx-trigger="every 2s"' in r.text and "HX-Trigger" not in r.headers
    run.done("b.jpg", "review", "low confidence")
    run.done("c.pdf", "duplicate", "same file")
    run.finish()
    p = inbox_data.progress()
    assert p["state"] == "done" and not p["poll"] and p["title"] == "Done: 1 filed, 1 needs you"
    r = c.get("/inbox/progress")
    assert 'every 2s' not in r.text and r.headers["HX-Trigger"] == "inbox-done" and "Already filed" in r.text
    assert inbox_data.progress(now=prog.time.time() + prog.RECENT_S + 5)["state"] == "waiting"  # old run: files only
    (paths.INBOX / "late.pdf").unlink()
    prog.path().unlink()
    assert inbox_data.progress()["state"] == ""
    assert '<section id="iprog" hidden>' in c.get("/inbox/body").text


def test_intake_run_reports_each_file(root, modules):
    paths, prog, ai_intake = modules("paths"), modules("intake_progress"), modules("ai_intake")
    _fresh_inbox(modules)
    (paths.INBOX / "note.xyz").write_bytes(b"plain")
    ai_intake.run(local=True)
    st = prog.read()
    assert st["finished"] and not st["running"] and st["recent"]
    assert [(f["name"], f["step"]) for f in st["files"]] == [("note.xyz", "done")]
    assert st["files"][0]["status"] == "review"


def test_open_mode_is_refused_off_this_pc_and_fails_closed_on_a_broken_config(root, modules, monkeypatch):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    sessions = modules("webapp.sessions")
    sessions.clear()
    fam_path = root / "config" / "family.json"
    saved = fam_path.read_text(encoding="utf-8")
    fam = dict(config.family())
    fam.pop("dashboard_users", None)
    fam.pop("dashboard_pin", None)
    config.write_json(fam_path, fam)
    try:
        monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"})
        pc = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
        assert pc.get("/").status_code == 200, "nobody has a PIN: this PC walks in"
        assert pc.cookies.get(app_mod.COOKIE), "and gets an open session for its forms"

        monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"127.0.0.1"})  # the test client is now 'somewhere on the Wi-Fi'
        lan = TestClient(app_mod.app, base_url="https://192.168.1.20:8701", follow_redirects=False)
        r = lan.get("/")
        assert r.status_code == 303 and r.headers["location"] == "/login", "a phone never walks in without a PIN"
        assert lan.get("/money").status_code in (303, 403)
        assert pc.get("/").status_code == 303, "the open session itself stops working off this PC"

        monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"})
        fam_path.write_text('{"family_name": "Broken", "members": [', encoding="utf-8")  # a hand edit gone wrong
        assert auth.locked_out() and not auth.users()
        r = pc.get("/")
        assert r.status_code == 303 and r.headers["location"] == "/login", "unreadable people list = locked, not open"
        login = pc.get("/login")
        assert login.status_code == 200 and "cannot be read" in login.text
        assert pc.post("/login", data={"name": "Ann", "pin": "1234"}).status_code == 503
        assert pc.get("/setup").status_code != 200 or "Broken" not in pc.get("/setup").text, "no first run over a broken file"

        fam_path.write_text(saved, encoding="utf-8")
        assert not auth.locked_out()
    finally:
        fam_path.write_text(saved, encoding="utf-8")
        sessions.clear()


def test_bodies_are_read_only_up_to_their_cap(web, modules):
    """Audit test gap: /login and the other forms stop reading at the cap instead of holding a huge body in memory."""
    import asyncio
    c, _, _ = web
    app_mod = modules("webapp.app")
    pulled = []

    class _Req:
        async def stream(self):
            for i in range(10_000):
                pulled.append(i)
                yield b"x" * 1024
    got = asyncio.run(app_mod.capped_body(_Req(), 8192))
    assert len(got) == 8192 and len(pulled) == 8, "the stream is not read past the cap"
    r = c.post("/login", content=b"name=Ann&pin=1234&" + b"z" * (3 * 1024 * 1024),
               headers={"content-type": "application/x-www-form-urlencoded"})
    assert r.status_code in (200, 303)


# ---- Simple / Advanced view (view_mode.py): a display preference only -------------------------------------------------
def _set_view(root, modules, mode):
    config = modules("config")
    fam = dict(config.family())
    if mode is None:
        fam.pop("ui", None)
    else:
        fam["ui"] = {"mode": mode}
    config.write_json(root / "config" / "family.json", fam)


def _tabs(html):
    nav = html.split('aria-label="Main"', 1)[1].split('<details class="rmore"', 1)[0].split('class="rsep"', 1)[0]
    return re.findall(r'<a href="(/[a-z]*)" class="tab', nav)


def _rail_extra(html):
    """Notes and Chat on the PC rail under the five tabs (the phone keeps them under More)."""
    nav = html.split('aria-label="Main"', 1)[1].split('<details class="rmore"', 1)[0]
    return re.findall(r'<a href="(/[a-z]*)" class="tab', nav.split('class="rsep"', 1)[1]) if 'class="rsep"' in nav else []


def _sheet(html):
    return set(re.findall(r'href="(/[a-z]*)"', html.split('class="sheet"', 1)[1].split("</div>", 1)[0]))


def _more(html):
    return set(re.findall(r'href="(/[a-z]*)"', html.split('class="rmenu"', 1)[1].split("</div>", 1)[0]))


FIVE = ["/", "/calendar", "/add", "/money", "/family"]


def test_finance_and_this_month_live_in_money(web):
    """Audit U14: Finance and This month are parts of Money; old links land on the same part."""
    c, _, _ = web
    _login(c)
    r = c.get("/finance?part=bills&month=2026-09")
    assert r.status_code == 303 and r.headers["location"] == "/money?part=bills&month=2026-09"
    assert c.get("/month?ym=2026-09").headers["location"] == "/money?part=month&ym=2026-09"
    assert c.get("/month?ym=<x>").headers["location"] == "/money?part=month"
    page = c.get("/money", params={"part": "month"}).text
    tabs = page.split('class="pchips mtabs"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'>([A-Za-z ]+)</a>', tabs) == ["Overview", "Statement", "Home costs", "Spending", "Bills", "Regular", "Pay", "Keep", "Look back"]
    assert "<h1>Money</h1>" in page and "All categories" in page, "This month stays (story card + every category)"
    bills = c.get("/money", params={"part": "bills"}).text
    assert 'class="pchip on" aria-current="true">Pay</a>' in bills and 'class="fchips"' in bills


def test_an_install_without_a_view_setting_shows_everything(web, root, modules):
    c, _, _ = web
    _set_view(root, modules, None)
    _login(c)
    assert modules("view_mode").get() == "advanced"
    home = c.get("/").text
    assert _tabs(home) == FIVE
    assert _rail_extra(home) == ["/notes", "/chat"]
    assert "/settings" in _more(home) and not _more(home) & {"/records", "/wallet", "/notes", "/chat"}
    assert {"/notes", "/chat", "/settings"} <= _sheet(home), "the phone keeps them under More"
    r = c.get("/settings?group=household")
    assert "How much to show" not in r.text, "the switch moved to the Settings home"
    assert "How much to show" in c.get("/settings").text and "<h2>Optional features</h2>" in r.text and "<h2>Tax papers</h2>" in r.text
    assert "Connections" in r.text


def test_simple_view_trims_the_rail_and_settings_but_blocks_nothing(web, root, modules):
    c, _, _ = web
    _set_view(root, modules, "simple")
    _login(c)
    home = c.get("/").text
    assert _tabs(home) == FIVE, "the five tabs, Money included, show in both views"
    more = _more(home)
    assert _rail_extra(home) == ["/notes"] and "/settings" in more
    assert not more & {"/money", "/chat", "/notes"}
    sheet = home.split('class="sheet"', 1)[1].split("</details>", 1)[0]
    assert 'href="/money"' not in sheet and 'href="/notes"' in sheet
    h = c.get("/settings?group=household").text
    assert "<h2>Optional features</h2>" not in h and "<h2>Tax papers</h2>" not in h and "<h2>How early to remind</h2>" not in h
    assert "Names on your papers" in h and "Traditions and holidays" in h and "How much to show" in c.get("/settings").text
    pills = h.split('aria-label="Settings group"', 1)[1].split("</nav>", 1)[0]
    assert "group=agent" in pills and "group=connections" not in pills and "group=phones" not in pills and "group=data" not in pills
    home_page = c.get("/settings").text
    assert "group=data" in home_page and "group=connections" in home_page and "group=phones" in home_page, "each has its card on the Settings home"
    assert "Advanced</h2>" not in c.get("/settings?group=data").text
    # nothing is gated: every page and group still opens by its address
    for url in ("/money", "/money/trends", "/chat", "/work", "/settings?group=connections"):
        assert c.get(url).status_code == 200, url
    assert "Phone bot (Telegram)" in c.get("/settings?group=connections").text


def test_the_switch_saves_the_mode_for_adults_only_and_is_audited(web, root, modules):
    c, _, _ = web
    _set_view(root, modules, None)
    _login(c, "Kid", "0000")
    r = c.post("/settings/view", data={"mode": "simple"}, headers={"x-csrf-token": _csrf(c)})
    assert r.status_code == 403
    assert modules("view_mode").get() == "advanced"
    c.post("/logout", headers={"x-csrf-token": _csrf(c)})
    _login(c)
    tok = _csrf(c)
    r = c.post("/settings/view", data={"mode": "simple"}, headers={"x-csrf-token": tok})
    assert r.status_code == 200 and r.headers["hx-redirect"].startswith("/settings")
    assert modules("view_mode").get() == "simple"
    assert modules("config").family()["ui"]["mode"] == "simple"
    assert "view_mode_set" in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    c.post("/settings/view", data={"mode": "bogus"}, headers={"x-csrf-token": tok})
    assert modules("view_mode").get() == "simple", "an unknown mode changes nothing"
    r = c.post("/settings/view", data={"mode": "advanced"}, headers={"x-csrf-token": tok})
    assert r.status_code == 200 and modules("view_mode").get() == "advanced"
    assert "/chat" in _rail_extra(c.get("/").text)
    assert c.post("/settings/view", data={"mode": "simple"}).status_code == 403, "no CSRF token, no change"


def test_view_mode_keeps_data(web, root, modules):
    c, _, _ = web
    config = modules("config")
    _set_view(root, modules, None)
    before = config.family()
    keep = {k: v for k, v in before.items() if k != "ui"}
    _login(c)
    tok = _csrf(c)
    for mode in ("simple", "advanced", "simple"):
        c.post("/settings/view", data={"mode": mode}, headers={"x-csrf-token": tok})
    after = config.family()
    assert {k: v for k, v in after.items() if k != "ui"} == keep, "only ui.mode changes"
    assert modules("view_mode").pages([("finance", "Finance"), ("notes", "Notes")]) == [("notes", "Notes")]


def test_standard_view_money_is_the_outlook(web, root, modules):
    """The Standard (simple) view: Money = Overview / Spending / Bills / Regular; every other page folded under All money
    pages (still open by URL). Advanced adds the lanes. This month has no budget / bills / upkeep cards (R2)."""
    c, _, _ = web
    _login(c)
    _set_view(root, modules, "simple")
    page = c.get("/money").text
    tabs = page.split('class="pchips mtabs"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'>([A-Za-z ]+)</a>', tabs) == ["Overview", "Statement", "Home costs", "Spending", "Bills", "Regular"]
    assert "All money pages" in page and 'href="/money?part=ledger"' in page and 'class="mo-sum"' in page
    for p, needle in (("spending", "Spending as in the Ledger"), ("paid", "Open on the bill list"), ("regular", "Subscriptions")):
        r = c.get(f"/money?part={p}")
        assert r.status_code == 200 and needle in r.text and ' style="' not in r.text.split("<main>", 1)[1], p
    bills = c.get("/money?part=bills").text
    assert 'class="pchip on" aria-current="true">Pay</a>' in bills, "an Advanced page opened in Standard shows its lane"
    _set_view(root, modules, "advanced")
    month = c.get("/money?part=month").text
    for gone in ("Spending against the plan", "Bills, next 30 days", "House and car", "Renewals and papers"):
        assert gone not in month, gone
    _set_view(root, modules, None)


def test_regular_next_7_days_chips_wrap_on_a_phone(web, root):
    """Money > Regular: the Next 7 days chips wrap and break inside a long name, and on a phone that card takes the
    whole row (three 105 px tiles left no room: the page was 428 px wide at 375)."""
    c, _, _ = web
    _login(c)
    page = c.get("/money?part=regular").text
    assert 'class="mo-top mo-reg"' in page and 'class="card mo-next"' in page
    css = (root / "data" / "webapp" / "static" / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.mo-soon\{[^}]*flex-wrap:wrap", css)
    assert re.search(r"\.mo-soon \.chip-s\{[^}]*flex:0 1 auto;min-width:0;overflow-wrap:anywhere", css), "chips shrink"
    assert re.search(r"@media \(max-width:600px\)\{\.mo-top\.mo-reg\{[^}]*\}\.mo-top \.mo-next\{grid-column:1/-1\}", css)



def test_cards_uncategorized_merchants_are_remembered_with_one_form(web, modules):
    c, _, _ = web
    con = sqlite3.connect(modules("paths").DB)
    try:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Web Rule Card', 'credit', '5151')").lastrowid
        month = dt.date.today().strftime("%Y-%m")
        for d in (-20.0, -5.0):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                        (acc, f"{month}-01", "ODDBALL ROASTERS 77 TROY NY", d))
        con.commit()
    finally:
        con.close()
    _login(c)
    token = _csrf(c)
    page = c.get("/money?part=ledger&cat=__none__").text
    assert "Uncategorized merchants" in page and "ODDBALL ROASTERS" in page and 'hx-post="/money/rule"' in page
    r = _post(c, "/money/rule", token, pattern="ODDBALL ROASTERS", category="Coffee", back="ledger", cat="__none__")
    assert r.headers["hx-redirect"] == "/money?part=ledger&cat=__none__"
    assert _one(modules, "SELECT COUNT(*) FROM transactions WHERE description LIKE 'ODDBALL%' AND category='coffee'") == (2,)
    assert "ODDBALL ROASTERS" not in c.get("/money?part=ledger&cat=__none__").text.split("Uncategorized merchants")[-1][:400]
    r = _post(c, "/money/rule", token, pattern="ab", category="x")
    assert "hx-redirect" in r.headers and "at least three letters" in str(c.get("/money?part=ledger").text)
    assert _post(c, "/money/rule", token, pattern="ODDBALL", category="x").status_code in (200, 303)
    c.cookies.clear()
    _login(c, "Kid", "0000")
    assert c.post("/money/rule", data={"pattern": "ODDBALL", "category": "x"}).status_code == 403


def test_deposits_say_what_a_source_is_and_paypal_has_a_page(web, modules):
    c, _, _ = web
    con = sqlite3.connect(modules("paths").DB)
    month = dt.date.today().strftime("%Y-%m")
    try:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Web Dep Checking', 'checking', '5353')").lastrowid
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, txn_type, category) "
                    "VALUES (?,?,?,?,?,?)", (acc, f"{month}-01", "TREASURYDRCT REDEMPTION 12", 1000.0, "income", "salary"))
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                    (acc, f"{month}-02", "PAYPAL INST XFER WEBSHOP", -9.99))
        con.commit()
    finally:
        con.close()
    _login(c)
    token = _csrf(c)
    page = c.get(f"/money?part=deposits&from={month}&to={month}").text
    assert "Where deposits come from" in page and "TREASURYDRCT REDEMPTION" in page and 'name="kind"' in page
    assert "See the pay in the Ledger" in page and "part=ledger&amp;type=income" in page, "R5: the list lives in the Ledger"
    r = _post(c, "/money/rule", token, pattern="TREASURYDRCT", category="", kind="investment_transfer", back="deposits",
              **{"from": month, "to": month})
    assert r.headers["hx-redirect"] == f"/money?part=deposits&from={month}&to={month}"
    assert _one(modules, "SELECT txn_type, category FROM transactions WHERE description LIKE 'TREASURYDRCT%'") == \
        ("investment_transfer", "investing")
    page = c.get("/money?part=paypal").text
    assert "PayPal charges with no statement line" in page and "PAYPAL INST XFER" in page
    assert 'href="/money?part=paypal"' in c.get("/money?part=receipts").text, "PayPal sits in the Pay chips"


def test_month_page_remembers_a_merchant_and_goes_back_to_the_month(web, modules):
    c, _, _ = web
    con = sqlite3.connect(modules("paths").DB)
    try:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Month Rule Checking', 'checking', '6161')").lastrowid
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                    (acc, "2026-03-04", "LONELY LAUNDRY 9 ALBANY NY", -18.0))
        con.commit()
    finally:
        con.close()
    _login(c)
    token = _csrf(c)
    page = c.get("/money?part=month&ym=2026-03").text
    assert "LONELY LAUNDRY" in page and 'hx-post="/money/rule"' in page and 'name="back" value="month"' in page
    r = _post(c, "/money/rule", token, pattern="LONELY LAUNDRY", category="laundry", month="2026-03", back="month")
    assert r.headers["hx-redirect"] == "/money?part=month&ym=2026-03"
    assert "Remembered: LONELY LAUNDRY is laundry" in c.get("/money?part=month&ym=2026-03").text


def test_ledger_page_filters_and_period(web):
    """Money > Ledger: adults only; one form (period, dates, account, category, type, amount, words); a period alone fills
    the dates; the Look back chips list it first."""
    c, _, _ = web
    _login(c)
    r = c.get("/money?part=ledger")
    assert r.status_code == 200
    for needle in ("data-ledger", 'name="period"', 'name="from"', 'name="to"', 'name="account"', 'name="cat"', 'name="type"',
                   'name="min"', 'name="max"', 'name="q"', "Uncategorized", "Reset"):
        assert needle in r.text, needle
    look_back = r.text.split('class="fchips" aria-label="Look back"', 1)[1].split("</nav>", 1)[0]
    assert re.findall(r'>([A-Za-z -]+)</a>', look_back)[:5] == ["Ledger", "Deposit sources", "Trends", "Missing statements",
                                                                 "Price rises"], "Ledger leads Look back (R5, R7, R8)"
    today = dt.date.today()
    monday = today - dt.timedelta(days=today.weekday())
    w = c.get("/money?part=ledger&period=week").text
    assert f'name="from" value="{monday.isoformat()}"' in w and f'name="to" value="{(monday + dt.timedelta(days=6)).isoformat()}"' in w
    assert 'value="week" selected' in w
    custom = c.get("/money?part=ledger&from=2020-01-01&to=2020-01-31").text
    assert 'value="custom" selected' in custom
    assert c.get("/money?part=ledger&page=zzz&min=abc&type=bogus").status_code == 200, "bad filters are ignored"
    _login(c, "Kid", "0000")
    assert c.get("/money?part=ledger").status_code == 403


def test_ledger_edit_changes_category_and_type_and_returns_to_the_same_filter(web, modules):
    c, _, _ = web
    con = sqlite3.connect(modules("paths").DB)
    try:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Web Ledger Visa', 'credit', '6464')").lastrowid
        tid = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                          (acc, "2033-03-05", "LEDGERTEST DINER 41", -23.5)).lastrowid
        con.commit()
    finally:
        con.close()
    _login(c)
    token = _csrf(c)
    page = c.get("/money?part=ledger&from=2033-03-01&to=2033-03-31").text
    assert "LEDGERTEST DINER 41" in page and 'hx-post="/money/txn"' in page and 'name="similar"' in page
    assert 'name="from" value="2033-03-01"' in page
    r = _post(c, "/money/txn", token, id=str(tid), category="Dining", txn_type="spend", **{"from": "2033-03-01", "to": "2033-03-31", "q": "diner"})
    assert r.headers["hx-redirect"] == "/money?part=ledger&from=2033-03-01&to=2033-03-31&q=diner"
    assert _one(modules, f"SELECT category, txn_type, manual FROM transactions WHERE id={tid}") == ("dining", "spend", 1)
    again = c.get("/money?part=ledger&from=2033-03-01&to=2033-03-31").text
    assert "edited" in again and "dining" in again
    r = _post(c, "/money/txn", token, id=str(tid), category="x", txn_type="not a type")
    assert "hx-redirect" in r.headers and "type" in c.get("/money?part=ledger").text
    assert _one(modules, f"SELECT category FROM transactions WHERE id={tid}") == ("dining",), "a bad type saves nothing"
    c.cookies.clear()
    _login(c, "Kid", "0000")
    assert c.post("/money/txn", data={"id": str(tid), "category": "x"}).status_code == 403


def test_ledger_download_is_a_csv_of_the_filter(web):
    c, _, _ = web
    _login(c)
    page = c.get("/money?part=ledger&from=2020-01-01&to=2020-01-31").text
    assert "Download this list (.csv)" in page and "/money/download?" in page and "part=ledger" in page
    r = c.get("/money/download?part=ledger&from=2020-01-01&to=2020-01-31")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert 'filename="ledger_2020-01-01_2020-01-31.csv"' in r.headers["content-disposition"]
    assert r.text.splitlines()[0] == "date,account,description,category,type,amount,card_member,edited"
    _login(c, "Kid", "0000")
    assert c.get("/money/download?part=ledger").status_code == 403



def test_ledger_quick_view_window_walks_the_list_and_saves_in_place(web, modules):
    c, _, _ = web
    con = sqlite3.connect(modules("paths").DB)
    try:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Quick View Visa', 'credit', '7474')").lastrowid
        ids = [con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, cardholder) VALUES (?,?,?,?,?)",
                           (acc, f"2034-04-{d:02d}", name, -amt, "Pat Quick")).lastrowid
               for d, name, amt in ((9, "QV FIRST SHOP", 5.0), (8, "QV SECOND SHOP", 6.0), (7, "QV THIRD SHOP", 7.0))]
        con.commit()
    finally:
        con.close()
    _login(c)
    token = _csrf(c)
    qs = "from=2034-04-01&to=2034-04-30"
    page = c.get(f"/money?part=ledger&{qs}").text
    assert f'hx-get="/money/txn/{ids[0]}?' in page and 'id="txn-dialog"' in page and 'id="txn-body"' in page
    assert f'href="/records?ref=transactions%3A{ids[0]}"' in page, "the plain link stays as a fallback"
    r = c.get(f"/money/txn/{ids[1]}?{qs}")
    assert r.status_code == 200
    for needle in ("QV SECOND SHOP", "-$6.00", "Pat Quick", "Quick View Visa x7474", "2 of 3", f"/money/txn/{ids[0]}?", f"/money/txn/{ids[2]}?",
                   "data-txn-prev", "data-txn-next", 'hx-post="/money/txn/' + str(ids[1]) + '"', "Open the full record"):
        assert needle in r.text, needle
    first = c.get(f"/money/txn/{ids[0]}?{qs}").text
    assert "1 of 3" in first and "data-txn-prev" in first and f"/money/txn/{ids[0]}?" not in first.split("data-txn-next")[0].split("data-txn-prev")[1], "no Previous on the first line"
    assert "disabled" in first.split("data-txn-next")[0]
    saved = _post(c, f"/money/txn/{ids[1]}", token, category="Quick Cat", txn_type="spend", **{"from": "2034-04-01", "to": "2034-04-30"})
    assert saved.status_code == 200 and saved.headers.get("hx-trigger") == "txn-saved"
    assert "Saved." in saved.text and "quick cat" in saved.text and "2 of 3" in saved.text
    assert _one(modules, f"SELECT category, txn_type, manual FROM transactions WHERE id={ids[1]}") == ("quick cat", "spend", 1)
    again = c.get(f"/money/txn/{ids[1]}?{qs}").text
    assert "Set by hand" in again and "txn update" in again, "the change shows in the window's history"
    bad = _post(c, f"/money/txn/{ids[1]}", token, category="x", txn_type="not a type")
    assert bad.status_code == 200 and "hx-trigger" not in bad.headers and 'class="alert"' in bad.text
    assert "no longer there" in c.get("/money/txn/99999999").text
    c.cookies.clear()
    _login(c, "Kid", "0000")
    assert c.get(f"/money/txn/{ids[0]}").status_code == 403 and c.post(f"/money/txn/{ids[0]}", data={"category": "x"}).status_code == 403


def test_finance_rows_open_in_a_window_with_next_and_edit_in_place(web, modules):
    """Money > Bills / Accounts (and every other Finance list): a row title opens a window over the list with the record, Previous /
    Next through the same list, and the record page's change forms answered inside the window."""
    c, _, _ = web
    con = sqlite3.connect(modules("paths").DB)
    try:
        ids = [con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES (?,?,?,?, 'due')",
                           (name, "Row Window Co", amt, f"2035-02-{d:02d}")).lastrowid
               for d, name, amt in ((3, "RW first bill", 10), (5, "RW second bill", 20), (9, "RW third bill", 30))]
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('RW Row Account', 'checking', '8181')").lastrowid
        con.commit()
    finally:
        con.close()
    _login(c)
    token = _csrf(c)
    qs = "from=2035-02&to=2035-02"
    page = c.get(f"/money?part=bills&{qs}").text
    assert f'hx-get="/money/row/bills/{ids[0]}?part=bills&amp;from=2035-02&amp;to=2035-02"' in page, "the row title opens the window"
    assert 'id="txn-dialog"' in page and 'id="txn-body"' in page
    assert f'href="/records?ref=bills%3A{ids[0]}"' in page, "the plain link stays as a fallback"
    seen = {}
    for i in ids:
        r = c.get(f"/money/row/bills/{i}?part=bills&{qs}")
        assert r.status_code == 200 and "RW " in r.text and "Open the full record" in r.text
        pos = re.search(r"(\d) of (\d)", r.text)
        seen[i] = (int(pos.group(1)), int(pos.group(2)))
    assert sorted(seen.values()) == [(1, 3), (2, 3), (3, 3)], "position in the list the row was opened from"
    mid = c.get(f"/money/row/bills/{ids[1]}?part=bills&{qs}").text
    assert f"/money/row/bills/{ids[0]}?part=bills" in mid and f"/money/row/bills/{ids[2]}?part=bills" in mid, "Previous and Next point at the neighbours"
    assert 'hx-post="/money/row/edit?part=bills' in mid and 'hx-target="#txn-body"' in mid and 'name="when"' in mid, "the change form posts back into the window"
    assert 'hx-post="/records/edit"' not in mid
    saved = _post(c, f"/money/row/edit?part=bills&{qs}", token, table="bills", id=str(ids[1]), op="paid", when="2026-10-01")
    assert saved.status_code == 200 and saved.headers.get("hx-trigger") == "txn-saved" and "hx-redirect" not in saved.headers
    assert 'class="txm"' in saved.text and "Mark as not paid" in saved.text
    assert _one(modules, f"SELECT status FROM bills WHERE id={ids[1]}")[0] == "paid"
    bad = _post(c, f"/money/row/edit?part=bills&{qs}", token, table="bills", id=str(ids[0]), op="paid", when="not a date")
    assert bad.status_code == 200 and "hx-trigger" not in bad.headers and 'role="alert"' in bad.text and 'class="txm"' in bad.text
    assert _post(c, "/money/row/edit?part=bills", token, table="bills", id=str(ids[0]), op="nonsense").status_code == 400
    accounts_page = c.get("/money?part=accounts").text
    assert f'hx-get="/money/row/accounts/{acc}?part=accounts"' in accounts_page
    ar = c.get(f"/money/row/accounts/{acc}?part=accounts")
    assert ar.status_code == 200 and "RW Row Account" in ar.text
    assert c.get("/money/row/not_a_table/1").status_code == 404
    assert "not there any more" in c.get("/money/row/bills/99999999?part=bills").text
    c.cookies.clear()
    _login(c, "Kid", "0000")
    assert c.get(f"/money/row/bills/{ids[0]}").status_code == 403
    assert c.post("/money/row/edit", data={"table": "bills", "id": str(ids[0]), "op": "paid"}).status_code == 403


def test_savings_goals_add_progress_follow_an_account_change_and_close(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/money?part=budget").text
    assert 'id="radd-savings_goals"' in page or "Add a savings goal" in page
    due = (modules("dates").today().replace(day=1) + __import__("datetime").timedelta(days=200)).isoformat()
    r = _post(c, "/records/add", token, part="money/budget", table="savings_goals", name="Beach trip", target="1200",
              due=due, saved="300", account="")
    assert r.headers.get("hx-redirect", "").startswith("/money?part=budget")
    gid, saved, aid = _one(modules, "SELECT id, saved, account_id FROM savings_goals WHERE name='Beach trip'")
    assert saved == 300 and aid is None
    page = c.get("/money?part=budget").text
    assert "Beach trip" in page and "$300" in page and "a month to reach it by" in page
    assert "savings_goal_add\tid=" in (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    # follow an account: the amount saved is its latest balance
    acct = _sql(modules, "INSERT INTO accounts(name, type, last4) VALUES ('Trip savings', 'savings', '4444')")
    _sql(modules, "INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?, '2026-01-01', 950, 'statement')", acct)
    base = {"table": "savings_goals", "id": str(gid)}
    _post(c, "/records/edit", token, **base, op="save", saved="", target="1200", due=due, account=str(acct))
    assert _one(modules, "SELECT account_id FROM savings_goals WHERE id=?", gid) == (acct,)
    assert "$950" in c.get("/money?part=budget").text
    assert "pick the account" in _post(c, "/records/edit", token, **base, op="save", saved="", target="", due=due,
                                       account="99999").text
    r = _post(c, "/records/edit", token, **base, op="status", how="done")
    assert "hx-redirect" in r.headers and "Well done" in c.get(r.headers["hx-redirect"]).text
    assert _one(modules, "SELECT status FROM savings_goals WHERE id=?", gid) == ("done",)
    assert "Beach trip" not in c.get("/money?part=budget").text
    assert "amount to save" in _post(c, "/records/add", token, part="money/budget", table="savings_goals", name="x",
                                     target="0").text.lower()


def test_home_office_setup_form_saves_a_profile(web, modules):
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    page = c.get("/money?part=home_office").text
    assert "Set up your home office" in page and 'id="radd-home_office_profile"' in page
    r = _post(c, "/records/add", token, part="money/home_office", table="home_office_profile", who="Sam", year="2026",
              office="120", home="1800", months="12", method="simplified", self_employed="1", exclusive="", regular="",
              principal="", income="")
    assert r.headers["hx-redirect"] == "/money?part=home_office"
    assert _one(modules, "SELECT office_sqft, home_sqft, self_employed FROM home_office_profile WHERE who='Sam'") == (120.0, 1800.0, 1)
    assert "No home-office profile yet" not in c.get("/money?part=home_office").text
    r = _post(c, "/records/add", token, part="money/home_office", table="home_office_profile", who="Sam", year="2026",
              office="abc", home="1800", months="12", method="", self_employed="", exclusive="", regular="", principal="", income="")
    assert "hx-redirect" not in r.headers and 'class="alert"' in r.text


def test_records_paper_viewer_shows_pdf_and_photos_inline_and_keeps_the_download(web, modules, root):  # noqa: F811
    c, _, _ = web
    _login(c)
    paths = modules("paths")
    rel = {}
    for name, body in (("2026-02-01_card.pdf", b"%PDF-1.4 view"), ("2026-02-02_photo.jpg", b"\xff\xd8\xff"),
                       ("2026-02-03_sheet.csv", b"a,b")):
        f = paths.ARCHIVE / "2026" / "misc" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(body)
        rel[name] = _sql(modules, "INSERT INTO documents (filed_path, doc_type, vendor, doc_date) VALUES (?, 'other', 'X', '2026-02-01')",
                         str(f.relative_to(paths.HOME)))
    pdf, jpg, csv = rel["2026-02-01_card.pdf"], rel["2026-02-02_photo.jpg"], rel["2026-02-03_sheet.csv"]
    page = c.get(f"/records?ref=documents:{pdf}").text
    assert f'data-view-paper="{pdf}"' in page and f'href="/records/paper/{pdf}"' in page, "View and Download both"
    assert 'id="pview"' in page, "the viewer window"
    assert f'data-view-paper="{csv}"' not in c.get(f"/records?ref=documents:{csv}").text, "a spreadsheet is download only"
    r = c.get(f"/records/paper/{pdf}/view")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content == b"%PDF-1.4 view"
    assert r.headers["content-disposition"].startswith("inline") and r.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'self'" in r.headers["content-security-policy"] and r.headers["x-frame-options"] == "SAMEORIGIN"
    assert c.get(f"/records/paper/{jpg}/view").headers["content-type"] == "image/jpeg"
    assert c.get(f"/records/paper/{csv}/view").status_code == 404
    assert c.get("/records/paper/999999/view").status_code == 404
    dl = c.get(f"/records/paper/{pdf}")
    assert dl.headers["content-type"] == "application/octet-stream" and "attachment" in dl.headers["content-disposition"]
    assert "frame-ancestors 'none'" in c.get("/records").headers["content-security-policy"], "other pages stay unframed"
