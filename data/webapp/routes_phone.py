"""The phone app's API (pairing, sessions, sync, uploads) and the page a phone opens (split from app.py, audit A7).

Names that live in app.py are read through `A` when a request comes in, so a test can still patch app.<name>.
"""
from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
from fastapi.responses import PlainTextResponse
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool
import datetime as dt
import json
import sqlite3
import time
import urllib.parse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from . import sessions  # noqa: E402
import admin_actions  # noqa: E402
import auth  # noqa: E402
import brand  # noqa: E402
import config  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import devices  # noqa: E402
import money  # noqa: E402
import paths  # noqa: E402
import phone_upload  # noqa: E402
import sync_data  # noqa: E402
import today_data  # noqa: E402
from webapp import app as A  # noqa: E402

router = APIRouter()


# ---- PWA ------------------------------------------------------------------------------------------------------
# ---- phones (/api/) ---------------------------------------------------------------------------------------------
API_MAX = 2048


PAIR_THROTTLE = "#phones"  # wrong pairing codes count like wrong PINs, on their own counter (never the all-names PIN lock)


def api_secure(request):
    """Phones talk HTTPS only (the LAN listener); plain http only from this PC itself."""
    return request.url.scheme == "https" or A.is_local(request)


def bearer(request):
    h = request.headers.get("authorization", "")
    return h[7:].strip() if h[:7].lower() == "bearer " else ""


def api_error(code, status):
    return JSONResponse({"error": code}, status_code=status)


