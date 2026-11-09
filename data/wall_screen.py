"""The Mitra Wall's resting screen: a full-size clock (digital, traditional, modular = big time with cards for the weather,
next event, children's jobs and dinner, or Roman = quiet hands with serif numerals), the family's photos in rotation, and
the schedule (photo hours, night hours, how long each shows). Set by adults in Settings > Phones > Mitra Wall > Wall screen
(edit_actions.wall_screen_set / wall_photo_add / wall_photo_remove); drawn by /wall/rest (webapp/routes_wall.py) and
static/wall.js.

Photos: `<household>/wall_photos/`, one JPEG per photo with a random name. Every photo is made here from the one an adult
added: turned upright, longest side at most MAX_SIDE pixels, saved again WITHOUT its EXIF (no GPS position, no camera
details); an iPhone HEIC is read through data/heic.py. They are served only to a paired wall (/wall/photo/<name>) and to
adults on Settings; nothing goes online. Removing one deletes this copy only (the original stays wherever it came from).

Schedule (config/family.json `wall.screen` = the household's; a wall may have its own in walls.screen, migration 064): `photos_from`..`photos_to` = photos may show (outside: the clock only);
`night_from`..`night_to` = night (the dark clock, never photos, back to the clock after 30 s untouched); a range may run
past midnight. `night_tone`: dim = the day's clock, darker; red / amber = a bedroom clock (black, the large time and the
date in that colour, nothing bright). In the day the wall shows the clock for `clock_seconds`, then up to `per_turn` photos for `photo_seconds`
each, then the clock again.

  python data/wall_screen.py status
"""
import io
import json
import pathlib
import re
import secrets
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import config  # noqa: E402
import paths  # noqa: E402

FACES = ("digital", "analog", "modular", "typograph", "flip", "word", "dual", "kidsday", "led")
FACE_NAMES = {"digital": "digital", "analog": "traditional", "modular": "modular", "typograph": "Roman", "flip": "flip",
              "word": "word", "dual": "two-city", "kidsday": "kids' day", "led": "LED"}
# Dual time: the other place's clock. IANA names only from this list (the tablet's own time zone data turns them into
# the time; nothing is fetched).
ZONES = {"Asia/Kolkata": "India", "Asia/Dubai": "Dubai", "Asia/Singapore": "Singapore", "Asia/Manila": "Manila",
         "Asia/Shanghai": "China", "Asia/Tokyo": "Japan", "Asia/Seoul": "Korea", "Asia/Karachi": "Pakistan",
         "Asia/Dhaka": "Bangladesh", "Asia/Kathmandu": "Nepal", "Asia/Colombo": "Sri Lanka",
         "Australia/Sydney": "Sydney", "Pacific/Auckland": "Auckland", "Europe/London": "London", "Europe/Dublin": "Dublin",
         "Europe/Paris": "Paris", "Europe/Berlin": "Berlin", "Europe/Madrid": "Madrid", "Europe/Rome": "Rome",
         "Europe/Warsaw": "Warsaw", "Europe/Kyiv": "Kyiv", "Europe/Istanbul": "Istanbul", "Africa/Lagos": "Lagos",
         "Africa/Nairobi": "Nairobi", "Africa/Johannesburg": "Johannesburg", "Africa/Cairo": "Cairo",
         "America/Sao_Paulo": "Sao Paulo", "America/Mexico_City": "Mexico City", "America/Toronto": "Toronto",
         "America/Vancouver": "Vancouver", "America/New_York": "US Eastern", "America/Chicago": "US Central",
         "America/Denver": "US Mountain", "America/Phoenix": "Arizona", "America/Los_Angeles": "US Pacific",
         "America/Anchorage": "Alaska", "Pacific/Honolulu": "Hawaii"}
TONES = ("dim", "red", "amber")
STYLES = ("fade", "kenburns", "blur", "collage", "frame", "scrapbook")   # how the photos show (wall.js / wall.css `st-<style>`)
# the look of the wall's pages (owner, 2026-10-26; body class `theme-<name>` in wall.css; the resting clock keeps its own)
THEMES = {"paper": "Paper (warm white)", "night": "Night (dark, high contrast)", "slate": "Slate (cool grey)",
          "bold": "Bold (large black type, for reading far away)", "photo": "Photo (a family photo behind frosted cards)"}
