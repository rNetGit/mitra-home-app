"""The Mitra Home app: sign-in, setup, rail, Chat, Inbox, Brief, Calendar, Notes, Finance, Work, Records, Settings, the
children's page, PWA files.

Security model (see THREAT_MODEL.md, "Web app"):
  * People and PINs from data/auth.py: PBKDF2 hashes, the file-backed throttle, adult / limited.
  * Session = random token in an HttpOnly, SameSite=Strict cookie; the session itself lives in memory (sessions.py).
  * Every state-changing request needs the session's CSRF token in `X-CSRF-Token` (HTMX adds it) and a same-origin
    Origin/Referer when the browser sends one.
  * Host header must be localhost or an IP literal (or listed in MITRAHOME_WEB_HOSTS): DNS rebinding cannot use a
    name the family does not control.
  * Strict CSP: scripts and styles only from this app (no inline script or style), no framing, no third parties.
  * /api/ is for paired phones only: no cookies, a per-phone bearer token (devices.py), HTTPS (or this PC) only; so it
    needs no CSRF token. Pairing (POST /api/pair) takes a one-time secret from the QR code shown on this PC. Scans
    (POST /api/upload) need the phone's `scan` scope and go through data/phone_upload.py (hash, dedupe, daily cap).
    Sync (GET /api/sync/pull, POST /api/sync/push, data/sync_data.py) sends only what the phone's scopes and its
    person's live role allow, and applies a phone's edits through edit_actions as that person.
  * The phone app opens the web app as its person without a PIN: POST /api/session (bearer, `web` scope, the person
    has a PIN) -> a one-time code (60 s, in memory) -> GET /phone/open?code= over HTTPS sets the normal session cookie.
    That session is tied to the phone: revoking it or turning `web` off ends the session within a minute.
  * The Mitra Wall (/wall, webapp/routes_wall.py) is a paired tablet with its own cookie and CSRF token, not a person's
    session: family-safe screens, ticks of family lists and children's routines, money only after an adult's PIN.
  * Nothing signed-in is cached by the browser or the service worker.
No users configured = open on this PC only; `web_app.py --lan` refuses to start in that case.
"""
import datetime as dt
import html
import ipaddress
import pathlib
import re
import sqlite3
import time
import urllib.parse

import admin_actions
import agent_profile
import auth
import brand
import brief_data
import ai_intake
import calendar_data
import calendar_manage
import config
import help_text
import chat_data
import dashboard_actions
import dates
import db
import devices
import finance_data
import home_costs
import month_statement
import ledger_data
import inbox_data
import inbox_upload
import kid_data
import look
import maintenance_data
import money
import notes_data
import paths
import records
import records_data
import records_edit
import setup_data
import sync_data
import today_data
import keepup  # noqa: E402
import wallet
import trends
import view_mode
import weather
import work_data
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import sessions

HERE = pathlib.Path(__file__).resolve().parent
COOKIE = "fa_session"
RANGES = (6, 12, 24)
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "manifest-src 'self'; worker-src 'self'; form-action 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'")
# Pages: (key, label); each is served at /<key>
PAGES = [("family", "Family"), ("calendar", "Calendar"), ("notes", "Notes"), ("chat", "Chat"), ("settings", "Settings")]
# The five tabs of every adult screen, the PC rail and the phone's bottom bar alike (audit U14): (key, label, href, icon).
# A page not yet folded into its tab lights the tab it belongs to (TAB_OF); every other page sits under More, which the
# person's avatar opens.
TABS = [("home", "Today", "/", "today"), ("calendar", "Calendar", "/calendar", "calendar"), ("inbox", "Add", "/add", "add"),
        ("money", "Money", "/money", "money"), ("family", "Family", "/family", "family")]
TAB_OF = {"records": "family", "wallet": "family", "routines": "family", "work": "family", "house": "family"}
# Pages the PC rail shows under the five tabs (the phone keeps them under More): (key, label, href, icon).
RAIL_EXTRA = [("notes", "Notes", "/notes", "note"), ("chat", "Ask Mitra", "/chat", "chat")]
# Family's own chips (U14): the person tiles, the Records areas and the Wallet, one row on each of those pages.
FAMILY_TABS = [("", "Everyone", "/family"), ("people", "People", "/records?domain=people"), ("home", "Home", "/records?domain=home"),
               ("vehicles", "Cars", "/records?domain=vehicles"), ("papers", "Papers & IDs", "/records?domain=papers"),
               ("wallet", "Wallet", "/wallet"), ("routines", "Routines", "/family/routines"), ("work", "Work", "/work"), ("house", "House", "/family/house")]

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")


@app.exception_handler(StarletteHTTPException)
async def not_found(request: Request, exc: StarletteHTTPException):
    """A page for a person who followed an old link (it was raw JSON); the phone API and files keep plain answers."""
    if exc.status_code == 404 and not request.url.path.startswith(("/api/", "/static/")) \
            and "text/html" in request.headers.get("accept", ""):
        return page(request, "notfound.html", status=404)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))


@app.exception_handler(config.Broken)
async def config_broken(request: Request, exc: config.Broken):
    """A change that would have rewritten a family.json that does not parse: say so, change nothing."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "config_broken"}, status_code=503)
    return HTMLResponse(f'<p class="notice bad" role="alert">{html.escape(str(exc))}</p>', status_code=409)
templates = Jinja2Templates(directory=HERE / "templates")
templates.env.filters["money"] = lambda v: money.fmt(v, 0)
templates.env.filters["money2"] = lambda v: money.fmt(v, 2)
templates.env.filters["pct"] = lambda v: "" if v is None else f"{v:+.0f}%"
templates.env.filters["sd"] = lambda v: finance_data.short_date(str(v)[:10]) if v else ""  # 2026-10-05 -> Oct 5
templates.env.filters["day"] = lambda v: dates.day_text(v) if v else ""  # 2026-10-23 -> Fri, Oct 23
templates.env.filters["md"] = lambda v: dates.md_text(v, short=True) or (v or "")  # 03-14 -> Mar 14
templates.env.filters["initial"] = lambda v: next((ch.upper() for ch in str(v or "") if ch.isalnum()), "?")  # "[DEMO] x" -> D


def _ym(v):
    """2026-10 -> Oct 2026; anything else unchanged."""
    try:
        return dt.date.fromisoformat(f"{v}-01").strftime("%b %Y")
    except (TypeError, ValueError):
        return v


templates.env.filters["ym"] = _ym


def _helpfmt(text):
    """Help lines: escaped, **bold**, [Button] as a key cap."""
    import re
    from jinja2.runtime import Markup, escape
    t = str(escape(text))
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"\[([^\]]+)\]", r'<kbd class="hk">\1</kbd>', t)
    return Markup(t)


templates.env.filters["helpfmt"] = _helpfmt


# ---- helpers ---------------------------------------------------------------------------------------------------
def _version():
    try:
        return (paths.ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_local(request):
    """True when the browser runs on this PC (keys, tokens and Google sign-in are taken only from there)."""
    return bool(request.client) and request.client.host in LOCAL_HOSTS


def host_ok(host):
    """True for localhost, an IP literal, or a name the family listed in MITRAHOME_WEB_HOSTS."""
    h = (host or "").strip().lower()
    if h.startswith("["):  # [::1]:8601
        h = h[1:].split("]")[0]
    elif h.count(":") == 1:
        h = h.split(":")[0]
    if not h:
        return False
    if h == "localhost":
        return True
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        pass
    extra = [x.strip().lower() for x in paths.env("MITRAHOME_WEB_HOSTS").split(",") if x.strip()]
    return h in extra


def same_origin(request):
    """The Origin (or, failing that, Referer) of a state-changing request names this app's own host."""
    host = request.headers.get("host", "")
    for name in ("origin", "referer"):
        v = request.headers.get(name)
        if v:
            return urllib.parse.urlsplit(v).netloc.lower() == host.lower()
    return True  # old clients and non-browser tools send neither; the CSRF token still applies


def session_of(request):
    """The live session, re-checked against the people list: a changed PIN or a removed person ends it, a new role applies."""
    token = request.cookies.get(COOKIE)
    s = sessions.get(token)
    if not s:
        return None
    if s.get("open"):  # the open-on-this-PC session lasts only while nobody has a PIN, and only on this PC
        if not open_ok(request):
            sessions.destroy(token)
            return None
        return s
    live = auth.current(s["user"]["name"])
    if live is None or live[1] != s.get("bind") or not phone_session_ok(s):
        sessions.destroy(token)
        return None
    s["user"] = live[0]
    return s


PHONE_CHECK_EVERY = 60  # seconds: how often a phone app's session re-checks its phone (revoked, `web` turned off)
PHONE_ERROR_GRACE = 600  # seconds: a database that cannot be read (busy, mid-backup) keeps a session checked this recently


def phone_session_ok(s):
    """A session opened by the phone app lives only while that phone may open the web app."""
    if not s.get("device"):
        return True
    now = time.time()
    if now - s.get("device_checked", 0) < PHONE_CHECK_EVERY:
        return True
    try:
        with db.open(paths.DB, readonly=True) as con:
            ok = devices.web_ok(con, s["device"])
    except sqlite3.Error:
        # cannot tell right now (a busy database is not a revoke): keep a session checked in the last few minutes,
        # end one that could not be checked for longer; the phone app simply opens a new one
        return now - s.get("device_checked", 0) < PHONE_ERROR_GRACE
    if ok:
        s["device_checked"] = now
    return ok


