"""The local weather (data/weather.py): fetched by the PC only while online look-ups are on and the ZIP is set, every
request through lookups.get (the fence: only the ZIP and the ZIP area's rounded position go out), the Weather Service
first and Open-Meteo as the fallback (and outside the US), a cache that is reused, retried and then dropped, plain-word
rain, and the wall / PC Today showing it, or nothing at all when there is none."""
import datetime as dt
import json
import re
import urllib.parse

import pytest

NOW = dt.datetime(2027, 3, 3, 9, 20)  # a Wednesday morning
ZIP = "07030"


def _aware(t):
    """A local time as the Weather Service writes it (with this PC's own offset)."""
    return t.astimezone().isoformat(timespec="seconds")


def _icon(look, day=True):
    return f"https://api.weather.gov/icons/land/{'day' if day else 'night'}/{look}?size=small"


def _hourly(start=NOW.replace(minute=0), n=48, rain_from=None):
    periods = []
    for i in range(n):
        t = start + dt.timedelta(hours=i)
        wet = rain_from is not None and t >= rain_from
        periods.append({"startTime": _aware(t), "isDaytime": 6 <= t.hour < 18, "temperature": 50 + (i % 12),
                        "probabilityOfPrecipitation": {"value": 70 if wet else 5},
                        "icon": _icon("rain,70" if wet else "few", 6 <= t.hour < 18), "shortForecast": "x"})
    return {"properties": {"periods": periods}}


def _forecast(day=NOW.date()):
    periods = []
    for i in range(7):
        d = dt.datetime.combine(day + dt.timedelta(days=i), dt.time(6))
        periods.append({"startTime": _aware(d), "isDaytime": True, "temperature": 60 + i,
                        "probabilityOfPrecipitation": {"value": 10}, "icon": _icon("sct"), "shortForecast": "Partly Sunny"})
        periods.append({"startTime": _aware(d.replace(hour=18)), "isDaytime": False, "temperature": 40 + i,
                        "probabilityOfPrecipitation": {"value": None}, "icon": _icon("skc", False),
                        "shortForecast": "Clear"})
    return {"properties": {"periods": periods}}


class FakeNet:
    """Stands in for lookups._open: answers by URL part, records every request."""

    def __init__(self):
        self.pages, self.seen, self.down = {}, [], set()

    def __call__(self, req):
        url = req.full_url
        self.seen.append(url)
        for key, body in self.pages.items():
            if key in url and not any(d in url for d in self.down):
                return 200, "application/json", json.dumps(body).encode(), url
        raise OSError("no such page")


@pytest.fixture()
def Wx(modules):
    return modules("weather")


@pytest.fixture()
def net(modules, monkeypatch, Wx):
    L = modules("lookups")
    f = FakeNet()
    monkeypatch.setattr(L, "_open", f)
    monkeypatch.setattr(L, "_public_host", lambda host: True)
    monkeypatch.setattr(Wx, "_refresh_in_background", lambda cfg, now: Wx.refresh(cfg, now))  # no thread in tests
    f.pages = {
        "api.zippopotam.us/us/07030": {"places": [{"latitude": "40.7445", "longitude": "-74.0324"}]},
        "api.weather.gov/points/40.74,-74.03": {"properties": {
            "forecast": "https://api.weather.gov/gridpoints/OKX/33,36/forecast",
            "forecastHourly": "https://api.weather.gov/gridpoints/OKX/33,36/forecast/hourly"}},
        "/forecast/hourly": _hourly(rain_from=NOW.replace(hour=15, minute=0)),
        "/33,36/forecast": _forecast(),
    }
    Wx._cache_path().unlink(missing_ok=True)
    yield f
    Wx._cache_path().unlink(missing_ok=True)


@pytest.fixture()
def home(modules):
    """Look-ups on, the ZIP set; back to off afterwards."""
    config = modules("config")

    def set_(online=True, zip_code=ZIP, country=None):
        with config.family_edit() as cfg:
            cfg["lookups"] = {"online": online}
            cfg["region"] = {**(cfg.get("region") or {}), "zip": zip_code}
            if country:
                cfg["country"] = country
            else:
                cfg.pop("country", None)
    set_()
    yield set_
    set_(online=False, zip_code="")


