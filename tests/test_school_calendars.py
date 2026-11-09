"""Schools, colleges and employers with their year calendars (0.123): the online look-ups switch and privacy fence
(lookups.py), schools near home and college names (schools.py, NCES directory), calendars read from .ics / PDF / web
pages (calendar_import.py), where a calendar lives (calendar_find.py, llm.web_lookup), the edits (home area, switch,
person -> org, import) and Family > House plus the person's calendar panel."""
import datetime as D
import json
import re
import urllib.parse

import pytest

from conftest import q

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}
ICS = ("BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{y}1126\r\nDTEND;VALUE=DATE:{y}1128\r\n"
       "SUMMARY:Thanksgiving Recess - Schools Clo\r\n sed\r\nEND:VEVENT\r\n"
       "BEGIN:VEVENT\r\nDTSTART:{y}1204T170000Z\r\nSUMMARY:Early Dismissal\r\nEND:VEVENT\r\n"
       "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{y}1210\r\nSUMMARY:Board Meeting\r\nEND:VEVENT\r\n"
       "BEGIN:VEVENT\r\nDTSTART;VALUE=DATE:{y}1224\r\nDTEND;VALUE=DATE:{z}0102\r\nSUMMARY:Winter Break\r\nEND:VEVENT\r\n"
       "END:VCALENDAR\r\n")


def _ics(today):
    y = today.year if today.month < 11 else today.year
    return ICS.format(y=y, z=y + 1).encode()


@pytest.fixture()
def online(modules):
    config = modules("config")
    with config.family_edit() as cfg:
        cfg["lookups"] = {"online": True}
        cfg["region"] = {**(cfg.get("region") or {}), "zip": "07030", "state": "NJ"}
    yield
    with config.family_edit() as cfg:
        cfg["lookups"] = {"online": False}


class FakeNet:
    """Stands in for lookups._open: answers by URL, records every request."""

    def __init__(self):
        self.pages, self.seen = {}, []

    def __call__(self, req):
        url = req.full_url
        self.seen.append(url)
        for key, (ctype, body) in self.pages.items():
            if key in url:
                return 200, ctype, body, url
        raise OSError("no such page")


@pytest.fixture()
def net(modules, monkeypatch):
    L = modules("lookups")
    f = FakeNet()
    monkeypatch.setattr(L, "_open", f)
    monkeypatch.setattr(L, "_public_host", lambda host: True)
    return f


# ---- the fence ----------------------------------------------------------------------------------------------------
def test_the_fence_lets_public_names_out_and_stops_personal_ones(root, modules):
    L = modules("lookups")
    assert L.problem("Lincoln Middle School 2026-27 calendar, Hoboken NJ 07030") == ""
    assert "name from this family" in L.problem("Sam's school calendar"), "a member's name never goes out"
    assert "name from this family" in L.problem("alex@example"), "names inside other text too"
    assert "name from this family" in L.problem("The Test family"), "the family name is a surname"
    assert "email" in L.problem("someone@example.com")
    assert "phone" in L.problem("call 201-555-0123")
    assert "street" in L.problem("near 12 Elm Street")
    assert "account" in L.problem("4111111111111111")
    assert L.problem("4111 1111 1111 1111"), "a card number in groups of four"
    with pytest.raises(L.Refused):
        L.check_out("fine", "Sam")


def test_web_addresses_are_checked_but_public_ids_pass(root, modules):
    L = modules("lookups")
    assert L.problem(L.url_text("https://calendar.google.com/calendar/ical/abc%40group.calendar.google.com/public/basic.ics")) == ""
    assert L.problem(L.url_text("https://x.org/cms/lib/123456789012/2026-2027.pdf")) == "", "file ids are not personal"
    assert L.problem(L.url_text("https://calendar.google.com/calendar/ical/me%40gmail.com/private-x/basic.ics"))
    assert L.problem(L.url_text("https://x.org/search?q=Alex"))
    for bad in ("ftp://x.org/a", "file:///c:/x", "https://user:pw@x.org/", "javascript:alert(1)"):
        with pytest.raises(L.Refused):
            L.safe_url(bad)
    assert not L._public_host("127.0.0.1") and not L._public_host("192.168.1.1") and not L._public_host("localhost")
    with pytest.raises(L.Refused):
        L._NoPrivateRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1:8601/settings")


