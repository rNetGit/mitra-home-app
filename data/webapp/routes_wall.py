"""The Mitra Wall's pages: /wall (today), /wall/week, /wall/month, /wall/chores, /wall/lists, /wall/meals, /wall/money (+ its
/spending, /bills and /regular pages from data/wall_money.py), /wall/rest, and the pairing page a new wall opens (data/wall.py pairs it; data/wall_data.py reads what it shows).

Security model, on top of the app's (webapp/app.py):
  * A wall holds no person's session. Its cookie (`mh_wall`, HttpOnly, SameSite=Strict, Secure over HTTPS, path /wall)
    carries a random token whose SHA-256 is in the walls table; a revoked wall is signed out at its next request.
  * Wall pages are served only over HTTPS (the phones' port) or to a browser on this PC itself.
  * Every POST under /wall/ needs this wall's CSRF token (kept in memory per wall, shown in the page) and a same-origin
    request; the middleware checks it. POST /wall/pair is the only exception (no wall exists yet), like /login: it is
    throttled per device and accepts a one-time code only.
  * The wall acts as a limited member named after the wall (wall.actor): edit_actions lets it tick family lists and
    children's routines and nothing else.
  * Money shows only after an adult types their own PIN on the wall (the same throttle as sign-in, counted per device),
    for UNLOCK_SECONDS; then it locks itself. Nothing else on the wall shows an amount.
"""
import datetime as dt
import hmac
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import admin_actions
import auth
import brand
import dates
import db
import edit_actions as ea
import paths
import wall as W
import math

import wall_data as WD
import wall_money as WM
import wall_screen
import wall_season
import weather
from webapp import app as A

router = APIRouter()
COOKIE = "mh_wall"
COOKIE_DAYS = 400
UNLOCK_SECONDS = 60
PAIR_THROTTLE = "#wall"  # wrong pairing codes count on their own key, never on the all-names PIN lock
IDLE_SECONDS = 120
REFRESH_SECONDS = 60
REST_REFRESH_SECONDS = 300  # the resting screen reloads less often, and only while it shows the clock (wall.js)
NAV = [("today", "Today", "/wall", "sun"), ("week", "Calendar", "/wall/day", "calendar"), ("chores", "Chores", "/wall/chores", "star"),
       ("lists", "Lists", "/wall/lists", "list"), ("meals", "Meals", "/wall/meals", "meal"), ("money", "Money", "/wall/money", "lock")]
ICONS = {
    **W.ICONS,
    "calendar": "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
    "list": "M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01",
    "meal": "M7 3v8a2 2 0 0 0 4 0V3M9 11v10M16 3c-1.7 1-2.5 3-2.5 6s1 4 2.5 4v8",
    "lock": "M6 11V8a6 6 0 0 1 12 0v3M5 11h14v10H5z",
    "money": "M3 7h18v12H3zM3 11h18M7 15h3",
    "check": "M5 12l5 5L20 7",
    "left": "M15 6l-6 6 6 6",
    "right": "M9 6l6 6-6 6",
    "plus": "M12 5v14M5 12h14",
    "x": "M6 6l12 12M18 6L6 18",
    "clock": "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
    "image": "M4 5h16v14H4zM4 16l5-5 4 4 3-3 4 4M15 9h.01",
    **{f"wx_{k}": p for k, p in weather.ICONS.items()},
}

_lock = threading.Lock()
_csrf = {}    # wall id -> token (in memory: a restart gives the wall a new one with its next page)
_unlock = {}  # wall id -> {'by': adult's name, 'until': time.time() deadline}


# ---- who is asking ------------------------------------------------------------------------------------------------
def _secure(request):
    return request.url.scheme == "https" or A.is_local(request)