def open_ok(request):
    """True when this request may use the app without a PIN: nobody has one yet, the browser is on this PC, and the
    people list could be read. A phone on the Wi-Fi never gets in without a PIN, and an unreadable family.json
    (a hand edit gone wrong) locks everyone out instead of opening the house."""
    return not auth.users() and not auth.locked_out() and is_local(request)


def current_user(request):
    """{'name','role'} for the signed-in person; the open-on-this-PC user when nobody has a PIN; else None."""
    s = session_of(request)
    if s:
        return s["user"]
    if open_ok(request):
        return {"name": "", "role": "adult"}
    return None


def csrf_token(request):
    s = session_of(request)
    return s["csrf"] if s else ""


OPEN_USER = {"name": "", "role": "adult"}
BROKEN_MSG = ("The family settings file on the PC cannot be read (a hand edit gone wrong?). Nobody can sign in until it "
              "is fixed: on the PC, repair the family settings file or put back the copy from the newest backup, then reload.")


def chrome(user):
    """What the rail and the phone's bottom bar show on every page: the signed-in person's avatar and how many Inbox
    items and files wait (adults only). Never stops a page from opening."""
    out = {"me_av": ("", "avn"), "inbox_n": 0}
    if not user:
        return out
    try:
        mem = today_data.members_now()
        out["me_av"] = today_data.avatar(user.get("name"), [m for m, _ in mem]) if user.get("name") else ("", "avn")
        if user.get("role") == "adult":
            with db.open(paths.DB, readonly=True) as con:
                n = con.execute("SELECT COUNT(*) FROM proposals WHERE status='open'").fetchone()[0]
            out["inbox_n"] = n + inbox_data.waiting()
    except (sqlite3.Error, OSError):
        pass
    return out


def page(request, name, status=200, **ctx):
    """A page. Open on this PC (nobody has a PIN): the first page gives the browser a session of its own, so its forms
    carry a CSRF token like any signed-in page (setting the first PIN ends that session)."""
    user = current_user(request)
    s, new = session_of(request), None
    if s is None and user is not None and open_ok(request):
        new = sessions.create(OPEN_USER)
        s = sessions.get(new)
        s["open"] = True
    tab_keys = {t[0] for t in TABS}
    base = {"user": user, "tabs": TABS, "family_tabs": [t for t in FAMILY_TABS if t[0] != "work" or config.pack("contracts")], "tab": TAB_OF.get(ctx.get("active"), ctx.get("active")),
            "more": [p for p in view_mode.pages(PAGES) if p[0] not in tab_keys],
            "rail_extra": [x for x in RAIL_EXTRA if x[0] in {k for k, _ in view_mode.pages(PAGES)}],
            "simple": view_mode.is_simple(), "version": _version(), "brand": brand.PRODUCT,
            "csrf": s["csrf"] if s else "", "theme": look.mode_for(user), "signed_in": bool(s) and not s.get("open"),
            "can_logout": bool(auth.users()), **chrome(user),
            "help_key": help_text.key_for(ctx.get("active"), ctx) if user and user.get("role") == "adult" else ""}
    r = templates.TemplateResponse(request, name, {**base, **ctx}, status_code=status)
    if new:
        r.set_cookie(COOKIE, new, httponly=True, samesite="strict", path="/", secure=request.url.scheme == "https",
                     max_age=sessions.ABSOLUTE)
    return r


async def form(request, limit=8192):
    """Parse an application/x-www-form-urlencoded body (no multipart dependency); bytes past `limit` are dropped."""
    return {k: v[0] for k, v in (await form_lists(request, limit)).items()}


async def capped_body(request, limit):
    """At most `limit` bytes of the body, read as it streams: a huge body (to /login or /api/pair, before anyone signed
    in) is never held in memory; the rest is left unread (audit 2026-10-14 test gap)."""
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk[:limit - len(buf)]
        if len(buf) >= limit:
            break
    return bytes(buf)


async def form_lists(request, limit=8192):
    """The same, with every value of a field (ticked boxes that share a name)."""
    body = (await capped_body(request, limit)).decode("utf-8", "replace")
    return urllib.parse.parse_qs(body, keep_blank_values=True)


def need_adult(request):
    """None when the person may see money pages, else the response to send."""
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    if user.get("role") != "adult":
        return page(request, "limited.html", status=403)
    return None


# ---- middleware ------------------------------------------------------------------------------------------------
SETUP_FREE = ("/setup", "/login", "/logout", "/theme", "/static/", "/tokens.css", "/manifest.webmanifest", "/sw.js",
              "/offline", "/healthz", "/api/")


@app.middleware("http")
async def guard(request: Request, call_next):
    if not host_ok(request.headers.get("host")):
        return PlainTextResponse("Unknown host", status_code=400)
    if request.method == "GET" and not request.url.path.startswith(SETUP_FREE) and setup_data.needed():
        return RedirectResponse("/setup", status_code=303)  # a new install: the first run comes first
    if request.url.path.startswith("/api/") and sync_data.phone_too_old(request.headers.get("x-app-version")):
        return JSONResponse({"error": "phone_too_old", "min_phone": sync_data.MIN_PHONE}, status_code=426)
    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.url.path.startswith("/api/"):
        if not same_origin(request):
            return PlainTextResponse("Cross-site request refused", status_code=403)
        if request.url.path.startswith("/wall/"):  # a wall has no person's session: its own token (routes_wall.py)
            if request.url.path != "/wall/pair" and not routes_wall.csrf_ok(request):  # pairing: no wall exists yet
                return PlainTextResponse("Missing or wrong security token. Reload the page.", status_code=403)
        elif request.url.path != "/login":  # no session exists yet at sign-in; its form has no token to send
            if not sessions.csrf_ok(session_of(request), request.headers.get("x-csrf-token")):
                return PlainTextResponse("Missing or wrong security token. Reload the page.", status_code=403)
    r = await call_next(request)
    framed = (request.url.path == "/settings/wall/preview"  # the pages shown in a frame of this site: the Settings preview window
              or (request.url.path.startswith("/records/paper/") and request.url.path.endswith("/view")))  # and the paper viewer
    r.headers["Content-Security-Policy"] = CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'") if framed else CSP
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["X-Frame-Options"] = "SAMEORIGIN" if framed else "DENY"
    # not "no-referrer": that makes browsers send "Origin: null" on same-origin form POSTs and same_origin() refuses them
    r.headers["Referrer-Policy"] = "same-origin"
    r.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    r.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    if not request.url.path.startswith("/static/") and request.url.path not in ("/manifest.webmanifest", "/sw.js"):
        r.headers["Cache-Control"] = "no-store"
    return r


# ---- sign in / out ---------------------------------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, pin: str = ""):
    if current_user(request) is not None:
        return RedirectResponse("/", status_code=303)
    note = "Your PIN was changed. Sign in with the new one." if pin == "changed" else ""
    return page(request, "login.html", names=[u["name"] for u in auth.users()], error=BROKEN_MSG if auth.locked_out() else "",
                who="", note=note)


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request):
    data = await form(request)
    who, pin = data.get("name", ""), data.get("pin", "")
    names = [u["name"] for u in auth.users()]
    ctx = {"names": names, "who": who}
    if auth.locked_out():
        return page(request, "login.html", status=503, error=BROKEN_MSG, **ctx)
    # another device on the Wi-Fi: its address is counted too (steeper locks); this PC skips the all-names lock, so a
    # device guessing names cannot lock the family out of the PC itself (audit S2)
    here = is_local(request)
    src = None if here else (request.client.host if request.client else "unknown")
    if who not in names:
        auth.record_failure("?", everyone=not here, source=src)  # unknown names share one counter (bounded file)
        return page(request, "login.html", status=401, error="Wrong name or PIN.", **ctx)
    # PBKDF2 takes a moment: off the event loop, and one check at a time so a burst of guesses is counted (audit M2)
    u, wait, locked = await run_in_threadpool(auth.attempt, who, pin, not here, src)
    if wait:
        return page(request, "login.html", status=429, error=f"Too many wrong PINs. Try again in {wait} seconds.", **ctx)
    if not u:
        msg = "Wrong name or PIN." + (f" Too many tries: locked for {locked} seconds." if locked else "")
        return page(request, "login.html", status=401, error=msg, **ctx)
    r = RedirectResponse("/", status_code=303)
    live = auth.current(u["name"])
    r.set_cookie(COOKIE, sessions.create(u, bind=live[1] if live else ""), httponly=True, samesite="strict", path="/",
                 secure=request.url.scheme == "https", max_age=sessions.ABSOLUTE)
    return r


@app.post("/logout")
def logout(request: Request):
    sessions.destroy(request.cookies.get(COOKIE))
    r = Response(status_code=204, headers={"HX-Redirect": "/login"})  # the button is an HTMX post (it carries the token)
    r.delete_cookie(COOKIE, path="/")
    return r


@app.post("/theme")
async def set_theme(request: Request):
    user = current_user(request)
    mode = (await form(request)).get("mode")
    if user is None or mode not in look.TOKENS:
        return Response(status_code=400)
    look.remember(user, mode)
    return Response(status_code=204)