def test_nothing_goes_out_while_the_switch_is_off(root, modules, net):
    L = modules("lookups")
    assert not L.enabled()
    with pytest.raises(L.Refused, match="off"):
        L.get("https://example.org/calendar.ics")
    assert net.seen == []


def test_get_refuses_names_and_private_redirects(root, modules, net, online):
    L = modules("lookups")
    with pytest.raises(L.Refused, match="name from this family"):
        L.get("https://example.org/?q=Sam")
    assert net.seen == [], "refused before anything was sent"
    net.pages["example.org/cal"] = ("text/calendar", b"BEGIN:VCALENDAR")
    assert L.get("https://example.org/cal.ics")[0] == "text/calendar"


# ---- schools and colleges -----------------------------------------------------------------------------------------
def _features(rows):
    return json.dumps({"features": [{"attributes": r} for r in rows]}).encode()


def test_schools_near_home_come_nearest_first_with_their_district(root, modules, net, online):
    S = modules("schools")
    here = [{"LAT": 40.744, "LON": -74.03}]
    box_pub = [{"NCESSCH": "340735002746", "LEAID": "3407350", "NAME": "LINCOLN MIDDLE SCHOOL", "CITY": "HOBOKEN",
                "STATE": "NJ", "ZIP": "07030", "LAT": 40.745, "LON": -74.031},
               {"NCESSCH": "340735002999", "LEAID": "3407350", "NAME": "Far Away High", "CITY": "Elsewhere",
                "STATE": "NJ", "ZIP": "07999", "LAT": 41.5, "LON": -74.0}]
    box_priv = [{"PPIN": "A9104271", "NAME": "All Saints Day School", "CITY": "Hoboken", "STATE": "NJ", "ZIP": "07030",
                 "LAT": 40.75, "LON": -74.03}]

    def answer(req):
        url = urllib.parse.unquote(req.full_url)
        net.seen.append(url)
        if "PUBLICLEA" in url:
            return 200, "application/json", _features([{"LEAID": "3407350", "NAME": "HOBOKEN PUBLIC SCHOOL DISTRICT"}]), url
        if "ZIP='07030'" in url:
            return 200, "application/json", _features(here), url
        return 200, "application/json", _features(box_priv if "PRIVATE" in url else box_pub), url
    L = modules("lookups")
    L._open = answer
    got = S.near("07030")
    assert [g["name"] for g in got] == ["Lincoln Middle School", "All Saints Day School"], "far school dropped"
    assert got[0]["district"] == "Hoboken Public School District" and got[1]["private"]
    assert all("07030" in u or "LEAID" in u or "geometry=" in u for u in net.seen), "only the ZIP and a box went out"
    with pytest.raises(S.SchoolError):
        S.near("7030")


def test_college_names_are_checked_with_did_you_mean(root, modules, online):
    S, L = modules("schools"), modules("lookups")
    rows = [{"UNITID": "186131", "NAME": "Princeton University", "CITY": "Princeton", "STATE": "NJ", "ZIP": "08544"}]

    def answer(req):
        url = urllib.parse.unquote_plus(req.full_url)
        if "LIKE '%PRINCETON%'" in url or "LIKE 'PRI%'" in url:
            return 200, "application/json", _features(rows), url
        return 200, "application/json", _features([]), url
    L._open = answer
    L._public_host = lambda host: True
    assert S.check_college("princeton university")["match"]["ext_id"] == "186131"
    res = S.check_college("Prinston University")
    assert res["match"] is None and res["suggest"][0]["name"] == "Princeton University", "a typo gets the closest name"
    with pytest.raises(L.Refused):
        S.colleges("Sam University"), "a member's name never goes into a search"


