"""Context help: the "?" panel on each adult page, the Help page, and help text that matches the screens."""
import re
from pathlib import Path

import pytest

pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

TEMPLATES = Path(__file__).resolve().parent.parent / "data" / "webapp" / "templates"
PAGES = {"home": "/", "family": "/family", "calendar": "/calendar", "wallet": "/wallet", "inbox": "/add", "month": "/money?part=month",
         "notes": "/notes", "chat": "/chat", "settings": "/settings", "routines": "/family/routines"}


@pytest.fixture()
def web(root, modules):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    return TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)


def test_every_main_page_has_help_and_named_buttons_exist(modules):
    ht = modules("help_text")
    source = " ".join(p.read_text(encoding="utf-8") for p in TEMPLATES.glob("*.html"))
    py = Path(modules("records_edit").__file__).read_text(encoding="utf-8") + Path(modules("webapp.app").__file__).read_text(encoding="utf-8")
    for key in PAGES:
        e = ht.get(key)
        assert e and e["title"] and e["purpose"] and e["sections"], key
        for name in ht.labels(e):
            assert name in source or f'"{name}"' in py, f"help for {key} names [{name}], which is no longer on any screen"


def test_panel_on_adult_pages_links_work_and_kids_get_none(web, modules):
    ht = modules("help_text")
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    for key, path in PAGES.items():
        page = c.get(path).text
        assert f'hx-get="/help/panel?key={key}"' in page and 'id="helpp"' in page, key
        panel = c.get("/help/panel", params={"key": key})
        assert panel.status_code == 200 and ht.get(key)["title"] in panel.text and '<kbd class="hk">' in panel.text
        for _label, url in ht.get(key)["links"]:
            assert c.get(url).status_code == 200, f"{key}: link {url}"
    assert c.get("/help/panel", params={"key": "<script>"}).status_code == 404
    everything = c.get("/help").text
    assert all(ht.get(k)["title"] in everything for k in PAGES)
    found = c.get("/help", params={"q": "pin a note"}).text
    assert 'id="help-notes"' in found and 'id="help-calendar"' not in found
    assert "<script>" not in c.get("/help", params={"q": "<script>"}).text
    c.post("/logout")
    k = web
    k.post("/login", data={"name": "Kid", "pin": "0000"})
    assert "helpbtn" not in k.get("/").text
    assert k.get("/help").status_code == 403 and k.get("/help/panel", params={"key": "home"}).status_code == 403


def test_help_text_formatting_escapes(modules):
    app_mod = modules("webapp.app")
    out = str(app_mod._helpfmt("Press [Save] then **done** <b>x</b>"))
    assert out == 'Press <kbd class="hk">Save</kbd> then <b>done</b> &lt;b&gt;x&lt;/b&gt;'
    assert re.search(r"\[", str(app_mod._helpfmt("no brackets"))) is None


def test_every_records_and_finance_part_has_help_and_the_panel_follows_it(web, modules):
    ht, records, rd, fd = modules("help_text"), modules("records"), modules("records_data"), modules("finance_data")
    source = " ".join(p.read_text(encoding="utf-8") for p in TEMPLATES.glob("*.html"))
    py = Path(modules("records_edit").__file__).read_text(encoding="utf-8")
    parts = [f"records:{d}:{s}" for d, ss in records.SECTIONS.items() if d != "money" for s, _ in ss
             if (d, s) not in rd.ELSEWHERE]
    parts += [f"finance:{p}" for _g, ps in fd.groups() for p, _ in ps]
    for key in parts + ["records", "finance"]:
        e = ht.get(key)
        assert e and e["sections"], f"no help for {key}"
        for name in ht.labels(e):
            assert name in source or f'"{name}"' in py, f"help for {key} names [{name}], which is no longer on any screen"
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    assert 'key=records:people:classes' in c.get("/records", params={"domain": "people", "section": "classes"}).text
    assert 'key=finance:budget' in c.get("/money", params={"part": "budget"}).text
    assert "/help/panel?key=family\"" in c.get("/family").text
    page = c.get("/help").text
    assert all(f'<h2 class="sec">{g}</h2>' in page for g in ("Pages", "Family records", "Money"))
    assert 'id="help-records-people-classes"' in c.get("/help", params={"q": "skip that day"}).text


