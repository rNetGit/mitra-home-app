"""Settings, Connections, Data, the data check and the first-run setup pages (split from app.py, audit A7).

Names that live in app.py are read through `A` when a request comes in, so a test can still patch app.<name>.
"""
from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
import html
import os
import urllib.parse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import admin_actions  # noqa: E402
import connections_data  # noqa: E402
import dates  # noqa: E402
import edit_actions as ea  # noqa: E402
import maintenance_data  # noqa: E402
import settings_data  # noqa: E402
import setup_data  # noqa: E402
import view_mode  # noqa: E402
from webapp import app as A  # noqa: E402

router = APIRouter()


# ---- Settings (adults; settings_data.py, connections_data.py, maintenance_data.py) ---------------------------------
def settings_url(group, tab=""):
    q = {"group": settings_data.group_of(group)}
    if tab:
        q["tab"] = tab
    return "/settings?" + urllib.parse.urlencode(q)


def settings_go(request, ok, msg, group, tab=""):
    """After a Settings form: remember the result and let HTMX load the group again."""
    s = A.session_of(request)
    if s is not None:
        s["settings_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = settings_url(group, tab)
    return r


@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request, group: str = "", tab: str = ""):
    denied = A.need_adult(request)
    if denied:
        return denied
    g, today = settings_data.group_of(group), dates.today()
    s = A.session_of(request)
    ctx = {"group": g, "groups": view_mode.groups(settings_data.PILLS), "titles": dict(settings_data.GROUPS), "view": view_mode.get(),
           "flash": s.pop("settings_flash", None) if s else None}
    if g == settings_data.DEFAULT:
        ctx["o"] = settings_data.overview(today, view_mode.groups(settings_data.HOME_LANES))
    elif g == "household":
        ctx.update(h=settings_data.household(today), packs=settings_data.packs(), tax=settings_data.tax_names(),
                   leads=settings_data.leads(), trad=settings_data.traditions())
    elif g == "agent":
        ctx.update(a=settings_data.agent(), pins=settings_data.pins(), hidden=settings_data.hidden(today),
                   me=A.current_user(request).get("name") or "")
    elif g == "connections":
        ctx.update(conns=settings_data.connections(), ai=connections_data.ai(), tg=connections_data.telegram(),
                   g=connections_data.google(), bank=connections_data.bank(), feeds=connections_data.feeds(), mail=connections_data.mail(), local=A.is_local(request),
                   local_only=connections_data.LOCAL_ONLY, bank_local_only=connections_data.BANK_LOCAL_ONLY,
                   conn_from="settings", pm=settings_data.phones_mode(), phn=len(settings_data.phones()["rows"]))
    elif g == "phones":
        pair, wpair = (s.pop("phone_pair", None), s.pop("wall_pair", None)) if s else (None, None)
        # Sub-tabs Phones / Walls / Connection; a fresh pairing code opens its own tab
        tab = "walls" if wpair else "phones" if pair else tab if tab in settings_data.DEVICE_TABS else "phones"
        ctx.update(ph=settings_data.phones(), local=A.is_local(request), pair=pair, wl=settings_data.walls(),
                   wpair=wpair, tab=tab, pm=settings_data.phones_mode())
    else:
        rows = settings_data.health(today)
        ctx.update(checks=rows, bad=[r for r in rows if r["status"] == "warn"], snaps=maintenance_data.snapshots(),
                   adv=settings_data.advanced(rows),
                   last_restore=maintenance_data.last_restore(), tasks=maintenance_data.tasks(),
                   upd=A._update_state(),
                   changes=maintenance_data.changes(), export_name=s.pop("export_name", None) if s else None,
                   restoring=s.pop("restoring", None) if s else None, local=A.is_local(request),
                   where=settings_data.where())
    return A.page(request, "settings.html", active="settings", **ctx)