# ---- reading calendars --------------------------------------------------------------------------------------------
def test_an_ics_feed_gives_days_off_and_early_dismissals_only(root, modules):
    C = modules("calendar_import")
    today = D.date(2026, 10, 18)
    r = C.read_ics(_ics(today).decode(), "school", today=today)
    assert [(d["day"], d["end"], d["kind"]) for d in r["days"]] == [
        ("2026-11-26", "2026-11-27", "closure"), ("2026-12-04", None, "early"), ("2026-12-24", "2027-01-01", "closure")]
    assert r["days"][0]["name"] == "Thanksgiving Recess - Schools Closed", "folded lines are joined"
    assert r["school_year"] == "2026-27" and r["how"] == "ics"
    w = C.read_ics(_ics(today).decode(), "employer", today=today)
    assert {d["kind"] for d in w["days"]} == {"holiday"} and len(w["days"]) == 2, "no early dismissals for work"
    with pytest.raises(C.ImportError_):
        C.read_ics("BEGIN:VCALENDAR\r\nEND:VCALENDAR", "school", today=today)


def test_a_page_in_a_known_layout_is_read_without_ai(root, modules):
    C = modules("calendar_import")
    page = ("<html><body><h1>Lincoln Public Schools 2026-2027 School Calendar</h1><p>Sep 7 Labor Day</p>"
            "<p>Nov 26-27 Thanksgiving Recess</p><p>Dec 24-Jan 1 Winter Recess</p><p>Feb 15 Presidents Day</p>"
            + "<p>filler text so the page is long enough to be a real page.</p>" * 6 + "</body></html>")
    r = C.read(page.encode(), "text/html", "https://x.org/calendar", "school")
    assert r["how"] == "page" and len(r["days"]) == 4 and r["days"][0]["day"] == "2026-09-07"
    with pytest.raises(C.ImportError_, match="not a calendar file"):
        C.read(b"\x89PNG....", "image/png", "x.png", "school")


# ---- edits --------------------------------------------------------------------------------------------------------
def test_home_area_and_switch_are_adult_edits(root, modules):
    ea, config = modules("edit_actions"), modules("config")
    assert ea.home_area_set(KID, "Hoboken", "NJ", "07030")[0] is False
    assert ea.home_area_set(ADULT, "Hoboken", "NJ", "7030")[0] is False, "five digits"
    assert ea.home_area_set(ADULT, "Hoboken", "Jersey", "07030")[0] is False
    ok, msg = ea.home_area_set(ADULT, "Hoboken", "New Jersey", "07030")
    assert ok, msg
    reg = config.family()["region"]
    assert (reg["place"], reg["state"], reg["zip"]) == ("Hoboken", "NJ", "07030"), "a state's name becomes its code"
    assert ea.lookups_set(ADULT, True)[0] and config.family()["lookups"]["online"] is True
    assert ea.lookups_set(ADULT, False)[0] and config.family()["lookups"]["online"] is False
    assert ea.lookups_set(KID, True)[0] is False
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "home_area_set\tfields=place,state,zip" in log and "07030" not in log


def test_linking_a_person_and_importing_a_calendar_file(root, modules):
    ea, P = modules("edit_actions"), modules("proposals")
    assert ea.member_org_set(ADULT, "Sam", "school", "Sam Academy")[0] is False, "a family name never names an org"
    assert ea.member_org_set(ADULT, "Nobody", "school", "Lincoln Middle School")[0] is False
    ok, msg = ea.member_org_set(ADULT, "Sam", "school", "Lincoln Middle School", ext_id="340735002746",
                                district="Hoboken Public School District", city="Hoboken", state="NJ")
    assert ok, msg
    oid, school = q(root, "SELECT org_id, school FROM members WHERE name='Sam'")[0]
    assert school == "Lincoln Middle School" and oid
    body = _ics(D.date.today())
    ok, msg = ea.org_calendar_import(ADULT, oid, filename="district.ics", body=body)
    assert ok and "wait in the Inbox" in msg, msg
    rows = q(root, "SELECT kind, member, source, label, status, org_id FROM calendar_days WHERE org_id=? ORDER BY day", oid)
    assert rows and all(r[1:] == ("Sam", "school", "Lincoln Middle School", "proposed", oid) for r in rows)
    ok, msg = ea.org_calendar_import(ADULT, oid, filename="district.ics", body=body)
    assert q(root, "SELECT COUNT(*) FROM calendar_days WHERE org_id=?", oid)[0][0] == len(rows), \
        "a second import replaces what still waits, nothing twice"
    items = [p for p in q(root, "SELECT summary FROM proposals WHERE source='days' AND status='open'")
             if "Lincoln Middle School calendar" in p[0]]
    assert items, "one Inbox item for the imported calendar"
    assert ea.org_calendar_import(KID, oid, filename="x.ics", body=body)[0] is False
    assert P is not None


