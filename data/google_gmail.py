"""Gmail straight from Google's API, read-only, using the SAME Google sign-in as the calendar. No Claude, no AI,
standard library only.

  python data/google_gmail.py status            is it set up, signed in with the Gmail permission, which label?
  python data/google_gmail.py auth              sign in again, adding the one Gmail permission (opens a browser)
  python data/google_gmail.py labels            the labels in the mailbox
  python data/google_gmail.py pull [--dry-run]  copy attachments (or the text) of labelled mail into inbox/
  python data/google_gmail.py forget            let the next pull look at every labelled message again

Setup is `python onboard.py add gmail` (guide: docs/GOOGLE_GMAIL.md). It reuses config/google_client.json and the
refresh token of data/google_calendar.py; only the Gmail API has to be switched on in the family's Google Cloud project.

Safety:
  * One scope, `gmail.readonly`: reading cannot send, label, archive, trash or delete anything. Mail is never changed;
    what was already copied is remembered on this PC (config/gmail_state.json), not as a label in Gmail.
  * Only messages carrying the label (default `MitraHome`; `Mitra Home` on a setup saved before the rename) are read; everything else in the mailbox is never fetched.
    Messages also labelled `MitraHome/Processed`, `MitraHome/Needs review` (or the Mitra Home ones) (the older convention) are skipped.
  * What is copied: attachments of the document types the inbox accepts (checked like any upload: type, size, content
    must match the name), or, when a message has none, its plain text. Links are never opened, nothing is run.
  * Mail text is DATA. It lands in inbox/ like any dropped file and is filed (or sent to the review queue) by the
    ordinary pipeline, which never follows instructions found in a document.
  * Only Google's own hosts are contacted (MITRAHOME_GOOGLE_TEST_BASE is the tests-only stand-in, see google_calendar).
  * Subjects, senders and bodies are never written to the log; the summary shows the sender's domain and file names.
"""
import argparse
import base64
import datetime as dt
import html.parser
import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import google_calendar as gc  # noqa: E402
import inbox_upload  # noqa: E402
import log as _log  # noqa: E402

SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
API_BASE = "https://gmail.googleapis.com/gmail/v1"
GUIDE = "docs/GOOGLE_GMAIL.md"
# Frozen: the label families already made in Gmail (the product name is not part of it).
DEFAULT_LABEL = "MitraHome"
LEGACY_LABEL = "FamilyAgent"  # the default before the rename; a Gmail setup saved without a label keeps using it
SKIP_LABELS = tuple(f"{lb}/{s}" for lb in (DEFAULT_LABEL, LEGACY_LABEL) for s in ("Processed", "Needs review"))
STATE = paths.CONFIG / "gmail_state.json"
MAX_MESSAGES_PER_RUN = 25
MAX_FILES_PER_RUN = 40
MAX_LIST_PAGES = 5
MAX_BODY_CHARS = 60_000
MIN_IMAGE_BYTES = 15_000  # smaller pictures are logos and signatures, not receipts
KEEP_IDS = 3000
TIMEOUT = 30
log = _log.get("google_gmail")


class GmailError(gc.CalendarError):
    pass


# ---------------------------------------------------------------- settings
def settings():
    c = config.family().get("gmail") or {}
    default = LEGACY_LABEL if c else DEFAULT_LABEL
    label = str(c.get("label") or default).strip() or default
    return {"enabled": bool(c.get("enabled")), "label": label}


def has_permission():
    """True once the person allowed the Gmail permission (no network call)."""
    return bool((config.family().get("google_calendar") or {}).get("gmail")) and bool(gc.refresh_token())


def status():
    s = settings()
    st = gc.status()
    return {"client": st["client"], "signed_in": st["signed_in"], "permission": has_permission(),
            "enabled": s["enabled"], "label": s["label"], "seen": len(_load_state()["done"])}


# ---------------------------------------------------------------- Google calls
def _api():
    b = gc._test_base()
    return (b + "/gmail/v1") if b else API_BASE