def wall_of(request):
    """The paired wall behind the cookie, or None (no cookie, unknown or revoked, database unreadable)."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    try:
        con = W._con()
    except sqlite3.Error:
        return None
    try:
        w = W.authenticate(con, token)
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return w if w and "id" in w else None


def csrf_for(w):
    with _lock:
        return _csrf.setdefault(w["id"], secrets.token_urlsafe(24))


def csrf_ok(request):
    """The middleware's check for POST /wall/...: this wall's token in X-CSRF-Token."""
    w = wall_of(request)
    if not w:
        return False
    supplied = request.headers.get("x-csrf-token") or ""
    return bool(supplied) and hmac.compare_digest(csrf_for(w), supplied)


def unlocked(w):
    """Seconds the money view stays open for this wall (0 = locked)."""
    if not w:
        return 0
    with _lock:
        u = _unlock.get(w["id"])
        left = int(u["until"] - time.time()) if u else 0
        if u and left <= 0:
            _unlock.pop(w["id"], None)
    return max(left, 0)


def _client(request):
    return request.client.host if request.client else "unknown"


def _render(request, name, w, status=200, screen=None, **ctx):
    now = dt.datetime.now()
    screen = screen or wall_screen.settings(wall_id=w["id"] if w else None)
    if w and screen["clock_only"] and name != "wall_rest.html":  # a bedroom wall: the clock, nothing else
        return RedirectResponse("/wall/rest", status_code=303)
    # the rail's quick starts: the clock now, and the photos now (only when this wall shows photos and some are kept)
    quick = [("rest", "Clock", "/wall/rest", "clock")] + \
        ([("photos", "Photos", "/wall/rest?photos=1", "image")] if screen["photos"] and wall_screen.photos() else [])
    nav = [n for n in NAV if n[0] not in wall_screen.TABS or n[0] in screen["tabs"]]  # Chores / Meals only when ticked
    pics = wall_screen.photos() if screen["theme"] == "photo" and w else []
    theme_photo = f"/wall/photo/{pics[now.date().toordinal() % len(pics)]}" if pics else ""  # a new one each day
    season = _season(request, screen)
    base = {"season": season, "wall": w, "screen": screen, "quick": quick, "csrf": csrf_for(w) if w else "", "version": A._version(), "brand": brand.PRODUCT, "nav": nav,
            "clock_now": WD.clock(now.hour * 60 + now.minute), "hm_now": f"{now.hour % 12 or 12}:{now.minute:02d}",
            "date_now": f"{now:%A}, {now:%B} {now.day}",
            "icons": ICONS, "now": now, "today": dates.today(), "unlock_left": unlocked(w), "idle": IDLE_SECONDS,
            "refresh": REFRESH_SECONDS, "family": _family_name(), "wx": weather.wall_view(now), "theme_photo": theme_photo}
    return A.templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status)


def _season(request, screen):
    """The seasonal look for today (data/wall_season.py), or None; `?season=<look key>` (wall_season.LOOKS) previews one."""
    want = request.query_params.get("season") if request is not None else None
    if want in wall_season.LOOKS:
        return _with_anim(_preview(want))
    if not wall_season.enabled():
        return None
    return _with_anim(wall_season.look_for_day(dates.today()))


def _preview(key):
    L = wall_season.LOOKS[key]
    return {"key": key, "name": L["name"], "colours": dict(L["colours"]), "marks": [dict(m) for m in L["marks"]],
            "backdrop": L["backdrop"], "clock": L["clock"], "runup_days": L["runup_days"], "festival_day": ""}


def _with_anim(look):
    if look:
        look["anim"] = {m["mark"]: m["animation"] for m in look["marks"]}
    return look


@router.get("/wall/season.css")
def wall_season_css():
    """The looks' colours as CSS custom properties (generated from data/wall_season.py; no family data in it)."""
    return Response(wall_season.css(), media_type="text/css", headers={"Cache-Control": "max-age=3600"})


def _page_off(w, tab):
    """A page this wall does not show (Settings > Phones > Walls > Pages) -> the redirect to Today, else None."""
    s = wall_screen.settings(wall_id=w["id"] if w else None)
    if tab not in s["tabs"] or s["clock_only"]:
        return RedirectResponse("/wall/rest" if s["clock_only"] else "/wall", status_code=303)
    return None


def _family_name():
    import config
    n = " ".join(str(config.family().get("family_name") or "").split())
    if not n:
        return brand.PRODUCT
    if n.lower().startswith("the "):
        return n
    return f"The {n}" if n.lower().endswith(" family") else f"The {n} Family"  # "Mock Family" -> "The Mock Family"


def _ro():
    return db.connect(paths.DB, readonly=True, row=True)


def _gate(request):
    """(wall, None) when the page may be drawn, else (None, the response to send)."""
    if not _secure(request):
        return None, HTMLResponse(f"The wall opens over HTTPS only: start {brand.PRODUCT} for phones on the PC and use "
                                  "the address shown there.", status_code=403)
    w = wall_of(request)
    if not w:
        return None, RedirectResponse("/wall", status_code=303)
    return w, None


@router.get("/wall/ping")
def wall_ping(request: Request):
    """Is the PC there for this wall? 204 = yes, go ahead and load the next page; 401 = this wall was removed (wall.js
    then opens the pairing page); 403 = not over HTTPS. wall.js asks before every reload or page change, so a PC that is
    off, asleep or restarting leaves the wall on its last screen instead of the browser's error page."""
    if not _secure(request):
        return Response(status_code=403)
    return Response(status_code=204 if wall_of(request) else 401, headers={"Cache-Control": "no-store"})


def _day(text, today):
    try:
        return dt.date.fromisoformat(str(text or "")[:10])
    except ValueError:
        return today


# ---- pairing --------------------------------------------------------------------------------------------------------
@router.get("/wall", response_class=HTMLResponse)
def wall_home(request: Request, code: str = ""):
    if not _secure(request):
        return _gate(request)[1]
    w = wall_of(request)
    if not w:
        return _render(request, "wall_pair.html", None, code=W.pretty_code(W.clean_code(code)) if W.clean_code(code) else "",
                       error="")
    con = _ro()
    try:
        v = WD.today(con, dt.datetime.now())
    finally:
        con.close()
    return _render(request, "wall_today.html", w, active="today", v=v)