# ---- pages -----------------------------------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if current_user(request) is None:
        return RedirectResponse("/login", status_code=303)
    user = current_user(request)
    if user.get("role") != "adult":
        s = session_of(request)
        return page(request, "kid.html", active="home", today=dates.today(), flash=s.pop("kid_flash", None) if s else None,
                    k=kid_data.view(user, dates.today(), request.query_params.get("q", "")))
    ctx = brief_context(user)
    v = today_data.today_view(ctx, request.query_params.get("who", ""))
    for r in v["needs"] + v["week"] + v["later"]:  # the row menu's Open record
        ref = (r.get("it") or {}).get("ref")
        r["record"] = record_link(records.ref_str(ref[0], [ref[1]])) if ref and ref[1] and ref[0] in records.SECTION else ""
    s = session_of(request)
    flash, undo = (s.pop("today_flash", None) if s else None) or (None, None)
    words, words_later = _brief_words(v, ctx.today)
    return page(request, "today.html", words=words, words_later=words_later, active="home", v=v, today=ctx.today, flash=flash, undo=undo, upd_line=update_line(user), rew_line=rewards_line(user), wall_line=wall_line(user),
                briefings=BRIEFINGS, wx_line=weather.line(), keep=keepup.rows(user, ctx.today),
                brief=today_data.brief_items(v), brief_more=today_data.brief_more(v, (weather.wall_view() or {}).get("rain") or ""))


def _brief_words(v, today):
    """(the AI wording of the brief if one is already cached, whether the page should ask for it afterwards).
    Never calls the AI: no AI, a signed-in CLI or a training-risk provider = ('', False), the plain brief only."""
    try:
        import brief_narrative
        if not brief_narrative.provider_ok():
            return "", False
        rows = today_data.narrative_rows(v)
        if not rows:
            return "", False
        if brief_narrative.cached(rows, today):
            return brief_narrative.narrate(rows, today), False  # cached: no call
        return "", True
    except Exception:  # noqa: BLE001 (the plain brief always stands)
        return "", False


def _today_redirect(request, flash, undo, who):
    """Done / Paid on Today: the message waits in the session; HTMX reloads the page (same person filter)."""
    s = session_of(request)
    if s is not None:
        s["today_flash"] = (flash, undo)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/" + (f"?who={urllib.parse.quote(who)}" if who else "")
    return r


@app.post("/today/act", response_class=HTMLResponse)
async def today_act(request: Request):
    """A row on Today: Done (life items, seasonal tasks) or Paid (bills), snooze 1 / 7 / 30 days, hide, or back up now."""
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request, limit=4096)
    op, key = data.get("op") or "done", data.get("key", "")
    user = current_user(request)
    ctx = brief_context(user)
    row = brief_data.find(ctx, key) if key else None
    flash, undo = (False, "That item is no longer on the list."), None
    if op == "backup":
        ok, msg = await run_in_threadpool(admin_actions.backup_now, user)
        flash = (ok, "Backup done." if ok else msg)
    elif op == "sync":
        ok, msg = await run_in_threadpool(admin_actions.bank_pull_now, user)
        flash = (ok, msg)
    elif op == "syncall":
        ok, msg = await run_in_threadpool(admin_actions.sync_all_start, user)
        flash = (ok, msg)
    elif row is None:
        pass
    elif op == "done" and row["src"] in ("item", "seasonal"):
        ok, msg, undo = await run_in_threadpool(brief_data.done, ctx, row)
        flash = (ok, msg)
    elif op in ("snooze", "hide"):
        days = None
        if op == "snooze":
            d = data.get("days", "1")
            days = int(d) if d in ("1", "7", "30") else 1
        ok, msg = dashboard_actions.hide(row["key"], row["title"], "snooze" if op == "snooze" else "ignore", days, ctx.today)
        if ok:
            msg = f"Hidden for {days} day{'' if days == 1 else 's'}." if days else "Hidden. Restore it in Settings."
        flash = (ok, msg)
    return _today_redirect(request, flash, undo, data.get("who", ""))


@app.post("/today/undo", response_class=HTMLResponse)
async def today_undo(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request, limit=4096)
    try:
        bid, due = int(data.get("bill", "")), dt.date.fromisoformat(data.get("due", "")).isoformat()
    except ValueError:
        return PlainTextResponse("Bad request", status_code=400)
    brief_data.undo_paid(brief_context(current_user(request)), bid, due)
    return _today_redirect(request, (True, "Put back on the list."), None, data.get("who", ""))


@app.get("/family", response_class=HTMLResponse)
def family_page(request: Request, who: str = ""):
    denied = need_adult(request)
    if denied:
        return denied
    ctx = brief_context(current_user(request))
    return page(request, "family.html", active="family", v=today_data.family_view(ctx, who), today=ctx.today,
                o=records_data.overview(ctx.today), q="")


@app.get("/month")
def month_page(request: Request, ym: str = ""):
    """This month is a part of Money now (audit U14): old links land there, same month."""
    q = {"part": "month", **({"ym": ym} if re.fullmatch(r"\d{4}-\d{2}", ym) else {})}
    return RedirectResponse("/money?" + urllib.parse.urlencode(q), status_code=303)


