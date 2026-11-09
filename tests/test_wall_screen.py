"""The Mitra Wall's resting screen (data/wall_screen.py): the settings and the schedule, photos made again without their
EXIF (no GPS), at most 1920 px, served only to a paired wall and to adults, the two clock faces and the photo rotation's
settings on the page, adults only for every change."""
import io
import json
import re

import pytest

from conftest import q  # noqa: F401

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


@pytest.fixture()
def WS(modules):
    ws = modules("wall_screen")
    for n in ws.photos():
        ws.remove_photo(n)
    yield ws
    for n in ws.photos():
        ws.remove_photo(n)
    config = modules("config")
    with config.family_edit() as cfg:
        (cfg.get("wall") or {}).pop("screen", None)


def _jpeg_with_gps(size=(3000, 2000)):
    Image = pytest.importorskip("PIL.Image")
    im = Image.new("RGB", size, (200, 120, 40))
    exif = Image.Exif()
    exif[0x010F] = "Phone maker"            # Make
    exif[0x8825] = {1: "N", 2: (40.0, 44.0, 55.0)}  # GPSInfo
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def test_settings_default_and_are_checked(WS):
    assert WS.settings({}) == WS.DEFAULTS
    s = WS.settings({"wall": {"screen": {"clock": "analog", "photo_seconds": 2, "night_from": "25:00", "photos": False}}})
    assert s["clock"] == "analog" and s["photos"] is False and s["photo_seconds"] == 15 and s["night_from"] == "22:00"
    ok = WS.clean("analog", True, "20", "60", "3", "08:00", "20:30", "21:30", "06:30")
    assert ok["per_turn"] == 3 and ok["photos_to"] == "20:30"
    for bad in (("sundial", True, 15, 45, 4, "07:00", "21:00", "22:00", "06:00"),
                ("digital", True, 1, 45, 4, "07:00", "21:00", "22:00", "06:00"),
                ("digital", True, 15, 45, 4, "7 am", "21:00", "22:00", "06:00"),
                ("digital", True, 15, 45, 4, "07:00", "07:00", "22:00", "06:00")):
        with pytest.raises(WS.ScreenError):
            WS.clean(*bad)
    ok = WS.clean("modular", False, 15, 45, 4, "07:00", "21:00", "22:00", "06:00", "red")
    assert ok["clock"] == "modular" and ok["night_tone"] == "red"
    assert WS.clean("typograph", True, 15, 45, 4, "07:00", "21:00", "22:00", "06:00")["night_tone"] == "dim"
    with pytest.raises(WS.ScreenError):
        WS.clean("digital", True, 15, 45, 4, "07:00", "21:00", "22:00", "06:00", "blue")
    assert WS.settings({"wall": {"screen": {"night_tone": "green"}}})["night_tone"] == "dim"
    assert WS.within("23:30", "22:00", "06:00") and WS.within("05:59", "22:00", "06:00")
    assert not WS.within("06:00", "22:00", "06:00") and WS.within("12:00", "07:00", "21:00")


def test_a_photo_is_made_again_without_its_location(WS):
    Image = pytest.importorskip("PIL.Image")
    name = WS.add_photo("IMG_0001.JPG", _jpeg_with_gps())
    assert re.fullmatch(r"[0-9a-f]{16}\.jpg", name) and WS.photos() == [name]
    with Image.open(WS.photo_path(name)) as im:
        assert max(im.size) == WS.MAX_SIDE and im.size == (1920, 1280)
        assert not im.getexif(), "no EXIF at all: no GPS, no camera"
    for bad_name, data in (("notes.txt", b"hello"), ("x.jpg", b"not a picture"), ("x.jpg", b"")):
        with pytest.raises(WS.ScreenError):
            WS.add_photo(bad_name, data)
    assert WS.photo_path("../family.db") is None and WS.photo_path("ABC.jpg") is None
    assert WS.remove_photo(name) and not WS.remove_photo(name) and WS.photos() == []