@router.post("/settings/view")
async def settings_view(request: Request):
    """Simple / Advanced: which pages and settings are shown. Display only (view_mode.py)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = admin_actions.view_mode_set(A.current_user(request), (await A.form(request)).get("mode", ""))
    return settings_go(request, ok, msg, "home")


@router.post("/settings/next")
async def settings_next(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(settings_data.answer_next, A.current_user(request), dates.today())
    if ok:
        r = Response(status_code=200)
        r.headers["HX-Redirect"] = "/add"
        return r
    return settings_go(request, ok, msg, "household")


@router.post("/settings/papers")
async def settings_papers(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = settings_data.paper_names_set(A.current_user(request), (await A.form(request)).get("names", ""))
    return settings_go(request, ok, msg, "household")


@router.post("/settings/packs")
async def settings_packs(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    on = (await A.form_lists(request)).get("pack", [])
    ok, msg = await run_in_threadpool(settings_data.packs_save, A.current_user(request), on)
    return settings_go(request, ok, msg, "household")


@router.post("/settings/traditions")
async def settings_traditions(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(settings_data.traditions_save, A.current_user(request), await A.form(request, limit=4096))
    return settings_go(request, ok, msg, "household")


@router.post("/settings/tax")
async def settings_tax(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = settings_data.tax_save(A.current_user(request), await A.form(request))
    return settings_go(request, ok, msg, "household")


@router.post("/settings/lead")
async def settings_lead(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    d = await A.form(request)
    ok, msg = settings_data.lead_save(A.current_user(request), d.get("type", ""), d.get("days", ""), d.get("reset") == "1")
    return settings_go(request, ok, msg, "household")


@router.post("/settings/agent")
async def settings_agent(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form_lists(request)
    one = {k: v[0] for k, v in data.items()}
    ok, msg = await run_in_threadpool(settings_data.agent_save, A.current_user(request), one, data.get("watch", []),
                                      data.get("approvers", []))
    return settings_go(request, ok, msg, "agent")


@router.post("/settings/pin")
async def settings_pin(request: Request):
    """A sign-in PIN (aa.pin_set: adults only, the old PIN is not asked). A changed PIN
    of the person signed in ends their session, so they go to the sign-in page. PINs are never sent back."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=2048)
    user = A.current_user(request)
    who = data.get("who", "")
    ok, msg = await run_in_threadpool(settings_data.pin_set, user, who, data.get("pin", ""), data.get("again", ""),
                                      data.get("current", ""))
    if ok and A.session_of(request) is None:  # their own PIN, or the first PIN (the open-on-this-PC mode ends)
        mode = await run_in_threadpool(settings_data.phones_mode)
        if A.is_local(request) and mode["restart"] and mode["want"]:  # the first PIN: open to phones, no second step
            return _restart_page(request, "/login?pin=changed")
        r = Response(status_code=200)
        r.headers["HX-Redirect"] = "/login?pin=changed"
        r.delete_cookie(A.COOKIE, path="/")
        return r
    return settings_go(request, ok, msg, "agent")


@router.post("/settings/phones/add")
async def settings_phones_add(request: Request):
    """A one-time pairing QR code for a phone (this PC only). It is kept in the session and shown once."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=2048)
    ok, msg, pair = await run_in_threadpool(settings_data.phone_pair, A.current_user(request), A.is_local(request),
                                            data.get("who", ""), data.get("name", ""))
    if not ok:
        return settings_go(request, ok, msg, "phones")
    s = A.session_of(request)
    if s is not None:
        s["phone_pair"] = pair
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = settings_url("phones")
    return r


@router.post("/settings/phones/revoke")
async def settings_phones_revoke(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(settings_data.phone_revoke, A.current_user(request), (await A.form(request)).get("id", ""))
    return settings_go(request, ok, msg, "phones")


@router.post("/settings/phones/scopes")
async def settings_phones_scopes(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form_lists(request)
    ok, msg = await run_in_threadpool(settings_data.phone_scopes, A.current_user(request), (data.get("id") or [""])[0],
                                      data.get("scope", []))
    return settings_go(request, ok, msg, "phones")


@router.post("/settings/phones/mode")
async def settings_phones_mode(request: Request):
    """Settings > Phones > Connection: the "phones and walls on the home Wi-Fi" switch (launch.py reads it)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = admin_actions.phones_set(A.current_user(request), (await A.form(request)).get("on") == "1")
    return settings_go(request, ok, msg, "phones", "connection")


@router.post("/settings/phones/restart")
async def settings_phones_restart(request: Request):
    """Start the app again so it matches the switch (for phones, or this PC only). This PC only, like a restore."""
    denied = A.need_adult(request)
    if denied:
        return denied
    await A.form(request)
    if not A.is_local(request):
        return settings_go(request, False, "Restart from the PC itself: the app closes and starts again there.",
                           "phones", "connection")
    return _restart_page(request, "/settings?group=phones&tab=connection")


