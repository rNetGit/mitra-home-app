"""Add from a network scanner (data/scanner.py): /add/scanner. Adults only. Find the scanner on the home network (or type
its address), then Scan puts each page in the Inbox through the same checks as any file added there."""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

import scanner
from webapp import app as A

router = APIRouter()


def _go(request, ok, msg, found=None):
    s = A.session_of(request)
    if s is not None:
        s["scanner_flash"] = (ok, msg)
        if found is not None:
            s["scanner_found"] = found
    r = Response(status_code=200)
    r.headers["HX-Redirect"] = "/add/scanner"
    return r


@router.get("/add/scanner", response_class=HTMLResponse)
def scanner_page(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    s = A.session_of(request)
    return A.page(request, "add_scanner.html", active="inbox", sc=scanner.saved(),
                  found=(s or {}).get("scanner_found") or [], flash=s.pop("scanner_flash", None) if s else None)


@router.post("/add/scanner/find")
async def scanner_find(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    found = await run_in_threadpool(scanner.find)
    return _go(request, bool(found), (f"Found {len(found)} scanner{'s' if len(found) != 1 else ''}." if found else
                                      "No scanner answered. Is it on and on the same Wi-Fi? You can type its address below."), found)


@router.post("/add/scanner/use")
async def scanner_use(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    s = A.session_of(request)
    found = (s or {}).get("scanner_found") or []
    pick = data.get("pick", "")
    if pick.isdigit() and int(pick) < len(found):
        sc = found[int(pick)]
    else:
        host, _, port = (data.get("host") or "").strip().partition(":")
        sc = {"host": host, "port": int(port) if port.isdigit() else 80, "tls": data.get("tls") == "1"}
    try:
        ok, msg = await run_in_threadpool(scanner.choose, sc)
    except scanner.ScannerError as e:
        ok, msg = False, str(e)
    return _go(request, ok, msg)


@router.post("/add/scanner/scan")
async def scanner_scan(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    data = await A.form(request)
    sc = scanner.saved()
    if not sc:
        return _go(request, False, "Choose a scanner first.")
    ok, msg, _ = await run_in_threadpool(scanner.scan_to_inbox, sc, "feeder" if data.get("source") == "feeder" else "glass")
    return _go(request, ok, msg + (" Open Add to file it." if ok else ""))


@router.post("/add/scanner/forget")
async def scanner_forget(request: Request):
    denied = A.need_adult(request)
    if denied:
        return denied
    scanner.forget()
    return _go(request, True, "The scanner was forgotten.")
