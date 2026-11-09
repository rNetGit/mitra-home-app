"""Seasonal looks for the Mitra Wall: which look (if any) a given day gets, and the look itself as plain data.

  python data/wall_season.py [YYYY-MM-DD]     the look for that day (default today) as JSON, or "none"
  python data/wall_season.py check            every shipped look passes validation

A look is DATA, so the wall (browser and app) can apply it through one generic hook and a new festival needs no new
code in the page: colours (CSS token values), decoration marks with the animation each one uses, a drawn backdrop (a
named scene the wall's CSS / SVG knows), which existing clock face to use and how many days before the festival the
look starts. The look applies on the festival day and for `runup_days` days before it, never after.

Festival days: Halloween (Oct 31) and New Year (Jan 1) are fixed dates; Christmas is the fixed date Dec 25 or any
special day named Christmas Day (not Christmas Eve, which would start the run-up a day early). Every other look comes
only from the PC's special days (data/calendar_days.py: the country's public holidays, the festival pack in
config/festivals.json, or a day an adult added), never from a date written here: a look's `names` are whole words
looked for in the day's name ("Holi" never matches "Holiday"), and `months` keeps a look to its own date when two
countries share a name (India's Independence Day is in August, the USA's in July). A look found by name shows that
day's own name on the wall ("Makar Sankranti / Pongal", "Lohri"), so one harvest look serves several festivals.
The day is always an argument: this module never reads the system date itself.
"""
import datetime as dt
import json
import re
import sys

HERE = __import__("pathlib").Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import dates  # noqa: E402
import wall_screen  # noqa: E402

MARKS = ("pumpkin", "bat", "moon", "lantern", "diya", "rangoli", "flame", "tree", "snow", "star",
         "toran", "kandil", "spark", "spark2", "gulal", "gulal2", "thali", "bell", "modak", "hibiscus", "durva", "bunting",
         "garbo", "dandiya", "bow", "apta", "kite", "kite2", "sun", "pot", "fire", "pookalam", "toranam", "beads", "bilva",
         "gudi", "confetti", "flag", "marigold", "leaf", "harvest")
ANIMATIONS = ("none", "flicker", "glow", "sway", "drift")
# the drawn scenes: templates/_wall_season.html and the companion's www/wallscenes.js, both written by the companion's
# scripts/wall_scenes.py (change the art there)
BACKDROPS = ("night_pumpkins", "snow_trees", "diwali_diyas", "holi_colours", "ganesh_modak", "navratri_garba", "dussehra_bow",
             "sankranti_kites", "onam_pookalam", "shivaratri_moon", "ugadi_gudi", "newyear_fireworks", "us_july4",
             "india_tricolour", "canada_maple", "thanksgiving_harvest")
COLOUR_KEYS = ("bg", "surface", "text", "muted", "accent", "on_accent", "ring")
MIN_CONTRAST = 4.5
RUNUP_DAYS = 3

