"""Add from a photo (data/photo_read.py): /add/photo?kind=dates (a flyer, invitation or school letter into dates) and
/add/photo?kind=recipe (a recipe card into a recipe). Adults only.

The photo goes up as the raw body (like the Inbox and the Wallet), waits as a draft in the session (one at a time) and
is read by the family's AI only when photo reading is on and the box was ticked. The person checks every line; nothing
is saved before Add / Save, and each line is saved through edit_actions. Discard (or a save) removes the photo.
"""
import urllib.parse

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from starlette.concurrency import run_in_threadpool

import dates
import edit_actions as ea
import heic
import llm
import photo_read as PR
import wallet
from webapp import app as A

router = APIRouter()
KINDS = {"dates": "Dates from a photo", "recipe": "A recipe from a photo"}
KEY = "photo_draft"


def _kind(value):
    return value if value in KINDS else "dates"


def _names():
    import records_edit
    return [p for p in records_edit.people()]


def _draft(request, kind=None):
    s = A.session_of(request)
    d = (s or {}).get(KEY) or {}
    if d and not wallet.draft_path(d.get("token")):
        s.pop(KEY, None)  # the photo is gone (saved, discarded or older than a day)
        return {}
    return d if d and (kind is None or d.get("kind") == kind) else {}


def _go(request, kind, ok, msg, keep=False):
    s = A.session_of(request)
    if s is not None:
        s["photo_flash"] = (ok, msg)
        if not keep:
            d = s.pop(KEY, None)
            if d:
                wallet.drop_draft(d.get("token"))
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = f"/add/photo?kind={kind}"
    return r


@router.get("/add/photo", response_class=HTMLResponse)
def photo_page(request: Request, kind: str = "dates"):
    denied = A.need_adult(request)
    if denied:
        return denied
    kind = _kind(kind)
    s = A.session_of(request)
    d = _draft(request, kind)
    names = _names()
    return A.page(request, "add_photo.html", active="inbox", kind=kind, kinds=KINDS, draft=d, names=names,
                  date_kinds=PR.DATE_KINDS, areas=PR.AREAS, blank=[{"date": "", "title": "", "who": "", "kind": "event",
                                                                     "time": "", "end": "", "area": "school"}] * 3,
                  photo_ai="" if llm.photos_allowed() else llm.settings()["provider"], heic_ok=heic.available(),
                  today=dates.today().isoformat(), flash=s.pop("photo_flash", None) if s else None)


@router.post("/add/photo")
async def photo_upload(request: Request):
    user = A.current_user(request)
    if user is None or user.get("role") != "adult":
        return JSONResponse({"ok": False, "message": "Only an adult can add from a photo."}, status_code=403)
    kind = _kind(request.query_params.get("kind"))
    buf = await A.capped_body(request, wallet.DRAFT_MAX + 1)
    if len(buf) > wallet.DRAFT_MAX:
        return JSONResponse({"ok": False, "message": "The photo must be under 10 MB."}, status_code=413)
    name = urllib.parse.unquote(request.headers.get("x-filename", ""))[:200]
    ok, token = await run_in_threadpool(wallet.save_draft, name, bytes(buf))
    if not ok:
        return JSONResponse({"ok": False, "message": token}, status_code=400)
    v, msg = ([] if kind == "dates" else {}), "Fill it in below; the photo is shown next to the form."
    if request.query_params.get("ai") == "1":
        path = wallet.draft_path(token)
        if kind == "dates":
            v, msg = await run_in_threadpool(PR.read_dates, path, dates.today(), _names())
        else:
            v, msg = await run_in_threadpool(PR.read_recipe, path)
    s = A.session_of(request)
    if s is not None:
        old = s.get(KEY)
        if old:
            wallet.drop_draft(old.get("token"))
        s[KEY] = {"token": token, "kind": kind, "v": v, "msg": msg}
    return JSONResponse({"ok": True, "redirect": f"/add/photo?kind={kind}#pcheck"})


@router.get("/add/photo/img")
def photo_img(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    f = wallet.draft_path(_draft(request).get("token"))
    if not f:
        return PlainTextResponse("No photo is waiting.", status_code=404)
    return FileResponse(f, media_type=wallet.IMAGE_MIME[f.suffix.lower()], headers={"Cache-Control": "no-store"})


@router.post("/add/photo/save", response_class=HTMLResponse)
async def photo_save(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form_lists(request, limit=32768)

    def one(k):
        return (data.get(k) or [""])[0]
    kind = _kind(one("kind"))
    user = A.current_user(request)
    if one("op") == "discard":
        return _go(request, kind, True, "The photo was not kept.")
    if kind == "recipe":
        ok, msg = await run_in_threadpool(ea.recipe_save, user, one("name"), one("ingredients"), one("servings") or None,
                                          None, None, one("notes") or None)
        return _go(request, kind, ok, msg + (" It is in Family › Home › Meals." if ok else ""), keep=not ok)
    cols = {k: data.get(k, []) for k in ("date", "title", "who", "kind_of", "time", "end", "area")}
    keep = set(data.get("keep", []))
    read = int(one("read")) if one("read").isdigit() else 0  # lines the AI read: kept only when ticked
    rows = []
    for i in range(min(len(cols["date"]), PR.MAX_ROWS + 3)):
        row = {k: (cols[k][i] if i < len(cols[k]) else "").strip() for k in cols}
        if not row["date"] and not row["title"]:
            continue
        if str(i) not in keep and (i < read or not (row["date"] and row["title"])):
            continue  # unticked: a line the AI read, or a blank line typed into only partly
        row["kind"] = row.pop("kind_of") if row.get("kind_of") in PR.DATE_KINDS else "event"
        rows.append(row)
    if not rows:
        return _go(request, kind, False, "Tick at least one date with a day and a name.", keep=True)
    added, failed = await run_in_threadpool(PR.save_dates, user, rows)
    msg = f"Added {added} of {len(rows)} to the calendar." + (" Not added: " + "; ".join(failed) + "." if failed else "")
    return _go(request, kind, added > 0, msg[:600], keep=added == 0)