@app.post("/me")
async def kid_act(request: Request):
    """A change from a limited person's own page (kid_data.act; edit_actions checks the role again), then reload it."""
    user = current_user(request)
    if user is None:
        return RedirectResponse("/login", status_code=303)
    data = await form(request, limit=4096)
    ok, msg = await run_in_threadpool(kid_data.act, user, data.get("op", ""), data)
    s = session_of(request)
    if s is not None:
        s["kid_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/"
    return r


def trends_context(months):
    """Trends for the Finance page, drawn on the server (no chart library): `flow` = the months that have statements
    (bars), `cats` = what changed against the period before when there is one, else where the money goes (share),
    `yoy` only when at least three months have a year-earlier month, and `table` with runs of empty months as one line."""
    months = months if months in RANGES else 12
    try:
        with db.open(paths.DB, readonly=True) as con:
            rows = trends.monthly(con, months)
            allcats = trends.categories(con, min(months, 12), top=100)
    except sqlite3.Error:
        rows, allcats = [], []
    have = [r for r in rows if r["rows"] and not r["partial"]] or [r for r in rows if r["rows"]]
    so_far = next((r for r in rows if r["partial"]), None)
    flow = [r for r in rows if r["rows"] and not r["partial"]]
    top = max([r["income"] for r in flow] + [r["expenses"] for r in flow] + [1])
    compared = any(c["before"] for c in allcats)
    total_now = sum(c["now"] for c in allcats) or 1
    if compared:
        cats = sorted(allcats, key=lambda c: -abs(c["change"]))[:8]
        span = max([abs(c["change"]) for c in cats] + [1])
    else:
        cats = sorted(allcats, key=lambda c: -c["now"])[:8]
        span = max([c["now"] for c in cats] + [1])
    for c in cats:
        c["share"] = round(c["now"] / total_now * 100)
        c["w"] = round((abs(c["change"]) if compared else c["now"]) / span * 100, 1)
    yoy = [r for r in flow if r["last_year"] is not None]
    table, gap = [], []
    for r in reversed(rows):
        if r["rows"]:
            if gap:
                table.append({"gap": f"{gap[-1]} to {gap[0]}" if len(gap) > 1 else gap[0]})
                gap = []
            table.append(r)
        else:
            gap.append(r["label"])
    if gap:
        table.append({"gap": f"{gap[-1]} to {gap[0]}" if len(gap) > 1 else gap[0]})
    return {"months": months, "ranges": RANGES, "table": table, "cats": cats, "compared": compared,
            "cat_months": min(months, 12), "totals": trends.totals(rows), "newest": have[-1] if have else None,
            "so_far": so_far, "flow": flow, "top": top, "yoy": yoy if len(yoy) >= 3 else []}


def finance_url(part, **params):
    return "/money?" + urllib.parse.urlencode({"part": part, **params})


@app.get("/finance")
def finance(request: Request):
    """Finance is Money now (audit U14): old links and bookmarks land on the same part."""
    q = urllib.parse.urlencode(list(request.query_params.multi_items()))
    return RedirectResponse("/money" + ("?" + q if q else ""), status_code=303)


@app.get("/money", response_class=HTMLResponse)
def money_page(request: Request, months: int = 12, part: str = "", ym: str = ""):
    """Money (audit U14): Overview, the outlook Spending / Bills / Regular (finance_data.OUTLOOK, wall_money.py), then in
    the Advanced view the lanes Pay, Keep, Look back. Overview = this month's story card, Needs a look and the lanes
    (Advanced) or one hero card, the three outlook figures and every page folded (Standard, view_mode simple). This month
    (`part=month`, `ym` picks another month) = the story card and every category; Trends or one Finance part
    (finance_data.view); rows open in /records, where the Pay parts' rows can be changed (records_edit); the Add forms of
    a part (subscriptions, receipts, budget, loans, accounts) sit above its lists."""
    denied = need_adult(request)
    if denied:
        return denied
    if part == "month":
        bc = brief_context(current_user(request))
        pick = ym if re.fullmatch(r"\d{4}-\d{2}", ym) else None
        return page(request, "money.html", active="money", part="month", groups=finance_data.groups(), group="",
                    outlook_parts=finance_data.OUTLOOK, furl=finance_url, v=today_data.month_view(bc, pick), today=bc.today,
                    flash=records_flash(request))
    if part == "homecosts":
        pick = ym if re.fullmatch(r"\d{4}-\d{2}", ym) else None
        return page(request, "money.html", active="money", part="homecosts", groups=finance_data.groups(), group="",
                    outlook_parts=finance_data.OUTLOOK, furl=finance_url, hc=home_costs.view(pick, dates.today()),
                    today=dates.today(), flash=records_flash(request))
    if part == "statement":
        pick = ym if re.fullmatch(r"\d{4}-\d{2}", ym) else None
        return page(request, "money.html", active="money", part="statement", groups=finance_data.groups(), group="",
                    outlook_parts=finance_data.OUTLOOK, furl=finance_url, st=month_statement.view(pick, dates.today()),
                    today=dates.today(), flash=records_flash(request))
    p = finance_data.part_of(part)
    grp = finance_data.group_of(p)
    ctx = {"part": p, "ptitle": finance_data.title(p), "groups": finance_data.groups(), "group": grp,
           "outlook_parts": finance_data.OUTLOOK, "furl": finance_url, "link": record_link, "today": dates.today(),
           "flash": records_flash(request),
           "rq": urllib.parse.urlencode([(k, v) for k, v in request.query_params.multi_items() if k != "part"]),
           "editable_here": ("money", p) in records_edit.EDIT_PARTS,
           "download": "/money/download?" + urllib.parse.urlencode({**dict(request.query_params), "part": p})
           if p in finance_data.DOWNLOADS else ""}
    adds = records_edit.adds(("money", p))
    if adds:
        ctx.update(adds=adds, ch=records_edit.choices())
    if p == finance_data.DEFAULT:
        ctx["o"] = finance_data.overview(dates.today())
        if view_mode.is_simple():
            ctx["mo"] = finance_data.outlook(dates.today())
        else:
            ctx["v"] = today_data.month_view(brief_context(current_user(request)))
    elif p in dict(finance_data.OUTLOOK):
        ctx["mo"] = finance_data.outlook(dates.today(), p)
    elif p == "trends":
        ctx.update(trends_context(months))
    else:
        ctx["v"] = finance_data.view(p, dates.today(), dict(request.query_params))
        ctx["md_html"] = render_md(ctx["v"]["md"]) if ctx["v"]["md"] else ""
    return page(request, "money.html", active="money", **ctx)


@app.post("/money/rule")
async def finance_rule(request: Request):
    """Remember a card merchant's category (Money > Ledger, category Uncategorized; This month) or what a deposit source
    is (Money > Deposit sources, with `kind`), then back to the same list."""
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    ok, msg = await run_in_threadpool(records_edit.ea.category_rule_add, current_user(request),
                                      data.get("pattern", ""), data.get("category", ""), data.get("kind") or None)
    back = {k: str(data.get(k) or "")[:100] for k in ("card", "month", "q") if data.get(k)}
    if data.get("back") == "deposits":
        back = {k: str(data.get(k) or "")[:100] for k in ("from", "to", "q") if data.get(k)}
        return records_go(request, ok, msg, finance_url("deposits", **back))
    if data.get("back") == "month":  # asked from the This month page
        ym = back.get("month", "")
        return records_go(request, ok, msg, finance_url("month", **({"ym": ym} if re.fullmatch(r"\d{4}-\d{2}", ym) else {})))
    back = {k: str(data.get(k) or "")[:100] for k in ledger_data.KEYS if data.get(k)}  # the Ledger, its filters kept
    return records_go(request, ok, msg, finance_url("ledger", **back))


@app.post("/money/txn")
async def ledger_txn(request: Request):
    """Money > Ledger: change one line's category and / or type (adults; `edit_actions.txn_update`), then back to the same
    filtered page. Only the Ledger's own filter keys are carried back."""
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    ok, msg = await run_in_threadpool(records_edit.ea.txn_update, current_user(request), data.get("id", ""),
                                      data.get("category", ""), data.get("txn_type", ""), bool(data.get("similar")))
    back = {k: str(data.get(k) or "")[:100] for k in ("from", "to", "q", "min", "max", "account", "cat", "type", "member", "page")
            if data.get(k)}
    return records_go(request, ok, msg, finance_url("ledger", **back))


@app.get("/money/download")
def finance_download(request: Request, part: str = ""):
    """The tax checklist or year-end summary (.md), the tax preparer's pack (.zip), or a month of card transactions
    (.csv), as a download."""
    denied = need_adult(request)
    if denied:
        return denied
    got = finance_data.download(finance_data.part_of(part), dates.today(), dict(request.query_params))
    if got is None:
        return PlainTextResponse("Nothing to download here.", status_code=404)
    name, media, body = got
    return Response(body, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/money/trends", response_class=HTMLResponse)
def finance_partial(request: Request, months: int = 12):
    denied = need_adult(request)
    if denied:
        return denied
    return page(request, "_trends.html", **trends_context(months))


# ---- Brief -----------------------------------------------------------------------------------------------------
BRIEFINGS = [("this_week", "This week"), ("weekly_digest", "Weekly digest"), ("family_meeting", "Family meeting"),
             ("emergency", "Emergency sheet")]


def render_md(text, links=True):
    """A briefing's markdown as HTML. The text is escaped first, so nothing in it (a vendor name, a note) can become a tag,
    and links are kept only when they go to http(s), mailto or an anchor. Falls back to plain text without `markdown`.
    links=False (AI answers in Chat): no links and no images at all, only their text, so an answer steered by a document
    cannot hand the person a link or make the browser fetch anything."""
    if not links:
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text))
    safe = html.escape(text, quote=False)
    try:
        import markdown
        out = markdown.markdown(safe, extensions=["tables", "sane_lists"])
    except ImportError:
        return "<pre>" + safe + "</pre>"
    # markdown escapes "&" again inside `code`: "&lt;category&gt;" would show as typed; undo only that second escape
    out = re.sub(r"<code>(.*?)</code>", lambda m: "<code>" + re.sub(r"&amp;(lt|gt|amp);", r"&\1;", m.group(1)) + "</code>",
                 out, flags=re.S)
    if not links:
        out = re.sub(r"<img\b[^>]*>", "", re.sub(r"<a\b[^>]*>(.*?)</a>", r"\1", out, flags=re.S))
    return re.sub(r'href="(?!https?://|mailto:|#)[^"]*"', 'href="#"', out)


def brief_context(user):
    today = dates.today()
    return brief_data.Context(today, user, brief_data.build_snapshot(today))


@app.get("/brief")
def brief(request: Request, who: str = ""):
    """To do is part of Today now (audit U14): an old link or bookmark lands there, same person."""
    return RedirectResponse("/" + (f"?who={urllib.parse.quote(who)}" if who else ""), status_code=303)


@app.get("/brief/doc/{kind}")
async def brief_doc_file(request: Request, kind: str):
    """One briefing (this week, digest, family meeting, emergency sheet) as a markdown download."""
    denied = need_adult(request)
    if denied:
        return denied
    if kind not in dict(BRIEFINGS):
        return PlainTextResponse("Not found", status_code=404)
    ok, _title, text, _name = await run_in_threadpool(admin_actions.briefing, current_user(request), kind)
    if not ok:
        return PlainTextResponse("That document could not be made just now.", status_code=404)
    return Response(text.encode("utf-8"), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{kind}.md"'})


def doc_extras(kind):
    """What a document card offers besides its text: the emergency sheet's "Where things are" form."""
    if kind != "emergency":
        return {}
    import emergency_sheet
    return {"where_fields": emergency_sheet.WHERE, "where": emergency_sheet.where(), "where_max": emergency_sheet.WHERE_MAX}


@app.post("/today/emergency/where", response_class=HTMLResponse)
async def emergency_where(request: Request):
    """Today > Documents > Emergency sheet: save "Where things are", then show the sheet again."""
    denied = need_adult(request)
    if denied:
        return denied
    import emergency_sheet
    data = await form(request)
    user = current_user(request)
    ok, msg = await run_in_threadpool(records_edit.ea.emergency_where_set, user, {k: data.get(k, "") for k, _ in emergency_sheet.WHERE})
    okd, title, text, _name = await run_in_threadpool(admin_actions.briefing, user, "emergency")
    doc = {"title": title, "html": render_md(text), "kind": "emergency"} if okd else None
    return page(request, "_doc.html", doc=doc, flash=(ok, msg), **doc_extras("emergency"))


@app.post("/brief/doc/emergency/sealed")
async def emergency_sealed(request: Request):
    """A sealed copy of the emergency sheet for someone the family trusts: one HTML file that opens with a passphrase
    in any browser. The passphrase is used once and never kept."""
    denied = need_adult(request)
    if denied:
        return denied
    import emergency_sheet
    data = await form(request)
    pw, again = data.get("passphrase", ""), data.get("again", "")
    if len(pw) < 10:
        return PlainTextResponse("Use a passphrase of at least 10 characters (a few words is easiest to say on the phone).",
                                 status_code=400)
    if pw != again:
        return PlainTextResponse("The two passphrases are not the same.", status_code=400)
    ok, _title, text, _name = await run_in_threadpool(admin_actions.briefing, current_user(request), "emergency")
    if not ok:
        return PlainTextResponse("That document could not be made just now.", status_code=400)
    try:
        body = await run_in_threadpool(emergency_sheet.seal, text, pw)
    except ImportError:
        return PlainTextResponse("Sealing needs the cryptography package (it is in requirements.txt).", status_code=400)
    return Response(body.encode("utf-8"), media_type="text/html; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="emergency_sheet_sealed.html"',
                             "Cache-Control": "no-store"})


@app.post("/today/brief", response_class=HTMLResponse)
async def today_brief(request: Request):
    """The brief in the AI's words, fetched after Today has drawn (the page never waits on it). The rows are rebuilt
    here, not taken from the form. 204 (the plain brief stays) when there is no AI, nothing to say or the answer failed."""
    denied = need_adult(request)
    if denied:
        return denied
    user = current_user(request)
    ctx = brief_context(user)
    who = (await form(request)).get("who", "")
    v = await run_in_threadpool(today_data.today_view, ctx, who)
    try:
        import brief_narrative
        text = await run_in_threadpool(brief_narrative.narrate, today_data.narrative_rows(v), ctx.today, "")
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        return Response(status_code=204)
    return HTMLResponse(html.escape(text))