@router.post("/wall/pair", response_class=HTMLResponse)
async def wall_pair(request: Request):
    if not _secure(request):
        return _gate(request)[1]
    data = await A.form(request, limit=512)
    code = data.get("code", "")
    src = None if A.is_local(request) else _client(request)
    key = auth.pair_key(PAIR_THROTTLE, src)
    wait = auth.locked_for(key, everyone=False, source=src)
    if wait:
        return _render(request, "wall_pair.html", None, status=429, code="",
                       error=f"Too many wrong codes. Try again in {wait} seconds.")
    try:
        con = W._con()
    except sqlite3.Error:
        return _render(request, "wall_pair.html", None, status=503, code="", error="The PC's database is busy. Try again.")
    try:
        got = W.pair_redeem(con, code)
    finally:
        con.close()
    if not got:
        auth.record_failure(key, everyone=False, source=src)
        return _render(request, "wall_pair.html", None, status=401, code="",
                       error="That code is wrong, used or too old. Make a new one on the PC: Settings > Phones > Mitra Wall.")
    token, w = got
    admin_actions._audit({"name": "wall"}, "wall_paired", f"id={w['id']}")
    r = RedirectResponse("/wall", status_code=303)
    r.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/wall", secure=request.url.scheme == "https",
                 max_age=COOKIE_DAYS * 86400)
    return r


# ---- the screens ----------------------------------------------------------------------------------------------------
@router.get("/wall/week", response_class=HTMLResponse)
def wall_week(request: Request, start: str = "", who: str = ""):
    w, stop = _gate(request)
    if stop:
        return stop
    today = dates.today()
    first = _day(start, today)
    con = _ro()
    try:
        v = WD.week(con, first, today, who or None)
    finally:
        con.close()
    prev, nxt = first - dt.timedelta(days=7), first + dt.timedelta(days=7)

    def link(day, person):
        q = {k: x for k, x in (("start", day.isoformat() if day != today else ""), ("who", person or "")) if x}
        return "/wall/week" + ("?" + urllib.parse.urlencode(q) if q else "")
    for c in v["chips"]:
        c["href"] = link(first, None if c["on"] else c["name"])
    return _render(request, "wall_week.html", w, active="week", v=v, prev=link(prev, v["who"]), next=link(nxt, v["who"]),
                   back=link(today, v["who"]) if first != today else "", everyone=link(first, None))


@router.get("/wall/day", response_class=HTMLResponse)
def wall_day(request: Request, d: str = ""):
    """One day, a lane per person (wall_data.day); a small screen gets the same day as one list (wall.css)."""
    w, stop = _gate(request)
    if stop:
        return stop
    today = dates.today()
    day = _day(d, today)
    con = _ro()
    try:
        v = WD.day(con, day, today)
    finally:
        con.close()

    def link(x):
        return "/wall/day" + ("" if x == today else f"?d={x.isoformat()}")
    return _render(request, "wall_day.html", w, active="week", v=v, prev=link(v["prev"]), next=link(v["next"]),
                   back=link(today) if day != today else "")


@router.get("/wall/month", response_class=HTMLResponse)
def wall_month(request: Request, m: str = ""):
    w, stop = _gate(request)
    if stop:
        return stop
    today = dates.today()
    try:
        first = dt.date.fromisoformat(f"{m[:7]}-01") if re.fullmatch(r"\d{4}-\d{2}", m or "") else today.replace(day=1)
    except ValueError:
        first = today.replace(day=1)
    con = _ro()
    try:
        v = WD.month(con, first, today)
    finally:
        con.close()

    def link(d):
        return "/wall/month" + ("" if (d.year, d.month) == (today.year, today.month) else f"?m={d:%Y-%m}")
    return _render(request, "wall_month.html", w, active="week", v=v, prev=link(v["prev"]), next=link(v["next"]),
                   back=link(today) if (first.year, first.month) != (today.year, today.month) else "")


@router.get("/wall/chores", response_class=HTMLResponse)
def wall_chores(request: Request, part: str = ""):
    w, stop = _gate(request)
    if stop or (stop := _page_off(w, "chores")):
        return stop
    now = dt.datetime.now()
    part = part if part in W.PARTS else W.part_of(now)
    con = _ro()
    try:
        names = [n for n, _ in WD.people(con)]
        kids = [{**k, "cls": WD.colour(k["name"], names), "rewards": W.reward_view(con, k["name"])}
                for k in W.day_view(con, dates.today(), part)]
    finally:
        con.close()
    return _render(request, "wall_chores.html", w, active="chores", kids=kids, part=part,
                   parts=[(p, W.PART_LABEL[p]) for p in W.PARTS], rate=W.star_cents())


@router.post("/wall/chores/tick", response_class=HTMLResponse)
async def wall_chores_tick(request: Request):
    w = wall_of(request)
    if not w:
        return RedirectResponse("/wall", status_code=303)
    data = await A.form(request, limit=256)
    try:
        rid = int(data.get("id", ""))
    except ValueError:
        return HTMLResponse("That job is no longer on the page. Reload it.", status_code=400)
    ok, msg = ea.routine_tick(W.actor(w), rid, data.get("done", "1") == "1")
    part = data.get("part", "")
    return RedirectResponse("/wall/chores" + (f"?part={part}" if part in W.PARTS else ""), status_code=303) if ok \
        else HTMLResponse(msg, status_code=409)