STYLE_NAMES = {"fade": "fade", "kenburns": "slow zoom", "blur": "blurred fill", "collage": "collage", "frame": "frame and date", "scrapbook": "scrapbook page"}
# the LED desk clock (owner, 2026-11-02: a clock-only wall read from across the room; the companion app reads the same
# keys from extras.screen): `led_style` time = the time only / wide = time, temperature + month.day, a weekday strip /
# side = a weekday column, time, rain chance + temperature; `led_weekdays` = side's column; `hours24` = 20:15, else
# 08:15 with AM / PM
LED_STYLES = {"time": "Time only", "wide": "Time, temperature, date and weekdays", "side": "Weekdays, time, rain and temperature"}
LED_COLOURS = ("white", "blue", "green", "red", "amber")
LED_BGS = ("black", "wood")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
          "December")
DEFAULTS = {"clock": "digital", "night_tone": "dim", "photos": True, "photo_seconds": 15, "clock_seconds": 45, "per_turn": 4,
            "photos_from": "07:00", "photos_to": "21:00", "night_from": "22:00", "night_to": "06:00", "zone": "Asia/Kolkata",
            "photo_style": "fade", "tabs": [], "clock_only": False, "theme": "paper", "rotate_seconds": 0,
            "led_style": "time", "led_colour": "white", "led_bg": "black", "led_weekdays": True, "hours24": False}
TABS = ("chores", "meals")  # wall pages a family turns on (owner, 2026-10-26: off until an adult ticks them)
# clock_only: a bedroom wall shows the resting screen and nothing else (owner, 2026-10-26)
LIMITS = {"photo_seconds": (5, 300), "clock_seconds": (10, 3600), "per_turn": (1, 20), "rotate_seconds": (0, 110)}  # rotate 0 = off
TIMES = ("photos_from", "photos_to", "night_from", "night_to")
HM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
NAME = re.compile(r"^[0-9a-f]{16}\.jpg$")
TYPES = (".jpg", ".jpeg", ".png", ".webp", ".heic")
MAX_PHOTOS = 300
MAX_UPLOAD = 25 * 1024 * 1024
MAX_SIDE = 1920
QUALITY = 85


class ScreenError(ValueError):
    """A setting or a photo was refused, with a sentence for the person."""


def folder():
    return paths.HOME / "wall_photos"


# ---- settings ---------------------------------------------------------------------------------------------------------
def settings(cfg=None, wall_id=None):
    """The wall screen settings, every field present and valid (bad or missing values fall back to DEFAULTS).

    With `wall_id`: that wall's own screen (walls.screen, migration 064) when it has one, else the household's."""
    cfg = config.family() if cfg is None else cfg
    base = _valid(((cfg.get("wall") or {}).get("screen")) or {}, DEFAULTS)
    if wall_id is None:
        return base
    own = own_screen(wall_id)
    return _valid(own, base) if own else base


def own_screen(wall_id, con=None):
    """A wall's own settings as stored (a dict), or None = it follows the household's (or before migration 064)."""
    import db
    close = con is None
    try:
        con = con or db.connect(paths.DB, readonly=True)
    except sqlite3.Error:
        return None
    try:
        r = con.execute("SELECT screen FROM walls WHERE id=?", (int(wall_id),)).fetchone()
    except (sqlite3.Error, TypeError, ValueError):
        return None
    finally:
        if close:
            con.close()
    try:
        v = json.loads(r[0]) if r and r[0] else None
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def set_own(con, wall_id, s):
    """Store a wall's own settings (from `clean`), or None = back to the household's. -> True when the wall exists."""
    cur = con.execute("UPDATE walls SET screen=? WHERE id=? AND revoked_at IS NULL",
                      (json.dumps(s, sort_keys=True) if s else None, int(wall_id)))
    return cur.rowcount == 1