def _restart_page(request, back):
    """Start the app again in the mode the Phones switch asks for, and show the page that waits for it."""
    port = int(os.environ.get("MITRAHOME_WEB_PORT") or request.url.port or 8601)  # the PC's own port
    lan = settings_data.phones_restart_lan()
    import restore_backup
    restore_backup.start_relaunch(port, lan)
    admin_actions._audit(A.current_user(request), "web_restart", "lan" if lan else "pc")
    maintenance_data.close_soon()
    msg = ("Starting again for phones and walls on the home Wi-Fi. This page comes back by itself in a few seconds." if lan
           else "Starting again for this PC only. This page comes back by itself in a few seconds.")
    return A.page(request, "_restoring.html", msg=msg, title="Restart", back=back)


@router.post("/settings/stop")
async def settings_stop(request: Request):
    """Stop the app: the installer's shortcuts start it with no window, so there is none to close. This PC only."""
    denied = A.need_adult(request)
    if denied:
        return denied
    await A.form(request)
    if not A.is_local(request):
        return settings_go(request, False, "Stop it from the PC itself.", "data")
    msg = settings_data.stop_app()
    admin_actions._audit(A.current_user(request), "web_stop", "")
    maintenance_data.close_soon()
    return A.page(request, "_stopped.html", msg=msg, title="Stopped")


@router.get("/settings/phones/firewall", response_class=HTMLResponse)
async def settings_phones_firewall(request: Request, fresh: str = ""):
    """The firewall and network check, loaded after the page (it asks Windows and takes a few seconds). This PC only."""
    denied = A.need_adult(request)
    if denied:
        return denied
    if not A.is_local(request):
        return HTMLResponse("")
    import firewall
    m = settings_data.phones_mode()
    fw = await run_in_threadpool(firewall.status, m["port"], settings_data.phones_lan()["ip"], fresh == "1")
    return A.page(request, "_firewall.html", fw=fw, m=m)


@router.post("/settings/phones/firewall")
async def settings_phones_firewall_act(request: Request):
    """"Allow phones through Windows Firewall" (Windows asks for permission) or open Windows' Wi-Fi settings."""
    denied = A.need_adult(request)
    if denied:
        return denied
    op = (await A.form(request)).get("op", "")
    if op == "allow":
        m = settings_data.phones_mode()
        ok, msg = await run_in_threadpool(admin_actions.firewall_allow, A.current_user(request), A.is_local(request),
                                          m["port"], settings_data.phones_lan()["ip"])
    elif op == "network" and A.is_local(request):
        import firewall
        ok, msg = firewall.open_network_settings()
    else:
        return PlainTextResponse("Bad request", status_code=400)
    return settings_go(request, ok, msg, "phones", "connection")


@router.post("/settings/folder")
async def settings_folder(request: Request):
    """Settings > Data > Where things are: open one folder in Explorer / Finder on this PC."""
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = settings_data.open_folder(A.current_user(request), A.is_local(request), (await A.form(request)).get("key", ""))
    return data_go(request, ok, msg)



@router.post("/settings/wall/add")
async def settings_wall_add(request: Request):
    """A one-time code (and QR) that makes a tablet the Mitra Wall (this PC only; kept in the session, shown once)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=1024)
    port = os.environ.get("MITRAHOME_WEB_PORT") or request.url.port or 8601  # the PC's own port, never the phones'
    ok, msg, pair = await run_in_threadpool(settings_data.wall_pair, A.current_user(request), A.is_local(request),
                                            data.get("name", ""), port)
    if not ok:
        return settings_go(request, ok, msg, "phones", "walls")
    s = A.session_of(request)
    if s is not None:
        pair["kind"] = "app" if data.get("kind") == "app" and pair.get("app_qr") else "browser"
        s["wall_pair"] = pair
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = settings_url("phones", "walls")
    return r


@router.post("/settings/wall/revoke")
async def settings_wall_revoke(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(settings_data.wall_revoke, A.current_user(request), (await A.form(request)).get("id", ""))
    return settings_go(request, ok, msg, "phones", "walls")

@router.post("/settings/wall/seasonal")
async def settings_wall_seasonal(request: Request):
    """Seasonal wall looks on / off (adults; data/wall_season.py)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    d = await A.form(request, limit=256)
    ok, msg = await run_in_threadpool(ea.wall_seasonal_set, A.current_user(request), d.get("on") == "1")
    return settings_go(request, ok, msg, "phones", "walls")


