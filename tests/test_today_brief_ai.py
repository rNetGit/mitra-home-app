"""The AI wording of Today's brief: the page never waits on the AI (cached answer, or the plain brief plus one call made
afterwards by POST /today/brief), no AI / a CLI / a bad answer leaves the plain brief, and the endpoint is adults-only."""
import datetime as dt
import re

import pytest

from conftest import set_ai
from test_today import _sql, web  # noqa: F401 (web is a fixture)

FAKE = "Two things need you today."


@pytest.fixture()
def ai(root, modules, web):  # noqa: F811
    c = web
    bn = modules("brief_narrative")
    (root / "logs").mkdir(exist_ok=True)
    bn.CACHE.unlink(missing_ok=True)
    set_ai(root, "none")  # the root is shared between tests
    name = _sql(modules, "SELECT name FROM members ORDER BY id")[0][0]
    _sql(modules, "INSERT INTO life_items(domain, member, title, due_date, status) VALUES ('school',?,'Zebra form',?,'open')",
         name, dt.date.today().isoformat())
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    fake = root / "config" / "fake_llm.json"
    yield c, bn, fake, root
    set_ai(root, "none")
    fake.unlink(missing_ok=True)
    bn.CACHE.unlink(missing_ok=True)


def token(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)


def btext(page):
    return page.split('class="btext"', 1)[1].split("</p>", 1)[0] if 'class="btext"' in page else ""


def test_no_ai_page_is_the_plain_brief_with_no_fetch(ai):
    c, bn, fake, root = ai
    page = c.get("/").text
    assert "Zebra form" in page and "/today/brief" not in page and 'data-ai' not in page


def test_cli_provider_is_the_plain_brief(ai):
    c, bn, fake, root = ai
    set_ai(root, "claude_cli")
    page = c.get("/").text
    assert "Zebra form" in page and "/today/brief" not in page


def test_api_provider_without_an_answer_yet_asks_afterwards_and_keeps_plain_text(ai):
    c, bn, fake, root = ai
    set_ai(root, "fake")
    fake.write_text(FAKE, encoding="utf-8")
    page = c.get("/").text
    assert 'hx-post="/today/brief"' in page and "Zebra form" in page, "plain sentences are the fallback"
    assert not bn.CACHE.exists(), "drawing the page made no AI call"
    r = c.post("/today/brief", headers={"X-CSRF-Token": token(c)})
    assert r.status_code == 200 and r.text == FAKE
    again = c.get("/").text
    assert FAKE in again and "/today/brief" not in again and "Zebra form" not in btext(again), "cached: shown at once"


def test_bad_answer_falls_back_to_plain(ai):
    c, bn, fake, root = ai
    set_ai(root, "fake")
    fake.write_text("You owe $999 at https://evil.example", encoding="utf-8")
    r = c.post("/today/brief", headers={"X-CSRF-Token": token(c)})
    assert r.status_code == 204, "the plain brief stays"
    page = c.get("/").text
    assert "Zebra form" in page and "evil.example" not in page and "/today/brief" not in page


def test_endpoint_without_ai_does_nothing(ai):
    c, bn, fake, root = ai
    r = c.post("/today/brief", headers={"X-CSRF-Token": token(c)})
    assert r.status_code == 204
    assert not bn.CACHE.exists()


def test_endpoint_needs_csrf_and_an_adult(ai):
    c, bn, fake, root = ai
    set_ai(root, "fake")
    fake.write_text(FAKE, encoding="utf-8")
    assert c.post("/today/brief").status_code == 403
    assert not bn.CACHE.exists()
    t = token(c)
    c.post("/logout", headers={"X-CSRF-Token": t})
    anon = c.post("/today/brief")
    assert anon.status_code in (303, 403)
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    kt = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    assert c.post("/today/brief", headers={"X-CSRF-Token": kt}).status_code == 403
    assert not bn.CACHE.exists()


def test_ai_wording_keeps_the_rain_spend_and_bill_lines(ai, modules):
    c, bn, fake, root = ai
    td = modules("today_data")
    v = {"late": [], "due": [], "today": [], "spend": {"spent": 412.4}, "money": {}}
    assert td.brief(v, "Rain likely from 3 PM") == td.brief_items(v) + td.brief_more(v, "Rain likely from 3 PM")
    said = " ".join(t for line in td.brief_more(v, "Rain likely from 3 PM") for t, _ in line)
    assert "Rain likely from 3 PM." in said and "spent" in said
    set_ai(root, "fake")
    fake.write_text(FAKE, encoding="utf-8")
    plain = c.get("/").text
    more = plain.split('class="bmore"', 1)[1].split("</span>", 1)[0] if 'class="bmore"' in plain else ""
    c.post("/today/brief", headers={"X-CSRF-Token": token(c)})
    again = c.get("/").text
    assert FAKE in btext(again) and "Zebra form" not in btext(again)
    assert more and more in btext(again), "the lines the AI never sees stay under its wording"
