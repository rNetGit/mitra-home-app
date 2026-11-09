"""The Mitra Wall as an app (the Mitra Home app in wall mode): pairing and the API it works from (/api/wall/*).

The app wall keeps its own encrypted copy of what a wall shows and works from it while the PC is off; it reaches the PC
on the home Wi-Fi over HTTPS pinned to the PC's key, with a bearer token (only its hash is kept, table walls, kind 'app',
migration 063). Like /api/ for phones: no cookies, no CSRF token, HTTPS (or this PC) only. A wall acts as the limited
wall actor (wall.actor): family lists, children's jobs and reward requests, nothing else; never money.

  POST /api/wall/pair  {"code": "ABCD-2345", "version": "0.19.0"} -> {"token", "wall": {id, name, kind}}
  GET  /api/wall/ping  -> {"ok", "wall", "version", "server_time"}; a removed wall gets 401 {"wipe": true}
  GET  /api/wall/pull?cursor=  one page of the wall's copy (data/sync_data.py, role wall: calendar, family lists,
                       children's jobs, rewards, meals; the next 35 days); `reset` = start the copy again
  GET  /api/wall/extras  what the PC works out (data/wall_copy.py): settings, special days, to-dos, goals, weather, photos
  GET  /api/wall/photo/{name}  one of the photos named in extras (made here without EXIF)
  POST /api/wall/money/unlock {"name", "pin"} -> {"by", "seconds"}: an adult's own PIN opens Money for this wall for a minute
  GET  /api/wall/money  -> bills paid in the last 7 days and due in the next 7 (data/wall_money.daily); 403 {"error": "locked"}
                       unless unlocked; nothing about money is ever part of the copy or kept on the tablet
  POST /api/wall/money/lock  closes it at once
  POST /api/wall/push  {"ops": [{"id", "op": list_add|list_tick|routine_tick|reward_ask, ...}]} -> {"results"} in order
                       (data/wall_ops.py: taps made while the PC was off, each applied once, the PC wins)
"""
from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
import datetime as dt
import json
import pathlib
import sqlite3
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import admin_actions  # noqa: E402
import sync_data  # noqa: E402
import wall_copy  # noqa: E402
import wall_money  # noqa: E402
import wall_ops  # noqa: E402
import wall_screen  # noqa: E402
import auth  # noqa: E402
import brand  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import paths  # noqa: E402
import wall as W  # noqa: E402
from webapp import app as A  # noqa: E402
from webapp import routes_phone as P  # noqa: E402
from webapp import routes_wall as RW  # noqa: E402

router = APIRouter()


def app_wall(request):
    """-> (wall, None) or (None, error response). A removed wall is told to wipe its copy."""
    if not P.api_secure(request):
        return None, P.api_error("https_only", 403)
    try:
        with db.open(paths.DB, row=True) as con:
            w = W.authenticate(con, P.bearer(request), kind="app")
            if w and "id" in w:
                W.app_seen(con, w["id"], request.headers.get("x-app-version"))
    except sqlite3.Error:
        return None, P.api_error("unavailable", 503)
    if w is None:
        return None, P.api_error("unknown_wall", 401)
    if w.get("revoked"):
        return None, JSONResponse({"error": "revoked", "wipe": True}, status_code=401)
    return w, None