@router.post("/api/pair")
async def api_pair(request: Request):
    """{"secret": "..."} from the QR code -> {"token", "device"}. The secret works once, for a few minutes."""
    if not api_secure(request):
        return api_error("https_only", 403)
    src = None if A.is_local(request) else (request.client.host if request.client else "unknown")
    key = auth.pair_key(PAIR_THROTTLE, src)
    if auth.locked_for(key, everyone=False, source=src):
        return api_error("wait", 429)
    try:
        body = json.loads((await A.capped_body(request, API_MAX)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    secret = body.get("secret") if isinstance(body, dict) else None

    def redeem():
        with db.open(paths.DB, row=True) as con:
            return devices.pair_redeem(con, secret)
    try:
        res = await run_in_threadpool(redeem)
    except sqlite3.Error:
        return api_error("unavailable", 503)
    if not res:
        auth.record_failure(key, everyone=False, source=src)
        return api_error("bad_code", 401)
    auth.clear_failures(key)
    token, dev = res
    admin_actions._audit({"name": dev["member"]}, "phone_paired", f"device {dev['id']}: {dev['name']}")
    return JSONResponse({"token": token, "device": dev, "app": brand.PRODUCT, "version": A._version()})


def api_device(request):
    """-> (device, None) or (None, error response). Revoked phones are told to wipe their copy."""
    if not api_secure(request):
        return None, api_error("https_only", 403)
    try:
        with db.open(paths.DB, row=True) as con:
            dev = devices.authenticate(con, bearer(request))
    except sqlite3.Error:
        return None, api_error("unavailable", 503)
    if dev is None:
        return None, api_error("unknown_device", 401)
    if dev.get("unavailable"):  # family.json unreadable right now: the phone tries again later, nothing is wiped
        return None, api_error("unavailable", 503)
    if dev.get("revoked"):
        return None, JSONResponse({"error": "revoked", "wipe": True}, status_code=401)
    return dev, None


@router.post("/api/session")
def api_session(request: Request):
    """The phone app opens the web app as its person: -> {"open": "/phone/open?code=..."} for its web view (one-time,
    60 seconds). Needs the `web` scope and a sign-in PIN for the person (the web app's sessions follow the PIN)."""
    dev, err = api_device(request)
    if err:
        return err
    if "web" not in dev.get("scopes", []):
        return api_error("no_web", 403)
    live = auth.current(dev["member"])
    if live is None:
        return api_error("no_pin", 409)
    code = sessions.handoff_create(live[0], live[1], dev["id"])
    return JSONResponse({"open": "/phone/open?code=" + code, "expires_in": sessions.HANDOFF_TTL})


@router.get("/phone/open", response_class=HTMLResponse)
def phone_open(request: Request, code: str = ""):
    """The phone app's web view trades its one-time code for the normal session cookie, then goes to Today."""
    if not api_secure(request):
        return PlainTextResponse("HTTPS only", status_code=403)
    h = sessions.handoff_take(code)
    live = auth.current(h["user"]["name"]) if h else None
    try:
        with db.open(paths.DB, readonly=True) as con:
            dev_ok = bool(h) and devices.web_ok(con, h["device"])
    except sqlite3.Error:
        dev_ok = False
    if not h or live is None or live[1] != h["bind"] or not dev_ok:
        return A.page(request, "login.html", status=401, names=[u["name"] for u in auth.users()], who="", note="",
                    error="That sign-in from the phone app ran out. Open the app again, or sign in with your PIN.")
    sessions.destroy(request.cookies.get(A.COOKIE))
    token = sessions.create(live[0], bind=live[1])
    s = sessions.get(token)
    s["device"], s["device_checked"] = h["device"], time.time()
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(A.COOKIE, token, httponly=True, samesite="strict", path="/", secure=request.url.scheme == "https",
                 max_age=sessions.ABSOLUTE)
    return r


@router.get("/api/ping")
def api_ping(request: Request):
    """A paired phone checks that it reaches its own household (and learns its person, role and scopes)."""
    dev, err = api_device(request)
    if err:
        return err

    def lim():
        with db.open(paths.DB, readonly=True, row=True) as con:
            return phone_upload.limits(con, dev)
    try:
        upload = lim()
    except sqlite3.Error:
        upload = None
    return JSONResponse({"ok": True, "app": brand.PRODUCT, "version": A._version(), "min_phone": sync_data.MIN_PHONE,
                         "device": dev, "upload": upload,
                         "sync": {"version": sync_data.VERSION, "sources": sync_data.sources_for(dev),
                                  "ops": [k for k in sync_data.OPS if sync_data.OPS[k][0 if dev["role"] == "adult" else 1]
                                          in dev.get("scopes", [])], "max_ops": sync_data.MAX_OPS},
                         "server_time": dt.datetime.now().isoformat(timespec="seconds")})


@router.get("/api/sync/pull")
def api_sync_pull(request: Request, cursor: str = ""):
    """One page of changes for this phone (data/sync_data.py). `reset` = wipe the copy first; `more` = ask again now."""
    dev, err = api_device(request)
    if err:
        return err
    try:
        with db.open(paths.DB, row=True) as con:
            sync_data.maybe_prune(con)
            body = sync_data.pull(con, dev, cursor[:200])
    except sqlite3.Error:
        return api_error("unavailable", 503)
    body["server_time"] = dt.datetime.now().isoformat(timespec="seconds")
    body["money"] = {"currency": (config.currency() or "USD").upper(), "symbol": money.symbol()}  # the phone's "$60.00"
    if dev.get("role") == "adult":  # the PC's own count (it sees papers, cars and jobs the copy does not carry)
        summary = {}
        try:
            s = today_data.summary(A.brief_context({"name": dev.get("member"), "role": "adult"}))
            summary = {k: s[k] for k in ("needs", "overdue", "due_today", "week")}
        except Exception:  # noqa: BLE001 (the copy must still arrive)
            pass
        if "finance" in dev.get("scopes", []) and not body.get("more"):
            # Money > Spending / Bills / Regular as the PC counts them (wall_money.py), once per sync (its last page).
            # Always a fresh summary: a phone that loses the finance scope drops the money block on its next sync.
            try:
                import wall_money
                with db.open(paths.DB, readonly=True) as con:
                    summary["money"] = wall_money.for_phone(con, dates.today())
            except Exception:  # noqa: BLE001
                pass
        if summary:
            body["summary"] = summary
    return JSONResponse(body)


SYNC_PUSH_MAX = 64 * 1024


@router.post("/api/sync/push")
async def api_sync_push(request: Request):
    """{"ops": [{"id": "<phone's id>", "op": "list_add", ...}, ...]} -> {"results": [...]} in the same order."""
    dev, err = await run_in_threadpool(api_device, request)
    if err:
        return err
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > SYNC_PUSH_MAX:
        return api_error("too_large", 413)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > SYNC_PUSH_MAX:
            return api_error("too_large", 413)
    try:
        body = json.loads(bytes(buf).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    ops = body.get("ops") if isinstance(body, dict) else None
    if not isinstance(ops, list) or len(ops) > sync_data.MAX_OPS:
        return api_error("bad_request", 400)

    def run():
        with db.open(paths.DB) as con:
            return sync_data.push(con, dev, ops)
    try:
        results = await run_in_threadpool(run)
    except sqlite3.Error:
        return api_error("unavailable", 503)
    return JSONResponse({"results": results})


@router.post("/api/upload")
async def api_upload(request: Request):
    """One scan or file from a phone: the raw bytes as the body; X-Filename (percent-encoded), X-Client-Id (the phone's
    id for this send, so a retry never makes a second copy) and X-Sha256. The phone is checked before the body is read;
    the body is read with a hard size cap and nothing in it is interpreted (data/phone_upload.py does the rest)."""
    dev, err = await run_in_threadpool(api_device, request)
    if err:
        return err
    if "scan" not in dev.get("scopes", []) or dev.get("role") != "adult":
        return api_error("no_scope", 403)
    cap = phone_upload.MAX_BYTES
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > cap:
        return api_error("too_large", 413)
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > cap:
            return api_error("too_large", 413)
    name = urllib.parse.unquote(request.headers.get("x-filename", ""))[:200]

    def save():
        with db.open(paths.DB, row=True) as con:
            return phone_upload.accept(con, dev, request.headers.get("x-client-id"), name, bytes(buf),
                                       request.headers.get("x-sha256"))
    try:
        status, body = await run_in_threadpool(save)
    except sqlite3.Error:
        return api_error("unavailable", 503)
    return JSONResponse(body, status_code=status)