# ---- nothing goes out, nothing shows -----------------------------------------------------------------------------
def test_off_or_no_zip_means_no_request_and_nothing_shown(Wx, net, home):
    for kw in ({"online": False}, {"zip_code": ""}, {"zip_code": "7030"}):
        home(**kw)
        assert Wx.setting() is None
        assert Wx.refresh(now=NOW) is False
        assert Wx.wall_view(NOW) is None and Wx.line(NOW) == ""
    assert net.seen == [], "the switch and the ZIP are checked before anything is sent"
    home()
    assert Wx.refresh(now=NOW) and Wx.wall_view(NOW)
    home(online=False)
    assert Wx.wall_view(NOW) is None, "a cache from before the switch went off is never shown"


def test_only_the_zip_and_the_rounded_position_go_out(Wx, net, home):
    assert Wx.refresh(now=NOW)
    hosts = {urllib.parse.urlsplit(u).hostname for u in net.seen}
    assert hosts == {"api.zippopotam.us", "api.weather.gov"}
    assert "40.74,-74.03" in net.seen[1], "two decimals: the ZIP area, not the house"
    assert not any(re.search(r"\d+\.\d{3,}", u) for u in net.seen)
    for u in net.seen:
        assert not re.search(r"(?i)alex|sam|test", u)


def test_the_fence_stops_a_request_carrying_a_family_name(Wx, net, home, modules):
    L = modules("lookups")
    with pytest.raises(L.Refused):
        L.get("https://api.weather.gov/points/Sam")
    assert net.seen == []


# ---- what the wall shows ------------------------------------------------------------------------------------------
def test_weather_service_now_today_and_the_week(Wx, net, home):
    assert Wx.refresh(now=NOW)
    v = Wx.wall_view(NOW)
    assert v["source"] == "National Weather Service" and v["unit"] == "F"
    assert (v["temp"], v["look"], v["label"]) == (50, "sun", "Sunny"), "the hour that holds 9:20"
    assert (v["hi"], v["lo"]) == (60, 40), "the day's forecast periods"
    assert v["rain"] == "Rain likely from 3 PM"
    thu = v["days"][(NOW.date() + dt.timedelta(days=1)).isoformat()]
    assert (thu["hi"], thu["lo"], thu["look"]) == (61, 41, "partly")
    ahead = v["ahead"]
    assert 2 <= len(ahead) <= Wx.AHEAD_DAYS and ahead[0]["dow"] == "Today" and (ahead[0]["hi"], ahead[0]["lo"]) == (60, 40)
    assert ahead[1]["dow"] == (NOW.date() + dt.timedelta(days=1)).strftime("%a") and ahead[1]["hi"] == 61
    assert Wx.line(NOW) == "50°F, Sunny · high 60° low 40° · Rain likely from 3 PM"
    data = json.loads(Wx._cache_path().read_text(encoding="utf-8"))
    assert data["key"] == "US:07030:F" and data["pos"] == {"lat": 40.74, "lon": -74.03}
    assert "Sam" not in json.dumps(data) and len(data["hours"]) <= Wx.HOURS_KEPT


def test_the_cache_is_reused_then_refreshed_and_a_failure_waits(Wx, net, home):
    assert Wx.wall_view(NOW)["temp"] == 50
    n = len(net.seen)
    assert Wx.wall_view(NOW + dt.timedelta(minutes=30)) and len(net.seen) == n, "fresh: nothing fetched"
    later = NOW + dt.timedelta(minutes=Wx.FRESH_MIN + 1)
    assert Wx.wall_view(later) and len(net.seen) == n + 2, "old: forecast + hourly again; ZIP and points are kept"
    net.down = {"api.weather.gov", "open-meteo"}
    t2 = later + dt.timedelta(minutes=Wx.FRESH_MIN + 1)
    v = Wx.wall_view(t2)
    assert v and v["temp"] is not None, "the earlier forecast still shows"
    assert Wx.load()["failed_at"]
    n = len(net.seen)
    assert Wx.wall_view(t2 + dt.timedelta(minutes=5)) and len(net.seen) == n, "a failure waits before the next try"
    assert Wx.wall_view(later + dt.timedelta(hours=Wx.STALE_HOURS, minutes=1)) is None, "too old: nothing shown"