@router.post("/api/wall/pair")
async def api_wall_pair(request: Request):
    """The wall code from Settings > Phones > Mitra Wall -> this app's token. The code works once, for 15 minutes."""
    if not P.api_secure(request):
        return P.api_error("https_only", 403)
    src = None if A.is_local(request) else RW._client(request)
    key = auth.pair_key(RW.PAIR_THROTTLE, src)  # the same counter as the browser wall's codes
    if auth.locked_for(key, everyone=False, source=src):
        return P.api_error("wait", 429)
    try:
        body = json.loads((await A.capped_body(request, P.API_MAX)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    body = body if isinstance(body, dict) else {}

    def redeem():
        with db.open(paths.DB, row=True) as con:
            return W.pair_redeem(con, body.get("code"), kind="app", version=body.get("version"))
    try:
        got = await run_in_threadpool(redeem)
    except sqlite3.Error:
        return P.api_error("unavailable", 503)
    if not got:
        auth.record_failure(key, everyone=False, source=src)
        return P.api_error("bad_code", 401)
    token, w = got
    admin_actions._audit({"name": "wall"}, "wall_paired", f"wall {w['id']}: {w['name']} (app)")
    return JSONResponse({"token": token, "wall": w, "app": brand.PRODUCT, "version": A._version()})


@router.get("/api/wall/ping")
def api_wall_ping(request: Request):
    """A paired app wall checks that it reaches its own household's PC."""
    w, err = app_wall(request)
    if err:
        return err
    return JSONResponse({"ok": True, "wall": w, "app": brand.PRODUCT, "version": A._version(),
                         "server_time": dt.datetime.now().isoformat(timespec="seconds")})


@router.get("/api/wall/pull")
def api_wall_pull(request: Request, cursor: str = ""):
    """One page of the wall's copy. When the last page goes out, the wall's last update is noted for Settings."""
    w, err = app_wall(request)
    if err:
        return err
    try:
        with db.open(paths.DB, row=True) as con:
            sync_data.maybe_prune(con)
            body = sync_data.pull(con, wall_copy.device(w), cursor[:200])
            if not body.get("more"):
                W.app_seen(con, w["id"], synced=True)
    except sqlite3.Error:
        return P.api_error("unavailable", 503)
    body["server_time"] = dt.datetime.now().isoformat(timespec="seconds")
    return JSONResponse(body)


@router.get("/api/wall/extras")
def api_wall_extras(request: Request):
    w, err = app_wall(request)
    if err:
        return err
    try:
        with db.open(paths.DB, readonly=True, row=True) as con:
            body = wall_copy.extras(con, wall_id=w["id"])
    except sqlite3.Error:
        return P.api_error("unavailable", 503)
    return JSONResponse(body)


@router.get("/api/wall/photo/{name}")
def api_wall_photo(request: Request, name: str):
    """A wall photo (only names wall_screen made, from wall_photos/ only); none while photos are switched off."""
    w, err = app_wall(request)
    if err:
        return err
    p = wall_screen.photo_path(name) if wall_screen.settings(wall_id=w["id"])["photos"] else None
    if not p:
        return P.api_error("not_found", 404)
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "private, no-store"})


PUSH_MAX = 64 * 1024


@router.post("/api/wall/push")
async def api_wall_push(request: Request):
    w, err = await run_in_threadpool(app_wall, request)
    if err:
        return err
    try:
        body = json.loads((await A.capped_body(request, PUSH_MAX)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    ops = body.get("ops") if isinstance(body, dict) else None
    if not isinstance(ops, list) or len(ops) > wall_ops.MAX_OPS:
        return P.api_error("bad_request", 400)

    def run():
        with db.open(paths.DB, row=True) as con:
            return wall_ops.push(con, w, ops)
    try:
        results = await run_in_threadpool(run)
    except sqlite3.Error:
        return P.api_error("unavailable", 503)
    return JSONResponse({"results": results})


# ---- money, behind an adult's PIN (the same minute and the same PIN rules as the browser wall's /wall/unlock) -----------
@router.post("/api/wall/money/unlock")
async def api_wall_money_unlock(request: Request):
    w, err = app_wall(request)
    if err:
        return err
    try:
        body = json.loads((await A.capped_body(request, P.API_MAX)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    body = body if isinstance(body, dict) else {}
    who, pin = str(body.get("name", ""))[:80], str(body.get("pin", ""))[:40]
    adults = [u["name"] for u in auth.users() if u.get("role", "adult") == "adult"]
    src = None if A.is_local(request) else RW._client(request)
    if who not in adults:
        auth.record_failure("?", everyone=src is not None, source=src)
        return P.api_error("wrong_pin", 401)
    u, wait, locked = await run_in_threadpool(auth.attempt, who, pin, src is not None, src)
    if wait:
        return JSONResponse({"error": "wait", "seconds": wait}, status_code=429)
    if not u:
        return JSONResponse({"error": "wrong_pin", "locked": locked or 0}, status_code=401)
    with RW._lock:
        RW._unlock[w["id"]] = {"by": u["name"], "until": time.time() + RW.UNLOCK_SECONDS}
    admin_actions._audit({"name": u["name"]}, "wall_money_unlock", f"wall={w['id']}")
    return JSONResponse({"by": u["name"], "seconds": RW.UNLOCK_SECONDS})


@router.get("/api/wall/money")
def api_wall_money(request: Request):
    w, err = app_wall(request)
    if err:
        return err
    left = RW.unlocked(w)
    if not left:
        return JSONResponse({"error": "locked"}, status_code=403)
    try:
        with db.open(paths.DB, readonly=True, row=True) as con:
            body = wall_money.daily(con, dates.today())
    except sqlite3.Error:
        return P.api_error("unavailable", 503)
    body["seconds"] = left
    return JSONResponse(body)


@router.post("/api/wall/money/lock")
def api_wall_money_lock(request: Request):
    w, err = app_wall(request)
    if err:
        return err
    with RW._lock:
        RW._unlock.pop(w["id"], None)
    return JSONResponse({"ok": True})