def test_an_employer_calendar_lands_as_holidays_for_that_adult(root, modules):
    ea = modules("edit_actions")
    ok, msg = ea.member_org_set(ADULT, "Alex", "employer", "Acme Hospital", state="NJ")
    assert ok, msg
    oid = q(root, "SELECT org_id FROM members WHERE name='Alex'")[0][0]
    ok, msg = ea.org_calendar_import(ADULT, oid, filename="holidays.ics", body=_ics(D.date.today()))
    assert ok, msg
    assert {r for r in q(root, "SELECT kind, member, source FROM calendar_days WHERE org_id=?", oid)} == \
        {("holiday", "Alex", "manual")}
    assert ea.member_org_clear(ADULT, "Alex")[0]
    assert q(root, "SELECT org_id FROM members WHERE name='Alex'")[0][0] is None


def test_import_from_a_link_follows_a_page_to_its_calendar_file(root, modules, net, online):
    ea = modules("edit_actions")
    oid = q(root, "SELECT org_id FROM members WHERE name='Sam'")[0][0]
    y = D.date.today().year
    label = f"{y}-{str(y + 1)[2:]}" if D.date.today().month >= 5 else f"{y - 1}-{str(y)[2:]}"
    net.pages["district.example/calendar"] = ("text/html", (
        f'<html><a href="/files/board-minutes.pdf">Board</a><a href="/files/{label}-calendar.pdf">{label} District '
        f'Calendar</a><a href="webcal://district.example/feed.ics">Subscribe</a></html>').encode())
    net.pages["district.example/feed.ics"] = ("text/calendar", _ics(D.date.today()))
    ok, msg = ea.org_calendar_import(ADULT, oid, url="https://district.example/calendar")
    assert ok, msg
    assert "feed.ics" in net.seen[-1], "the feed was the best link on the page"
    assert q(root, "SELECT calendar_url FROM orgs WHERE id=?", oid)[0][0].endswith("feed.ics")


# ---- finding the calendar -----------------------------------------------------------------------------------------
def test_find_asks_the_ai_with_public_words_only_and_ranks_files(root, modules, net, online, monkeypatch):
    F, llm = modules("calendar_find"), modules("llm")
    asked = []
    monkeypatch.setattr(llm, "web_ready", lambda s=None: "")

    def web(question, **k):
        asked.append(question)
        return '{"urls": [{"url": "https://district.example/calendar", "what": "district calendar"}]}'
    monkeypatch.setattr(llm, "web_lookup", web)
    net.pages["district.example/calendar"] = ("text/html", (
        '<html><a href="/files/board-minutes.pdf">Board minutes</a>'
        '<a href="webcal://district.example/feed.ics">Subscribe to the district calendar</a></html>').encode())
    org = {"id": 1, "kind": "school", "name": "Lincoln Middle School", "district": "Hoboken Public School District",
           "city": "Hoboken", "state": "NJ", "calendar_url": None}
    res = F.find(org)
    assert asked and "Lincoln Middle School" in asked[0] and "Sam" not in asked[0] and "Alex" not in asked[0]
    urls = [c["url"] for c in res["candidates"]]
    assert urls[0].endswith("feed.ics") and not any("minutes" in u for u in urls), urls