LOOKS = {
    "halloween": {
        "name": "Halloween", "fixed": (10, 31), "names": (), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "night_pumpkins",
        "colours": {"bg": "#1a1024", "surface": "#2a1a3a", "text": "#f5ecff", "muted": "#cdbbea", "accent": "#ff8a1f",
                    "on_accent": "#1a1024", "ring": "#7b4fc9"},
        "marks": [{"mark": "pumpkin", "animation": "glow"}, {"mark": "bat", "animation": "drift"},
                  {"mark": "moon", "animation": "none"}, {"mark": "lantern", "animation": "sway"}],
    },
    "diwali": {
        "name": "Diwali", "fixed": None, "names": ("diwali", "deepavali"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "diwali_diyas",
        "colours": {"bg": "#3a0f1e", "surface": "#521830", "text": "#fff3dc", "muted": "#f0cfa8", "accent": "#f2b63d",
                    "on_accent": "#3a0f1e", "ring": "#d63a7a"},
        "marks": [{"mark": "diya", "animation": "flicker"}, {"mark": "kandil", "animation": "sway"},
                  {"mark": "spark", "animation": "glow"}, {"mark": "rangoli", "animation": "none"}, {"mark": "toran", "animation": "none"},
                  {"mark": "star", "animation": "glow"}],
    },
    "christmas": {
        "name": "Christmas", "fixed": (12, 25), "names": ("christmas day",), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "snow_trees",
        "colours": {"bg": "#0f2a22", "surface": "#17382e", "text": "#f4f8f6", "muted": "#bfd8cc", "accent": "#c93b3b",
                    "on_accent": "#ffffff", "ring": "#e8c872"},
        "marks": [{"mark": "tree", "animation": "none"}, {"mark": "snow", "animation": "drift"},
                  {"mark": "star", "animation": "glow"}],
    },
    "holi": {
        "name": "Holi", "fixed": None, "names": ("holi", "holika", "dhulandi", "rangwali holi"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "holi_colours",
        "colours": {"bg": "#1e1538", "surface": "#2c2050", "text": "#fdf6ff", "muted": "#dccbf7", "accent": "#ff5fae", "on_accent": "#1e1538", "ring": "#ffd23f"},
        "marks": [{"mark": "gulal", "animation": "drift"}, {"mark": "gulal2", "animation": "glow"}, {"mark": "thali", "animation": "none"}],
    },
    "ganesh": {
        "name": "Ganesh Chaturthi", "fixed": None, "names": ("ganesh", "vinayaka", "vinayagar", "ganeshotsav"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "ganesh_modak",
        "colours": {"bg": "#2a1206", "surface": "#3f1d0c", "text": "#fff4e0", "muted": "#f3d2a2", "accent": "#ff9933", "on_accent": "#2a1206", "ring": "#d7263d"},
        "marks": [{"mark": "diya", "animation": "flicker"}, {"mark": "bell", "animation": "sway"}, {"mark": "modak", "animation": "none"}, {"mark": "hibiscus", "animation": "none"}, {"mark": "toran", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "navratri": {
        "name": "Navratri", "fixed": None, "names": ("navratri", "navaratri", "durga puja"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "navratri_garba",
        "colours": {"bg": "#2b0f3a", "surface": "#3f1753", "text": "#fff1fb", "muted": "#ecc9f3", "accent": "#ff5c93", "on_accent": "#2b0f3a", "ring": "#ffc93c"},
        "marks": [{"mark": "garbo", "animation": "glow"}, {"mark": "flame", "animation": "flicker"}, {"mark": "dandiya", "animation": "none"}, {"mark": "bunting", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "dussehra": {
        "name": "Dussehra", "fixed": None, "names": ("dussehra", "dussera", "dasara", "vijayadashami"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "dussehra_bow",
        "colours": {"bg": "#2e1003", "surface": "#451a06", "text": "#fff3e3", "muted": "#f2cfa6", "accent": "#ffb020", "on_accent": "#2e1003", "ring": "#d62839"},
        "marks": [{"mark": "diya", "animation": "flicker"}, {"mark": "spark", "animation": "glow"}, {"mark": "bow", "animation": "none"}, {"mark": "apta", "animation": "none"}, {"mark": "toran", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "sankranti": {
        "name": "Makar Sankranti", "fixed": None, "names": ("sankranti", "pongal", "lohri", "bhogi", "kanuma", "uttarayan", "baisakhi", "vaisakhi", "bihu"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "sankranti_kites",
        "colours": {"bg": "#0f2747", "surface": "#173863", "text": "#f4f9ff", "muted": "#c6dbf5", "accent": "#ffb81c", "on_accent": "#0f2747", "ring": "#ff5a5f"},
        "marks": [{"mark": "kite", "animation": "sway"}, {"mark": "kite2", "animation": "sway"}, {"mark": "sun", "animation": "glow"}, {"mark": "fire", "animation": "flicker"}, {"mark": "pot", "animation": "none"}],
    },
    "onam": {
        "name": "Onam", "fixed": None, "names": ("onam", "thiruvonam"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "onam_pookalam",
        "colours": {"bg": "#0e2a1c", "surface": "#163d29", "text": "#f6fbf2", "muted": "#cfe5c4", "accent": "#ffd23f", "on_accent": "#0e2a1c", "ring": "#ff7a1a"},
        "marks": [{"mark": "pookalam", "animation": "none"}, {"mark": "flame", "animation": "flicker"}, {"mark": "toranam", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "shivaratri": {
        "name": "Maha Shivaratri", "fixed": None, "names": ("shivaratri", "shivratri", "mahashivratri", "mahashivaratri"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "shivaratri_moon",
        "colours": {"bg": "#0b1226", "surface": "#141f3d", "text": "#eef3ff", "muted": "#c3cdea", "accent": "#8fb3ff", "on_accent": "#0b1226", "ring": "#f6efd2"},
        "marks": [{"mark": "moon", "animation": "glow"}, {"mark": "diya", "animation": "flicker"}, {"mark": "beads", "animation": "none"}, {"mark": "bilva", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "ugadi": {
        "name": "Ugadi", "fixed": None, "names": ("ugadi", "yugadi", "gudi padwa"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "ugadi_gudi",
        "colours": {"bg": "#2b1a05", "surface": "#40280a", "text": "#fff6e3", "muted": "#f1d9a8", "accent": "#ffc233", "on_accent": "#2b1a05", "ring": "#d62839"},
        "marks": [{"mark": "gudi", "animation": "none"}, {"mark": "toranam", "animation": "none"}, {"mark": "rangoli", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "newyear": {
        "name": "New Year", "fixed": (1, 1), "names": ("new year's day",), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "newyear_fireworks",
        "colours": {"bg": "#0a0f24", "surface": "#141b3d", "text": "#f3f5ff", "muted": "#c8cdee", "accent": "#ffd23f", "on_accent": "#0a0f24", "ring": "#ff5fae"},
        "marks": [{"mark": "spark", "animation": "glow"}, {"mark": "spark2", "animation": "glow"}, {"mark": "confetti", "animation": "drift"}, {"mark": "star", "animation": "glow"}],
    },
    "july4": {
        "name": "Independence Day", "fixed": None, "names": ("independence day", "fourth of july"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "us_july4", "months": (7,),
        "colours": {"bg": "#0b1d3a", "surface": "#12305c", "text": "#f5f8ff", "muted": "#c9d6ee", "accent": "#ff6b6b", "on_accent": "#0b1d3a", "ring": "#4f8cff"},
        "marks": [{"mark": "spark", "animation": "glow"}, {"mark": "spark2", "animation": "glow"}, {"mark": "bunting", "animation": "none"}, {"mark": "flag", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "india": {
        "name": "Independence Day", "fixed": None, "names": ("independence day", "republic day", "swatantrata diwas", "gantantra diwas"), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "india_tricolour", "months": (1, 8),
        "colours": {"bg": "#102a43", "surface": "#173a5c", "text": "#f6fbff", "muted": "#cfe0f0", "accent": "#ff9933", "on_accent": "#102a43", "ring": "#2ecc71"},
        "marks": [{"mark": "kite", "animation": "sway"}, {"mark": "bunting", "animation": "none"}, {"mark": "flag", "animation": "none"}, {"mark": "marigold", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "canada": {
        "name": "Canada Day", "fixed": None, "names": ("canada day",), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "canada_maple",
        "colours": {"bg": "#2b0a0e", "surface": "#401219", "text": "#fff5f5", "muted": "#f2cfd2", "accent": "#ff6b75", "on_accent": "#2b0a0e", "ring": "#ffffff"},
        "marks": [{"mark": "leaf", "animation": "drift"}, {"mark": "spark2", "animation": "glow"}, {"mark": "bunting", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
    "thanksgiving": {
        "name": "Thanksgiving", "fixed": None, "names": ("thanksgiving",), "runup_days": RUNUP_DAYS, "clock": "analog",
        "backdrop": "thanksgiving_harvest",
        "colours": {"bg": "#2a1405", "surface": "#3f1f08", "text": "#fff3e6", "muted": "#f2d3ae", "accent": "#ff922b", "on_accent": "#2a1405", "ring": "#c92a2a"},
        "marks": [{"mark": "leaf", "animation": "drift"}, {"mark": "harvest", "animation": "none"}, {"mark": "star", "animation": "glow"}],
    },
}

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _lum(hex_):
    def chan(i):
        v = int(hex_[1 + 2 * i:3 + 2 * i], 16) / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * chan(0) + 0.7152 * chan(1) + 0.0722 * chan(2)


def contrast(a, b):
    """WCAG contrast ratio of two #rrggbb colours (1 to 21)."""
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def validate(look):
    """[problem, ...] for one look: empty when it is fit to ship."""
    out = []
    col = look.get("colours") or {}
    for k in COLOUR_KEYS:
        if not _HEX.match(str(col.get(k) or "")):
            out.append(f"colour {k} is not a #rrggbb value")
    if not out:
        for fg, bg in (("text", "bg"), ("text", "surface"), ("muted", "surface"), ("on_accent", "accent")):
            if contrast(col[fg], col[bg]) < MIN_CONTRAST:
                out.append(f"{fg} on {bg} is under {MIN_CONTRAST}:1")
    if not look.get("name"):
        out.append("no name")
    for m in look.get("marks") or []:
        if m.get("mark") not in MARKS:
            out.append(f"unknown mark {m.get('mark')!r}")
        if m.get("animation") not in ANIMATIONS:
            out.append(f"unknown animation {m.get('animation')!r}")
    if look.get("backdrop") not in BACKDROPS:
        out.append(f"unknown backdrop {look.get('backdrop')!r}")
    if look.get("clock") not in wall_screen.FACES:
        out.append(f"unknown clock face {look.get('clock')!r}")
    if not isinstance(look.get("runup_days"), int) or not 0 <= look["runup_days"] <= 14:
        out.append("run-up days must be 0 to 14")
    return out


def _words(names):
    return re.compile(r"\b(?:" + "|".join(re.escape(w) for w in names) + r")\b") if names else None


def _festival_dates(look, day, con):
    """[(date, name), ...]: the festival dates of this look that fall on `day` or up to `runup_days` after it, with the
    special day's own name when it was found by name (None for a fixed date)."""
    end = day + dt.timedelta(days=look["runup_days"])
    found = []
    if look["fixed"]:
        m, d = look["fixed"]
        for y in {day.year, end.year}:
            f = dt.date(y, m, d)
            if day <= f <= end:
                found.append((f, None))
    words = _words(look["names"])
    if words:
        import calendar_days
        try:
            for r in calendar_days.between(day, end, con):
                n = str(r["name"])
                low = n.lower()
                if not words.search(low) or "observed" in low or (look.get("months") and r["start"].month not in look["months"]):
                    continue  # an observed day off is not the festival: the look keeps to the day itself
                f = max(r["start"], day)  # a span (a festival of several days) counts from its first day in range
                if day <= f <= end:
                    found.append((f, n.strip()[:30]))
        except Exception:  # noqa: BLE001 (a broken source must not break the wall)
            pass
    return found


def look_for_day(day, con=None, enabled=True):
    """The look for `day` -> {key, name, colours, marks, backdrop, clock, runup_days, festival_day} or None.
    The nearest festival wins; on a tie the order of LOOKS."""
    if not enabled:
        return None
    best = None
    for key, look in LOOKS.items():
        for f, name in _festival_dates(look, day, con):
            if best is None or f < best[0]:
                best = (f, key, name)
    if not best:
        return None
    f, key, name = best
    look = LOOKS[key]
    return {"key": key, "name": name or look["name"], "colours": dict(look["colours"]),
            "marks": [dict(m) for m in look["marks"]], "backdrop": look["backdrop"], "clock": look["clock"],
            "runup_days": look["runup_days"], "festival_day": f.isoformat()}


def enabled(cfg=None):
    """Seasonal looks on? family.json wall.seasonal, on unless switched off (Settings > Phones > Walls)."""
    import config
    cfg = config.family() if cfg is None else cfg
    return (cfg.get("wall") or {}).get("seasonal", True) is not False


def css():
    """The looks' colours as CSS custom properties, one rule per look: body.season-<key> { --s-bg: ...; }. Generated from the
    data (served as /wall/season.css), so a new look needs no change in wall.css for its colours."""
    out = []
    for key, look in LOOKS.items():
        props = ";".join(f"--s-{k.replace('_', '-')}:{v}" for k, v in look["colours"].items())
        out.append(f"body.season-{key}{{{props}}}")
    return "\n".join(out) + "\n"


def windows(start, days=60, con=None, enabled=True):
    """Look windows for a wall that may be offline: [{from, to, key, name, colours, marks, backdrop, clock, festival_day}]
    for the run of days from `start` for `days` days that share a look, so the tablet can apply the right one by its own date."""
    out = []
    for i in range(days + 1):
        d = start + dt.timedelta(days=i)
        look = look_for_day(d, con, enabled)
        if not look:
            continue
        if out and out[-1]["festival_day"] == look["festival_day"] and out[-1]["key"] == look["key"] \
                and dt.date.fromisoformat(out[-1]["to"]) == d - dt.timedelta(days=1):
            out[-1]["to"] = d.isoformat()
        else:
            out.append({**look, "from": d.isoformat(), "to": d.isoformat()})
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["check"]:
        bad = {k: validate(v) for k, v in LOOKS.items()}
        for k, probs in bad.items():
            print(k, "ok" if not probs else "; ".join(probs))
        return 1 if any(bad.values()) else 0
    day = dt.date.fromisoformat(argv[0]) if argv else dates.today()
    look = look_for_day(day)
    print(json.dumps(look, indent=2) if look else "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
