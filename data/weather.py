"""The local weather for the Mitra Wall and Today: fetched by this PC (the tablet never goes online), only while the
family's online look-ups are on (Family > House switch, config/family.json lookups.online) and the home ZIP / postal
code is set (Family > House, edit_actions.home_area_set).

What goes out, through lookups.get() (the switch, the privacy fence and public hosts only): the ZIP code and the
country code (to find the ZIP area's rough position), then that position rounded to 2 decimals (about a kilometre:
the ZIP area, never the house). Nothing about a person.

Sources, no key: US = the National Weather Service (api.weather.gov: /points -> the forecast and the hourly forecast);
elsewhere, or when the Weather Service does not answer, Open-Meteo (api.open-meteo.com, hourly only: the day's high,
low and look come from its hours). The ZIP's position: zippopotam.us, else Open-Meteo's geocoding.

Cache: logs/weather.json (FRESH_MIN minutes; a failed refresh waits RETRY_MIN before the next try; data older than
STALE_HOURS is not shown). The wall never waits for the network: wall_view() reads the cache and starts a refresh in
the background when it is old. No weather = nothing shown, never an error.

  python data/weather.py status
  python data/weather.py now [--refresh]      what the wall would show (--refresh fetches first)
"""
import argparse
import datetime as dt
import json
import sys
import threading
import urllib.parse

import pathlib
HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import config  # noqa: E402
import log  # noqa: E402
import lookups  # noqa: E402
import paths  # noqa: E402

CACHE_NAME = "weather.json"
FRESH_MIN = 45
RETRY_MIN = 15
STALE_HOURS = 3
AHEAD_DAYS = 6                     # the resting screen's strip: today and the next five days
HOURS_KEPT = 72
NWS = "https://api.weather.gov"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
ZIPPO = "https://api.zippopotam.us"
SOURCE_NAME = {"nws": "National Weather Service", "open-meteo": "Open-Meteo"}

# Inline SVG paths (24 x 24, stroked like the wall's other icons; the CSP allows no outside images)
ICONS = {
    "sun": "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
           "M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z",
    "moon": "M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z",
    "partly": "M8 2v1.5M3.5 4.5l1 1M2 9h1.5M12.5 4.5l-1 1M5 11.8a3.5 3.5 0 0 1 6.4-4.3"
              "M17.5 12.5h-.9A5.5 5.5 0 1 0 11 19.5h6.5a3.5 3.5 0 0 0 0-7z",
    "partly_night": "M11 8.25A4 4 0 1 1 5.75 3a3.25 3.25 0 0 0 5.25 5.25z"
                    "M17.5 12.5h-.9A5.5 5.5 0 1 0 11 19.5h6.5a3.5 3.5 0 0 0 0-7z",
    "cloud": "M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z",
    "rain": "M16 13v8M8 13v8M12 15v8M20 16.58A5 5 0 0 0 18 7h-1.26A8 8 0 1 0 4 15.25",
    "storm": "M19 16.9A5 5 0 0 0 18 7h-1.26a8 8 0 1 0-11.62 9M13 11l-4 6h6l-4 6",
    "snow": "M20 17.58A5 5 0 0 0 18 8h-1.26A8 8 0 1 0 4 16.25M8 16h.01M8 20h.01M12 18h.01M12 22h.01M16 16h.01M16 20h.01",
    "fog": "M4 9h16M3 13h18M5 17h14M8 21h8",
    "wind": "M9.6 4.6A2 2 0 1 1 11 8H2M12.6 19.4A2 2 0 1 0 14 16H2M17.7 7.7A2.5 2.5 0 1 1 19.5 12H2",
}
LABEL = {"sun": "Sunny", "moon": "Clear", "partly": "Partly cloudy", "partly_night": "Partly cloudy", "cloud": "Cloudy",
         "rain": "Rain", "storm": "Thunderstorms", "snow": "Snow", "fog": "Fog", "wind": "Windy"}