@app.post("/today/doc", response_class=HTMLResponse)
async def today_doc(request: Request):
    """Today > Documents: one briefing (this week, digest, family meeting, emergency sheet) shown under the buttons."""
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    kind = data.get("kind", "")
    if kind not in dict(BRIEFINGS):
        return PlainTextResponse("Not found", status_code=404)
    ok, title, text, _name = await run_in_threadpool(admin_actions.briefing, current_user(request), kind)
    doc = {"title": title, "html": render_md(text), "kind": kind} if ok else None
    return page(request, "_doc.html", doc=doc, **doc_extras(kind))


# ---- Calendar (read-only) -------------------------------------------------------------------------------------
def calendar_view(request, view, ref):
    """The Calendar body: view switch, Prev / Today / Next, and the week, month or year grid."""
    view = view if view in calendar_data.VIEWS else "week"
    today = dates.today()
    ref = calendar_data.parse_ref(ref, today)
    lay = calendar_data.layout(view, ref, today)
    cells = [c for m in lay.get("months", []) for w in m["weeks"] for c in w] + [c for w in lay.get("weeks", []) for c in w]
    shown = {k for c in cells for k, _ in c["things"]}  # the legend explains only the colours on screen
    return page(request, "_calendar.html", views=calendar_data.VIEWS, ref=ref, today=today, link=record_link,
                prev=calendar_data.shift(view, ref, -1), next=calendar_data.shift(view, ref, 1),
                kinds=[k for k in calendar_data.KIND_COLOR if k in shown], kclass=calendar_data.kind_class, **lay)


@app.get("/calendar", response_class=HTMLResponse)
def calendar_page(request: Request, view: str = "week", ref: str = ""):
    denied = need_adult(request)
    if denied:
        return denied
    return page(request, "calendar.html", active="calendar", days=calendar_data.GOOGLE_DAYS,
                body=calendar_view(request, view, ref).body.decode("utf-8"))


def manage_back(text, default="/calendar/manage"):
    """Where a Records change made from Manage calendar returns to: only a /calendar/manage address of this site."""
    t = str(text or "")
    bad = "//" in t or "\\" in t or any(c in t for c in "\r\n\t")
    return t if t.startswith("/calendar/manage") and len(t) < 300 and not bad else default


@app.get("/calendar/manage", response_class=HTMLResponse)
def calendar_manage_page(request: Request):
    """One place for an adult to see, add, change and remove the family's calendar items (events, holidays, days off)."""
    denied = need_adult(request)
    if denied:
        return denied
    q, today = request.query_params, dates.today()
    start, end = calendar_manage.parse_range(q.get("from"), q.get("to"), today)
    people = records_edit.people()
    who = q.get("who", "") if q.get("who", "") in people else ""
    everything = q.get("all") == "1"
    found = calendar_manage.rows(start, end, names=people, today=today)
    kinds = sorted({r["kind"] for r in found if everything or r["editable"]})
    kind = q.get("kind", "") if q.get("kind", "") in kinds else ""
    back = "/calendar/manage?" + urllib.parse.urlencode({"from": start.isoformat(), "to": end.isoformat(), "who": who,
                                                          "kind": kind, **({"all": "1"} if everything else {})})
    return page(request, "calendar_manage.html", active="calendar", start=start, end=end, people=people, who=who, kind=kind,
                kinds=kinds, everything=everything, items=calendar_manage.pick(found, who, kind, everything), back=back,
                adds=records_edit.adds(("people", "dates")), ch=records_edit.choices(), err="", note="",
                link=record_link, kclass=calendar_data.kind_class, flash=records_flash(request))


@app.get("/calendar/body", response_class=HTMLResponse)
def calendar_body(request: Request, view: str = "week", ref: str = ""):
    denied = need_adult(request)
    if denied:
        return denied
    return calendar_view(request, view, ref)


@app.get("/calendar/google", response_class=HTMLResponse)
async def calendar_google(request: Request, days: int = 14):
    """The family's Google Calendar, read-only; loaded after the page so a slow Google never holds the grid up."""
    denied = need_adult(request)
    if denied:
        return denied
    days = days if days in calendar_data.GOOGLE_DAYS else 14
    state, data = await run_in_threadpool(calendar_data.google, days, dates.today())
    import calendar_feeds
    others = await run_in_threadpool(calendar_feeds.view, days)
    return page(request, "_gcal.html", state=state, data=data, days=days, choices=calendar_data.GOOGLE_DAYS,
                settings_url="/settings?group=connections", others=others)


# ---- Chat ------------------------------------------------------------------------------------------------------
_LOCAL_CHAT = chat_data.new_state()  # open on this PC (nobody has a PIN): one conversation, no session to keep it in


def chat_state(request):
    s = session_of(request)
    return s.setdefault("chat", chat_data.new_state()) if s else _LOCAL_CHAT


def record_url(ref):
    """A "From:" citation as a link into the Records page (only the known query fields), or into the Help page."""
    if "help" in ref:
        key = str(ref["help"])
        return f"/help#help-{key.replace(':', '-')}" if help_text.get(key) else "/help"
    params = {}
    if ref.get("ref"):
        params["ref"] = str(ref["ref"])[:200]
    if ref.get("section") and "/" in str(ref["section"]):
        params["domain"], params["section"] = str(ref["section"]).split("/", 1)
    if ref.get("q"):
        params["q"] = str(ref["q"])[:80]
    return "/records?" + urllib.parse.urlencode(params)


def chat_view(request, status=200):
    """The conversation, the waiting card (if any) and the chips."""
    state = chat_state(request)
    today = dates.today()
    ready = chat_data.ai_ready()
    chips, _ = chat_data.chips(brief_data.build_snapshot(today), ready, chat_data.has_transactions())
    lines = []
    for h in state["hist"]:
        body = render_md(h["text"], links=False) if h["who"] == "assistant" else ""
        lines.append({"who": h["who"], "text": h["text"], "html": body,
                      "refs": [{"label": r.get("label") or "record", "url": record_url(r)} for r in h["refs"]]})
    pend = state.get("pend")
    card = {"lines": chat_data.describe_pending(pend, today), "nonce": pend["nonce"]} if pend else None
    return page(request, "_chat.html", status=status, lines=lines, card=card, chips=chips, ready=ready,
                settings_url="/settings?group=connections", text_max=chat_data.TEXT_MAX)


