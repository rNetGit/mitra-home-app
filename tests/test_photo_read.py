"""Add from a photo (data/photo_read.py, webapp/routes_photo.py): the AI's answer is checked and only proposes; each
ticked line is saved through edit_actions; without the AI the same form is typed; adults only; the photo is removed on
save or discard."""
import datetime as dt
import re
import struct
import zlib

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

TODAY = dt.date(2026, 10, 20)
ADULT = {"name": "Alex", "role": "adult"}


def _png():
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


def test_the_ais_dates_are_checked(modules):
    PR = modules("photo_read")
    obj = {"has_dates": True, "items": [
        {"date": "2026-10-28", "title": "Picture day", "who": "sam", "kind": "event", "time": "8:15"},
        {"date": "2026-11-11", "title": "No school: Veterans Day", "kind": "no_school"},
        {"date": "2026-11-03", "end_date": "2026-11-05", "title": "Book fair, bring $10", "kind": "deadline", "area": "school"},
        {"date": "2026-11-03", "title": "Book fair, bring $10", "kind": "deadline"},       # the same line twice
        {"date": "2024-01-01", "title": "Last year's flyer"},                             # too far back
        {"date": "next week", "title": "No date"},
        {"date": "2026-11-20", "title": "Call 555 www.example.com"},                      # a link: not copied
        {"date": "2026-11-25", "title": "=cmd()"},                                        # a formula: not copied
        {"date": "2026-11-25", "title": "Early dismissal", "kind": "early", "time": "12:30", "who": "Nobody"},
        {"date": "2026-11-26", "title": "Odd kind", "kind": "party", "time": "25:00"},
    ]}
    rows = PR.clean_dates(obj, TODAY, ["Alex", "Sam"])
    assert [r["title"] for r in rows] == ["Picture day", "Book fair, bring $10", "No school: Veterans Day",
                                          "Early dismissal", "Odd kind"]
    pic, fair, off, early, odd = rows
    assert (pic["who"], pic["time"], pic["kind"]) == ("Sam", "08:15", "event")
    assert (fair["kind"], fair["end"], fair["area"], fair["time"]) == ("deadline", "2026-11-05", "school", "")
    assert (off["kind"], off["who"]) == ("no_school", "")
    assert (early["kind"], early["time"], early["who"]) == ("early", "12:30", "")
    assert (odd["kind"], odd["time"]) == ("event", "")
    many = {"items": [{"date": "2026-11-01", "title": f"Item {i}"} for i in range(40)]}
    assert len(PR.clean_dates(many, TODAY, [])) == PR.MAX_ROWS


def test_the_ais_recipe_is_checked(modules):
    PR = modules("photo_read")
    f = PR.clean_recipe({"is_recipe": True, "name": "  Banana   bread ", "servings": 8.0,
                         "ingredients": [{"text": "3 bananas"}, {"text": "https://x.example"}, {"text": "1 cup flour"}],
                         "notes": "Mash, mix, bake 60 minutes."})
    assert f == {"name": "Banana bread", "servings": "8", "ingredients": "3 bananas\n1 cup flour",
                 "notes": "Mash, mix, bake 60 minutes."}
    assert PR.clean_recipe({"servings": 400})["servings"] == ""