@router.post("/wall/reward", response_class=HTMLResponse)
async def wall_reward(request: Request):
    """A child asks for a reward on the wall: the stars are held until an adult answers on the PC."""
    w = wall_of(request)
    if not w:
        return RedirectResponse("/wall", status_code=303)
    data = await A.form(request, limit=256)
    ok, msg = ea.reward_ask(W.actor(w), data.get("reward", ""), data.get("member", ""))
    return RedirectResponse("/wall/chores?asked=1", status_code=303) if ok else HTMLResponse(msg, status_code=409)


@router.get("/wall/lists", response_class=HTMLResponse)
def wall_lists(request: Request):
    w, stop = _gate(request)
    if stop:
        return stop
    con = _ro()
    try:
        lists = WD.lists(con, dates.today())
    finally:
        con.close()
    return _render(request, "wall_lists.html", w, active="lists", lists=lists)


@router.post("/wall/lists/tick", response_class=HTMLResponse)
async def wall_lists_tick(request: Request):
    w = wall_of(request)
    if not w:
        return RedirectResponse("/wall", status_code=303)
    data = await A.form(request, limit=256)
    try:
        iid = int(data.get("item", ""))
    except ValueError:
        return HTMLResponse("That item is no longer on the page. Reload it.", status_code=400)
    ok, msg = ea.list_item_tick(W.actor(w), iid, data.get("done", "1") == "1")
    return RedirectResponse("/wall/lists", status_code=303) if ok else HTMLResponse(msg, status_code=409)


@router.post("/wall/lists/add", response_class=HTMLResponse)
async def wall_lists_add(request: Request):
    w = wall_of(request)
    if not w:
        return RedirectResponse("/wall", status_code=303)
    data = await A.form(request, limit=512)
    text = " ".join(str(data.get("text", "")).split())[:120]
    try:
        lid = int(data.get("list", ""))
    except ValueError:
        return HTMLResponse("That list is no longer on the page. Reload it.", status_code=400)
    if not text:
        return HTMLResponse("Type the item first.", status_code=400)
    ok, msg = ea.list_item_add(W.actor(w), lid, text)
    return RedirectResponse("/wall/lists", status_code=303) if ok else HTMLResponse(msg, status_code=409)


@router.get("/wall/meals", response_class=HTMLResponse)
def wall_meals(request: Request):
    w, stop = _gate(request)
    if stop or (stop := _page_off(w, "meals")):
        return stop
    today = dates.today()
    con = _ro()
    try:
        v = WD.meals(con, today, today)
    finally:
        con.close()
    return _render(request, "wall_meals.html", w, active="meals", v=v)


@router.get("/wall/rest", response_class=HTMLResponse)
def wall_rest(request: Request, photos: str = ""):
    """The resting screen; ?photos=1 (the rail's Photos) starts the photos at once, also outside the photo hours."""
    w, stop = _gate(request)
    if stop:
        return stop
    con = _ro()
    try:
        v = WD.today(con, dt.datetime.now())
        nxt = WD.week(con, dates.today() + dt.timedelta(days=1), dates.today(), days=7)
    finally:
        con.close()
    later = [{"when": d["dow"], "title": e["title"], "time": e["time"].split(" – ")[0], "cls": e["cls"]}
             for d in nxt["days"] for e in d["events"]][:3]
    now = dt.datetime.now()
    show = wall_screen.view(wall_id=w["id"] if w else None)
    days = [{"title": a["title"], "kind": a["kind"]} for a in v["allday"] if a["kind"] in ("Holiday", "Festival")]
    return _render(request, "wall_rest.html", w, active="rest", v=v, later=later, show=show, face=analog_face(now),
                   rest_refresh=REST_REFRESH_SECONDS, rings=job_rings(v["kids"]), special=days, ampm="AM" if now.hour < 12 else "PM",
                   roman=ROMAN if show["clock"] == "typograph" else None, faces=FACE_PICK,
                   lit=wall_screen.word_lit(now.hour, now.minute) if show["clock"] == "word" else [],
                   zt=wall_screen.zone_time(show["zone"]) if show["clock"] == "dual" else None,
                   zlabel=wall_screen.ZONES.get(show["zone"], ""), ring=day_ring(v["line"], now) if show["clock"] == "kidsday" else None,
                   flip=flip_digits(now), word_rows=WORD_ROWS, start_photos=photos == "1" and bool(show["urls"]),
                   **_led_ctx(now, show))


def _led_ctx(now, show):
    """The LED face's template values; the LED desk clock keeps its own black or wood look (no seasonal art)."""
    if show["clock"] != "led":
        return {"led": None}
    return {"led": led_view(now, show, weather.wall_view(now)), "season": None}