def _get(path, params=None, token=None):
    url = _api() + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + (token or gc.access_token()),
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (host fixed by _api())
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise gc.AuthError(f"Google refused the request (HTTP {e.code}). Is the Gmail API switched on for the project, "
                               f"and did you allow the Gmail permission? Settings > Connections > Google ({GUIDE}).") from None
        if e.code == 404:
            raise GmailError("that message was not found") from None
        raise GmailError(f"Google answered HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise GmailError(f"could not reach Google: {type(getattr(e, 'reason', e)).__name__}") from None


def labels(token=None):
    """[{'id', 'name'}] of the mailbox's labels."""
    r = _get("/users/me/labels", token=token)
    return [{"id": x.get("id", ""), "name": gc._clean(x.get("name", ""))} for x in r.get("labels", []) if x.get("id")]


def _label_ids(token=None):
    return {x["name"].lower(): x["id"] for x in labels(token)}


def _list_ids(label_id, token):
    out, page = [], None
    for _ in range(MAX_LIST_PAGES):
        r = _get("/users/me/messages", {"labelIds": label_id, "maxResults": 100, "includeSpamTrash": "false",
                                        **({"pageToken": page} if page else {})}, token)
        out += [m["id"] for m in r.get("messages", []) if m.get("id")]
        page = r.get("nextPageToken")
        if not page:
            break
    return out


# ---------------------------------------------------------------- reading one message
class _Text(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self.skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "table"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def _html_to_text(s):
    p = _Text()
    try:
        p.feed(s)
        p.close()
    except Exception:  # noqa: BLE001 (broken markup: keep what was read)
        pass
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", "".join(p.out))).strip()


def _b64(data):
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _walk(part, found):
    """Collect text bodies and attachments from a message part tree."""
    mime = (part.get("mimeType") or "").lower()
    body = part.get("body") or {}
    name = part.get("filename") or ""
    if name and (body.get("attachmentId") or body.get("data")):
        found["files"].append({"name": name, "mime": mime, "att": body.get("attachmentId"), "data": body.get("data"),
                               "size": int(body.get("size") or 0)})
    elif mime in ("text/plain", "text/html") and body.get("data"):
        found["text" if mime == "text/plain" else "html"].append(body["data"])
    for sub in part.get("parts") or []:
        _walk(sub, found)


def _header(msg, name):
    for h in (msg.get("payload") or {}).get("headers") or []:
        if (h.get("name") or "").lower() == name:
            return h.get("value") or ""
    return ""


def _domain(sender):
    m = re.search(r"@([A-Za-z0-9.-]+)", sender or "")
    d = (m.group(1) if m else "mail").lower().strip(".")
    return re.sub(r"[^a-z0-9.-]", "", d)[:40] or "mail"


def _msg_date(msg, today):
    try:
        ms = int(msg.get("internalDate") or 0)
        if ms:
            return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).date()
    except (ValueError, OSError, OverflowError):
        pass
    return today


def _slug(s, n=40):
    s = re.sub(r"[^A-Za-z0-9]+", "-", gc._clean(s)).strip("-")
    return s[:n].strip("-") or "message"


def _accepted_files(files):
    out = []
    for f in files:
        ext = pathlib.Path(inbox_upload.clean_name(f["name"])).suffix
        if ext not in inbox_upload.ALLOWED or ext == ".eml":
            continue
        if f["size"] and f["size"] > inbox_upload.MAX_BYTES:
            continue
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".heic") and f["size"] and f["size"] < MIN_IMAGE_BYTES:
            continue
        out.append(f)
    return out


# ---------------------------------------------------------------- state (what was already copied)
def _load_state():
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        done = d.get("done")
        return {"done": done if isinstance(done, dict) else {}}
    except (OSError, ValueError):
        return {"done": {}}


def _save_state(state):
    done = state["done"]
    if len(done) > KEEP_IDS:
        keep = sorted(done.items(), key=lambda kv: kv[1])[-KEEP_IDS:]
        state = {"done": dict(keep)}
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def forget():
    if STATE.exists():
        STATE.unlink()