@router.post("/settings/wall/screen")
async def settings_wall_screen(request: Request):
    """The wall's resting screen: clock face, night clock, photos on / off and the schedule (data/wall_screen.py)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    d = await A.form(request, limit=4096)
    ok, msg = await run_in_threadpool(ea.wall_screen_set, A.current_user(request), d.get("clock", ""), d.get("photos") == "1",
                                      d.get("photo_seconds", ""), d.get("clock_seconds", ""), d.get("per_turn", ""),
                                      d.get("photos_from", ""), d.get("photos_to", ""), d.get("night_from", ""),
                                      d.get("night_to", ""), d.get("night_tone", "dim"), d.get("zone", ""),
                                      d.get("photo_style", ""), _wall_tabs(d), d.get("clock_only") == "1",
                                      d.get("theme", ""), d.get("rotate_seconds", "0"), _wall_led(d))
    return settings_go(request, ok, msg, "phones", "walls")


@router.get("/settings/wall/preview", response_class=HTMLResponse)
async def settings_wall_preview(request: Request):
    """The resting screen with the form's choices, not saved (shown in the preview window next to Save the wall screen)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    import wall_screen
    from webapp import routes_wall
    d = dict(request.query_params)
    try:
        s = wall_screen.clean(d.get("clock", ""), d.get("photos") == "1", d.get("photo_seconds", ""), d.get("clock_seconds", ""),
                              d.get("per_turn", ""), d.get("photos_from", ""), d.get("photos_to", ""), d.get("night_from", ""),
                              d.get("night_to", ""), d.get("night_tone", "dim"), d.get("zone", ""), d.get("photo_style", ""),
                              _wall_tabs(d), d.get("clock_only") == "1", d.get("theme", ""), d.get("rotate_seconds", "0"), _wall_led(d))
    except wall_screen.ScreenError as e:
        return HTMLResponse(f"<p style=\"font:16px sans-serif;padding:1em\">Cannot preview: {html.escape(str(e))}</p>", status_code=200)
    return routes_wall.preview_rest(request, s)


def _wall_led(d):
    """The LED clock's choices on the form (wall_screen.clean checks them; unticked boxes = off)."""
    return {"led_style": d.get("led_style", ""), "led_colour": d.get("led_colour", ""), "led_bg": d.get("led_bg", ""),
            "led_weekdays": d.get("led_weekdays") == "1", "hours24": d.get("hours24") == "1"}


def _wall_tabs(d):
    """The optional wall pages ticked on the form (tab_chores, tab_meals)."""
    import wall_screen
    return [t for t in wall_screen.TABS if d.get("tab_" + t) == "1"]


@router.post("/settings/wall/own")
async def settings_wall_own(request: Request):
    """One wall's own resting screen, or back to the household's (`own` unticked; data/wall_screen.py)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    d = await A.form(request, limit=4096)
    ok, msg = await run_in_threadpool(ea.wall_screen_own_set, A.current_user(request), d.get("id", ""), d.get("own") == "1",
                                      d.get("clock", ""), d.get("photos") == "1", d.get("photo_seconds", ""),
                                      d.get("clock_seconds", ""), d.get("per_turn", ""), d.get("photos_from", ""),
                                      d.get("photos_to", ""), d.get("night_from", ""), d.get("night_to", ""),
                                      d.get("night_tone", "dim"), d.get("zone", ""), d.get("photo_style", ""),
                                      _wall_tabs(d), d.get("clock_only") == "1", d.get("theme", ""), d.get("rotate_seconds", "0"), _wall_led(d))
    return settings_go(request, ok, msg, "phones", "walls")


@router.post("/settings/wall/photo")
async def settings_wall_photo(request: Request):
    """One photo for the wall as the raw body (name in X-Filename), made here without its EXIF. -> {ok, message}."""
    denied = A.need_adult(request)
    if denied:
        return denied
    import wall_screen
    body = await A.capped_body(request, wall_screen.MAX_UPLOAD + 1)
    name = urllib.parse.unquote(request.headers.get("x-filename", ""))[:200]
    ok, msg = await run_in_threadpool(ea.wall_photo_add, A.current_user(request), name, bytes(body))
    return JSONResponse({"ok": ok, "message": msg}, status_code=200 if ok else 400)


@router.post("/settings/wall/photo/remove")
async def settings_wall_photo_remove(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(ea.wall_photo_remove, A.current_user(request), (await A.form(request)).get("name", ""))
    return settings_go(request, ok, msg, "phones", "walls")


@router.get("/settings/wall/photo/{name}")
def settings_wall_photo_file(request: Request, name: str):
    """A wall photo for the Settings thumbnails (adults; only names wall_screen made, from wall_photos/ only)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    import wall_screen
    p = wall_screen.photo_path(name)
    if not p:
        return PlainTextResponse("Not found", status_code=404)
    return FileResponse(p, media_type="image/jpeg")