def preview_rest(request, s):
    """The resting screen as the Settings form would make it (`s` = checked settings, nothing saved), for the preview window
    on Settings > Phones > Walls: an adult on this PC, no wall behind it, never reloads or leaves the page."""
    con = _ro()
    try:
        v = WD.today(con, dt.datetime.now())
        nxt = WD.week(con, dates.today() + dt.timedelta(days=1), dates.today(), days=7)
    finally:
        con.close()
    later = [{"when": d["dow"], "title": e["title"], "time": e["time"].split(" – ")[0], "cls": e["cls"]}
             for d in nxt["days"] for e in d["events"]][:3]
    now = dt.datetime.now()
    names = wall_screen.photos() if s["photos"] else []
    taken = wall_screen.taken() if names else {}
    show = {**s, "urls": [f"/settings/wall/photo/{n}" for n in names],
            "taken": {f"/settings/wall/photo/{n}": wall_screen.taken_label(d) for n, d in taken.items()}}
    days = [{"title": a["title"], "kind": a["kind"]} for a in v["allday"] if a["kind"] in ("Holiday", "Festival")]
    return _render(request, "wall_rest.html", None, screen=s, preview=True, v=v, later=later, show=show, face=analog_face(now),
                   rest_refresh=REST_REFRESH_SECONDS, rings=job_rings(v["kids"]), special=days, ampm="AM" if now.hour < 12 else "PM",
                   roman=ROMAN if show["clock"] == "typograph" else None, faces=FACE_PICK,
                   lit=wall_screen.word_lit(now.hour, now.minute) if show["clock"] == "word" else [],
                   zt=wall_screen.zone_time(show["zone"]) if show["clock"] == "dual" else None,
                   zlabel=wall_screen.ZONES.get(show["zone"], ""), ring=day_ring(v["line"], now) if show["clock"] == "kidsday" else None,
                   flip=flip_digits(now), word_rows=WORD_ROWS, start_photos=False,
                   **_led_ctx(now, show))


@router.post("/wall/face", response_class=HTMLResponse)
async def wall_face(request: Request):
    """The face picked on the wall itself (the clock button on the resting screen): this wall's own screen."""
    w = wall_of(request)
    if not w:
        return RedirectResponse("/wall", status_code=303)
    data = await A.form(request, limit=256)
    ok, msg = ea.wall_face_set(W.actor(w), data.get("clock", ""))
    return RedirectResponse("/wall/rest", status_code=303) if ok else HTMLResponse(msg, status_code=409)


ROMAN = [{"t": t, "x": round(100 + (76 if q else 80) * math.sin(math.radians(i * 30)), 1),
          "y": round(100 - (76 if q else 80) * math.cos(math.radians(i * 30)) + (8 if q else 5), 1), "q": q}
         for i, (t, q) in enumerate((("XII", 1), ("I", 0), ("II", 0), ("III", 1), ("IV", 0), ("V", 0), ("VI", 1), ("VII", 0),
                                      ("VIII", 0), ("IX", 1), ("X", 0), ("XI", 0)))]
RING_R = 31


def job_rings(kids):
    """The modular face's job rings: each child's done / total as an SVG stroke-dasharray (no inline style)."""
    c = 2 * math.pi * RING_R
    out = []
    for k in [k for k in kids if k.get("total")][:3]:  # a child with no jobs today has no ring
        total, done = k["total"], k.get("done") or 0
        f = done / total
        out.append({"name": k["name"], "done": done, "total": total, "all": bool(total) and done >= total,
                    "dash": f"{c * f:.1f} {c:.1f}", "cls": k.get("cls", "")})
    return out


# ---- the flip, word and kids' day faces (wall.js keeps them going; the app wall draws the same in www/wall.js) -------
FACE_PICK = [("digital", "Digital"), ("flip", "Flip"), ("word", "Words"), ("analog", "Traditional"), ("typograph", "Roman"),
             ("modular", "Modular"), ("dual", "Two cities"), ("kidsday", "Kids' day"), ("led", "LED")]
# the word clock's rows: (data-w key, text); the minute words FIVE / TEN / TWENTY are m5 / m10 / m20, the hours h<name>
WORD_ROWS = [[("it", "IT"), ("is", "IS"), ("half", "HALF"), ("m10", "TEN")],
             [("quarter", "QUARTER"), ("m20", "TWENTY")],
             [("m5", "FIVE"), ("minutes", "MINUTES"), ("to", "TO")],
             [("past", "PAST"), ("hone", "ONE"), ("hthree", "THREE")],
             [("htwo", "TWO"), ("hfour", "FOUR"), ("hfive", "FIVE")],
             [("hsix", "SIX"), ("hseven", "SEVEN"), ("height", "EIGHT")],
             [("hnine", "NINE"), ("hten", "TEN"), ("heleven", "ELEVEN")],
             [("htwelve", "TWELVE"), ("oclock", "O'CLOCK")]]
DAY_FROM, DAY_TO = 6 * 60, 22 * 60   # the kids' day ring: 6 AM at the start, 10 PM at the end, the night as a gap at the top
DAY_GAP = 30                         # degrees left open at the top for the night
DAY_PARTS = [("morning", "Morning", 6 * 60, 12 * 60), ("afternoon", "Afternoon", 12 * 60, 17 * 60),
             ("evening", "Evening", 17 * 60, 22 * 60)]


def day_angle(m):
    """Degrees clockwise from the top for minute-of-day `m` on the kids' day ring (clamped to the day)."""
    m = max(DAY_FROM, min(DAY_TO, m))
    return DAY_GAP / 2 + (m - DAY_FROM) / (DAY_TO - DAY_FROM) * (360 - DAY_GAP)


