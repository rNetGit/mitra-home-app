"""Saved items (migration 030 + data/saved.py): URL rules (http(s) only, tracking stripped, token links refused), kind
guessing, word search, who sees what (private = owner only, kids = family items), kid caps, the edit log without text,
deals in expiries / Action items / digest, export bookmarks.html, purge, the assistant actions and the phone brief."""
import datetime as D
import sqlite3
from html.parser import HTMLParser

import pytest

from conftest import db, q, run

ADULT, OTHER, KID = {"name": "Alex", "role": "adult"}, {"name": "Jordan", "role": "adult"}, {"name": "Sam", "role": "limited"}
NOBODY = {"name": "", "role": "adult"}  # no-login mode


@pytest.fixture(scope="module")
def S(root, modules):
    return modules("saved")


def _id(root, title):
    return q(root, "select id from saved_items where title=? order by id desc", title)[0][0]


@pytest.mark.parametrize("url,clean,domain,kind", [
    ("https://github.com/debpalash/VoiceStudio", "https://github.com/debpalash/VoiceStudio", "github.com", "repo"),
    ("https://youtu.be/abc123?si=SHAREID&t=42", "https://youtu.be/abc123?t=42", "youtu.be", "video"),
    ("https://www.youtube.com/watch?v=abc&feature=share&si=x", "https://www.youtube.com/watch?v=abc&feature=share", "youtube.com", "video"),
    ("https://www.example.com/news?utm_source=fb&utm_medium=x&id=7&fbclid=ZZ", "https://www.example.com/news?id=7", "example.com", "link"),
    ("HTTPS://WWW.Facebook.com/groups/x?gclid=1", "https://www.facebook.com/groups/x", "facebook.com", "social"),
    ("https://www.google.com/maps/place/Pizza+Place", "https://www.google.com/maps/place/Pizza+Place", "google.com", "place"),
    ("https://maps.app.goo.gl/AbC", "https://maps.app.goo.gl/AbC", "maps.app.goo.gl", "place"),
    ("https://example.com/2026/10/08/123456789-story", "https://example.com/2026/10/08/123456789-story", "example.com", "link"),
    ("http://localhost:8501/x", "http://localhost:8501/x", "localhost", "link"),
])
def test_url_cleaning_and_kind_guess(S, url, clean, domain, kind):
    assert S.clean_url(url) == (clean, domain)
    assert S.guess_kind(clean, domain) == kind


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "file:///C:/secret.txt", "data:text/html,hi", "ftp://x.com/a", "mailto:a@b.com",
    "https://a.com/reset?token=abc", "https://a.com/cb#access_token=abc", "https://a.com/?password=x",
    "https://a.com/s3?X-Amz-Signature=abc", "https://user:pw@a.com/", "https://a.com/?email=pat@example.com",
    "https://a.com/x y", "https://", "https://a.com/" + "x" * 2000,
])
def test_bad_urls_are_refused(S, url):
    with pytest.raises(ValueError):
        S.clean_url(url)


def test_migration_and_checks(root, S):
    assert q(root, "select name from schema_migrations where name='migrate_030_saved.py'")
    r = run(["data/migrate_030_saved.py"], root)
    assert r.returncode == 0 and "saved items" in r.stdout
    con = db(root)
    try:
        for sql in ("insert into saved_items(kind, title, added_at) values ('podcast', 'x', 'now')",
                    "insert into saved_items(title, url, added_at) values ('x', 'javascript:alert(1)', 'now')",
                    "insert into saved_items(title, audience, added_at) values ('x', 'private', 'now')",
                    "insert into saved_items(title, audience, added_at) values ('x', 'everyone', 'now')",
                    "insert into saved_items(title, expires_on, added_at) values ('x', '10/08/2026', 'now')",
                    "insert into saved_items(title, added_at) values ('', 'now')"):
            with pytest.raises(sqlite3.IntegrityError):
                con.execute(sql)
    finally:
        con.rollback()
        con.close()