def _valid(raw, base):
    raw = dict(raw or {})
    out = dict(base)
    if raw.get("clock") in FACES:
        out["clock"] = raw["clock"]
    if raw.get("night_tone") in TONES:
        out["night_tone"] = raw["night_tone"]
    for k, ok in (("led_style", LED_STYLES), ("led_colour", LED_COLOURS), ("led_bg", LED_BGS)):
        if raw.get(k) in ok:
            out[k] = raw[k]
    for k in ("photos", "clock_only", "led_weekdays", "hours24"):
        if isinstance(raw.get(k), bool):
            out[k] = raw[k]
    for k, (lo, hi) in LIMITS.items():
        try:
            v = int(raw.get(k, out[k]))
        except (TypeError, ValueError):
            continue
        if lo <= v <= hi:
            out[k] = v
    for k in TIMES:
        if HM.match(str(raw.get(k) or "")):
            out[k] = raw[k]
    if raw.get("zone") in ZONES:
        out["zone"] = raw["zone"]
    if raw.get("photo_style") in STYLES:
        out["photo_style"] = raw["photo_style"]
    if raw.get("theme") in THEMES:
        out["theme"] = raw["theme"]
    if isinstance(raw.get("tabs"), list):
        out["tabs"] = [t for t in TABS if t in raw["tabs"]]
    return out


def clean(clock, photos, photo_seconds, clock_seconds, per_turn, photos_from, photos_to, night_from, night_to,
          night_tone="dim", zone="", photo_style="", tabs=(), clock_only=False, theme="", rotate_seconds=0, led=None):
    """Checked settings from a form (`tabs` = the TABS pages to show, `clock_only` = the resting screen only, `led` = the
    LED clock's led_style / led_colour / led_bg / led_weekdays / hours24, missing = DEFAULTS). Raises ScreenError with
    the field and the reason."""
    if clock not in FACES:
        raise ScreenError("clock: pick one of the faces in the list")
    if night_tone not in TONES:
        raise ScreenError("night clock: pick dim, red or amber")
    zone = zone or DEFAULTS["zone"]
    if zone not in ZONES:
        raise ScreenError("other place: pick one from the list")
    photo_style = photo_style or DEFAULTS["photo_style"]
    if photo_style not in STYLES:
        raise ScreenError("photo style: pick one from the list")
    theme = theme or DEFAULTS["theme"]
    if theme not in THEMES:
        raise ScreenError("look: pick one of the themes in the list")
    out = {"clock": clock, "night_tone": night_tone, "photos": bool(photos), "zone": zone, "photo_style": photo_style,
           "tabs": [t for t in TABS if t in (tabs or ())], "clock_only": bool(clock_only), "theme": theme}
    labels = {"photo_seconds": "seconds per photo", "clock_seconds": "seconds on the clock", "per_turn": "photos each turn"}
    for k, v in (("photo_seconds", photo_seconds), ("clock_seconds", clock_seconds), ("per_turn", per_turn)):
        lo, hi = LIMITS[k]
        try:
            n = int(str(v).strip())
        except (TypeError, ValueError):
            raise ScreenError(f"{labels[k]}: a whole number from {lo} to {hi}") from None
        if not lo <= n <= hi:
            raise ScreenError(f"{labels[k]}: a whole number from {lo} to {hi}")
        out[k] = n
    try:
        r = int(str(rotate_seconds or 0).strip())
    except ValueError:
        raise ScreenError("seconds per page: 0 (off) or a whole number from 10 to 110") from None
    if r != 0 and not 10 <= r <= 110:
        raise ScreenError("seconds per page: 0 (off) or a whole number from 10 to 110")
    out["rotate_seconds"] = r
    led = dict(led or {})
    for k, ok, what in (("led_style", LED_STYLES, "LED layout"), ("led_colour", LED_COLOURS, "LED colour"),
                        ("led_bg", LED_BGS, "LED background")):
        v = led.get(k) or DEFAULTS[k]
        if v not in ok:
            raise ScreenError(f"{what}: pick one from the list")
        out[k] = v
    for k in ("led_weekdays", "hours24"):
        out[k] = bool(led.get(k, DEFAULTS[k]))
    names = {"photos_from": "photos from", "photos_to": "photos until", "night_from": "night from", "night_to": "night until"}
    for k, v in (("photos_from", photos_from), ("photos_to", photos_to), ("night_from", night_from), ("night_to", night_to)):
        v = str(v or "").strip()
        if not HM.match(v):
            raise ScreenError(f"{names[k]}: a time like 07:00")
        out[k] = v
    if out["photos_from"] == out["photos_to"]:
        raise ScreenError("photos from and until: pick two different times")
    if out["night_from"] == out["night_to"]:
        raise ScreenError("night from and until: pick two different times")
    return out