def _arc(a, b, r):
    """An SVG arc path on a 200 x 200 face from angle a to b (degrees clockwise from the top), radius r."""
    def pt(deg):
        t = math.radians(deg)
        return f"{100 + r * math.sin(t):.1f} {100 - r * math.cos(t):.1f}"
    return f"M {pt(a)} A {r} {r} 0 {1 if b - a > 180 else 0} 1 {pt(b)}"


def day_ring(line, now):
    """The kids' day face: the part bands, today's timed events as arcs (person colour) and where now is."""
    parts = [{"key": k, "label": lab, "d": _arc(day_angle(a), day_angle(b) - 1, 84)} for k, lab, a, b in DAY_PARTS]
    events = []
    for e in line:
        s, t = e.get("s"), e.get("e")
        if s is None or t is None or t <= DAY_FROM or s >= DAY_TO:
            continue
        a, b = day_angle(s), day_angle(max(t, s + 10))
        events.append({"d": _arc(a, max(b, a + 2), 68), "cls": e.get("cls", ""), "past": e.get("past"), "title": e["title"]})
    m = now.hour * 60 + now.minute
    part = next((lab for _, lab, a, b in DAY_PARTS if a <= m < b), "Night")
    return {"parts": parts, "events": events[:12], "now": round(day_angle(m), 1), "awake": DAY_FROM <= m < DAY_TO,
            "part": part, "ticks": [{"a": round(day_angle(h * 60), 1), "t": lab} for h, lab in
                                    ((6, "6"), (9, "9"), (12, "12"), (15, "3"), (18, "6"), (21, "9"))]}


# ---- the LED face: seven-segment digits as SVG polygons (wall.js lights them every second; the app wall draws the same) --
LED_W, LED_H, LED_GAP = 44, 100, 10   # one digit cell in viewBox units, the space between two cells
LED_SEGS = {"0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg", "5": "acdfg", "6": "acdefg", "7": "abc",
            "8": "abcdefg", "9": "abcdfg", "-": "g", " ": ""}   # = wall.js LED_SEGS
