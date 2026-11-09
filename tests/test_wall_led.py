"""The LED resting clock (wall_screen led_*, routes_wall.led_view, _wall_led.html): a seven-segment desk clock for a
clock-only wall read from across the room. Its settings and their defaults, a wall's own screen, the keys the app wall
reads from extras.screen, the three layouts with and without weather, the night colours, and no inline style."""
import datetime as dt
import re

import pytest

from test_wall_web import ADULT, _pair, _post, _sign_in, _wall_id, pc, wall  # noqa: F401 (the fixtures)

LED_KEYS = {"led_style": "time", "led_colour": "white", "led_bg": "black", "led_weekdays": True, "hours24": False}
BASE = ("led", False, 15, 45, 4, "07:00", "21:00", "22:00", "06:00")


def _wx(today, temp=63.4, pop=40):
    return {"unit": "F", "temp": temp, "look": "partly", "label": "Partly cloudy", "hi": 66, "lo": 50, "rain": "",
            "days": {today.isoformat(): {"date": today.isoformat(), "hi": 66, "lo": 50, "pop": pop}}, "ahead": []}


def _set(modules, night_tone="dim", **led):
    ok, msg = modules("edit_actions").wall_screen_set(ADULT, *BASE, night_tone=night_tone, led=led)
    assert ok, msg
    return msg


def test_led_settings_default_are_checked_and_kept(modules):
    WS = modules("wall_screen")
    assert "led" in WS.FACES and {k: WS.DEFAULTS[k] for k in LED_KEYS} == LED_KEYS
    s = WS.settings({"wall": {"screen": {"clock": "led", "led_style": "side", "led_colour": "blue", "led_bg": "wood",
                                         "led_weekdays": False, "hours24": True}}})
    assert (s["clock"], s["led_style"], s["led_colour"], s["led_bg"], s["led_weekdays"], s["hours24"]) == \
        ("led", "side", "blue", "wood", False, True)
    bad = WS.settings({"wall": {"screen": {"led_style": "huge", "led_colour": "pink", "led_bg": "oak",
                                           "led_weekdays": "no", "hours24": 1}}})
    assert {k: bad[k] for k in LED_KEYS} == LED_KEYS, "bad values fall back to the defaults"
    assert {k: WS.clean(*BASE)[k] for k in LED_KEYS} == LED_KEYS, "an older form without the LED fields"
    ok = WS.clean(*BASE, led={"led_style": "wide", "led_colour": "amber", "led_bg": "wood", "led_weekdays": False,
                              "hours24": True})
    assert (ok["led_style"], ok["led_colour"], ok["led_bg"], ok["led_weekdays"], ok["hours24"]) == ("wide", "amber", "wood", False, True)
    for k, v in (("led_style", "huge"), ("led_colour", "pink"), ("led_bg", "oak")):
        with pytest.raises(WS.ScreenError):
            WS.clean(*BASE, led={k: v})
    assert WS.led_time(8, 5) == ("08", "05", "AM") and WS.led_time(20, 15) == ("08", "15", "PM")
    assert WS.led_time(0, 0) == ("12", "00", "AM") and WS.led_time(20, 15, True) == ("20", "15", "")
    assert WS.led_time(7, 9, True) == ("07", "09", "")


def test_led_digits_are_seven_segment_polygons(modules):
    modules("webapp.app")  # the routes load through the app
    R = modules("webapp.routes_wall")
    s = R.led_svg("11.02", 8)
    assert [c["lit"] for c in s["cells"]] == ["bc", "bc", "abcdef", "abdeg"] and [c["dp"] for c in s["cells"]] == [False, True, False, False]
    assert s["w"] == 4 * R.LED_W + 3 * R.LED_GAP and [k for k, _ in s["segs"]] == list("abcdefg")
    assert all(len(p.split()) == 6 for _, p in s["segs"]), "each segment is a six-point polygon"
    assert [c["key"] for c in R.led_svg("08", 5, "h")["cells"]] == ["h0", "h1"]
    assert [c["lit"] for c in R.led_svg("-5", 8)["cells"]] == ["g", "acdfg"]
    js = (modules("paths").ROOT / "data" / "webapp" / "static" / "wall.js").read_text(encoding="utf-8")
    for d, segs in R.LED_SEGS.items():
        if d.isdigit():
            assert f"{d}: '{segs}'" in js, f"wall.js lights {d} as routes_wall does"


