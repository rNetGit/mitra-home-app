"""Money > Ledger quick view: one transaction in a window over the list, with Previous / Next through the filtered list and the
category / type edit in place, so a person can go down the list without leaving the page. Names that live in app.py are read
through `A` when a request comes in, so a test can still patch app.<name>."""
import pathlib
import sys
import urllib.parse

from fastapi import APIRouter
from fastapi import Request
from starlette.concurrency import run_in_threadpool

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import dates  # noqa: E402
import finance_data  # noqa: E402
import ledger_data  # noqa: E402
import records_data  # noqa: E402
from webapp import app as A  # noqa: E402

router = APIRouter()


def _filters(params):
    """The Ledger's own filter keys from a query string or a form, each cut to a sane length."""
    return {k: str(params.get(k) or "")[:100] for k in ledger_data.KEYS if params.get(k)}


def _modal(request, txn_id, filters, flash=None, nav=True):
    today = dates.today()
    try:
        con = finance_data._con()
    except Exception:  # noqa: BLE001 (no database yet: nothing to show)
        return A.page(request, "_txn_modal.html", t=None, flash=None)
    try:
        t = ledger_data.txn_detail(con, txn_id)
        if t is None:
            return A.page(request, "_txn_modal.html", t=None, flash=flash)
        accounts, cats, people = ledger_data.account_list(con), ledger_data.categories(con), ledger_data.members(con)
        f = ledger_data.parse(filters, today, accounts, cats, people)
        pos, total, prev, nxt = ledger_data.neighbors(con, f, t["id"]) if nav else (None, 0, None, None)
    finally:
        con.close()
    t["date_text"] = finance_data.short_date(t["date"], today)
    det = records_data.detail(A.current_user(request), f"transactions:{t['id']}")
    one = (det or {}).get("one") or {}
    return A.page(request, "_txn_modal.html", t=t, pos=pos, total=total, prev=prev, nxt=nxt, filters=filters,
                  qs=urllib.parse.urlencode(filters), flash=flash, nav=nav, cats=cats, types=ledger_data.TYPES,
                  paper=one.get("paper"), history=one.get("history") or [], link=A.record_link)


@router.get("/money/txn/{txn_id}")
def ledger_quick_view(request: Request, txn_id: int):
    denied = A.need_adult(request)
    if denied:
        return denied
    return _modal(request, txn_id, _filters(request.query_params))


@router.post("/money/txn/{txn_id}")
async def ledger_quick_save(request: Request, txn_id: int):
    """Save the category / type from the window, then show the same line again with the result (`HX-Trigger: txn-saved`
    makes the page behind it refresh when the window closes)."""
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    ok, msg = await run_in_threadpool(A.records_edit.ea.txn_update, A.current_user(request), txn_id, data.get("category", ""),
                                      data.get("txn_type", ""), bool(data.get("similar")))
    r = await run_in_threadpool(_modal, request, txn_id, _filters(data), (ok, msg))
    if ok:
        r.headers["HX-Trigger"] = "txn-saved"
    return r