LED_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _n(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def led_shapes(t):
    """The seven segments a-g of one digit cell as polygon points, `t` = the segment's thickness (viewBox units)."""
    g, h, m = t * 0.16, t / 2, LED_H / 2

    def hz(y):
        x1, x2 = h + g, LED_W - h - g
        return " ".join(f"{_n(x)},{_n(yy)}" for x, yy in ((x1, y), (x1 + h, y - h), (x2 - h, y - h), (x2, y), (x2 - h, y + h), (x1 + h, y + h)))

    def vt(x, y1, y2):
        return " ".join(f"{_n(xx)},{_n(y)}" for xx, y in ((x, y1), (x + h, y1 + h), (x + h, y2 - h), (x, y2), (x - h, y2 - h), (x - h, y1 + h)))
    return [("a", hz(h)), ("b", vt(LED_W - h, h + g, m - g)), ("c", vt(LED_W - h, m + g, LED_H - h - g)), ("d", hz(LED_H - h)),
            ("e", vt(h, m + g, LED_H - h - g)), ("f", vt(h, h + g, m - g)), ("g", hz(m))]


def led_svg(text, t, key=""):
    """One row of LED digits for the template's `seg` macro: {'w': viewBox width, 'segs': led_shapes(t), 'cells': [{'x',
    'lit', 'key' (data-led = key + index, for wall.js), 'dp' (a decimal point after it)}], 'r', 'dpx', 'dpy'}. Digits,
    '-' and ' '; a '.' becomes the point of the cell before it."""
    cells = []
    for ch in str(text):
        if ch == "." and cells:
            cells[-1]["dp"] = True
            continue
        if ch not in LED_SEGS:
            continue
        cells.append({"x": len(cells) * (LED_W + LED_GAP), "lit": LED_SEGS[ch], "dp": False,
                      "key": f"{key}{len(cells)}" if key else ""})
    w = len(cells) * LED_W + max(len(cells) - 1, 0) * LED_GAP
    return {"w": w, "segs": led_shapes(t), "cells": cells, "r": _n(t * 0.6), "dpx": _n(LED_W + LED_GAP / 2), "dpy": _n(LED_H - t / 2)}


def led_wood():
    """The dark wood behind the LED face: grain lines as SVG paths in a 1000 x 600 box (drawn, no image file)."""
    out = []
    for i in range(34):
        y = 8 + i * 17.5 + 5 * math.sin(i * 1.7)
        a, f, ph = 4 + 6 * abs(math.sin(i * 0.9)), 0.004 + 0.003 * abs(math.cos(i * 1.3)), i * 2.1
        pts = " ".join(f"{x},{y + a * math.sin(x * f + ph) + 2 * math.sin(x * f * 3.1 + ph):.1f}" for x in range(0, 1001, 50))
        out.append({"d": "M" + pts.replace(" ", " L"), "cls": f"wg{i % 4}"})
    return out


def led_view(now, show, wx):
    """What the LED face draws: the time (wall_screen.led_time), and for `wide` / `side` the readings from the weather
    (temperature now, today's rain chance `pop`, high / low; never humidity, there is none). No weather: `wide` shows the
    year in place of the temperature, `side` leaves the readings out."""
    style = show["led_style"]
    hh, mm, ap = wall_screen.led_time(now.hour, now.minute, show["hours24"])
    t = 5 if style == "time" else 8
    out = {"style": style, "hh": led_svg(hh, t, "h"), "mm": led_svg(mm, t, "m"), "ap": ap, "hm": f"{hh}:{mm} {ap}".strip(),
           "colon": {"r": _n(t * 0.75), "t": t}, "week": [{"n": n, "today": i == now.weekday()} for i, n in enumerate(LED_DAYS)],
           "wood": led_wood() if show["led_bg"] == "wood" else []}
    temp = wx.get("temp") if wx else None
    temp = None if temp is None else str(int(round(temp)))
    unit = "°" + (wx.get("unit") or "F") if wx else ""
    if style == "wide":
        out["r1"] = {"svg": led_svg(temp, 8), "unit": unit, "label": f"Now {temp}{unit}"} if temp is not None else             {"svg": led_svg(str(now.year), 8), "unit": "", "label": f"Year {now.year}"}
        out["r2"] = {"svg": led_svg(f"{now.month:02d}.{now.day:02d}", 8), "label": f"{now:%B} {now.day}"}
    elif style == "side":
        pop = ((wx.get("days") or {}).get(now.date().isoformat()) or {}).get("pop") if wx else None
        out["rain"] = {"svg": led_svg(str(int(pop)), 8), "unit": "%", "label": f"Rain chance {int(pop)}%"} if pop is not None else None
        out["now"] = {"svg": led_svg(temp, 8), "unit": unit, "label": f"Now {temp}{unit}"} if temp is not None else None
        hi, lo = (wx.get("hi"), wx.get("lo")) if wx else (None, None)
        out["hilo"] = f"H {int(round(hi))}° · L {int(round(lo))}°" if hi is not None and lo is not None else ""
    return out


def flip_digits(now):
    """The flip clock's four cards: the hour (blank first card before 10) and the minutes."""
    h = f"{now.hour % 12 or 12:>2}"
    return [h[0].strip(), h[1], f"{now.minute:02d}"[0], f"{now.minute:02d}"[1]]


def analog_face(now):
    """The traditional clock's numbers, ticks and starting hand angles (degrees; wall.js turns the hands from there)."""
    nums = []
    for n in range(1, 13):
        a = math.radians(n * 30)
        nums.append({"n": n, "x": round(100 + 76 * math.sin(a), 1), "y": round(100 - 76 * math.cos(a) + 7, 1)})
    ticks = [{"a": i * 6, "major": i % 5 == 0} for i in range(60)]
    sec = now.second
    mins = now.minute + sec / 60
    return {"nums": nums, "ticks": ticks, "h": round((now.hour % 12 + mins / 60) * 30, 2), "m": round(mins * 6, 2),
            "s": sec * 6}


@router.get("/wall/photo/{name}")
def wall_photo(request: Request, name: str):
    """A family photo for this wall's resting screen (a paired wall only; only names wall_screen made)."""
    w, stop = _gate(request)
    if stop:
        return stop
    p = wall_screen.photo_path(name)
    if not p:
        return Response("Not found", status_code=404)
    from fastapi.responses import FileResponse
    return FileResponse(p, media_type="image/jpeg")


# ---- money, behind an adult's PIN -----------------------------------------------------------------------------------
MONEY_PAGES = {"": ("wall_money.html", WD.money), "spending": ("wall_money_spending.html", WM.spending),
               "bills": ("wall_money_bills.html", WM.bills), "regular": ("wall_money_regular.html", WM.regular)}
MONEY_TABS = [("", "Overview"), ("spending", "Spending"), ("bills", "Bills"), ("regular", "Regular")]


def _money_page(request, part):
    w, stop = _gate(request)
    if stop:
        return stop
    if not unlocked(w):
        adults = [u["name"] for u in auth.users() if u.get("role", "adult") == "adult"]
        return _render(request, "wall_unlock.html", w, active="money", adults=adults, error="", part=part)
    template, build = MONEY_PAGES[part]
    con = _ro()
    try:
        v = build(con, dates.today())
    finally:
        con.close()
    with _lock:
        by = (_unlock.get(w["id"]) or {}).get("by", "")
    return _render(request, template, w, active="money", v=v, by=by, part=part, money_tabs=MONEY_TABS)


@router.get("/wall/money", response_class=HTMLResponse)
def wall_money(request: Request):
    return _money_page(request, "")


@router.get("/wall/money/{part}", response_class=HTMLResponse)
def wall_money_part(request: Request, part: str):
    """Spending by category, bills this month against last, and the regular bills and subscriptions: same PIN, same minute."""
    if part not in MONEY_PAGES or not part:
        return RedirectResponse("/wall/money", status_code=303)
    return _money_page(request, part)


@router.post("/wall/unlock", response_class=HTMLResponse)
async def wall_unlock(request: Request):
    w = wall_of(request)
    if not w:
        return RedirectResponse("/wall", status_code=303)
    data = await A.form(request, limit=256)
    who, pin = data.get("name", ""), data.get("pin", "")
    adults = [u["name"] for u in auth.users() if u.get("role", "adult") == "adult"]
    src = None if A.is_local(request) else _client(request)

    def again(status, error):  # the pad posts through wall.js, which shows this sentence under the pad
        return HTMLResponse(error, status_code=status)
    if who not in adults:
        auth.record_failure("?", everyone=src is not None, source=src)
        return again(401, "Wrong name or PIN.")
    from starlette.concurrency import run_in_threadpool
    u, wait, locked = await run_in_threadpool(auth.attempt, who, pin, src is not None, src)
    if wait:
        return again(429, f"Too many wrong PINs. Try again in {wait} seconds.")
    if not u:
        return again(401, "Wrong name or PIN." + (f" Too many tries: locked for {locked} seconds." if locked else ""))
    with _lock:
        _unlock[w["id"]] = {"by": u["name"], "until": time.time() + UNLOCK_SECONDS}
    admin_actions._audit({"name": u["name"]}, "wall_money_unlock", f"wall={w['id']}")
    part = data.get("part", "")
    return RedirectResponse(f"/wall/money/{part}" if part and part in MONEY_PAGES else "/wall/money", status_code=303)


@router.post("/wall/lock", response_class=HTMLResponse)
async def wall_lock(request: Request):
    w = wall_of(request)
    if w:
        with _lock:
            _unlock.pop(w["id"], None)
    return RedirectResponse("/wall", status_code=303)


@router.post("/wall/forget", response_class=HTMLResponse)
async def wall_forget(request: Request):
    """A wall that should start over (moved to another house, given away): its cookie is dropped here; the PC's list
    keeps it until an adult removes it in Settings > Phones. A POST with the wall's token: a link cannot unpair it."""
    r = RedirectResponse("/wall", status_code=303)
    r.delete_cookie(COOKIE, path="/wall")
    return r


# ---- Family > Routines: the adults set the children's jobs (a normal signed-in page, not a wall page) --------------
ICON_NAMES = {"star": "Star", "bed": "Bed", "tooth": "Teeth", "shirt": "Clothes", "bag": "School bag", "book": "Reading",
              "music": "Practice", "paw": "Pet", "plate": "Table", "bin": "Bins", "broom": "Tidy", "bath": "Bath",
              "sun": "Morning", "moon": "Bedtime"}


@router.get("/family/routines", response_class=HTMLResponse)
def routines_page(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    con = _ro()
    try:
        v = W.manage(con, dates.today())
    finally:
        con.close()
    s = A.session_of(request)
    return A.page(request, "routines.html", active="routines", v=v, parts=[(p, W.PART_LABEL[p]) for p in W.PARTS],
                  days=[(d, W.DAY_SHORT[d]) for d in W.DAYS], icons=[(k, ICON_NAMES.get(k, k), p) for k, p in W.ICONS.items()],
                  walls=bool(_walls_paired()), flash=s.pop("routines_flash", None) if s else None)


def _walls_paired():
    try:
        con = W._con()
    except sqlite3.Error:
        return 0
    try:
        return W.live_count(con)
    except sqlite3.OperationalError:
        return 0
    finally:
        con.close()


@router.post("/family/routines", response_class=HTMLResponse)
async def routines_post(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form_lists(request, limit=4096)

    def one(k):
        return (data.get(k) or [""])[0]
    user = A.current_user(request)
    op = one("op")
    from starlette.concurrency import run_in_threadpool
    if op == "add":
        ok, msg = await run_in_threadpool(ea.routine_add, user, one("member"), one("part"), one("title"),
                                          icon=one("icon") or "star", stars=one("stars") or 1, weekdays=data.get("day", []))
    elif op == "drop":
        ok, msg = await run_in_threadpool(ea.routine_drop, user, one("id"))
    elif op == "goal":
        ok, msg = await run_in_threadpool(ea.goal_set, user, one("member"), one("title"), one("stars"))
    elif op == "goal_clear":
        ok, msg = await run_in_threadpool(ea.goal_clear, user, one("member"))
    elif op == "reward_add":
        ok, msg = await run_in_threadpool(ea.reward_add, user, one("title"), one("stars"), one("member"))
    elif op == "reward_drop":
        ok, msg = await run_in_threadpool(ea.reward_drop, user, one("id"))
    elif op in ("reward_give", "reward_no"):
        ok, msg = await run_in_threadpool(ea.reward_decide, user, one("id"), op == "reward_give")
    elif op == "allowance":
        ok, msg = await run_in_threadpool(ea.allowance_budget_set, user, one("member"))
    elif op == "rate":
        text = one("rate").strip().lstrip("$").strip()  # 25 = 25 cents; 0.25 or $0.25 = 25 cents too
        if re.fullmatch(r"\d{1,3}", text):
            cents = int(text)
        elif re.fullmatch(r"\d{0,2}\.\d{1,2}", text):
            cents = int(round(float(text) * 100))
        else:
            cents = None
        if cents is None:
            ok, msg = False, "Type what a star is worth in cents, for example 25."
        else:
            ok, msg = await run_in_threadpool(ea.star_rate_set, user, cents)
    else:
        ok, msg = False, "Reload the page and try again."
    s = A.session_of(request)
    if s is not None:
        s["routines_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/family/routines"
    return r