def test_a_wall_has_its_own_led_screen_and_the_app_wall_gets_the_keys(pc, monkeypatch, wall, modules):  # noqa: F811
    c, W, _, app_mod = pc
    WS = modules("wall_screen")
    _pair(wall[0], W)
    wid = _wall_id(W)
    token = _sign_in(c, monkeypatch, app_mod)
    page = c.get("/settings?group=phones&tab=walls").text
    for name in ('name="led_style"', 'name="led_colour"', 'name="led_bg"', 'name="led_weekdays"', 'name="hours24"', 'value="led"'):
        assert name in page, name
    form = {"id": str(wid), "own": "1", "clock": "led", "photos": "", "photo_seconds": "15", "clock_seconds": "45",
            "per_turn": "4", "photos_from": "07:00", "photos_to": "21:00", "night_from": "22:00", "night_to": "06:00",
            "night_tone": "red", "led_style": "side", "led_colour": "blue", "led_bg": "wood", "hours24": "1"}
    _post(c, "/settings/wall/own", form, token)
    own = WS.settings(wall_id=wid)
    assert (own["clock"], own["led_style"], own["led_colour"], own["led_bg"], own["led_weekdays"], own["hours24"]) == \
        ("led", "side", "blue", "wood", False, True), "an unticked box is off"
    assert WS.settings()["clock"] != "led" and WS.settings()["led_style"] == "time", "the household's stays"
    con = W._con()
    try:
        x = modules("wall_copy").extras(con, wall_id=wid)["screen"]
    finally:
        con.close()
    assert {k: x[k] for k in ("clock", *LED_KEYS)} == {"clock": "led", "led_style": "side", "led_colour": "blue",
                                                        "led_bg": "wood", "led_weekdays": False, "hours24": True}
    _post(c, "/settings/wall/own", {**form, "led_colour": "pink"}, token)
    assert "LED colour" in c.get("/settings?group=phones&tab=walls").text and WS.settings(wall_id=wid)["led_colour"] == "blue"
    page = wall[0].get("/wall/rest").text
    assert 'class="ledf led-side led-c-blue led-bg-wood' in page and 'data-led-24="1"' in page and 'class="lwood"' in page
    assert "data-led-ap" not in page, "24-hour: no AM / PM"
    prev = c.get("/settings/wall/preview", params={k: v for k, v in form.items() if k not in ("id", "own")}).text
    assert 'class="ledf led-side led-c-blue led-bg-wood' in prev and " style=" not in prev


