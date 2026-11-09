"""Money: a row of any Finance list (an account, a bill, a receipt, a subscription ...) opens in a window over the list: its
details, filed paper and history, Previous / Next through the rows of the same list (with the page's filters), and the same
change forms as the record page, answered in place. A transaction opens the Ledger's window. Names that live in app.py are
read through `A` when a request comes in, so a test can still patch app.<name>."""
import pathlib
import sys
import urllib.parse

from fastapi import APIRouter
from fastapi import Request
from fastapi.responses import PlainTextResponse
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import dates  # noqa: E402
import finance_data  # noqa: E402
import records  # noqa: E402
import records_data  # noqa: E402
import records_edit  # noqa: E402
from webapp import app as A  # noqa: E402
from webapp import routes_ledger  # noqa: E402

router = APIRouter()


def _args(params):
    """The page's own query (month, from, to, q, ...) without the part, each cut to a sane length."""
    return {k: str(v)[:100] for k, v in params.items() if k != "part" and len(k) <= 20}


def _neighbors(part, args, table, rid):
    """(position from 1, total, previous id, next id) of a row in the list it was opened from; None when there is no such list."""
    if not part or finance_data.part_of(part) != part or part == finance_data.DEFAULT:
        return None
    try:
        v = finance_data.view(part, dates.today(), args)
    except Exception:  # noqa: BLE001 (a part that cannot be listed just has no Previous / Next)
        return None
    for b in v.get("blocks") or []:
        if b.get("table") != table:
            continue
        ids = [r["id"] for r in b["rows"] if r.get("id") is not None]
        if rid in ids:
            i = ids.index(rid)
            return i + 1, len(ids), ids[i - 1] if i else None, ids[i + 1] if i + 1 < len(ids) else None
    return None


def _render(request, table, rid, part, args, flash=None, err=None, values=None):
    ref = records.ref_str(table, [rid])
    det = records_data.detail(A.current_user(request), ref)
    edit = None
    if det and det.get("one") and table in records_edit.EDIT_OPS:
        ev = records_edit.values(table, rid)
        if ev is not None:
            edit = {"table": table, "id": rid, "ops": records_edit.EDIT_OPS[table], "v": values if values is not None else ev}
    nav = _neighbors(part, args, table, rid)
    pos, total, prev, nxt = nav if nav else (None, 0, None, None)
    qs = urllib.parse.urlencode({"part": part, **args})

    def url(i):
        return f"/money/row/{table}/{i}?{qs}"
    return A.page(request, "_row_modal.html", det=det, edit=edit, ch=records_edit.choices(), err=err, flash=flash,
                  pos=pos, total=total, prev_url=url(prev) if prev else "", next_url=url(nxt) if nxt else "", has_nav=bool(nav),
                  edit_url="/money/row/edit?" + qs, edit_target="#txn-body", link=A.record_link, ref=ref)


@router.get("/money/row/{table}/{rid}")
def row_quick_view(request: Request, table: str, rid: int):
    denied = A.need_adult(request)
    if denied:
        return denied
    if not table.isidentifier() or not records.parse_ref(records.ref_str(table, [rid])):
        return PlainTextResponse("Not a record.", status_code=404)
    if table == "transactions":  # the Ledger's window: richer, and its edit does not leave the page
        return routes_ledger._modal(request, rid, {}, nav=False)
    return _render(request, table, rid, request.query_params.get("part", ""), _args(request.query_params))


@router.post("/money/row/edit")
async def row_edit(request: Request):
    """The record page's change forms, answered inside the window (the same `records_edit.edit`). A change makes the
    page behind the window refresh when it closes (`HX-Trigger: txn-saved`)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    table, op, rid = data.get("table", ""), data.get("op", ""), data.get("id", "")
    if op not in records_edit.EDIT_OPS.get(table, ()) or not str(rid).isdigit():
        return PlainTextResponse("Bad request", status_code=400)
    rid = int(rid)
    part, args = request.query_params.get("part", ""), _args(request.query_params)
    ok, msg, gone = await run_in_threadpool(records_edit.edit, A.current_user(request), table, op, rid, data)
    if gone and ok:
        r = A.page(request, "_row_modal.html", det=None, edit=None, flash=(True, msg), gone=True)
    elif ok or gone:
        r = await run_in_threadpool(_render, request, table, rid, part, args, (ok, msg))
    else:
        ev = records_edit.values(table, rid)
        vals = {**ev, **records_edit.typed(table, data)} if ev else None
        return await run_in_threadpool(_render, request, table, rid, part, args, None, msg, vals)
    r.headers["HX-Trigger"] = "txn-saved"
    return r
