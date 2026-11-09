"""Family > House (city, state, ZIP and the online look-ups switch) and each person's school, college or employer with
its year calendar (schools near home, college name check, find and import the calendar). Names that live in app.py are
read through `A` when a request comes in, so a test can still patch app.<name>."""
import pathlib
import sqlite3
import sys
import urllib.parse

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import calendar_find  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import edit_actions as ea  # noqa: E402
import lookups  # noqa: E402
import paths  # noqa: E402
import schools  # noqa: E402
from edit_family import US_STATES, us_state_code  # noqa: E402
from webapp import app as A  # noqa: E402

router = APIRouter()
UPLOAD_MAX = 8_000_000


def house_view():
    cfg = config.family()
    reg = cfg.get("region") or {}
    hol = ""
    try:
        import holidays as H
        r = H.rules(H.code()) or {}
        reg_rules = H.region_of(r, reg.get("state") or "")
        hol = (r.get("title") or "") + (f" + {reg_rules['name']}" if reg_rules and r.get("title") else "")
    except Exception:  # noqa: BLE001 (the page must still render)
        pass
    return {"place": reg.get("place", ""), "state": us_state_code(reg.get("state", "")) or reg.get("state", ""), "zip": reg.get("zip", ""),
            "us": (cfg.get("country") or "US").upper() == "US", "online": lookups.enabled(cfg), "holidays": hol,
            "states": sorted(US_STATES)}


@router.get("/family/house")
def house_page(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    s = A.session_of(request)
    flash = s.pop("house_flash", None) if s is not None else None
    return A.page(request, "family_house.html", active="family", v=house_view(), flash=flash)


@router.post("/family/house")
async def house_save(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    user = A.current_user(request)
    if data.get("op") == "online":
        ok, msg = await run_in_threadpool(ea.lookups_set, user, data.get("on") in ("1", "on", "yes"))
    else:
        ok, msg = await run_in_threadpool(ea.home_area_set, user, data.get("place", ""), data.get("state", ""),
                                          data.get("zip", ""))
    s = A.session_of(request)
    if s is not None:
        s["house_flash"] = (ok, msg)
    r = RedirectResponse("/family/house", status_code=303)
    if request.headers.get("hx-request"):
        r = A.Response(status_code=200)
        r.headers["HX-Redirect"] = "/family/house"
    return r


# ---- a person's school, college or employer --------------------------------------------------------------------
def _member(member_id):
    try:
        with db.open(paths.DB, readonly=True) as con:
            con.row_factory = sqlite3.Row
            m = con.execute("SELECT id, name, role, school, org_id FROM members WHERE id=?", (int(member_id),)).fetchone()
            if not m:
                return None, None
            m = dict(m)
            org = None
            if m["org_id"]:
                r = con.execute("SELECT * FROM orgs WHERE id=?", (m["org_id"],)).fetchone()
                org = dict(r) if r else None
                if org:
                    org["waiting"] = con.execute("SELECT COUNT(*) FROM calendar_days WHERE org_id=? AND status='proposed'",
                                                 (org["id"],)).fetchone()[0]
                    org["active"] = con.execute("SELECT COUNT(*) FROM calendar_days WHERE org_id=? AND status='active'",
                                                (org["id"],)).fetchone()[0]
            return m, org
    except (sqlite3.Error, ValueError, TypeError):
        return None, None


def _block(request, member_id, flash=None, **extra):
    m, org = _member(member_id)
    if not m:
        return A.page(request, "_org_block.html", m=None, flash=flash)
    import llm
    cfg = config.family()
    return A.page(request, "_org_block.html", m=m, org=org, flash=flash, online=lookups.enabled(cfg),
                  zip=(cfg.get("region") or {}).get("zip", ""), state=(cfg.get("region") or {}).get("state", ""),
                  web_ai=not llm.web_ready(), **extra)


@router.get("/family/org")
def org_block(request: Request, member: int):
    denied = A.need_adult(request)
    if denied:
        return denied
    return _block(request, member)


@router.get("/family/org/schools")
async def org_schools(request: Request, member: int):
    """Schools near the home's ZIP code (public directory), each with a Pick button."""
    denied = A.need_adult(request)
    if denied:
        return denied
    zip_code = (config.family().get("region") or {}).get("zip", "")
    try:
        found = await run_in_threadpool(schools.near, zip_code)
        return _block(request, member, schools=found)
    except (schools.SchoolError, lookups.Refused) as e:
        return _block(request, member, flash=(False, str(e)))


@router.get("/family/org/college")
async def org_college(request: Request, member: int, q: str = ""):
    """Is this a college's name? Exact = Save; otherwise 'Did you mean ...' buttons."""
    denied = A.need_adult(request)
    if denied:
        return denied
    try:
        res = await run_in_threadpool(schools.check_college, q[:100])
        return _block(request, member, college=res, college_q=q[:100])
    except (schools.SchoolError, lookups.Refused) as e:
        return _block(request, member, flash=(False, str(e)), college_q=q[:100])


@router.post("/family/org")
async def org_save(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    member = data.get("member", "")
    m, _org = _member(member)
    if not m:
        return _block(request, member, flash=(False, "That person is not on record."))
    user = A.current_user(request)
    if data.get("op") == "clear":
        ok, msg = await run_in_threadpool(ea.member_org_clear, user, m["name"])
    else:
        ok, msg = await run_in_threadpool(ea.member_org_set, user, m["name"], data.get("kind", ""), data.get("name", ""),
                                          data.get("ext_id") or None, data.get("district") or None,
                                          data.get("city") or None, data.get("state") or None)
    return _block(request, member, flash=(ok, msg))


@router.post("/family/org/find")
async def org_find(request: Request):
    """Where this year's calendar lives (calendar_find): candidates to import, nothing imported yet."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    m, org = _member(data.get("member", ""))
    if not m or not org:
        return _block(request, data.get("member", ""), flash=(False, "Link a school, college or employer first."))
    try:
        res = await run_in_threadpool(calendar_find.find, org)
    except lookups.Refused as e:
        return _block(request, m["id"], flash=(False, str(e)))
    flash = None
    if not res["candidates"]:
        flash = (False, " ".join(res["notes"]) or "No calendar link was found. Paste the link from the school's site.")
    return _block(request, m["id"], flash=flash, found=res)


@router.post("/family/org/import")
async def org_import(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    m, org = _member(data.get("member", ""))
    if not m or not org:
        return _block(request, data.get("member", ""), flash=(False, "Link a school, college or employer first."))
    ok, msg = await run_in_threadpool(ea.org_calendar_import, A.current_user(request), org["id"], url=data.get("url", ""))
    return _block(request, m["id"], flash=(ok, msg))


@router.post("/family/org/file")
async def org_file(request: Request, member: int):
    """A calendar file (.ics, PDF) sent as the raw body (X-Filename header), read like a link."""
    denied = A.need_adult(request)
    if denied:
        return denied
    m, org = _member(member)
    if not m or not org:
        return JSONResponse({"ok": False, "message": "Link a school, college or employer first."})
    body = await A.capped_body(request, UPLOAD_MAX + 1)
    if len(body) > UPLOAD_MAX:
        return JSONResponse({"ok": False, "message": "That file is too big (over 8 MB)."})
    name = urllib.parse.unquote(request.headers.get("x-filename") or "calendar")[:120]
    ok, msg = await run_in_threadpool(ea.org_calendar_import, A.current_user(request), org["id"], filename=name, body=body)
    return JSONResponse({"ok": ok, "message": msg})