def conn_go(request, ok, msg, where="settings"):
    """After a Connections change: the result once, then the setup step or Settings > Connections again."""
    if where == "setup":
        s = A.session_of(request)
        if s is not None:
            s["settings_flash"] = (ok, msg)
        r = Response(status_code=200)
        r.headers["HX-Redirect"] = "/setup"
        return r
    return settings_go(request, ok, msg, "connections")


@router.post("/settings/ai")
async def settings_ai(request: Request):
    """The AI provider (and key: only from this PC). A good save of a provider that answers at once is tested once."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=4096)
    ok, msg = await run_in_threadpool(connections_data.ai_save, A.current_user(request), data, A.is_local(request))
    return conn_go(request, ok, msg, data.get("from"))


@router.post("/settings/ai/test")
async def settings_ai_test(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    ok, msg = await run_in_threadpool(connections_data.ai_test, A.current_user(request))
    return conn_go(request, ok, ("Test call: " if ok else "Test call failed: ") + msg, data.get("from"))


@router.post("/settings/telegram")
async def settings_telegram(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=2048)
    ok, msg = await run_in_threadpool(connections_data.telegram_act, A.current_user(request), data.get("op", ""), data,
                                      A.is_local(request))
    return conn_go(request, ok, msg)


@router.post("/settings/google/client")
async def settings_google_client(request: Request):
    """The Google client file as the raw request body (no multipart parser), from this PC only, at most 100 kB."""
    denied = A.need_adult(request)
    if denied:
        return JSONResponse({"ok": False, "message": "Only an adult can do this."}, status_code=403)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > connections_data.CLIENT_MAX:
            return JSONResponse({"ok": False, "message": "That file is too large to be a Google client file."}, status_code=413)
    ok, msg = await run_in_threadpool(connections_data.google_client, A.current_user(request), bytes(buf), A.is_local(request))
    if ok:
        s = A.session_of(request)
        if s is not None:
            s["settings_flash"] = (ok, msg)
    return JSONResponse({"ok": ok, "message": msg}, status_code=200 if ok else 400)


@router.post("/settings/google")
async def settings_google(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form_lists(request, limit=8192)
    one = {k: v[0] for k, v in data.items()}
    ok, msg = await run_in_threadpool(connections_data.google_act, A.current_user(request), one.get("op", ""), one,
                                      A.is_local(request), data.get("cal", []))
    return conn_go(request, ok, msg)


@router.post("/settings/bank")
async def settings_bank(request: Request):
    """Bank sync (SimpleFIN): token (this PC only), ticked accounts, pull now, forget. Adults; CSRF like every change."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form_lists(request, limit=8192)
    one = {k: v[0] for k, v in data.items()}
    ok, msg = await run_in_threadpool(connections_data.bank_act, A.current_user(request), one.get("op", ""), one,
                                      A.is_local(request), data.get("acct", []))
    return conn_go(request, ok, msg)


@router.post("/settings/mail")
async def settings_mail(request: Request):
    """The mail folder (IMAP, read-only): mailbox and app password (the password only on this PC), test, read now, forget."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=4096)
    ok, msg = await run_in_threadpool(connections_data.mail_act, A.current_user(request), data.get("op", ""), data,
                                      A.is_local(request))
    return conn_go(request, ok, msg)


@router.post("/settings/feeds")
async def settings_feeds(request: Request):
    """Other calendars (.ics addresses, read-only): add (this PC only, the address is a private link), read now, remove."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=4096)
    ok, msg = await run_in_threadpool(connections_data.feeds_act, A.current_user(request), data.get("op", ""), data,
                                      A.is_local(request))
    return conn_go(request, ok, msg)