def test_web_lookup_refuses_a_question_with_a_name(root, modules):
    llm = modules("llm")
    with pytest.raises(llm.LLMError, match="name from this family"):
        llm.web_lookup("Find Sam's school calendar")


# ---- pages ----------------------------------------------------------------------------------------------------------
@pytest.fixture()
def page_client(root, modules):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    sessions = modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    with config.family_edit() as fam:
        fam["dashboard_users"] = [{"name": "Alex", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                                  {"name": "Sam", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    from fastapi.testclient import TestClient
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    yield c
    sessions.clear()


def _csrf(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/family").text).group(1)


def test_house_page_saves_the_area_and_the_switch(root, page_client):
    c = page_client
    assert c.post("/login", data={"name": "Alex", "pin": "1234"}).status_code == 303
    r = c.get("/family/house")
    assert r.status_code == 200 and "Look things up online" in r.text and "No street address is kept" in r.text
    assert 'href="/family/house"' in c.get("/family").text, "the House tile has an edit link"
    h = {"X-CSRF-Token": _csrf(c), "HX-Request": "true"}
    r = c.post("/family/house", data={"place": "Hoboken", "state": "NJ", "zip": "07030"}, headers=h)
    assert r.headers.get("HX-Redirect") == "/family/house"
    assert "Saved the home" in c.get("/family/house").text
    c.post("/family/house", data={"op": "online", "on": "1"}, headers=h)
    assert "checked" in c.get("/family/house").text
    c.post("/family/house", data={"op": "online"}, headers=h)
    mid = q(root, "SELECT id FROM members WHERE name='Sam'")[0][0]
    r = c.get(f"/family/org?member={mid}")
    assert r.status_code == 200 and "Lincoln Middle School" in r.text and "Turn on" in r.text


def test_children_cannot_open_house_or_the_calendar_panel(root, page_client):
    c = page_client
    c.post("/login", data={"name": "Sam", "pin": "0000"})
    assert c.get("/family/house").status_code == 403
    assert c.get("/family/org?member=1").status_code == 403


def test_the_connection_goes_only_to_the_address_that_was_checked(root, modules, monkeypatch):
    """audit 2026-10-28 (DNS rebinding): the host was checked by one look-up and urllib looked it up again to connect;
    now the socket opens to an address checked in the same call, and a private answer is refused there too"""
    import socket
    L = modules("lookups")
    answers = iter([[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))],
                    [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]])
    monkeypatch.setattr(L.socket, "getaddrinfo", lambda *a, **k: next(answers))
    opened = []
    monkeypatch.setattr(L.socket, "create_connection", lambda addr, *a: opened.append(addr) or "sock")
    assert L._public_ips("rebind.example") == ["93.184.215.14"], "the first answer is public"
    with pytest.raises(L.Refused):
        L._connect_public(("rebind.example", 80))
    assert opened == [], "nothing was opened to 127.0.0.1"
    monkeypatch.setattr(L.socket, "getaddrinfo",
                        lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.215.14", 0))])
    assert L._connect_public(("ok.example", 443)) == "sock" and opened == [("93.184.215.14", 443)]
    handlers = {type(h).__name__ for h in L.urllib.request.build_opener(L._PublicHTTPHandler, L._PublicHTTPSHandler).handlers}
    assert {"_PublicHTTPHandler", "_PublicHTTPSHandler"} <= handlers


def test_a_card_number_in_a_web_address_never_leaves(root, modules):
    """audit 2026-10-28: the fence read the address with long numbers made into N, so a card number in the path went out"""
    L = modules("lookups")
    assert "account" in L.problem(L.url_text("https://attacker.example/4111111111111111"))
    assert L.problem(L.url_text("https://attacker.example/x?n=4111-1111-1111-1111"))
    assert L.problem(L.url_text("https://recipes.example/r/123456789012")) == "", "page ids still pass"
    assert L.problem(L.url_text("https://recipes.example/r/4111111111111112")) == "", "only a Luhn-valid number is a card"