def minutes(hm):
    h, m = HM.match(hm).groups()
    return int(h) * 60 + int(m)


def within(hm_now, start, end):
    """True when the time HH:MM is in start..end (end not included); a range may run past midnight."""
    n, a, b = minutes(hm_now), minutes(start), minutes(end)
    return a <= n < b if a < b else (n >= a or n < b)


# ---- the word clock and the two-city clock (wall.js does the same in the browser) -------------------------------------
HOUR_WORDS = ("twelve", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven")
MINUTE_WORDS = {5: ("m5", "minutes"), 10: ("m10", "minutes"), 15: ("quarter",), 20: ("m20", "minutes"),
                25: ("m20", "m5", "minutes"), 30: ("half",)}


def word_lit(hour, minute):
    """The words the word clock lights at hour:minute: 'it', 'is', the minutes (m5 / m10 / m20 = FIVE / TEN /
    TWENTY before MINUTES), 'past' / 'to', the hour as 'h<name>', 'oclock' on the hour, and dots d1-d4 for the
    minutes after the last five."""
    five = minute - minute % 5
    h = hour % 12
    words = ["it", "is"]
    if five == 0:
        words += ["h" + HOUR_WORDS[h], "oclock"]
    elif five <= 30:
        words += list(MINUTE_WORDS[five]) + ["past", "h" + HOUR_WORDS[h]]
    else:
        words += list(MINUTE_WORDS[60 - five]) + ["to", "h" + HOUR_WORDS[(h + 1) % 12]]
    return words + [f"d{i}" for i in range(1, minute % 5 + 1)]


def led_time(hour, minute, hours24=False):
    """The LED clock's time as (hours, minutes, AM / PM): always two hour digits, '08', '15', 'PM'; 24-hour = '20', '15',
    '' (wall.js does the same every second)."""
    h = hour if hours24 else (hour % 12 or 12)
    return f"{h:02d}", f"{minute:02d}", "" if hours24 else ("AM" if hour < 12 else "PM")


def zone_time(zone, now=None):
    """The time in `zone` as {'hm': '9:05', 'ap': 'PM', 'day': -1 / 0 / 1 against this PC's date}, or None when this
    Python has no time zone data (Windows without tzdata: the wall's own browser fills it in)."""
    import datetime as dt
    try:
        from zoneinfo import ZoneInfo
        here = now or dt.datetime.now().astimezone()
        there = here.astimezone(ZoneInfo(zone))
    except Exception:  # noqa: BLE001 - no tz database, or an unknown name
        return None
    return {"hm": f"{there.hour % 12 or 12}:{there.minute:02d}", "ap": "AM" if there.hour < 12 else "PM",
            "day": (there.date() - here.date()).days}


# ---- photos -----------------------------------------------------------------------------------------------------------
def photos():
    """The photo file names, oldest first."""
    f = folder()
    if not f.is_dir():
        return []
    return [p.name for p in sorted(f.iterdir(), key=lambda p: (p.stat().st_mtime, p.name)) if NAME.match(p.name)]


def photo_path(name):
    """The photo's file, or None (not a photo name, or not there). Only names this module made are served."""
    if not NAME.match(str(name or "")):
        return None
    p = folder() / name
    return p if p.is_file() else None


def make_jpeg(name, data):
    """JPEG bytes made from a photo: upright, longest side MAX_SIDE, no EXIF. Raises ScreenError."""
    ext = pathlib.Path(str(name or "")).suffix.lower()
    if ext not in TYPES:
        raise ScreenError("Use a photo: .jpg, .png, .webp or an iPhone .heic.")
    if not data or len(data) > MAX_UPLOAD:
        raise ScreenError(f"The photo must be under {MAX_UPLOAD // (1024 * 1024)} MB.")
    if ext == ".heic":
        import heic
        try:
            data = heic.to_jpeg(data)
        except ValueError:
            raise ScreenError("This PC could not read that iPhone photo (HEIC). Use a .jpg or .png.") from None
    try:
        from PIL import Image, ImageOps
    except ImportError:
        raise ScreenError("This PC cannot prepare photos (Pillow is not installed).") from None
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width * im.height > 80_000_000:
                raise ScreenError("That photo is too large to prepare.")
            im = ImageOps.exif_transpose(im)
            im = im.convert("RGB")
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            im.save(out, "JPEG", quality=QUALITY, optimize=True)  # a new file: no EXIF, no GPS, no camera details
    except ScreenError:
        raise
    except Exception:  # noqa: BLE001 - a broken or unknown picture
        raise ScreenError("That file does not look like a photo this PC can read.") from None
    return out.getvalue()


def taken_on(data):
    """The day a photo was taken (YYYY-MM-DD from its EXIF DateTimeOriginal / DateTime), or None. Read before make_jpeg
    drops the EXIF; only the day is kept (taken.json), never the place or the camera."""
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            ex = im.getexif()
            v = ex.get_ifd(0x8769).get(36867) or ex.get(306)
    except Exception:  # noqa: BLE001 - no Pillow, no EXIF, an odd file
        return None
    m = re.match(r"^(\d{4}):(\d{2}):(\d{2})", str(v or ""))
    if not m or m.group(1) < "1900":
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def _taken_file():
    return folder() / "taken.json"


def taken():
    """{photo name: 'YYYY-MM-DD'} for the photos whose day is known."""
    try:
        v = json.loads(_taken_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: d for k, d in v.items() if NAME.match(str(k)) and re.match(r"^\d{4}-\d{2}-\d{2}$", str(d))} \
        if isinstance(v, dict) else {}


def _taken_set(name, day):
    t = taken()
    if day:
        t[name] = day
    else:
        t.pop(name, None)
    f = _taken_file()
    tmp = f.with_name(".taken.json.tmp")
    tmp.write_text(json.dumps(t, sort_keys=True), encoding="utf-8")
    tmp.replace(f)


def taken_label(day):
    """'July 2024' for '2024-07-04' (the frame style's caption), '' when unknown."""
    m = re.match(r"^(\d{4})-(\d{2})-\d{2}$", str(day or ""))
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}" if m and 1 <= int(m.group(2)) <= 12 else ""