# worst first: the look of a day is its worst daytime hour
SEVERITY = ("storm", "snow", "rain", "fog", "wind", "cloud", "partly", "sun")
# api.weather.gov icon names (the last part of an icon address: .../land/day/rain_showers,40)
NWS_ICON = {"skc": "sun", "few": "sun", "hot": "sun", "cold": "sun", "sct": "partly", "bkn": "cloud", "ovc": "cloud",
            "wind_skc": "wind", "wind_few": "wind", "wind_sct": "wind", "wind_bkn": "wind", "wind_ovc": "wind",
            "snow": "snow", "rain_snow": "snow", "rain_sleet": "snow", "snow_sleet": "snow", "fzra": "snow",
            "rain_fzra": "snow", "snow_fzra": "snow", "sleet": "snow", "blizzard": "snow",
            "rain": "rain", "rain_showers": "rain", "rain_showers_hi": "rain",
            "tsra": "storm", "tsra_sct": "storm", "tsra_hi": "storm", "tornado": "storm", "hurricane": "storm",
            "tropical_storm": "storm", "dust": "fog", "smoke": "fog", "haze": "fog", "fog": "fog"}

_lock = threading.Lock()
_busy = [False]


def _log():
    return log.get("weather")


def _cache_path():
    return paths.LOGS / CACHE_NAME


# ---- the family's settings ------------------------------------------------------------------------------------------
def setting(cfg=None):
    """-> {"zip", "country", "unit"} when the weather may be fetched (look-ups on, a ZIP / postal code set), else None."""
    cfg = config.family() if cfg is None else cfg
    if not lookups.enabled(cfg):
        return None
    country = str(cfg.get("country") or "US").strip().upper()[:2] or "US"
    raw = " ".join(str((cfg.get("region") or {}).get("zip") or "").split())
    if country == "US":
        z = raw[:5]
        if not (len(z) == 5 and z.isdigit()):
            return None
    else:  # the part before the space is the postal area (UK SW1A, Canada M5V); letters and digits only
        z = "".join(c for c in raw.split(" ")[0] if c.isalnum()).upper()[:10]
        if len(z) < 2:
            return None
    return {"zip": z, "country": country, "unit": "F" if country in ("US", "LR", "MM") else "C"}


def _key(s):
    return f"{s['country']}:{s['zip']}:{s['unit']}"


# ---- the cache --------------------------------------------------------------------------------------------------------
def load():
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data):
    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        config.write_json(_cache_path(), data)
    except OSError:
        _log().warning("weather: the cache could not be written")


def _age_min(stamp, now):
    try:
        return (now - dt.datetime.fromisoformat(str(stamp))).total_seconds() / 60
    except (TypeError, ValueError):
        return None


# ---- fetching -----------------------------------------------------------------------------------------------------------
def _json(url, accept="application/json"):
    _ctype, body, _final = lookups.get(url, accept=accept)
    try:
        return json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise lookups.Refused("The weather service sent something unreadable.") from None


def place(s):
    """The ZIP area's rough position: {"lat", "lon"} rounded to 2 decimals. Raises lookups.Refused / ValueError."""
    cc = s["country"].lower()
    try:
        d = _json(f"{ZIPPO}/{cc}/{urllib.parse.quote(s['zip'])}")
        p = (d.get("places") or [])[0]
        lat, lon = float(p["latitude"]), float(p["longitude"])
    except (lookups.Refused, IndexError, KeyError, TypeError, ValueError, AttributeError):
        q = urllib.parse.urlencode({"name": s["zip"], "count": 1, "countryCode": s["country"]})
        d = _json(f"{GEOCODE}?{q}")
        r = (d.get("results") or [{}])[0]
        lat, lon = float(r["latitude"]), float(r["longitude"])
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("position out of range")
    return {"lat": round(lat, 2), "lon": round(lon, 2)}


def _local(stamp):
    """An ISO time with an offset (the Weather Service) -> this PC's local time without one; a plain one stays."""
    t = dt.datetime.fromisoformat(str(stamp))
    return t.astimezone().replace(tzinfo=None) if t.tzinfo else t


def _nws_icon(url, daytime):
    """'https://api.weather.gov/icons/land/night/rain_showers,40/sct?size=small' -> 'rain' (the first, worse part)."""
    path = urllib.parse.urlsplit(str(url or "")).path
    parts = [p.split(",")[0] for p in path.split("/")[4:] if p]  # after /icons/land/day/
    looks = [NWS_ICON[p] for p in parts if p in NWS_ICON]
    look = min(looks, key=SEVERITY.index) if looks else "cloud"
    return _night(look, daytime)


def _night(look, daytime):
    if daytime is False:
        return {"sun": "moon", "partly": "partly_night"}.get(look, look)
    return look