def test_saving_puts_each_kind_where_it_belongs(modules, root):
    PR, W = modules("photo_read"), modules("wall")
    rows = [{"date": "2026-11-11", "title": "Photo test day off", "kind": "no_school", "who": "", "time": "", "end": "", "area": "school"},
            {"date": "2026-11-25", "title": "Photo test early", "kind": "early", "who": "Sam", "time": "12:30", "end": "", "area": "school"},
            {"date": "2026-11-03", "title": "Photo test fair money", "kind": "deadline", "who": "Sam", "time": "", "end": "", "area": "school"},
            {"date": "2026-10-28", "title": "Photo test picture day", "kind": "event", "who": "Sam", "time": "08:15", "end": "", "area": "school"},
            {"date": "2026-10-30", "title": "Photo test party", "kind": "event", "who": "", "time": "18:00", "end": "", "area": "other"},
            {"date": "not a day", "title": "Photo test broken", "kind": "event", "who": "", "time": "", "end": "", "area": "other"}]
    assert PR.save_dates({"name": "Sam", "role": "limited"}, rows[:1])[0] == 0, "adults only"
    added, failed = PR.save_dates(ADULT, rows)
    assert added == 5 and len(failed) == 1 and failed[0].startswith("Photo test broken:")
    con = W._con()
    try:
        days = {r[0]: r[1] for r in con.execute("SELECT name, kind FROM calendar_days WHERE name LIKE 'Photo test%'")}
        assert days == {"Photo test day off": "closure", "Photo test early": "early"}
        assert con.execute("SELECT domain, member, due_date FROM life_items WHERE title='Photo test fair money'").fetchone()[:] \
            == ("school", "Sam", "2026-11-03")
        assert con.execute("SELECT person, appt_datetime FROM appointments WHERE purpose='Photo test picture day'").fetchone()[:] \
            == ("Sam", "2026-10-28 08:15")
        assert con.execute("SELECT event_date, start_time, end_time, recurs_yearly FROM events "
                           "WHERE name='Photo test party'").fetchone()[:] == ("2026-10-30", "18:00", None, 0), "the time kept as a time"
    finally:
        con.close()


@pytest.fixture()
def web(root, modules, monkeypatch):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    sessions = modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Alex", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Sam", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    yield c, modules
    sessions.clear()


def _sign_in(c, name="Alex", pin="1234"):
    assert c.post("/login", data={"name": name, "pin": pin}).status_code == 303
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)


def _upload(c, token, kind, ai=False):
    return c.post(f"/add/photo?kind={kind}" + ("&ai=1" if ai else ""), content=_png(),
                  headers={"X-CSRF-Token": token, "X-Filename": "flyer.png", "Content-Type": "application/octet-stream"})


def test_dates_typed_next_to_the_photo(web):
    c, modules = web
    wallet = modules("wallet")
    token = _sign_in(c)
    assert "Dates from a photo" in c.get("/add").text
    page = c.get("/add/photo?kind=dates").text
    assert 'id="photo-read"' in page and 'data-kind="dates"' in page
    r = _upload(c, token, "dates")
    assert r.json() == {"ok": True, "redirect": "/add/photo?kind=dates#pcheck"}
    page = c.get("/add/photo?kind=dates").text
    assert "Check the dates" in page and 'src="/add/photo/img"' in page and page.count('name="keep"') == 3
    assert c.get("/add/photo/img").headers["content-type"] == "image/png"
    drafts = list(wallet.DRAFTS.glob("*.png"))
    assert drafts
    form = "kind=dates&read=0&date=2026-11-11&title=Typed+day+off&time=&who=&kind_of=no_school&end=&area=school" \
           "&date=&title=&time=&who=&kind_of=event&end=&area=school&date=&title=&time=&who=&kind_of=event&end=&area=school"
    r = c.post("/add/photo/save", content=form, headers={"X-CSRF-Token": token, "Content-Type": "application/x-www-form-urlencoded"})
    assert r.headers["hx-redirect"] == "/add/photo?kind=dates"
    page = c.get("/add/photo?kind=dates").text
    assert "Added 1 of 1 to the calendar." in page and "Check the dates" not in page
    assert not any(f.exists() for f in drafts), "the photo is removed after the save"


