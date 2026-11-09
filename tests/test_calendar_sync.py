"""0.46.0 calendar sync (data/calendar_sync.py, google_calendar.py write permission): Mitra Home puts due dates on a
Google calendar of its own. Against a Google stand-in on 127.0.0.1 that refuses any event call outside the app's own
calendar: nothing is written without the permission or a preview/apply, ids are stable so nothing duplicates,
changed items update, paid ones are removed, lost records recover, and "primary" is never touched."""
import datetime as D
import http.server
import json
import threading
import urllib.parse
import urllib.request

import pytest

from conftest import db, read_family, run, write_family

FAM = "fam123@group.calendar.google.com"
FAMQ = urllib.parse.quote(FAM, safe="")


class FakeGoogle:
    def __init__(self):
        self.calls = []          # (method, path, body)
        self.events = {}         # id -> body
        self.cal_exists = False
        self.requested_scope = ""
        self.fail_patch_404 = set()
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj=None):
                data = json.dumps(obj if obj is not None else {}).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n).decode() if n else ""
                return raw

            def _route(self, method):
                path = self.path.split("?")[0]
                raw = self._body()
                if path == "/token":
                    f = {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}
                    if f.get("grant_type") == "authorization_code":
                        return self._send(200, {"access_token": "AT-1", "refresh_token": "RT-W", "scope": outer.requested_scope})
                    return self._send(200, {"access_token": "AT-2"})
                if path == "/revoke":
                    return self._send(200)
                body = json.loads(raw) if raw.strip().startswith("{") else None
                outer.calls.append((method, path, body))
                if self.headers.get("Authorization") != "Bearer AT-2":
                    return self._send(401)
                if "/calendars/primary" in path and "/users/me" not in path:
                    return self._send(403, {"error": "primary is not writable by this app"})
                if path == "/calendar/v3/users/me/calendarList":
                    return self._send(200, {"items": [{"id": "me@example.com", "summary": "Me", "primary": True}]})
                if path == "/calendar/v3/users/me/calendarList/primary":
                    return self._send(200, {"id": "me@example.com", "timeZone": "America/Chicago"})
                if path == "/calendar/v3/calendars" and method == "POST":
                    outer.cal_exists = True
                    outer.created_body = body
                    return self._send(200, {"id": FAM, "summary": body["summary"], "timeZone": body.get("timeZone")})
                base = f"/calendar/v3/calendars/{FAMQ}"
                if path == base and method == "GET":
                    return self._send(200, {"id": FAM, "summary": "Mitra Home"}) if outer.cal_exists else self._send(404)
                if path == base and method == "DELETE":
                    outer.cal_exists = False
                    outer.events.clear()
                    return self._send(204)
                if path == base + "/events" and method == "POST":
                    if body["id"] in outer.events:
                        return self._send(409)
                    outer.events[body["id"]] = body
                    return self._send(200, body)
                if path.startswith(base + "/events/"):
                    eid = path.rsplit("/", 1)[1]
                    if method == "PATCH":
                        if eid in outer.fail_patch_404 or eid not in outer.events:
                            return self._send(404)
                        outer.events[eid].update(body)
                        return self._send(200, outer.events[eid])
                    if method == "DELETE":
                        return self._send(204) if outer.events.pop(eid, None) else self._send(410)
                self._send(404)

            def do_GET(self):
                self._route("GET")

            def do_POST(self):
                self._route("POST")

            def do_PATCH(self):
                self._route("PATCH")

            def do_DELETE(self):
                self._route("DELETE")

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def event_calls(self):
        return [c for c in self.calls if "/events" in c[1]]

    def close(self):
        self.srv.shutdown()


@pytest.fixture(scope="module")
def G(root, modules):
    import os
    fake = FakeGoogle()
    (root / "config" / "google_client.json").write_text(json.dumps(
        {"installed": {"client_id": "c.apps.googleusercontent.com", "client_secret": "s"}}), encoding="utf-8")
    os.environ["MITRAHOME_GOOGLE_TEST_BASE"] = fake.base
    os.environ["MITRAHOME_GOOGLE_REFRESH_TOKEN"] = "RT-W"
    cs = modules("calendar_sync")
    yield cs, fake
    os.environ.pop("MITRAHOME_GOOGLE_TEST_BASE", None)
    os.environ.pop("MITRAHOME_GOOGLE_REFRESH_TOKEN", None)
    fake.close()