def add_photo(name, data):
    """Prepare and keep one photo. -> its file name. Raises ScreenError."""
    if len(photos()) >= MAX_PHOTOS:
        raise ScreenError(f"The wall keeps at most {MAX_PHOTOS} photos. Remove some first.")
    day = taken_on(data)
    jpeg = make_jpeg(name, data)
    f = folder()
    f.mkdir(parents=True, exist_ok=True)
    fname = f"{secrets.token_hex(8)}.jpg"
    tmp = f / f".{fname}.tmp"
    tmp.write_bytes(jpeg)
    tmp.replace(f / fname)
    if day:
        _taken_set(fname, day)
    return fname


def remove_photo(name):
    """Delete this wall copy of a photo. -> True when it was there."""
    p = photo_path(name)
    if not p:
        return False
    p.unlink()
    if name in taken():
        _taken_set(name, None)
    return True


# ---- what the resting screen gets -------------------------------------------------------------------------------------
def view(cfg=None, wall_id=None):
    """For /wall/rest: the face, the photo addresses (only when photos are on) and the schedule for wall.js."""
    s = settings(cfg, wall_id)
    urls = [f"/wall/photo/{n}" for n in photos()] if s["photos"] else []
    days = taken() if urls else {}
    return {**s, "urls": urls, "taken": {f"/wall/photo/{n}": taken_label(d) for n, d in days.items()}}


def main(argv=None):
    s = settings()
    print(f"Clock: {FACE_NAMES[s['clock']]}; night clock {s['night_tone']}")
    print(f"Photos: {'on' if s['photos'] else 'off'}, {len(photos())} kept in {folder()}")
    print(f"Photos between {s['photos_from']} and {s['photos_to']}; night {s['night_from']} to {s['night_to']}")
    print(f"Clock {s['clock_seconds']} s, then {s['per_turn']} photos of {s['photo_seconds']} s each")
    return 0


if __name__ == "__main__":
    sys.exit(main())