def test_cli_round_trip(root, S):
    ok = lambda *a: run(["data/saved.py", *a], root)  # noqa: E731
    r = ok("add", "Voice cloning tool", "--url", "https://github.com/debpalash/VoiceStudio?utm_source=x", "--tags", "AI, #voice",
           "--note", "Local voice cloning.\nTry with the kids' audiobook.")
    assert r.returncode == 0 and "repo" in r.stdout, r.stdout + r.stderr
    assert q(root, "select kind, url, domain, tags, body from saved_items where title='Voice cloning tool'") == [
        ("repo", "https://github.com/debpalash/VoiceStudio", "github.com", "ai,voice", "Local voice cloning.\nTry with the kids' audiobook.")]
    assert "already saved" in ok("add", "Same repo", "--url", "https://github.com/debpalash/VoiceStudio").stdout
    assert ok("add", "Luigi's pizza", "--kind", "place", "--where", "Next to the station", "--tags", "restaurants").returncode == 0
    assert ok("add", "Card", "--note", "card 4111111111111111").returncode != 0, "no full card numbers"
    assert ok("add", "Reset link", "--url", "https://a.com/?token=1").returncode != 0
    assert ok("add", "Secret", "--private").returncode != 0, "private needs --by"
    assert ok("add", "Secret", "--private", "--by", "Nobody").returncode != 0
    assert ok("add", "Alex's secret", "--private", "--by", "alex").returncode == 0
    assert q(root, "select audience, owner from saved_items where title=?", "Alex's secret") == [("private", "Alex")]
    assert ok("add", "Couch sale", "--kind", "deal", "--until", "2026-13-01").returncode != 0
    out = ok("find", "pizza station").stdout
    assert "Luigi's pizza" in out and "Voice" not in out, out
    assert "Voice cloning tool" in ok("find", "--tag", "voice").stdout
    assert "Luigi" in ok("find", "--kind", "place").stdout and "Luigi" not in ok("find", "--kind", "repo").stdout
    assert "nothing found" in ok("find", "zebra").stdout
    assert "[private: Alex]" in ok("recent").stdout, "the terminal sees everything, marked"
    vid = _id(root, "Voice cloning tool")
    assert "tags: ai, voice, kids" in ok("tag", str(vid), "+Kids", "-nothing").stdout
    assert ok("tag", str(vid), "kids").returncode != 0, "each tag starts with + or -"
    assert ok("tag", str(vid), "-ai").returncode == 0
    assert q(root, "select tags from saved_items where id=?", vid) == [("voice,kids",)]
    assert ok("pin", str(vid)).returncode == 0
    assert ok("recent").stdout.splitlines()[0].startswith("* "), "pinned first"
    show = ok("show", str(vid)).stdout
    assert "Try with the kids' audiobook." in show
    assert q(root, "select last_opened is not null from saved_items where id=?", vid) == [(1,)]
    assert ok("archive", str(_id(root, "Luigi's pizza"))).returncode == 0
    assert "Luigi" not in ok("find", "pizza").stdout and "Luigi" in ok("find", "pizza", "--all").stdout
    assert ok("show", "99999").returncode != 0


def test_who_sees_what(root, S, modules):
    ea = modules("edit_actions")
    assert ea.saved_add(ADULT, "Alex dashboard secret", note="surprise party plan", audience="private")[0]
    assert ea.saved_add(ADULT, "Grown-up article", url="https://news.example.com/a", audience="adults")[0]
    assert ea.saved_add(KID, "Science fair idea", url="https://www.youtube.com/watch?v=volcano")[0]
    assert not ea.saved_add(KID, "Kid secret", audience="private")[0], "kids save family items only"
    assert not ea.saved_add(NOBODY, "Nobody's secret", audience="private")[0], "private needs a signed-in person"
    con = db(root)
    try:
        seen = lambda who, w="": {r["title"] for r in S.search(con, w, viewer=who)}  # noqa: E731
        a, o, k = seen(ADULT), seen(OTHER), seen(KID)
        assert "Alex dashboard secret" in a and "Alex's secret" in a
        assert "Alex dashboard secret" not in o and "Alex's secret" not in o, "private: other adults never see it"
        assert "Grown-up article" in o and "Grown-up article" not in k
        assert "Science fair idea" in k and "Voice cloning tool" in k and "Alex dashboard secret" not in k
        assert not seen(OTHER, "surprise party"), "private items do not leak through search either"
    finally:
        con.close()
    secret = _id(root, "Alex dashboard secret")
    assert not ea.saved_archive(OTHER, secret)[0] and not ea.saved_pin(OTHER, secret)[0]
    science = _id(root, "Science fair idea")
    assert not ea.saved_archive(KID, _id(root, "Voice cloning tool"))[0], "kids archive only their own"
    assert not ea.saved_pin(KID, science)[0], "pins are for adults"
    assert ea.saved_tags(KID, science, "school, Science")[0]
    assert q(root, "select tags, owner from saved_items where id=?", science) == [("school,science", "Sam")]
    assert ea.saved_archive(KID, science)[0]
    elog = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    for action in ("saved_add", "saved_archive", "saved_tags"):
        assert action in elog, action
    for text in ("secret", "Science", "youtube", "volcano", "surprise", "Grown-up"):
        assert text not in elog, f"edits.log must not hold item text: {text}"


def test_kid_daily_cap(root, S, modules):
    ea = modules("edit_actions")
    con = db(root)
    try:
        already = S.added_today_by(con, "Sam")
    finally:
        con.close()
    for n in range(S.MAX_KID_PER_DAY - already):
        assert ea.saved_add(KID, f"kid note {n}")[0]
    ok, msg = ea.saved_add(KID, "one too many")
    assert not ok and str(S.MAX_KID_PER_DAY) in msg
    assert ea.saved_add(ADULT, "adults have no cap")[0]