def set_write(root, on, **sync):
    fam = read_family(root)
    fam["google_calendar"] = {"enabled": True, "calendars": ["primary"], "write": on, "sync": sync}
    write_family(root, fam)


def test_nothing_is_written_without_the_permission_and_a_preview_changes_nothing(root, G):
    cs, fake = G
    set_write(root, False)
    with pytest.raises(cs.gc.AuthError) as e:
        cs.apply()
    assert "allowed" in str(e.value) and fake.calls == []
    p = cs.plan()
    assert len(p["create"]) >= 3 and p["update"] == [] and p["delete"] == []
    assert fake.calls == [], "a preview makes no call at all"
    assert all(r["date"] >= D.date.today().isoformat() for r in p["create"]), "overdue items stay on the dashboard"
    assert all("$" not in r["title"] for r in p["create"]), "amounts are left out by default"
    assert any(r["title"].startswith("Bill: ") for r in p["create"])


def test_apply_makes_its_own_calendar_and_only_writes_there(root, G):
    cs, fake = G
    set_write(root, True)
    p = cs.plan()
    n = len(p["create"])
    r = cs.apply(p)
    assert r["created"] == n and r["problems"] == []
    assert fake.created_body["summary"] == "Mitra Home" and fake.created_body["timeZone"] == "America/Chicago"
    assert len(fake.events) == n
    assert not any("primary" in c[1] for c in fake.calls if "/users/me" not in c[1]), "never the personal calendar"
    ev = next(iter(fake.events.values()))
    assert set(ev) >= {"summary", "start", "end", "reminders", "transparency"} and "date" in ev["start"]
    assert ev["reminders"]["overrides"] == [{"method": "popup", "minutes": 900}], "9:00 the day before"
    assert ev["extendedProperties"]["private"]["familyagent"]
    assert (root / "config" / "calendar_sync.json").exists()
    assert "RT-W" not in (root / "config" / "calendar_sync.json").read_text(encoding="utf-8")


def test_second_run_changes_nothing_then_moved_and_paid_items_follow(root, G):
    cs, fake = G
    p = cs.plan()
    assert p["create"] == [] and p["update"] == [] and p["delete"] == [] and p["same"] == len(fake.events)
    before = len(fake.event_calls())
    cs.apply(p)
    assert len(fake.event_calls()) == before, "nothing to do means no calls"
    con = db(root)
    row = con.execute("select id, due_date from bills where vendor like 'Electric%' and status in ('due','overdue')").fetchone()
    assert row, "demo data has the electric bill"
    new_due = (D.date.fromisoformat(row[1]) + D.timedelta(days=2)).isoformat()
    con.execute("update bills set due_date=? where id=?", (new_due, row[0]))
    con.commit()
    p = cs.plan()  # the due date is part of an item's identity: the event moves (old one out, new one in)
    assert len(p["create"]) == 1 and len(p["delete"]) == 1 and p["create"][0]["date"] == new_due
    n0 = len(fake.events)
    r = cs.apply(p)
    assert r["created"] == 1 and r["deleted"] == 1 and len(fake.events) == n0
    assert cs.plan()["create"] == [], "settled"
    con.execute("update bills set status='paid' where id=?", (row[0],))
    con.commit()
    con.close()
    p = cs.plan()
    assert len(p["delete"]) == 1 and p["create"] == []
    n = len(fake.events)
    r = cs.apply(p)
    assert r["deleted"] == 1 and len(fake.events) == n - 1


def test_lost_record_and_hand_deleted_events_recover(root, G):
    cs, fake = G
    state = root / "config" / "calendar_sync.json"
    st = json.loads(state.read_text(encoding="utf-8"))
    keep = len(fake.events)
    st["events"] = {}                       # our record is lost; Google still has the events
    state.write_text(json.dumps(st), encoding="utf-8")
    p = cs.plan()
    assert len(p["create"]) == keep
    r = cs.apply(p)
    assert r["created"] == keep and r["problems"] == [] and len(fake.events) == keep, "409 falls back to an update"
    gone = next(iter(fake.events))
    fake.events.pop(gone)                    # someone deleted one by hand in Google
    st = json.loads(state.read_text(encoding="utf-8"))
    st["events"][gone]["hash"] = "stale"     # and its content changed here
    state.write_text(json.dumps(st), encoding="utf-8")
    p = cs.plan()
    assert [u["id"] for u in p["update"]] == [gone]
    r = cs.apply(p)
    assert r["updated"] == 1 and gone in fake.events, "put back"