def _pop(p):
    try:
        v = (p.get("probabilityOfPrecipitation") or {}).get("value")
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def parse_nws(forecast, hourly):
    """The two Weather Service answers -> {"hours": [...], "days": [...]} (see _shape). Raises KeyError / ValueError."""
    hours = []
    for p in (hourly.get("properties") or {})["periods"]:
        hours.append({"t": _local(p["startTime"]).isoformat(timespec="minutes"), "temp": int(round(float(p["temperature"]))),
                      "pop": _pop(p), "look": _nws_icon(p.get("icon"), p.get("isDaytime"))})
    days = {}
    for p in (forecast.get("properties") or {})["periods"]:
        d = _local(p["startTime"]).date().isoformat()
        row = days.setdefault(d, {"date": d, "hi": None, "lo": None, "look": None, "pop": 0, "text": ""})
        t = int(round(float(p["temperature"])))
        if p.get("isDaytime"):
            row.update(hi=t, look=_nws_icon(p.get("icon"), True), text=str(p.get("shortForecast") or "")[:60])
        else:
            row["lo"] = t
            if not row["look"]:  # only tonight is left of today (the evening): its night look, a moon when clear
                row.update(look=_nws_icon(p.get("icon"), False), text=str(p.get("shortForecast") or "")[:60])
        row["pop"] = max(row["pop"], _pop(p))
    # in the evening the forecast starts with Tonight: today has no high (the hours left are not the day's high);
    # refresh() keeps the high of an earlier fetch the same day
    return {"hours": hours[:HOURS_KEPT], "days": sorted(days.values(), key=lambda r: r["date"])[:8]}


def _wmo(code, daytime=True):
    """Open-Meteo's WMO weather code -> a look."""
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "cloud"
    if c in (0, 1):
        look = "sun"
    elif c == 2:
        look = "partly"
    elif c == 3:
        look = "cloud"
    elif c in (45, 48):
        look = "fog"
    elif 51 <= c <= 67 or 80 <= c <= 82:
        look = "rain"
    elif 71 <= c <= 77 or c in (85, 86):
        look = "snow"
    elif c >= 95:
        look = "storm"
    else:
        look = "cloud"
    return _night(look, bool(daytime))


def parse_open_meteo(data):
    """Open-Meteo's hourly answer -> {"hours", "days"}: a day's high / low = its hours, its look = the worst daytime
    hour (8 AM - 8 PM), its rain chance = the highest hour."""
    h = data["hourly"]
    hours = []
    for i, t in enumerate(h["time"]):
        temp = h["temperature_2m"][i]
        if temp is None:
            continue
        pop = (h.get("precipitation_probability") or [None] * len(h["time"]))[i]
        day = (h.get("is_day") or [1] * len(h["time"]))[i]
        hours.append({"t": _local(t).isoformat(timespec="minutes"), "temp": int(round(float(temp))),
                      "pop": int(pop or 0), "look": _wmo((h.get("weather_code") or [None] * len(h["time"]))[i], day)})
    days = {}
    for x in hours:
        d = x["t"][:10]
        row = days.setdefault(d, {"date": d, "hi": x["temp"], "lo": x["temp"], "look": None, "pop": 0, "text": ""})
        row["hi"], row["lo"], row["pop"] = max(row["hi"], x["temp"]), min(row["lo"], x["temp"]), max(row["pop"], x["pop"])
        if 8 <= int(x["t"][11:13]) < 20:
            look = {"moon": "sun", "partly_night": "partly"}.get(x["look"], x["look"])
            if row["look"] is None or SEVERITY.index(look) < SEVERITY.index(row["look"]):
                row["look"] = look
    for row in days.values():
        row["look"] = row["look"] or "cloud"
        row["text"] = LABEL[row["look"]]
    return {"hours": hours[:HOURS_KEPT], "days": sorted(days.values(), key=lambda r: r["date"])[:8]}


def _fetch_nws(pos, old):
    pts = old.get("nws") if (old.get("pos") == pos and old.get("nws")) else None
    if not pts:
        d = _json(f"{NWS}/points/{pos['lat']:.2f},{pos['lon']:.2f}", accept="application/geo+json")
        prop = d.get("properties") or {}
        pts = {"forecast": prop["forecast"], "hourly": prop["forecastHourly"]}
        for u in pts.values():  # the answer names the next addresses: they must be the Weather Service's own
            if urllib.parse.urlsplit(str(u)).hostname != "api.weather.gov":
                raise lookups.Refused("The Weather Service pointed somewhere else.")
    fc = _json(pts["forecast"], accept="application/geo+json")
    hr = _json(pts["hourly"], accept="application/geo+json")
    return parse_nws(fc, hr), pts


