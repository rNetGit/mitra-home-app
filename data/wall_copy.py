"""What the Mitra Home app in wall mode keeps besides its synced rows (sync_data role "wall"): the things this PC works out
rather than stores, sent whole at every contact (GET /api/wall/extras, webapp/routes_wall_api.py).

The wall works from its copy while the PC is off (offline plan, maintainer PLAN_wall_offline.md), so this holds what the
browser wall asks the PC for on every page: the screen settings, the holidays, festivals and school days for the year
ahead, the "to do" lines of the PC's Today for the next WALL_DAYS, the children's goals and star balances, the last
weather forecast, and the names of the photos to keep. Only what a wall already shows: no money (stars only, never
cents), no amounts, no account or policy numbers, no notes, no adults-only rows.

  python data/wall_copy.py show      print what a wall would get now
"""
import datetime as dt
import hashlib
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import paths  # noqa: E402

SPECIAL_BACK = 7
SPECIAL_AHEAD = 400
MAX_PHOTOS = 30   # offline plan D4: the newest 30 photos stay on the tablet


def device(w):
    """The pseudo-device sync_data.pull serves an app wall as: role wall, the calendar, lists and wall sources."""
    return {"id": f"wall:{w['id']}", "member": None, "role": "wall", "scopes": ["calendar", "lists", "wall"],
            "name": w.get("name")}


def family_name():
    n = " ".join(str(config.family().get("family_name") or "").split())
    if not n:
        import brand
        return brand.PRODUCT
    if n.lower().startswith("the "):
        return n
    return f"The {n}" if n.lower().endswith(" family") else f"The {n} Family"  # "Mock Family" -> "The Mock Family"


def _iso(d):
    return d.isoformat() if isinstance(d, (dt.date, dt.datetime)) else d


def special_days(con, today):
    import calendar_days
    out = []
    for r in calendar_days.between(today - dt.timedelta(days=SPECIAL_BACK), today + dt.timedelta(days=SPECIAL_AHEAD), con):
        out.append({"start": _iso(r["start"]), "end": _iso(r["end"]), "kind": r["kind"], "name": r["name"],
                    "member": r.get("member")})
    return out


def todo(con, today, names):
    import sync_data
    import wall_data as WD
    rows = WD.todo_items(con, today, today + dt.timedelta(days=sync_data.WALL_DAYS), today, names)
    return [{"date": _iso(t["date"]), "title": t["title"], "kind": t["kind"], "who": t["who"], "late": t["late"]}
            for t in rows if t.get("ref") != "life_items"]  # life items reach the wall as its `needs` rows


def children(con, today):
    """Goal and star balance per child with jobs (stars only)."""
    import wall as W
    kids = [r[0] for r in con.execute("SELECT DISTINCT member FROM routines WHERE status='active' ORDER BY member")]
    out = []
    for k in kids:
        g = W.goal_view(con, k, today, rate=0)
        out.append({"name": k, "balance": W.star_balance(con, k),
                    "goal": {f: g[f] for f in ("title", "stars", "earned")} if g else None})
    return out


def weather_days(now):
    import weather
    v = weather.wall_view(now)
    if not v:
        return None
    return {"unit": v.get("unit"), "updated": v.get("updated"),
            "now": {"temp": v["temp"]} if v.get("temp") is not None else None,  # the LED clock's temperature now
            "days": [{"date": d["date"], "hi": d.get("hi"), "lo": d.get("lo"), "look": d.get("look"), "pop": d.get("pop")}
                     for d in sorted((v.get("days") or {}).values(), key=lambda d: d["date"])]}


def photos(wall_id=None):
    import wall_screen
    s = wall_screen.settings(wall_id=wall_id)
    if not s["photos"]:
        return []
    days = wall_screen.taken()
    out = []
    for name in wall_screen.photos()[-MAX_PHOTOS:]:
        p = wall_screen.photo_path(name)
        if p:
            out.append({"name": name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                        "taken": wall_screen.taken_label(days.get(name))})
    return out


def season(con, today):
    """The seasonal looks (data/wall_season.py) for the next 60 days as windows, so a wall that is offline picks the right one
    by its own date. Empty when seasonal looks are off."""
    import wall_season
    return wall_season.windows(today, 60, con, wall_season.enabled())


def extras(con, now=None, wall_id=None):
    """Everything a wall needs besides its synced rows. Never raises for a missing optional part."""
    import wall_data as WD
    import wall_screen
    now = now or dt.datetime.now()
    today = now.date()
    names = [n for n, _ in WD.people(con)]
    out = {"made_at": now.isoformat(timespec="seconds"), "family": family_name(), "screen": wall_screen.settings(wall_id=wall_id),
           "people": names}
    for key, fn in (("special_days", lambda: special_days(con, today)), ("todo", lambda: todo(con, today, names)),
                    ("children", lambda: children(con, today)), ("weather", lambda: weather_days(now)),
                    ("photos", lambda: photos(wall_id)), ("season", lambda: season(con, today))):
        try:
            out[key] = fn()
        except (sqlite3.OperationalError, OSError, ValueError):
            out[key] = None
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] != ["show"]:
        print(__doc__)
        return 2
    with db.open(paths.DB, readonly=True, row=True) as con:
        print(json.dumps(extras(con, dt.datetime.combine(dates.today(), dt.datetime.now().time())), indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