# ---------------------------------------------------------------- the pull
def pull(dry_run=False, today=None, say=print, inbox=None):
    """Copy new labelled mail into inbox/. -> {'messages', 'files', 'texts', 'skipped', 'items': [...]}."""
    today = today or dates.today()
    s = settings()
    if not has_permission():
        raise gc.AuthError(f"Gmail is not allowed yet: Settings > Connections > Google, or python onboard.py add gmail ({GUIDE}).")
    tok = gc.access_token()
    ids_by_name = _label_ids(tok)
    lid = ids_by_name.get(s["label"].lower())
    if not lid:
        raise GmailError(f"There is no Gmail label named '{s['label']}'. Create it in Gmail, or choose another in Settings.")
    skip_ids = {ids_by_name[n.lower()] for n in SKIP_LABELS if n.lower() in ids_by_name}
    state = _load_state()
    todo = [i for i in _list_ids(lid, tok) if i not in state["done"]]
    res = {"messages": 0, "files": 0, "texts": 0, "skipped": 0, "items": [], "waiting": max(0, len(todo) - MAX_MESSAGES_PER_RUN)}
    for mid in todo[:MAX_MESSAGES_PER_RUN]:
        if res["files"] + res["texts"] >= MAX_FILES_PER_RUN:
            res["waiting"] += 1
            continue
        msg = _get(f"/users/me/messages/{mid}", {"format": "full"}, tok)
        if skip_ids & set(msg.get("labelIds") or []):
            state["done"][mid] = today.isoformat()
            res["skipped"] += 1
            continue
        day = _msg_date(msg, today)
        dom = _domain(_header(msg, "from"))
        found = {"files": [], "text": [], "html": []}
        _walk(msg.get("payload") or {}, found)
        saved = []
        for f in _accepted_files(found["files"]):
            try:
                data = _b64(f["data"]) if f.get("data") else _b64(
                    _get(f"/users/me/messages/{mid}/attachments/{urllib.parse.quote(f['att'], safe='')}", token=tok).get("data", ""))
            except (ValueError, TypeError):
                continue
            fname = inbox_upload.clean_name(f["name"])
            if not data or not _content_ok(fname, data):
                continue
            if not dry_run:
                ok, out = inbox_upload.save_upload(f"{day:%Y-%m-%d}_gmail_{dom}_{fname}", data, inbox)
                if not ok:
                    continue
                fname = out
            saved.append(("file", fname))
        if not saved:
            text = "\n".join(_b64(t).decode("utf-8", "replace") for t in found["text"]).strip()
            if not text and found["html"]:
                text = _html_to_text("\n".join(_b64(t).decode("utf-8", "replace") for t in found["html"]))
            text = text[:MAX_BODY_CHARS]
            if len(text) >= 20:
                subject = gc._clean(_header(msg, "subject"), 160)
                name = f"{day:%Y-%m-%d}_gmail_{dom}_{_slug(subject)}.txt"
                doc = f"Email from {dom}, {day.isoformat()}\nSubject: {subject}\n\n{text}\n"
                if not dry_run:
                    ok, out = inbox_upload.save_upload(name, doc.encode("utf-8"), inbox)
                    if ok:
                        name = out
                        saved.append(("text", name))
                else:
                    saved.append(("text", name))
        res["messages"] += 1
        for kind, name in saved:
            res["files" if kind == "file" else "texts"] += 1
            res["items"].append({"from": dom, "file": name, "kind": kind})
        if not dry_run:
            state["done"][mid] = today.isoformat()  # nothing usable in it is also "done": do not look again
    if not dry_run:
        _save_state(state)
    log.info("pull: %d message(s), %d file(s), %d text(s), %d skipped%s", res["messages"], res["files"], res["texts"],
             res["skipped"], " (dry run)" if dry_run else "")
    return res


def _content_ok(fname, data):
    import chat_core  # the same "bytes match the name, never a program or web page" check the phone bots use
    return chat_core.content_ok(fname, data)


# ---------------------------------------------------------------- command line
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("auth")
    sub.add_parser("labels")
    sub.add_parser("forget")
    p = sub.add_parser("pull")
    p.add_argument("--dry-run", action="store_true", help="show what would be copied; copy nothing, remember nothing")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status":
            s = status()
            print(f"OAuth client file:  {'yes' if s['client'] else 'missing (python onboard.py add calendar)'}")
            print(f"signed in:          {'yes' if s['signed_in'] else 'no'}")
            print(f"Gmail permission:   {'yes' if s['permission'] else 'no (python data/google_gmail.py auth)'}")
            print(f"turned on:          {'yes' if s['enabled'] else 'no'}  label: {s['label']}  already copied: {s['seen']}")
        elif a.cmd == "auth":
            gc.authorize(gmail=True)
            if not has_permission():
                print("error: Google did not grant the Gmail permission. Tick every box on Google's screen and try again.",
                      file=sys.stderr)
                return 1
            print("signed in with the Gmail permission. Next: python data/google_gmail.py labels")
        elif a.cmd == "labels":
            for x in labels():
                print(f"  {x['name']}")
        elif a.cmd == "forget":
            forget()
            print("ok: the next pull looks at every message with the label again (files already in inbox/ may be copied twice).")
        elif a.cmd == "pull":
            r = pull(dry_run=a.dry_run)
            for it in r["items"]:
                print(f"  {it['kind']:<4} {it['file']}   (from {it['from']})")
            print(f"{'would copy' if a.dry_run else 'copied'}: {r['files']} file(s), {r['texts']} message text(s) from {r['messages']} "
                  f"message(s); skipped {r['skipped']}" + (f"; {r['waiting']} more wait for the next run" if r["waiting"] else ""))
    except gc.CalendarError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