def _fetch_open_meteo(pos, unit):
    q = {"latitude": f"{pos['lat']:.2f}", "longitude": f"{pos['lon']:.2f}",
         "hourly": "temperature_2m,precipitation_probability,weather_code,is_day", "timezone": "auto", "forecast_days": 7}
    if unit == "F":
        q["temperature_unit"] = "fahrenheit"
    return parse_open_meteo(_json(f"{OPEN_METEO}?{urllib.parse.urlencode(q)}"))


def refresh(cfg=None, now=None):
    """Fetch now (the caller waits). -> True when fresh weather was saved. Never raises: a failure is remembered in the
    cache (failed_at) and the earlier weather stays until it is too old to show."""
    s = setting(cfg)
    if not s:
        return False
    now = now or dt.datetime.now()
    old = load()
    if old.get("key") != _key(s):
        old = {}
    try:
        pos = old.get("pos") or place(s)
        got, pts, source = None, None, None
        if s["country"] == "US":
            try:
                got, pts = _fetch_nws(pos, old)
                source = "nws"
            except (lookups.Refused, KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
                _log().info("weather: the Weather Service did not answer (%s); trying Open-Meteo", str(e)[:80])
        if got is None:
            got, source = _fetch_open_meteo(pos, s["unit"]), "open-meteo"
        if not got["hours"] and not got["days"]:
            raise ValueError("no forecast in the answer")
    except (lookups.Refused, KeyError, TypeError, ValueError, IndexError, AttributeError) as e:
        _log().info("weather: no update (%s)", str(e)[:120])
        _save({**old, "key": _key(s), "failed_at": now.isoformat(timespec="seconds")})
        return False
    before = {d["date"]: d for d in old.get("days") or []}
    for d in got["days"]:  # a high from an earlier fetch the same day (the afternoon is gone from the new one)
        if d["hi"] is None and (before.get(d["date"]) or {}).get("hi") is not None:
            d["hi"] = before[d["date"]]["hi"]
    _save({"key": _key(s), "unit": s["unit"], "pos": pos, "nws": pts, "source": source,
           "fetched_at": now.isoformat(timespec="seconds"), "failed_at": None, **got})
    return True


def _refresh_in_background(cfg, now):
    with _lock:
        if _busy[0]:
            return
        _busy[0] = True

    def run():
        try:
            refresh(cfg, now)
        except Exception:  # noqa: BLE001 - the wall must never break because of the weather
            _log().exception("weather: refresh failed")
        finally:
            with _lock:
                _busy[0] = False
    threading.Thread(target=run, name="weather-refresh", daemon=True).start()


def ensure(cfg=None, now=None, background=True):
    """Start a refresh when the cache is old (and the last failure is not too recent). -> the cache as it is now."""
    s = setting(cfg)
    if not s:
        return {}
    now = now or dt.datetime.now()
    data = load()
    same = data.get("key") == _key(s)
    age = _age_min(data.get("fetched_at"), now) if same else None
    failed = _age_min(data.get("failed_at"), now) if same else None
    due = age is None or age >= FRESH_MIN or age < 0
    if due and (failed is None or failed >= RETRY_MIN or failed < 0):
        if background:
            _refresh_in_background(cfg, now)
        else:
            refresh(cfg, now)
        data = load()
    return data if data.get("key") == _key(s) else {}


# ---- what the screens show ----------------------------------------------------------------------------------------------
def rain_words(hours, now):
    """The rest of today (until 10 PM, at least the next 6 hours) in plain words: 'No rain expected', 'Rain likely from
    3 PM'. '' when there are no hours."""
    end = max(now.replace(hour=22, minute=0, second=0, microsecond=0), now + dt.timedelta(hours=6))
    start = now.replace(minute=0, second=0, microsecond=0)
    ahead = [h for h in hours if start <= dt.datetime.fromisoformat(h["t"]) < end]
    if not ahead:
        return ""
    top = max(h["pop"] for h in ahead)
    snow = any(h["look"] == "snow" and h["pop"] >= 30 for h in ahead)
    word = "snow" if snow else "rain"
    if top < 20:
        return f"No {word} expected"
    level = (f"A small chance of {word}" if top < 40 else f"Maybe some {word}" if top < 60
             else f"{word.capitalize()} likely" if top < 80 else f"{word.capitalize()} expected")
    first = next(h for h in ahead if h["pop"] >= min(top, 40))
    t = dt.datetime.fromisoformat(first["t"])
    if t <= now:
        return level + (" now" if top >= 60 else " today")
    return f"{level} from {t.hour % 12 or 12} {'AM' if t.hour < 12 else 'PM'}"


def view(data, now):
    """The cache -> what a screen shows, or None (nothing, too old, or nothing for now)."""
    if not data or not data.get("fetched_at"):
        return None
    age = _age_min(data.get("fetched_at"), now)
    if age is None or age > STALE_HOURS * 60 or age < -60:
        return None
    hours = data.get("hours") or []
    cur = None
    for h in hours:
        t = dt.datetime.fromisoformat(h["t"])
        if t <= now < t + dt.timedelta(hours=1):
            cur = h
            break
    today = now.date().isoformat()
    days = {d["date"]: {**d, "label": LABEL.get(d.get("look"), "")} for d in data.get("days") or [] if d.get("date", "") >= today}
    if cur is None and today not in days:
        return None
    t_day = days.get(today) or {}
    unit = data.get("unit") or "F"
    hi, lo = t_day.get("hi"), t_day.get("lo")
    out = {"unit": unit, "source": SOURCE_NAME.get(data.get("source"), ""), "hi": hi, "lo": lo,
           "rain": rain_words(hours, now), "days": days,
           "updated": _hm(dt.datetime.fromisoformat(data["fetched_at"]))}
    if cur is not None:
        out.update(temp=cur["temp"], look=cur["look"], label=LABEL.get(cur["look"], ""))
    else:
        out.update(temp=None, look=t_day.get("look") or "cloud", label=t_day.get("label", ""))
    # today and the next five days for the resting screen's strip (owner, 2026-10-26: weather on every clock)
    out["ahead"] = [{"date": k, "dow": "Today" if k == today else dt.date.fromisoformat(k).strftime("%a"),
                     "hi": d.get("hi"), "lo": d.get("lo"), "look": d.get("look") or "cloud", "label": d["label"],
                     "chance": d.get("pop")}  # not "pop": a template reads d.pop as the dict's method
                    for k, d in sorted(days.items())[:AHEAD_DAYS]]
    return out


def _hm(t):
    return f"{t.hour % 12 or 12}:{t.minute:02d} {'AM' if t.hour < 12 else 'PM'}"


def wall_view(now=None, cfg=None):
    """What the wall shows, or None. Never fetches in the caller's thread and never raises."""
    try:
        now = now or dt.datetime.now()
        if not setting(cfg):
            return None
        return view(ensure(cfg, now), now)
    except Exception:  # noqa: BLE001 - no weather is fine; a broken wall is not
        _log().exception("weather: view failed")
        return None


def line(now=None, cfg=None):
    """One line for the PC's Today page: '61°F, Partly cloudy · high 66° low 50° · No rain expected', or ''."""
    v = wall_view(now, cfg)
    if not v:
        return ""
    bits = []
    if v.get("temp") is not None:
        bits.append(f"{v['temp']}°{v['unit']}" + (f", {v['label']}" if v.get("label") else ""))
    elif v.get("label"):
        bits.append(v["label"])
    if v.get("hi") is not None and v.get("lo") is not None:
        bits.append(f"high {v['hi']}° low {v['lo']}°")
    elif v.get("lo") is not None:
        bits.append(f"low {v['lo']}° tonight")
    if v.get("rain"):
        bits.append(v["rain"])
    return " · ".join(bits)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    n = sub.add_parser("now")
    n.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    s = setting()
    if a.cmd == "status":
        if not s:
            print("Weather: off (turn on online look-ups and set the ZIP code in Family > House).")
            return 0
        d = load()
        same = d.get("key") == _key(s)
        print(f"Weather: on for {s['zip']} ({s['country']}, °{s['unit']}).")
        print(f"Last update: {d.get('fetched_at') if same and d.get('fetched_at') else 'none'}"
              f"{' from ' + SOURCE_NAME.get(d.get('source'), '') if same and d.get('source') else ''}")
        if same and d.get("failed_at"):
            print(f"Last failed try: {d['failed_at']}")
        return 0
    if not s:
        print("Weather is off.")
        return 1
    if a.refresh:
        refresh()
    text = line()
    print(text or "No weather to show yet.")
    return 0 if text else 1


if __name__ == "__main__":
    sys.exit(main())