@router.get("/settings/google/preview", response_class=HTMLResponse)
async def settings_google_preview(request: Request):
    """What a calendar sync would add, change or remove; nothing is sent to Google."""
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, summary, rows = await run_in_threadpool(connections_data.sync_preview, A.current_user(request))
    return A.page(request, "_sync_plan.html", ok=ok, summary=summary, rows=rows)


# ---- Settings > Data (maintenance_data.py) --------------------------------------------------------------------------
def data_go(request, ok, msg, **keep):
    s = A.session_of(request)
    if s is not None:
        s["settings_flash"] = (ok, msg)
        s.update({k: v for k, v in keep.items() if v})
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = settings_url("data")
    return r


@router.post("/settings/backup")
async def settings_backup(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(maintenance_data.backup, A.current_user(request))
    return data_go(request, ok, msg)


@router.post("/settings/export")
async def settings_export(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg, z = await run_in_threadpool(maintenance_data.export, A.current_user(request))
    return data_go(request, ok, msg, export_name=z.name if ok and z is not None else None)


@router.get("/settings/export/{name}")
def settings_export_file(request: Request, name: str):
    """An export zip, only by its file name and only from inside exports/, as a download."""
    denied = A.need_adult(request)
    if denied:
        return denied
    f = maintenance_data.export_file(name)
    if f is None:
        return PlainTextResponse("That export is not on this PC.", status_code=404)
    return FileResponse(f, media_type="application/zip", filename=f.name)


@router.post("/settings/backup/restore")
async def settings_backup_restore(request: Request):
    """Check a backup, or restore it: a separate process waits for this web app to close, restores, and starts it again."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=4096)
    user, op = A.current_user(request), data.get("op", "")
    if op == "check":
        ok, msg = await run_in_threadpool(maintenance_data.restore_check, user, data.get("snap"), data.get("passphrase", ""))
        return data_go(request, ok, msg)
    if op != "start":
        return PlainTextResponse("Bad request", status_code=400)
    if data.get("sure") != "1":
        return data_go(request, False, "Tick the box to confirm that everything entered after this backup is replaced.")
    if not A.is_local(request):  # the app closes and starts again: only where it can be started again by hand too
        return data_go(request, False, "A restore can be started only on this PC (it closes the app and starts it again).")
    port = int(os.environ.get("MITRAHOME_WEB_PORT") or request.url.port or 8601)  # the PC's own port, never the phones'
    ok, msg = await run_in_threadpool(maintenance_data.restore_start, user, data.get("snap"), data.get("passphrase", ""),
                                      port, os.environ.get("MITRAHOME_WEB_LAN") == "1")
    if not ok:
        return data_go(request, ok, msg)
    maintenance_data.close_soon()
    return A.page(request, "_restoring.html", msg=msg)


@router.post("/settings/tasks")
async def settings_tasks(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    ok, msg = await run_in_threadpool(maintenance_data.tasks_register, A.current_user(request), data.get("inbox") == "1")
    return data_go(request, ok, msg)


@router.post("/settings/tasks/job")
async def settings_task_job(request: Request):
    """Switch one scheduled job on or off (Settings > Data > Runs on its own)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    ok, msg = await run_in_threadpool(maintenance_data.task_set, A.current_user(request), str(data.get("job") or ""),
                                      data.get("on") == "1")
    return data_go(request, ok, msg)


@router.post("/settings/tasks/time")
async def settings_task_time(request: Request):
    """Change when the daily brief, weekly digest or weekly backup runs; registered again when it is on here."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    ok, msg = await run_in_threadpool(maintenance_data.task_time, A.current_user(request), str(data.get("job") or ""),
                                      str(data.get("day") or ""), str(data.get("time") or ""))
    return data_go(request, ok, msg)


@router.post("/settings/update")
async def settings_update(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    op = data.get("op", "")
    if op == "check":
        u = await run_in_threadpool(maintenance_data.check_update, True)
        if u["error"]:
            return data_go(request, False, u["error"])
        return data_go(request, True, f"Version {u['newer']} is available." if u["newer"] else "Up to date.")
    if op == "go":
        port = int(os.environ.get("MITRAHOME_WEB_PORT") or request.url.port or 8601)
        ok, msg = await run_in_threadpool(maintenance_data.update, A.current_user(request), port,
                                          os.environ.get("MITRAHOME_WEB_LAN") == "1")
        if not ok:
            return data_go(request, ok, msg)
        maintenance_data.close_soon()  # the old code stops serving; restore_backup.py relaunch starts the new one
        return A.page(request, "_restoring.html", msg=msg, title="Update")
    if op == "daily":
        ok, msg = maintenance_data.daily_check_set(A.current_user(request), data.get("on") == "1")
        return data_go(request, ok, msg)
    return PlainTextResponse("Bad request", status_code=400)


@router.post("/settings/doctor", response_class=HTMLResponse)
async def settings_doctor(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    lines = await run_in_threadpool(maintenance_data.full_check)
    return A.page(request, "_doctor.html", lines=lines)


@router.get("/settings/audit", response_class=HTMLResponse)
def settings_audit(request: Request):
    """Settings > Data > Data check: the newest run of data/audit.py, every check and the score over time."""
    denied = A.need_adult(request)
    if denied:
        return denied
    s = A.session_of(request)
    return A.page(request, "audit.html", active="settings", a=maintenance_data.audit_state(),
                flash=s.pop("audit_flash", None) if s else None)


@router.post("/settings/audit")
async def settings_audit_run(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(maintenance_data.audit_run, A.current_user(request))
    s = A.session_of(request)
    if s is not None:
        s["audit_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/settings/audit"
    return r


@router.post("/settings/audit/explain")
async def settings_audit_explain(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(maintenance_data.audit_explain, A.current_user(request))
    s = A.session_of(request)
    if s is not None:
        s["audit_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/settings/audit"
    return r


@router.post("/settings/audit/undo")
async def settings_audit_undo(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = await run_in_threadpool(maintenance_data.audit_undo, A.current_user(request), (await A.form(request)).get("fix", ""))
    s = A.session_of(request)
    if s is not None:
        s["audit_flash"] = (ok, msg)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/settings/audit"
    return r


@router.post("/settings/restore")
async def settings_restore(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msg = settings_data.restore(A.current_user(request), (await A.form(request)).get("key", ""), dates.today())
    return settings_go(request, ok, msg, "agent")


@router.get("/settings/calendar.ics")
def settings_calendar(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    text = settings_data.calendar_file(dates.today())
    return Response(text.encode("utf-8"), media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="mitrahome.ics"'})


# ---- first run (the setup interview; setup_data.py) ---------------------------------------------------------------
def setup_page(request, a, step, problems=(), typed=None, partial=False):
    rerun = not setup_data.needed()
    v = setup_data.view(a, step, typed)
    s = A.session_of(request)
    flash = s.pop("settings_flash", None) if s else None
    ai = connections_data.ai() if "AI" in v["names"] else None
    return A.page(request, "_setup.html" if partial else "setup.html", active="setup", v=v, problems=list(problems),
                rerun=rerun, ai=ai, local=A.is_local(request), conn_from="setup", flash=flash,
                bare=not rerun)  # no rail on a new install: every page leads back here


@router.get("/setup", response_class=HTMLResponse)
def setup(request: Request):
    """A new install (anyone on this PC while nobody has a PIN) or a re-run from Settings (adults)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    a, step = setup_data.state()
    return setup_page(request, a, step)


@router.post("/setup", response_class=HTMLResponse)
async def setup_post(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request, limit=16384)
    op = data.get("op", "next")
    if op not in ("next", "back", "goto", "later", "check"):
        return PlainTextResponse("Bad request", status_code=400)
    step, problems, typed, a = await run_in_threadpool(setup_data.submit, op, data.get("step", "0"), data)
    if op == "later":
        return A.page(request, "_setup_saved.html")
    return setup_page(request, a, step, problems, typed, partial=True)


@router.post("/setup/finish", response_class=HTMLResponse)
async def setup_finish(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    ok, msgs = await run_in_threadpool(setup_data.finish)
    if not ok:
        a, step = setup_data.state()
        return setup_page(request, a, step, msgs, partial=True)
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/setup/done"
    return r


@router.get("/setup/done", response_class=HTMLResponse)
def setup_done(request: Request):
    if setup_data.needed():
        return RedirectResponse("/setup", status_code=303)
    import chat_data
    return A.page(request, "setup_done.html", msgs=setup_data.done_messages(), ai_on=chat_data.ai_ready())


@router.post("/setup/cancel")
async def setup_cancel(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    if setup_data.needed():
        return PlainTextResponse("Bad request", status_code=400)
    setup_data.cancel()
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = settings_url("household")
    return r