@app.get("/chat", response_class=HTMLResponse)
def chat(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    user = current_user(request)
    try:
        inbox_n = inbox_data.cards("all")[0]["all"]
    except (sqlite3.Error, KeyError):
        inbox_n = 0
    hello = f"{chat_data.greeting()}{', ' + user['name'] if user.get('name') else ''}."
    return page(request, "chat.html", active="chat", hello=hello, today=dates.today(), inbox_n=inbox_n,
                body=chat_view(request).body.decode("utf-8"))


@app.get("/chat/body", response_class=HTMLResponse)
def chat_body(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    return chat_view(request)


@app.post("/chat/say", response_class=HTMLResponse)
async def chat_say(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    text = (await form(request)).get("text", "")
    await run_in_threadpool(chat_data.message, chat_state(request), current_user(request), dates.today(), text,
                            chat_data.ai_ready())
    return chat_view(request)


@app.post("/chat/ask")
async def chat_ask(request: Request):
    """The Ask Mitra bar at the top of every adult page: the question goes into the conversation, then Chat opens on
    the answer (the text never goes in an address)."""
    denied = need_adult(request)
    if denied:
        return denied
    text = (await form(request)).get("text", "")
    if text.strip():
        await run_in_threadpool(chat_data.message, chat_state(request), current_user(request), dates.today(), text,
                                chat_data.ai_ready())
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/chat#chatlog"
    return r


@app.post("/chat/chip", response_class=HTMLResponse)
async def chat_chip(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    key = (await form(request)).get("key", "")
    today = dates.today()
    await run_in_threadpool(chat_data.chip, chat_state(request), current_user(request), today,
                            brief_data.build_snapshot(today), key, chat_data.ai_ready())
    return chat_view(request)


@app.post("/chat/answer", response_class=HTMLResponse)
async def chat_answer(request: Request):
    """Yes / No on the waiting card: the form carries only the card's one-time nonce, never the changes."""
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    await run_in_threadpool(chat_data.answer, chat_state(request), current_user(request), data.get("nonce", ""),
                            data.get("yes") == "1")
    return chat_view(request)


@app.post("/chat/clear", response_class=HTMLResponse)
async def chat_clear(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    chat_data.clear(chat_state(request))
    return chat_view(request)


# ---- Inbox -----------------------------------------------------------------------------------------------------
INBOX_CATS = [{"key": "all", "title": "All"}] + [{"key": c[0], "title": c[1]} for c in inbox_data.CATEGORIES]


def inbox_view(request, view="all", flash=None, status=200, open_src=""):
    """The Inbox body (progress panel, category chips, one section per category with its cards); `flash` = (ok, text)."""
    view = view if view in inbox_data.VIEWS else "all"
    counts, items = inbox_data.cards(view)
    waiting, can_file, note = inbox_data.file_now_note()
    for it in items:
        rt, rid = it.get("ref_table"), it.get("ref_id")
        it["record"] = record_link(records.ref_str(rt, [rid])) if rt and rid and rt in records.SECTION else ""
    return page(request, "_inbox.html", status=status, view=view, cats=INBOX_CATS, counts=counts, items=items,
                sections=inbox_data.sections(items, view), open_src=open_src, flash=flash, can_file=can_file, note=note,
                prog=inbox_data.progress(), categories=list(ai_intake.CATEGORY), today=dates.today().isoformat(),
                accounts=inbox_data.accounts() if counts.get("files") else [], no_ai=inbox_data.provider() == "none")


@app.get("/inbox")
def inbox(request: Request, view: str = ""):
    """The Inbox lives on Add now (audit U14): old links land there, same view."""
    return RedirectResponse("/add" + (f"?view={urllib.parse.quote(view)}" if view else ""), status_code=303)


# Add (audit U14): scan or drop a paper, type something in through the forms where it lives, and the Inbox below.
ADD_TILES = [("Person or pet", "/records?domain=people&section=people#add-members", "family"),
             ("Class or activity", "/records?domain=people&section=classes#add-activity_schedules", "calendar"),
             ("Date or reminder", "/records?domain=people&section=life#add-life_items", "today"),
             ("Family event", "/records?domain=people&section=dates#add-events", "calendar"),
             ("List item", "/records?domain=home&section=lists#add-lists", "brief"),
             ("Note or link", "/notes#nadd", "note"),
             ("Subscription", "/money?part=subs#add-subscriptions", "money"),
             ("Card for the wallet", "/wallet#wadd", "card"),
             ("Dates from a photo", "/add/photo?kind=dates", "calendar"),
             ("Recipe from a photo", "/add/photo?kind=recipe", "brief"),
             ("Tell Chat", "/chat", "chat")]


@app.get("/add", response_class=HTMLResponse)
def add_page(request: Request, view: str = "all"):
    denied = need_adult(request)
    if denied:
        return denied
    accept = ",".join(sorted(inbox_upload.ALLOWED))
    return page(request, "add.html", active="inbox", tiles=ADD_TILES, accept=accept, max_mb=inbox_upload.MAX_BYTES // (1024 * 1024),
                autofile=inbox_data.provider() in inbox_data.FILE_NOW or inbox_data.provider() == "none", agent=agent_profile.name(),
                body=inbox_view(request, view).body.decode("utf-8"))


@app.get("/inbox/body", response_class=HTMLResponse)
def inbox_body(request: Request, view: str = "all"):
    denied = need_adult(request)
    if denied:
        return denied
    return inbox_view(request, view)


@app.get("/inbox/progress", response_class=HTMLResponse)
def inbox_progress(request: Request):
    """The progress panel alone (polled every 2 s while a run is going). When the run has just ended, the
    `inbox-done` event tells the page to load the cards again (new questions may be waiting)."""
    denied = need_adult(request)
    if denied:
        return denied
    _, can_file, note = inbox_data.file_now_note()
    prog = inbox_data.progress()
    r = page(request, "_inbox_progress.html", prog=prog, can_file=can_file, note=note, view="all")
    if not prog["poll"]:
        r.headers["HX-Trigger"] = "inbox-done"
    return r


@app.post("/inbox/decide", response_class=HTMLResponse)
async def inbox_decide(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    ok, msg = await run_in_threadpool(inbox_data.decide, current_user(request), data.get("id", ""), data.get("option", ""), data)
    return inbox_view(request, data.get("view", "all"), flash=(ok, msg), open_src=data.get("open", ""))


@app.post("/inbox/filenow", response_class=HTMLResponse)
async def inbox_filenow(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    ok, msg = await run_in_threadpool(inbox_data.file_now, False)  # in the background: the progress panel follows it
    return inbox_view(request, data.get("view", "all"), flash=None if ok else (ok, msg))


@app.post("/inbox/retryall", response_class=HTMLResponse)
async def inbox_retry_all(request: Request):
    """Every file waiting for a person goes back into the inbox and is read again (inbox_data.retry_all)."""
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    ok, msg = await run_in_threadpool(inbox_data.retry_all, current_user(request))
    return inbox_view(request, data.get("view", "all"), flash=(ok, msg))


@app.post("/inbox/upload")
async def inbox_upload_file(request: Request):
    """One file per request: the raw bytes as the body, the name in X-Filename (percent-encoded). Adults only; the same
    checks as the dashboard box and the phone bot (type, size, content matches the name, never overwrites). No multipart
    parser: the body is read with a hard size cap and nothing in it is interpreted."""
    user = current_user(request)
    if user is None:
        return JSONResponse({"ok": False, "message": "Please sign in again."}, status_code=401)
    if user.get("role") != "adult":
        return JSONResponse({"ok": False, "message": "Only an adult can add files."}, status_code=403)
    cap = inbox_upload.MAX_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        return JSONResponse({"ok": False, "message": f"Too large (limit {cap // (1024 * 1024)} MB)."}, status_code=413)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            return JSONResponse({"ok": False, "message": f"Too large (limit {cap // (1024 * 1024)} MB)."}, status_code=413)
    name = urllib.parse.unquote(request.headers.get("x-filename", ""))[:200]
    ok, msg = await run_in_threadpool(inbox_data.save_file, name, bytes(buf))
    return JSONResponse({"ok": ok, "message": ("Saved as " + msg) if ok else msg}, status_code=200 if ok else 400)


# ---- Notes -----------------------------------------------------------------------------------------------------
NOTES_ADD_MAX = 80_000  # a 5000-character note + a 2000-character link, percent-encoded, still fits


def notes_view(request, data=None, flash=None, status=200):
    """The Notes list for the filters in `data` (query or form fields); `flash` = (ok, text)."""
    user, today = current_user(request), dates.today()
    f = notes_data.filters(data or {}, user, today)
    ready, rows = notes_data.rows(user, f, today)
    return page(request, "_notes.html", status=status, f=f, rows=rows, ready=ready, flash=flash)


@app.get("/help", response_class=HTMLResponse)
def help_page(request: Request, q: str = ""):
    """Every help entry on one page, with a word search (no AI, no network)."""
    denied = need_adult(request)
    if denied:
        return denied
    q = q[:100]
    keys = help_text.search(q)
    groups = [(label, [(k, help_text.get(k)) for k in keys if help_text.group_of(k) == g]) for g, label in help_text.GROUPS]
    return page(request, "help.html", active="help", q=q, n=len(keys), groups=[x for x in groups if x[1]])


@app.get("/help/panel", response_class=HTMLResponse)
def help_panel(request: Request, key: str = ""):
    """The "?" panel of one page."""
    denied = need_adult(request)
    if denied:
        return denied
    e = help_text.get(key)
    if not e:
        return HTMLResponse("", status_code=404)
    return page(request, "_help_panel.html", key=key, e=e)


@app.get("/notes", response_class=HTMLResponse)
def notes(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    user, today = current_user(request), dates.today()
    data = dict(request.query_params)
    f = notes_data.filters(data, user, today)
    ready, rows = notes_data.rows(user, f, today)
    return page(request, "notes.html", active="notes", f=f, kinds=notes_data.KINDS, chips=notes_data.kinds(user, today), open_add=ready and not rows and not f["q"],
                tags=notes_data.tags(user, today), people=notes_data.people(), audiences=notes_data.AUDIENCE_LABEL,
                body=notes_view(request, data).body.decode("utf-8"))


@app.get("/notes/body", response_class=HTMLResponse)
def notes_body(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    return notes_view(request, dict(request.query_params))


@app.post("/notes/act", response_class=HTMLResponse)
async def notes_act(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    op = data.get("op", "")
    if op not in notes_data.OPS:
        return PlainTextResponse("Bad request", status_code=400)
    ok, msg = await run_in_threadpool(notes_data.act, current_user(request), op, data.get("id"), data.get("tags", ""))
    return notes_view(request, data, flash=(ok, msg))


@app.post("/notes/add", response_class=HTMLResponse)
async def notes_add(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request, NOTES_ADD_MAX)
    ok, msg = await run_in_threadpool(notes_data.add, current_user(request), data)
    r = notes_view(request, data, flash=(ok, msg))
    if ok:
        r.headers["X-Saved"] = "1"  # app.js clears the Add form only after a save went through
    return r


# ---- Records (look up everywhere; edit forms from records_edit.py; anything else through Chat) -----------------------
REF_MAX = 600  # 50 ids of up to 7 digits and a table name


def record_link(ref):
    """Where an "Open record" / "From:" link goes: one row (table:id) in the web app's Records page."""
    return "/records?" + urllib.parse.urlencode({"ref": ref})


@app.get("/records", response_class=HTMLResponse)
def records_page(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    user, today = current_user(request), dates.today()
    data = dict(request.query_params)
    ref = str(data.get("ref", ""))[:REF_MAX]
    text = records_data.words(data)
    dom, sec = records_data.where(data)
    find = " ".join(str(data.get("f", "")).split())[:80]  # the Filter box on a part's page
    if dom == "money":  # Finance parts have a page of their own
        return RedirectResponse(finance_url(finance_data.part_of(data.get("section"))), status_code=303)
    det = records_data.detail(user, ref) if ref else None
    if det and det["domain"] in records_data.AREAS and "domain" not in data:
        dom, sec = det["domain"], det["section"]
    edit = None
    if det and det["one"] and det["table"] in records_edit.EDIT_OPS:
        rid = records.parse_ref(ref)[1][0]
        ev = records_edit.values(det["table"], rid)
        if ev is not None:
            edit = {"table": det["table"], "id": rid, "ops": records_edit.EDIT_OPS[det["table"]], "v": ev}
    adds = records_edit.adds((dom, sec)) if not ref and not text else []
    show_all, fin = None, ""
    if det and det["domain"]:
        title = records_data.section_title(det["domain"], det["section"])
        url = (finance_url(finance_data.part_of(det["section"])) if det["domain"] == "money"
               else "/records?" + urllib.parse.urlencode({"domain": det["domain"], "section": det["section"]}))
        show_all = (f"Show all {title.lower()}" if title else "Show the list", url)
        fin = (title or "Money") if det["domain"] == "money" else ""  # a Finance row: no Records lists under it
    if "domain" not in data and not ref and not text:  # the old Records home: Family has its search and Needs a look
        return RedirectResponse("/family", status_code=303)
    back = None  # (text, url) above a record: the list it belongs to
    if det and det["domain"] and det["domain"] != "money":
        back = (records_data.section_title(det["domain"], det["section"]) or records_data.NAMES.get(det["domain"], "Records"),
                show_all[1])
    return page(request, "records.html", active="records", areas=[(k, records_data.NAMES[k]) for k in records_data.AREAS],
                back=back,
                dom=dom, sec=sec, area=records_data.NAMES[dom], parts=records_data.parts(dom), title=records_data.section_title(dom, sec),
                q=text, find=find, hits=records_data.search(user, text) if text else None, ref=ref, det=det, show_all=show_all,
                blocks=[] if ref or text else records_data.blocks(dom, sec, today, find),
                strip=records_data.strip(dom, today),
                elsewhere=records_data.ELSEWHERE.get((dom, sec)), link=record_link,
                edit=edit, ch=records_edit.choices(),
                adds=adds, flash=records_flash(request),
                editable_here=(dom, sec) in records_edit.EDIT_PARTS, fin=fin)


def records_flash(request):
    """The result of the last Records change, shown once on the page it sent the person to."""
    s = session_of(request)
    return s.pop("records_flash", None) if s else None


def records_go(request, ok, msg, url):
    """After a change went through: remember the message and let HTMX load `url` (lists and record show the change)."""
    s = session_of(request)
    if s is not None:
        s["records_flash"] = (ok, msg)
    r = Response(status_code=200)  # HTMX reads HX-Redirect and loads the page; 200 keeps every htmx version happy
    r.headers["HX-Redirect"] = url
    return r


def records_section_url(dom, sec):
    """The list a part's rows live in: Finance parts on the Finance page, the rest in Records."""
    if dom == "money":
        return finance_url(finance_data.part_of(sec))
    return "/records?" + urllib.parse.urlencode({"domain": dom, "section": sec})


@app.post("/records/edit", response_class=HTMLResponse)
async def records_edit_post(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    table, op, rid = data.get("table", ""), data.get("op", ""), data.get("id", "")
    if op not in records_edit.EDIT_OPS.get(table, ()):
        return PlainTextResponse("Bad request", status_code=400)
    ok, msg, gone = await run_in_threadpool(records_edit.edit, current_user(request), table, op, rid, data)
    if ok or gone:
        dom, sec = records.where(table)
        url = records_section_url(dom, sec) if gone else record_link(f"{table}:{int(rid)}")
        if data.get("back"):
            url = manage_back(data.get("back"), url)
        return records_go(request, ok, msg, url)
    ev = records_edit.values(table, rid)
    v = {**ev, **records_edit.typed(table, data)} if ev else {}
    return page(request, "_redit.html", edit={"table": table, "id": int(rid), "ops": records_edit.EDIT_OPS[table], "v": v},
                ch=records_edit.choices(), err=msg, err_op=op)


@app.post("/records/add", response_class=HTMLResponse)
async def records_add_post(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    part = tuple(str(data.get("part", "")).split("/", 1))
    tables = records_edit.add_tables(part)
    table = data.get("table") or (tables[0] if tables else "")
    if table not in tables:
        return PlainTextResponse("Bad request", status_code=400)
    ok, msg = await run_in_threadpool(records_edit.add, current_user(request), part, data)
    if ok:
        return records_go(request, ok, msg, manage_back(data.get("back"), records_section_url(*part)))
    add = records_edit.adds(part, {table: records_edit.typed(table, data)})[tables.index(table)]
    return page(request, "_radd.html", add=add, ch=records_edit.choices(), err=msg, back=manage_back(data.get("back"), ""))


@app.post("/records/recipe/url", response_class=HTMLResponse)
async def records_recipe_url(request: Request):
    """Records > Home > Meals: fill the Save a recipe form from a recipe page (recipe_web.py; look-ups switch and fence)."""
    denied = need_adult(request)
    if denied:
        return denied
    import lookups
    import recipe_web
    data = await form(request)
    part = ("home", "meals")
    tables = records_edit.add_tables(part)
    url = str(data.get("url", "")).strip()
    try:
        got = await run_in_threadpool(recipe_web.from_url, url)
    except (recipe_web.RecipeError, lookups.Refused) as e:
        add = records_edit.adds(part, {"recipes": {"url": url[:500]}})[tables.index("recipes")]
        return page(request, "_radd.html", add=add, ch=records_edit.choices(), err=str(e)[:300])
    add = records_edit.adds(part, {"recipes": got})[tables.index("recipes")]
    return page(request, "_radd.html", add=add, ch=records_edit.choices(),
                note=f"Filled in from {urllib.parse.urlsplit(got['url']).hostname or 'the page'}: check it, then Add.")


@app.get("/wallet", response_class=HTMLResponse)
def wallet_page(request: Request):
    """The Card Wallet: IDs, cars, insurance, memberships and home facts as cards (wallet.py)."""
    denied = need_adult(request)
    if denied:
        return denied
    g = request.query_params.get("g", "")
    g = g if g in dict(wallet.GROUPS) else ""
    q = " ".join(str(request.query_params.get("q", "")).split())[:100]
    s = session_of(request)
    draft = (s or {}).get("wallet_draft")
    if draft and not wallet.draft_path(draft.get("token")):
        s.pop("wallet_draft", None)  # the photo is gone (saved, discarded or older than a day)
        draft = None
    import heic
    import llm
    return page(request, "wallet.html", active="wallet", w=wallet.page(g or None, q=q), g=g, q=q, kinds=wallet.KINDS,
                draft=draft, photo_ai="" if llm.photos_allowed() else llm.settings()["provider"], heic_ok=heic.available(),
                bodies=wallet.BODY_TYPES, people=records_edit.people(), link=record_link,
                flash=s.pop("wallet_flash", None) if s else None)


@app.get("/wallet/park", response_class=HTMLResponse)
def wallet_park(request: Request):
    """Parking mode: the plate big enough to read off at a parking meter or toll booth, the screen kept awake."""
    denied = need_adult(request)
    if denied:
        return denied
    return page(request, "wallet_park.html", active="wallet", p=wallet.parking(request.query_params.get("car")))


def wallet_go(request, ok, msg):
    s = session_of(request)
    if s is not None:
        s["wallet_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/wallet"
    return r


@app.post("/wallet/photo")
async def wallet_photo(request: Request):
    """A card photo as the raw body (name in X-Filename, like the Inbox upload); ?ai=1 lets the family's AI read it when
    photo reading is on. The photo waits in wallet_drafts/ until the person checks the card and saves or discards it."""
    user = current_user(request)
    if user is None or user.get("role") != "adult":
        return JSONResponse({"ok": False, "message": "Only an adult can add cards."}, status_code=403)
    buf = await capped_body(request, wallet.DRAFT_MAX + 1)
    if len(buf) > wallet.DRAFT_MAX:
        return JSONResponse({"ok": False, "message": "The photo must be under 10 MB."}, status_code=413)
    name = urllib.parse.unquote(request.headers.get("x-filename", ""))[:200]
    ok, token = await run_in_threadpool(wallet.save_draft, name, bytes(buf))
    if not ok:
        return JSONResponse({"ok": False, "message": token}, status_code=400)
    fields, msg = ({}, "Fill in the card below; the photo is kept with it.")
    if request.query_params.get("ai") == "1":
        fields, msg = await run_in_threadpool(wallet.read_photo, wallet.draft_path(token))
    s = session_of(request)
    if s is not None:
        old = s.get("wallet_draft")
        if old:
            wallet.drop_draft(old.get("token"))
        s["wallet_draft"] = {"token": token, "v": fields, "msg": msg}
    return JSONResponse({"ok": True, "redirect": "/wallet#wcheck"})


@app.get("/wallet/draft-photo")
def wallet_draft_photo(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    s = session_of(request)
    f = wallet.draft_path(((s or {}).get("wallet_draft") or {}).get("token"))
    if not f:
        return PlainTextResponse("No photo is waiting.", status_code=404)
    return FileResponse(f, media_type=wallet.IMAGE_MIME[f.suffix.lower()], headers={"Cache-Control": "no-store"})


@app.get("/wallet/scan/{doc_id}")
def wallet_scan(request: Request, doc_id: int):
    """The photo on the back of a card, inline, only a filed photo inside archive/."""
    denied = need_adult(request)
    if denied:
        return denied
    got = wallet.scan_file(doc_id)
    if not got:
        return PlainTextResponse("That scan is not on this PC.", status_code=404)
    return FileResponse(got[0], media_type=got[1], headers={"Cache-Control": "private, no-store"})


@app.post("/wallet/card", response_class=HTMLResponse)
async def wallet_card_post(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    op, user = data.get("op", ""), current_user(request)
    fields = {k: str(data.get(k, ""))[:records_edit.FIELD_MAX] for k in wallet.FIELDS}
    s = session_of(request)
    draft = (s or {}).get("wallet_draft") or {}
    if op == "discard":
        wallet.drop_draft(draft.get("token"))
        if s is not None:
            s.pop("wallet_draft", None)
        return wallet_go(request, True, "The photo was not kept.")
    if op == "add" and data.get("draft") == "1":
        scan = wallet.draft_path(draft.get("token"))
        if not scan:
            return wallet_go(request, False, "The photo is no longer waiting; add it again.")
        ok, msg = await run_in_threadpool(records_edit.ea.wallet_card_add, user, scan=scan, **fields)
        if ok and s is not None:
            s.pop("wallet_draft", None)
        elif s is not None:
            s["wallet_draft"] = {**draft, "v": fields, "msg": msg}
    elif op == "add":
        ok, msg = await run_in_threadpool(records_edit.ea.wallet_card_add, user, **fields)
    elif op == "save":
        ok, msg = await run_in_threadpool(records_edit.ea.wallet_card_update, user, data.get("id", ""), **fields)
    elif op == "drop":
        if data.get("sure") not in ("1", "on", "yes"):
            return wallet_go(request, False, "Tick 'Yes, remove this card' first.")
        ok, msg = await run_in_threadpool(records_edit.ea.wallet_card_drop, user, data.get("id", ""))
    else:
        return PlainTextResponse("Bad request", status_code=400)
    return wallet_go(request, ok, msg)


@app.post("/wallet/car", response_class=HTMLResponse)
async def wallet_car_post(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request)
    f = {k: str(data.get(k, ""))[:40] for k in ("color", "body_type", "plate", "plate_region")}
    ok, msg = await run_in_threadpool(records_edit.ea.vehicle_details, current_user(request), data.get("id", ""), **f)
    return wallet_go(request, ok, msg)


@app.get("/records/paper/{doc_id}")
def records_paper(request: Request, doc_id: int):
    """The filed paper behind a record, as a download (never shown inline), only from inside this install's archive/."""
    denied = need_adult(request)
    if denied:
        return denied
    f = records_data.paper(current_user(request), doc_id)
    if f is None:
        return PlainTextResponse("That paper is not on this PC.", status_code=404)
    return FileResponse(f, media_type="application/octet-stream", filename=f.name)


@app.get("/records/paper/{doc_id}/view")
def records_paper_view(request: Request, doc_id: int):
    """A filed PDF or photo shown inline, for the viewer window of Records / Wallet (same site frame only; adults only,
    only from inside archive/). Anything else is still a download."""
    denied = need_adult(request)
    if denied:
        return denied
    f = records_data.paper(current_user(request), doc_id)
    mime = records_data.view_mime(f) if f is not None else None
    if f is None or mime is None:
        return PlainTextResponse("That paper cannot be shown here: download it instead.", status_code=404)
    return FileResponse(f, media_type=mime, headers={"Content-Disposition": f'inline; filename="{f.name}"',
                                                     "Cache-Control": "private, no-store"})


# ---- Work (work contracts pack; work_data.py) ----------------------------------------------------------------------
WORK_KEEP = ("c", "tab", "month", "cycle", "year")


@app.get("/work", response_class=HTMLResponse)
def work_page(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    s = session_of(request)
    return page(request, "work.html", active="work", w=work_data.view(current_user(request), dict(request.query_params)),
                flash=s.pop("work_flash", None) if s else None)


def work_go(request, ok, msg, data):
    s = session_of(request)
    if s is not None:
        s["work_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/work?" + urllib.parse.urlencode({k: data[k] for k in WORK_KEEP if data.get(k)})
    return r


@app.post("/work")
async def work_post(request: Request):
    denied = need_adult(request)
    if denied:
        return denied
    data = await form(request, limit=16384)
    op = data.get("op", "")
    if op not in work_data.OPS:
        return PlainTextResponse("Bad request", status_code=400)
    ok, msg = await run_in_threadpool(work_data.act, current_user(request), op, data)
    return work_go(request, ok, msg, data)


@app.post("/work/import")
async def work_import(request: Request, kind: str = "", c: str = "", calendar: str = ""):
    """A timesheet or work calendar as the raw body (name in X-Filename): the inbox's checks, then imported and filed."""
    denied = need_adult(request)
    if denied:
        return JSONResponse({"ok": False, "message": "Only an adult can do this."}, status_code=403)
    cap = inbox_upload.MAX_BYTES
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            return JSONResponse({"ok": False, "message": f"Too large (limit {cap // (1024 * 1024)} MB)."}, status_code=413)
    name = urllib.parse.unquote(request.headers.get("x-filename", ""))[:200]
    cid = int(c) if c.isascii() and c.isdigit() else None
    ok, msg = await run_in_threadpool(work_data.import_file, current_user(request), kind, name, bytes(buf), cid, calendar[:60])
    if ok:
        s = session_of(request)
        if s is not None:
            s["work_flash"] = (ok, msg)
    return JSONResponse({"ok": ok, "message": msg}, status_code=200 if ok else 400)


def _update_state():
    """What the Updates card says without asking GitHub (that happens only on "Check for updates")."""
    st = maintenance_data._UPDATE
    daily = maintenance_data.daily_check()
    newer = st["newer"] if st["at"] > 0 else (daily["newer"] or None)  # the daily look counts until a manual check
    site = st.get("site", "") if st["at"] > 0 else daily.get("site", "")  # a version found on the public site: download, not install
    return {"current": _version(), "newer": newer, "error": st["error"], "checked": st["at"] > 0, "daily": daily, "site": site}


def update_line(user):
    """The short "a new version is available" line on Today and the Brief: adults only (update_notice.notice)."""
    try:
        import update_notice
        with db.open(paths.DB, readonly=True) as con:
            return update_notice.notice(user, con)
    except Exception:  # noqa: BLE001 (a missing line never breaks the page)
        return None


def rewards_line(user):
    """Today's line for adults when a child asked for a reward ("Mateo asked for a reward"), or None."""
    if not user or user.get("role") != "adult":
        return None
    try:
        import wall
        with db.open(paths.DB, readonly=True) as con:
            asks = wall.reward_requests(con)
    except Exception:  # noqa: BLE001 (a missing line never breaks the page)
        return None
    if not asks:
        return None
    who = sorted({a["member"] for a in asks})
    return {"n": len(asks), "text": (f"{who[0]} asked for a reward" if len(asks) == 1 else
                                     f"{len(asks)} rewards asked for ({', '.join(who)})")}


def wall_line(user):
    """Today's line for adults when an app wall has not updated for two weeks ("Kitchen wall last updated 16 days
    ago"), or None. The wall updates whenever this PC runs Mitra Home on the home Wi-Fi."""
    if not user or user.get("role") != "adult":
        return None
    try:
        import wall
        with db.open(paths.DB, readonly=True, row=True) as con:
            old = wall.stale(con)
    except Exception:  # noqa: BLE001 (a missing line never breaks the page)
        return None
    if not old:
        return None
    w = old[0]
    text = f"{w['name']} has not taken a copy yet" if w["days"] is None else f"{w['name']} last updated {w['days']} days ago"
    if len(old) > 1:
        text += f" (and {len(old) - 1} more wall{'s' if len(old) > 2 else ''})"
    return {"text": text}


@app.get("/tokens.css")
def tokens_css():
    """The colour tokens (data/look.py) as CSS variables; color-scheme so native checkboxes, pickers and scrollbars follow."""
    out = []
    for mode, t in look.TOKENS.items():
        out.append(f'[data-theme="{mode}"]{{color-scheme:{mode};' + "".join(f"--{k}:{v};" for k, v in t.items()) + "}")
    out.append(":root{" + "".join(f"--chart-{i + 1}:{c};" for i, c in enumerate(look.CHART)) + "}")
    out.append("".join(f".av{i},.av.av{i}{{background:{c}}}" for i, c in enumerate(look.PEOPLE))
               + f".avh,.av.avh{{background:{look.HOUSE}}}")
    out.append("".join(f".{calendar_data.kind_class(k)}{{--k:{c}}}" for k, c in calendar_data.KIND_COLOR.items()))
    return Response("\n".join(out), media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest():
    return JSONResponse({
        "name": brand.PRODUCT, "short_name": brand.PRODUCT, "start_url": "/", "scope": "/", "display": "standalone",
        "shortcuts": [{"name": "Parking: my plate", "short_name": "Plate", "url": "/wallet/park"},
                      {"name": "Wallet", "short_name": "Wallet", "url": "/wallet"}],
        "background_color": look.TOKENS["light"]["canvas"], "theme_color": look.TOKENS["light"]["accent"],
        "icons": [{"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                  {"src": "/static/icon-512-maskable.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]},
        media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    body = (HERE / "static" / "sw.js").read_text(encoding="utf-8").replace("__VERSION__", re.sub(r"[^0-9A-Za-z.-]", "", _version()))
    return Response(body, media_type="text/javascript", headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/offline", response_class=HTMLResponse)
def offline(request: Request):
    # Standalone and identity-free: the service worker stores this page, so it must never carry a name or a token.
    return templates.TemplateResponse(request, "offline.html", {"brand": brand.PRODUCT, "version": _version()})


@app.get("/healthz")
def healthz():
    return PlainTextResponse("ok")


# The settings / setup and phone API routes live in routes_settings.py and routes_phone.py (audit A7); they read this
# module's helpers at call time. Included last so the route order of what stays here is unchanged.
from webapp import routes_family, routes_ledger, routes_phone, routes_photo, routes_rows, routes_settings, routes_wall  # noqa: E402
from webapp import routes_wall_api  # noqa: E402

app.include_router(routes_settings.router)
app.include_router(routes_phone.router)
app.include_router(routes_ledger.router)
app.include_router(routes_rows.router)
app.include_router(routes_family.router)
app.include_router(routes_wall.router)
app.include_router(routes_wall_api.router)
app.include_router(routes_photo.router)