def test_deals_in_expiries_action_items_and_digest(root, S, modules):
    today = D.date.today()
    ea = modules("edit_actions")
    soon, later, gone = (today + D.timedelta(days=2)), (today + D.timedelta(days=30)), (today - D.timedelta(days=1))
    assert ea.saved_add(ADULT, "Couch sale", url="https://shop.example.com/couch", until=soon.isoformat())[0]
    assert ea.saved_add(ADULT, "Winter tyres offer", kind="deal", until=later.isoformat())[0]
    assert ea.saved_add(ADULT, "Old offer", kind="deal", until=gone.isoformat())[0]
    assert ea.saved_add(ADULT, "My private deal", kind="deal", until=soon.isoformat(), audience="private")[0]
    assert q(root, "select kind from saved_items where title='Couch sale'") == [("deal",)], "an end date and no kind: a deal"
    ex, ai = modules("expiries"), modules("action_items")
    assert ex.lead_days("deal") == 3 and "deal" in ex.types()
    con = sqlite3.connect(root / "data" / "family.db")
    try:
        rows = {r["what"]: r for r in ex.rows(con, today) if r["type"] == "deal"}
        assert set(rows) == {"Couch sale", "Winter tyres offer"}, "ended and private deals stay out"
        assert {r["what"] for r in ex.soon(con, today) if r["type"] == "deal"} == {"Couch sale"}
        items = [i for i in ai.collect_items(con, today, 30) if i["kind"] == "Deal"]
        assert len(items) == 1 and "Couch sale" in items[0]["title"] and f"{soon:%a %b %d}" in items[0]["title"]
        deals = [r["title"] for r in S.deals(con, viewer=ADULT, today=today)]
        assert set(deals[:2]) == {"My private deal", "Couch sale"}, "soonest end first; the owner sees their private deal"
        assert "Old offer" not in deals and deals[-1] == "Winter tyres offer"
    finally:
        con.close()
    assert "Old offer" in run(["data/saved.py", "find", "offer", "--all"], root).stdout
    assert "Old offer" not in run(["data/saved.py", "deals"], root).stdout
    assert run(["data/make_digest.py"], root).returncode == 0
    digest = sorted((root / "brief").glob("*_weekly_digest.md"))[-1].read_text(encoding="utf-8")
    assert "## Saved" in digest and "Saved this week:" in digest
    assert "Couch sale" in digest, "a deal ending inside its lead is in the Expiring section"
    assert "My private deal" not in digest and "Alex's secret" not in digest


def test_export_bookmarks_and_phone_brief(root, S):
    out = root / "exports" / "saved_test"
    r = run(["data/export_data.py", "--out", str(out), "--tables", "saved_items"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert (out / "saved_items.csv").exists()
    page = (out / "bookmarks.html").read_text(encoding="utf-8")
    assert page.startswith("<!DOCTYPE NETSCAPE-Bookmark-file-1>")
    links = []

    class P(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == "a":
                links.append(dict(attrs)["href"])
    P().feed(page)
    assert "https://github.com/debpalash/VoiceStudio" in links and all(u.startswith("http") for u in links)
    assert "Luigi" not in page, "archived items are not bookmarked"
    assert "nothing pinned" not in run(["data/saved.py", "brief"], root).stdout
    md = (root / "brief" / "saved.md").read_text(encoding="utf-8")
    assert "Voice cloning tool" in md and "secret" not in md.lower() and "Grown-up" not in md


def test_assistant_catalog_runs_saved(root, modules):
    asst = modules("assistant")
    for name in ("saved_add", "saved_find", "saved_deals"):
        assert name in asst.CATALOG
    _, _, params, build = asst.CATALOG["saved_add"]
    assert params["url"][0]("https://x.example.com/p?utm_source=a&q=1") == "https://x.example.com/p?q=1"
    with pytest.raises(ValueError):
        params["url"][0]("javascript:alert(1)")
    argv = build({"title": "Tea shop", "url": "https://tea.example.com", "tags": "tea", "adults_only": 1})
    assert argv[2:] == ["add", "Tea shop", "--url", "https://tea.example.com", "--tags", "tea", "--adults"], argv
    assert run(argv[1:], root).returncode == 0
    assert q(root, "select audience, kind from saved_items where title='Tea shop'") == [("adults", "link")]
    found = run(asst.CATALOG["saved_find"][3]({"words": "tea"})[1:], root)
    assert "Tea shop" in found.stdout


def test_purge_person_removes_private_keeps_shared(root):
    before = q(root, "select count(*) from saved_items where owner='Sam'")[0][0]
    assert before > 0
    r = run(["data/purge.py", "person", "Alex", "--yes"], root)
    assert r.returncode == 0, r.stdout[-400:] + r.stderr[-400:]
    assert not q(root, "select count(*) from saved_items where audience='private'")[0][0], "Alex's private items are gone"
    assert not q(root, "select count(*) from saved_items where owner='Alex'")[0][0]
    assert q(root, "select count(*) from saved_items where title='adults have no cap'")[0][0] == 1, "shared items stay"
    assert q(root, "select count(*) from saved_items where owner='Sam'")[0][0] == before