def test_only_adults_change_the_wall_screen(WS, modules):
    pytest.importorskip("PIL.Image")
    ea = modules("edit_actions")
    ok, msg = ea.wall_screen_set(ADULT, "analog", True, 20, 30, 2, "08:00", "20:00", "21:00", "07:00")
    assert ok, msg
    assert WS.settings()["clock"] == "analog" and WS.settings()["night_to"] == "07:00"
    assert ea.wall_screen_set(KID, "digital", True, 20, 30, 2, "08:00", "20:00", "21:00", "07:00")[0] is False
    assert ea.wall_screen_set(ADULT, "digital", True, 20, 30, 2, "08:00", "08:00", "21:00", "07:00")[0] is False
    assert ea.wall_photo_add(KID, "a.jpg", _jpeg_with_gps((100, 80)))[0] is False and WS.photos() == []
    ok, _ = ea.wall_photo_add(ADULT, "a.jpg", _jpeg_with_gps((100, 80)))
    assert ok and len(WS.photos()) == 1
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert "\twall_photo_add\t" in log and "\twall_screen_set\t" in log
    assert ea.wall_photo_remove(ADULT, WS.photos()[0])[0] and WS.photos() == []


# ---- the pages ---------------------------------------------------------------------------------------------------------
@pytest.fixture()
def wall_client(root, modules, WS):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    app_mod, routes, W = modules("webapp.app"), modules("webapp.routes_wall"), modules("wall")
    con = W._con()
    for t in ("wall_pairings", "walls"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    code = W.pair_start(con, "Kitchen wall", by="Alex")[0]
    con.close()
    routes._csrf.clear()
    c = TestClient(app_mod.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    assert c.get("/wall/photo/0123456789abcdef.jpg").status_code in (303, 403), "no wall yet: no photo"
    assert c.post("/wall/pair", data={"code": W.pretty_code(code)}).status_code == 303
    return c


def test_the_resting_screen_draws_both_clocks_and_the_photo_rotation(wall_client, WS, modules):
    pytest.importorskip("PIL.Image")
    c, ea = wall_client, modules("edit_actions")
    page = c.get("/wall/rest").text
    assert 'class="time" data-clock' in page and "data-hand" not in page and 'id="stage"' not in page, "digital, no photos"
    assert 'data-night-from="22:00"' in page and 'data-refresh="300"' in page
    name = WS.add_photo("a.png", _jpeg_with_gps((400, 300)))
    ea.wall_screen_set(ADULT, "analog", True, 20, 30, 2, "08:00", "20:00", "21:00", "07:00")
    page = c.get("/wall/rest").text
    assert page.count("data-hand=") == 3 and 'class="aclock"' in page and 'id="stage"' in page
    urls = json.loads(re.search(r"data-photos='([^']*)'", page).group(1))
    assert urls == [f"/wall/photo/{name}"]
    assert 'data-photo-s="20"' in page and 'data-per-turn="2"' in page and 'data-night-from="21:00"' in page
    assert " style=" not in page and not re.search(r"<script(?![^>]*\ssrc=)", page)
    r = c.get(urls[0])
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"
    assert c.get("/wall/photo/..%2Ffamily.db").status_code == 404
    ea.wall_screen_set(ADULT, "analog", False, 20, 30, 2, "08:00", "20:00", "21:00", "07:00")
    assert 'id="stage"' not in c.get("/wall/rest").text, "photos off: the clock only"


def test_the_modular_and_roman_faces_and_the_bedroom_night_clock(wall_client, WS, modules):
    c, ea = wall_client, modules("edit_actions")
    page = c.get("/wall/rest").text
    assert 'class="nightv"' not in page and "tone-dim" in page, "dim: no separate night clock"
    ok, msg = ea.wall_screen_set(ADULT, "modular", False, 20, 30, 2, "08:00", "20:00", "21:00", "07:00", "red")
    assert ok and "modular" in msg and "(red)" in msg
    page = c.get("/wall/rest").text
    assert 'class="modgrid"' in page and "data-ampm" in page and "Next up" in page and "data-hand" not in page
    assert "face-modular tone-red" in page and 'class="nightv"' in page
    assert " style=" not in page and not re.search(r"<script(?![^>]*\ssrc=)", page)
    ea.wall_screen_set(ADULT, "typograph", False, 20, 30, 2, "08:00", "20:00", "21:00", "07:00", "amber")
    page = c.get("/wall/rest").text
    assert page.count("data-hand=") == 3 and 'class="tclock"' in page and ">XII<" in page and ">IX<" in page
    assert "tone-amber" in page and " style=" not in page
    css = (modules("paths").ROOT / "data" / "webapp" / "static" / "wall.css").read_text(encoding="utf-8")
    for cls in (".modgrid", ".mcard", ".ring .rv", ".tclock", ".nightv", "tone-red", "tone-amber"):
        assert cls in css, cls