def test_amounts_and_reminder_settings_are_honoured(root, G):
    cs, fake = G
    set_write(root, True)
    cs.apply(cs.plan())  # the events as written without amounts (run alone with -k, nothing earlier wrote them)
    set_write(root, True, amounts=True, reminder_days=2)
    p = cs.plan()
    assert p["update"], "the wording changed, so events are updated"
    assert any("$" in r["title"] for r in p["update"])
    cs.apply(p)
    mins = {e["reminders"]["overrides"][0]["minutes"] for e in fake.events.values()}
    assert mins == {2 * 1440 - 540}
    set_write(root, True)


def test_cli_preview_needs_yes_and_auto_is_off_by_default(root, G):
    cs, fake = G
    env = {"MITRAHOME_GOOGLE_TEST_BASE": fake.base, "MITRAHOME_GOOGLE_REFRESH_TOKEN": "RT-W"}
    r = run(["data/calendar_sync.py", "preview"], root, env=env)
    assert r.returncode == 0 and "already there" in r.stdout
    n = len(fake.event_calls())
    r = run(["data/calendar_sync.py", "apply"], root, env=env)
    assert "Nothing was written" in r.stdout and len(fake.event_calls()) == n
    r = run(["data/calendar_sync.py", "auto"], root, env=env)
    assert "auto-sync is off" in r.stdout
    r = run(["data/calendar_sync.py", "status"], root, env=env)
    assert "yes" in r.stdout and "auto-sync: off" in r.stdout


def test_remove_deletes_only_the_familyagent_calendar(root, G):
    cs, fake = G
    assert cs.remove() is True
    assert fake.cal_exists is False and not (root / "config" / "calendar_sync.json").exists()
    assert cs.remove() is False
    deletes = [c[1] for c in fake.calls if c[0] == "DELETE" and "/events" not in c[1]]
    assert deletes and all(FAMQ in d for d in deletes)


def test_sign_in_with_write_asks_for_one_extra_permission_and_records_it(root, G, modules):
    cs, fake = G
    gc = modules("google_calendar")
    seen = {}

    def browser(url):
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        seen.update({k: v[0] for k, v in q.items()})
        fake.requested_scope = seen["scope"]
        urllib.request.urlopen(f"{seen['redirect_uri']}/?code=c&state={seen['state']}", timeout=5).read()

    gc.authorize(browser=browser, timeout=20, say=lambda *_: None, write=True)
    assert gc.WRITE_SCOPE in seen["scope"].split() and set(gc.SCOPES) <= set(seen["scope"].split())
    assert read_family(root)["google_calendar"]["write"] is True
    gc.authorize(browser=browser, timeout=20, say=lambda *_: None, write=False)
    assert gc.WRITE_SCOPE not in seen["scope"].split()
    assert read_family(root)["google_calendar"]["write"] is False, "a read-only sign-in withdraws the write flag"


ADULT, KID = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}


def test_dashboard_actions_are_adults_only_and_preview_before_apply(root, G, modules):
    cs, fake = G
    aa = modules("admin_actions")
    set_write(root, True)
    for fn, args in ((aa.calendar_sync_preview, ()), (aa.calendar_sync_apply, ()), (aa.calendar_sync_remove, ()),
                     (aa.calendar_sync_settings, (30, 1, False, False)), (aa.calendar_write_sign_in, ())):
        assert fn(KID, *args)[0] is False
    n = len(fake.event_calls())
    ok, summ, rows = aa.calendar_sync_preview(ADULT)
    assert ok and "to add" in summ and rows and {r["what"] for r in rows} == {"add"}
    assert len(fake.event_calls()) == n, "a preview sends nothing"
    assert aa.calendar_sync_settings(ADULT, 30, 2, True, False)[0] is True
    s = read_family(root)["google_calendar"]
    assert s["sync"] == {"horizon": 30, "reminder_days": 2, "amounts": True, "auto": False} and s["write"] is True
    assert cs.settings()["amounts"] is True
    ok, msg = aa.calendar_sync_apply(ADULT)
    assert ok and "Added" in msg
    log = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "calendar_sync" in log
    assert aa.calendar_sync_remove(ADULT)[0] is True
    set_write(root, True)