def test_the_ai_fills_the_form_and_unticked_lines_are_left_out(web, monkeypatch):
    c, modules = web
    PR = modules("photo_read")
    token = _sign_in(c)
    monkeypatch.setattr(PR, "read_dates", lambda path, today, names: (
        [{"date": "2026-11-12", "title": "AI read one", "who": "", "kind": "event", "time": "", "end": "", "area": "school"},
         {"date": "2026-11-13", "title": "AI read two", "who": "", "kind": "event", "time": "", "end": "", "area": "school"}],
        "Read by AI: 2 dates found."))
    assert _upload(c, token, "dates", ai=True).json()["ok"]
    page = c.get("/add/photo?kind=dates").text
    assert "Read by AI: 2 dates found." in page and 'value="AI read one"' in page and page.count('name="keep"') == 5
    form = ("kind=dates&read=2&keep=1" + "".join(f"&date={d}&title={t}&time=&who=&kind_of=event&end=&area=school"
                                                for d, t in (("2026-11-12", "AI+read+one"), ("2026-11-13", "AI+read+two")))
            + "&date=&title=&time=&who=&kind_of=event&end=&area=school" * 3)
    c.post("/add/photo/save", content=form, headers={"X-CSRF-Token": token, "Content-Type": "application/x-www-form-urlencoded"})
    W = modules("wall")
    con = W._con()
    try:
        names = {r[0] for r in con.execute("SELECT name FROM events WHERE name LIKE 'AI read%'")}
    finally:
        con.close()
    assert names == {"AI read two"}


def test_a_recipe_from_a_photo(web, monkeypatch):
    c, modules = web
    PR = modules("photo_read")
    token = _sign_in(c)
    monkeypatch.setattr(PR, "read_recipe", lambda path: ({"name": "Photo pancakes", "servings": "4",
                                                          "ingredients": "2 eggs\n1 cup milk", "notes": "Whisk and fry."},
                                                         "Read by AI: check the recipe, then save it."))
    assert _upload(c, token, "recipe", ai=True).json()["redirect"] == "/add/photo?kind=recipe#pcheck"
    page = c.get("/add/photo?kind=recipe").text
    assert 'value="Photo pancakes"' in page and "2 eggs\n1 cup milk" in page
    r = c.post("/add/photo/save", data={"kind": "recipe", "name": "Photo pancakes", "servings": "4",
                                        "ingredients": "2 eggs\n1 cup milk", "notes": "Whisk and fry."},
               headers={"X-CSRF-Token": token})
    assert r.headers["hx-redirect"] == "/add/photo?kind=recipe"
    assert "Recipe &#39;Photo pancakes&#39; saved." in c.get("/add/photo?kind=recipe").text
    M, W = modules("meals"), modules("wall")
    con = W._con()
    try:
        rid = con.execute("SELECT id FROM recipes WHERE name='Photo pancakes'").fetchone()[0]
        rec = M.get_recipe(con, rid)
        assert (rec["servings"], len(rec["ingredients"]), rec["notes"]) == (4, 2, "Whisk and fry.")
    finally:
        con.close()


def test_discard_children_and_other_sites(web):
    c, modules = web
    wallet = modules("wallet")
    token = _sign_in(c)
    assert _upload(c, token, "dates").json()["ok"]
    before = set(wallet.DRAFTS.glob("*"))
    c.post("/add/photo/save", data={"op": "discard", "kind": "dates"}, headers={"X-CSRF-Token": token})
    assert "The photo was not kept." in c.get("/add/photo?kind=dates").text
    assert not [f for f in before if f.exists() and f.suffix == ".png" and f.stat().st_size == len(_png())]
    assert c.post("/add/photo?kind=dates", content=_png(), headers={"X-Filename": "x.png"}).status_code == 403, "CSRF"
    kid = TestClient(c.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    t2 = _sign_in(kid, "Sam", "0000")
    assert _upload(kid, t2, "dates").status_code == 403
    assert kid.get("/add/photo?kind=dates").status_code == 403
    bad = c.post("/add/photo?kind=dates", content=b"<html><script>", headers={"X-CSRF-Token": token, "X-Filename": "x.png",
                                                                               "Content-Type": "application/octet-stream"})
    assert bad.status_code == 400 and not bad.json()["ok"]