# ---- Chat "How do I ...?" (part 3) --------------------------------------------------------------------------------
HOWTO = {
    "How do I add a birthday?": "records:people:life",
    "how can I mark a bill paid": "finance:bills",
    "Where do I add my passport": "records:papers:ids",
    "how to pin a note": "notes",
    "help with a dentist appointment": "records:people:health",
    "how do I add a class for Sam": "records:people:classes",
    "how do I add a car": "records:vehicles:vehicles",
    "how do I change my PIN": "settings",
    "how do I snooze something on the to do": "home",
    "how do I snooze a reminder": "home",
    "how do I add a grocery item": "records:home:shopping",
    "how do I add a subscription": "finance:subs",
}


def test_howto_finds_the_entry_and_only_for_how_questions(modules):
    ht = modules("help_text")
    for q, key in HOWTO.items():
        assert ht.is_howto(q), q
        assert ht.howto(q)[:1] == [key], f"{q!r} -> {ht.howto(q)}"
    for q in ("what is due", "zorbo power", "add a dentist visit"):
        assert not ht.is_howto(q), q
    assert ht.howto("how do I fly to mars") == [] and ht.howto("how do I add things") == []
    assert all(k in ht.HELP for k in ht.SYNONYMS.values())
    assert all(w == ht._stem(w) for w in ht.SYNONYMS), "synonym words must be in their stemmed form"
    lines = ht.as_chat("finance:bills")
    assert lines[0].startswith("**Bills**") and not any("[" in x for x in lines)


def _csrf(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)


def test_chat_answers_how_do_i_from_help_without_ai(web, modules, monkeypatch):
    cd = modules("chat_data")
    asked = []
    monkeypatch.setattr(cd, "ai_ready", lambda: False)
    monkeypatch.setattr(cd.aa, "ask", lambda *a, **k: asked.append(a) or {})
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    h = {"X-CSRF-Token": _csrf(c)}
    r = c.post("/chat/say", data={"text": "How do I add a birthday?"}, headers=h)
    assert r.status_code == 200 and "<strong>Life items</strong>" in r.text and "From: Help &gt; Life items" in r.text
    assert 'href="/help#help-records-people-life"' in r.text
    r = c.post("/chat/say", data={"text": "how do I fly to mars"}, headers=h)
    assert "I have no help on that yet" in r.text and 'href="/help"' in r.text
    r = c.post("/chat/chip", data={"key": "howto"}, headers=h)
    assert "How do I mark a bill paid?" in r.text
    assert asked == []
    for q in cd.HOWTO_EXAMPLES:
        assert modules("help_text").howto(q), f"chip example {q!r} finds no help"
    # with an AI: help still answers what it knows, the AI gets the rest
    monkeypatch.setattr(cd, "ai_ready", lambda: True)
    monkeypatch.setattr(cd.aa, "ask", lambda user, text, history=None: asked.append(text) or {
        "lines": ["AI says hi"], "answer": "AI says hi", "needs_confirm": False, "writes": [], "refs": [], "ok": True})
    c.post("/chat/say", data={"text": "how do I add a car"}, headers=h)
    r = c.post("/chat/say", data={"text": "how do I fly to mars"}, headers=h)
    assert asked == ["how do I fly to mars"] and "AI says hi" in r.text


def test_an_unknown_address_gets_a_page_with_a_way_back(web):
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    r = c.get("/no-such-page", headers={"accept": "text/html"})
    assert r.status_code == 404 and "This page is not here" in r.text and 'href="/"' in r.text
    r = c.get("/no-such-page", headers={"accept": "application/json"})
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}, "scripts and the phone API keep plain answers"
    assert c.get("/api/nope", headers={"accept": "text/html"}).headers["content-type"].startswith("application/json")