@pytest.mark.parametrize("style", ["time", "wide", "side"])
def test_each_led_layout_draws_with_and_without_weather(wall, monkeypatch, modules, style):  # noqa: F811
    c, W, routes, _ = wall
    _pair(c, W)
    today = dt.date.today()
    _set(modules, led_style=style, led_weekdays=True)
    for wx in (_wx(today), None):
        monkeypatch.setattr(routes.weather, "wall_view", lambda now=None, cfg=None, wx=wx: wx)
        page = c.get("/wall/rest").text
        assert f'class="ledf led-{style} led-c-white led-bg-black' in page and "face-led" in page
        assert " style=" not in page and not re.search(r"<script(?![^>]*\ssrc=)", page)
        assert page.count('data-led="') == 4 and 'data-led-ap=""' in page, "12-hour: four time digits and AM / PM"
        assert page.count("<polygon") >= 28 and 'class="nightv"' not in page and 'class="wxstrip"' not in page
        assert "umid" not in page.lower(), "there is no humidity in the data"
        if style == "time":
            assert 'class="lr"' not in page and 'class="lstrip"' not in page
        elif style == "wide":
            strip = re.search(r'<ol class="lstrip".*?</ol>', page, re.S).group(0)
            assert strip.count("<li") == 7 and strip.count('<li class="on">') == 1
            assert ('aria-label="Now 63°F"' in page) == bool(wx) and ('aria-label="Year ' in page) == (not wx)
            assert f'aria-label="{today:%B} {today.day}"' in page, "month.day"
        else:
            assert 'class="lwkc"' in page and page.count('<li class="on">') == 1
            if wx:
                assert '<span class="lk">RAIN</span>' in page and '<span class="lk">NOW</span>' in page
                assert 'aria-label="Rain chance 40%"' in page and "H 66° · L 50°" in page and "led-solo" not in page
            else:
                assert 'class="lr"' not in page and "RAIN" not in page and "led-solo" in page, "no weather: left out"
    _set(modules, led_style=style, led_weekdays=False)
    monkeypatch.setattr(routes.weather, "wall_view", lambda now=None, cfg=None: _wx(today, pop=None))
    page = c.get("/wall/rest").text
    assert 'class="lwkc"' not in page
    if style == "side":
        assert "RAIN" not in page and '<span class="lk">NOW</span>' in page, "no rain chance: only the temperature"


def test_led_night_colours_and_css_classes(wall, monkeypatch, modules):  # noqa: F811
    c, W, routes, _ = wall
    _pair(c, W)
    monkeypatch.setattr(routes.weather, "wall_view", lambda now=None, cfg=None: None)
    for tone in ("red", "amber", "dim"):
        _set(modules, night_tone=tone, led_style="wide", led_colour="green", led_bg="wood")
        page = c.get("/wall/rest").text
        assert f"face-led tone-{tone}" in page and 'class="nightv"' not in page, "the LED face turns the night colour itself"
    css = (modules("paths").ROOT / "data" / "webapp" / "static" / "wall.css").read_text(encoding="utf-8")
    tpl = (modules("paths").ROOT / "data" / "webapp" / "templates" / "_wall_led.html").read_text(encoding="utf-8")
    WS = modules("wall_screen")
    classes = {f"led-{s}" for s in WS.LED_STYLES if s != "time"} | {f"led-c-{k}" for k in WS.LED_COLOURS if k != "white"} | \
        {"led-bg-wood", "led-wk", "led-solo"}
    classes |= {c for attr in re.findall(r'class="([^"{]+)"', tpl) for c in attr.split()}
    for cls in sorted(classes):
        assert f".{cls}" in css, cls
    for rule in ("body.rest.night .ledf .sg:not(.on)", "body.rest.night .lwood", "body.rest.night.tone-red .ledf",
                 "body.rest.night.tone-amber .ledf", "body.rest.night.tone-dim .ledf", "body.rest.night.face-led .restv"):
        assert rule in css, rule
    assert "style=" not in tpl


def test_a_wall_picks_the_led_face_and_the_app_wall_gets_the_temperature_now(wall, monkeypatch, modules):  # noqa: F811
    c, W, routes, ea = wall
    _pair(c, W)
    wid = _wall_id(W)
    assert ("led", "LED") in routes.FACE_PICK
    ok, msg = ea.wall_face_set({"name": "Kitchen wall", "role": "limited", "wall": wid}, "led")
    assert ok and "LED" in msg and modules("wall_screen").settings(wall_id=wid)["clock"] == "led"
    wc, wx = modules("wall_copy"), modules("weather")
    today = dt.date.today()
    monkeypatch.setattr(wx, "wall_view", lambda now=None, cfg=None: _wx(today))
    assert wc.weather_days(dt.datetime.now())["now"] == {"temp": 63.4}
    monkeypatch.setattr(wx, "wall_view", lambda now=None, cfg=None: {**_wx(today), "temp": None})
    assert wc.weather_days(dt.datetime.now())["now"] is None