def test_a_new_zip_starts_over(Wx, net, home):
    assert Wx.refresh(now=NOW)
    home(zip_code="10001")
    net.pages["api.zippopotam.us/us/10001"] = {"places": [{"latitude": "40.7484", "longitude": "-73.9967"}]}
    assert Wx.wall_view(NOW) is None, "the old ZIP's weather is not shown"
    assert any("us/10001" in u for u in net.seen)


def test_open_meteo_when_the_weather_service_fails_and_outside_the_us(Wx, net, home):
    times = [(NOW.replace(hour=0) + dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(48)]
    om = {"hourly": {"time": times, "temperature_2m": [10.4 + (i % 24) / 2 for i in range(48)],
                     "precipitation_probability": [0] * 48, "weather_code": [61 if 12 <= i < 14 else 2 for i in range(48)],
                     "is_day": [1 if 7 <= i % 24 < 19 else 0 for i in range(48)]}}
    net.pages["api.open-meteo.com/v1/forecast"] = om
    net.down = {"api.weather.gov"}
    assert Wx.refresh(now=NOW)
    v = Wx.wall_view(NOW)
    assert v["source"] == "Open-Meteo" and (v["temp"], v["look"]) == (15, "partly")
    assert v["days"][NOW.date().isoformat()]["look"] == "rain", "a day looks like its worst daytime hour"
    om_url = next(u for u in net.seen if "open-meteo" in u)
    assert "temperature_unit=fahrenheit" in om_url and "latitude=40.74" in om_url
    assert not re.search(r"(?i)\b(max|min)\b|_max|_min", om_url), "no words a child's name could match"
    # a Canadian postal code: the area before the space, Celsius, Open-Meteo only
    home(zip_code="M5V 3L9", country="CA")
    net.pages["api.zippopotam.us/ca/M5V"] = {"places": [{"latitude": "43.6426", "longitude": "-79.3871"}]}
    net.seen.clear()
    assert Wx.refresh(now=NOW)
    assert Wx.load()["key"] == "CA:M5V:C" and not any("weather.gov" in u for u in net.seen)
    assert "temperature_unit" not in next(u for u in net.seen if "open-meteo" in u)


def test_a_points_answer_pointing_elsewhere_is_not_followed(Wx, net, home):
    net.pages["api.weather.gov/points/40.74,-74.03"] = {"properties": {
        "forecast": "https://evil.example/forecast", "forecastHourly": "https://evil.example/hourly"}}
    assert Wx.refresh(now=NOW) is False, "no Open-Meteo answer either"
    assert not any("evil.example" in u for u in net.seen)


def test_an_evening_forecast_keeps_the_day_s_high_or_shows_only_tonight(Wx, net, home):
    evening = NOW.replace(hour=19)
    fc = _forecast()
    fc["properties"]["periods"] = fc["properties"]["periods"][1:]  # starts with Tonight
    net.pages["/33,36/forecast"] = fc
    net.pages["/forecast/hourly"] = _hourly(start=evening.replace(minute=0))
    assert Wx.refresh(now=evening)
    v = Wx.wall_view(evening)
    assert (v["hi"], v["lo"]) == (None, 40), "the hours left in the evening are not the day's high"
    assert Wx.line(evening).endswith("low 40° tonight · No rain expected")
    Wx._cache_path().unlink()
    net.pages["/33,36/forecast"] = _forecast()
    assert Wx.refresh(now=NOW)
    net.pages["/33,36/forecast"] = fc
    assert Wx.refresh(now=evening)
    assert Wx.wall_view(evening)["hi"] == 60, "the morning's high is kept"


def test_rain_in_plain_words(Wx):
    def hours(pops, look="rain"):
        return [{"t": (NOW.replace(minute=0) + dt.timedelta(hours=i)).isoformat(timespec="minutes"), "temp": 50,
                 "pop": p, "look": look} for i, p in enumerate(pops)]
    assert Wx.rain_words(hours([0] * 14), NOW) == "No rain expected"
    assert Wx.rain_words(hours([0, 0, 30, 30] + [0] * 10), NOW) == "A small chance of rain from 11 AM"
    assert Wx.rain_words(hours([90] * 14), NOW) == "Rain expected now"
    assert Wx.rain_words(hours([0] * 6 + [55] * 8, "snow"), NOW) == "Maybe some snow from 3 PM"
    assert Wx.rain_words([], NOW) == ""


def test_parse_the_weather_service_icons(Wx):
    assert Wx._nws_icon("https://api.weather.gov/icons/land/night/rain_showers,40/tsra,60?size=small", False) == "storm"
    assert Wx._nws_icon("https://api.weather.gov/icons/land/night/few?size=small", False) == "moon"
    assert Wx._nws_icon("https://api.weather.gov/icons/land/day/sct?size=small", True) == "partly"
    assert Wx._nws_icon("", True) == "cloud"
    assert set(Wx.LABEL) == set(Wx.ICONS)


# ---- the wall's pages and Today ----------------------------------------------------------------------------------
@pytest.fixture()
def wall_client(root, modules, Wx, home, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    app_mod, routes, W = modules("webapp.app"), modules("webapp.routes_wall"), modules("wall")
    monkeypatch.setattr(Wx, "_refresh_in_background", lambda cfg, now: None)
    con = W._con()
    for t in ("wall_pairings", "walls"):
        con.execute(f"DELETE FROM {t}")
    code = W.pair_start(con, "Kitchen wall", by="Ann")[0]
    con.close()
    routes._csrf.clear()
    c = TestClient(app_mod.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    assert c.post("/wall/pair", data={"code": W.pretty_code(code)}).status_code == 303
    now = dt.datetime.now()
    hours = [{"t": (now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=i)).isoformat(timespec="minutes"),
              "temp": 61, "pop": 0, "look": "rain"} for i in range(4)]
    days = [{"date": (now.date() + dt.timedelta(days=i)).isoformat(), "hi": 70 + i, "lo": 40 + i, "look": "snow", "pop": 0,
             "text": ""} for i in range(7)]
    modules("config").write_json(Wx._cache_path(), {"key": f"US:{ZIP}:F", "unit": "F", "source": "nws",
                                                    "fetched_at": now.isoformat(timespec="seconds"), "hours": hours,
                                                    "days": days})
    yield c
    Wx._cache_path().unlink(missing_ok=True)


def test_the_wall_shows_the_weather_and_hides_it_when_off(wall_client, home):
    c = wall_client
    today = c.get("/wall").text
    assert 'class="wx"' in today and "61°" in today and "high 70°, low 40°" in today and "No rain expected" in today
    rest = c.get("/wall/rest").text
    assert 'class="wxr"' in rest and "61°" in rest
    assert 'class="wxstrip"' in rest and rest.count('class="wxday') >= 2 and "Today" in rest, "today and the days ahead"
    week = c.get("/wall/week").text
    assert week.count('class="wxd"') == 7 and "70°/40°" in week
    assert "style=" not in today + rest + week, "no inline styles (CSP)"
    home(online=False)
    for page in ("/wall", "/wall/rest", "/wall/week"):
        html = c.get(page).text
        assert 'class="wx' not in html and "°" not in html


def test_the_stylesheet_has_the_weather_classes(root):
    css = (root / "data" / "webapp" / "static" / "wall.css").read_text(encoding="utf-8")
    for cls in (".wx ", ".wxt", ".wxs", ".wxd", ".wxr", ".timerow", ".wxstrip", ".wxday"):
        assert cls in css, cls
