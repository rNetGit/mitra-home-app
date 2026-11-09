"""A mailbox made for Mitra Home, read-only over IMAP: forwarded bills, statements, school letters and receipts go to the
inbox, the same way the Gmail label does, with any mail provider. No AI here, nothing ever changed in the mailbox.

  python data/mail_folder.py status            the settings (never the password) and what was read last
  python data/mail_folder.py test              sign in and count the messages in the folder
  python data/mail_folder.py pull [--dry-run]  copy new mail into inbox/
  python data/mail_folder.py forget            forget the app password and what was read

Use a mailbox made only for Mitra Home (forward to it from your main mail), signed in with an APP PASSWORD the mail
provider makes for one app (Gmail, iCloud, Outlook.com, Yahoo and Fastmail all offer them), never the account's own
password. Settings in config/family.json `mail_folder` {enabled, address, host, port, folder}; the app password in
config/secrets.env as MAIL_SECRET (write-only: typed only on this PC, never shown again). Docs: docs/MAIL_FOLDER.md.

Safety: IMAP over TLS only (certificate checked), the server must be a public host, the folder is opened read-only
(EXAMINE) and messages are fetched with BODY.PEEK (they stay unread, nothing is moved, flagged or deleted). Attachments
pass the same checks as the Gmail label (inbox types, size, the bytes match the name); a message without one becomes a
text file. Message ids already copied are kept in config/mail_folder_state.json (per folder and UIDVALIDITY).
"""
import argparse
import datetime as dt
import email
import email.policy
import email.utils
import html.parser
import imaplib
import json
import pathlib
import re
import ssl
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dates  # noqa: E402
import inbox_upload  # noqa: E402
import log as _log  # noqa: E402
import paths  # noqa: E402

log = _log.get("mail_folder")
MAIL_SECRET = "MITRAHOME_MAIL_APP_PASSWORD"
STATE = paths.CONFIG / "mail_folder_state.json"
GUIDE = "docs/MAIL_FOLDER.md"
TIMEOUT = 30
FIRST_DAYS = 30  # the first read looks back this far
MAX_MESSAGES_PER_RUN = 25
MAX_FILES_PER_RUN = 40
MAX_MESSAGE_BYTES = 30_000_000
MAX_BODY_CHARS = 60_000
MIN_IMAGE_BYTES = 15_000
KEEP_IDS = 3000
# the IMAP server for common providers, by the address's domain
PROVIDERS = {"gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com", "icloud.com": "imap.mail.me.com",
             "me.com": "imap.mail.me.com", "mac.com": "imap.mail.me.com", "outlook.com": "outlook.office365.com",
             "hotmail.com": "outlook.office365.com", "live.com": "outlook.office365.com", "msn.com": "outlook.office365.com",
             "yahoo.com": "imap.mail.yahoo.com", "ymail.com": "imap.mail.yahoo.com", "aol.com": "imap.aol.com",
             "fastmail.com": "imap.fastmail.com", "zoho.com": "imap.zoho.com", "gmx.com": "imap.gmx.com",
             "proton.me": "", "protonmail.com": ""}
ADDRESS = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,}$")
HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}$")


class MailError(Exception):
    pass


# ---- settings ---------------------------------------------------------------------------------------------------------
def settings(cfg=None):
    m = (cfg if cfg is not None else config.family()).get("mail_folder") or {}
    try:
        port = int(m.get("port") or 993)
    except (TypeError, ValueError):
        port = 993
    return {"enabled": bool(m.get("enabled")), "address": str(m.get("address") or ""), "host": str(m.get("host") or ""),
            "port": port, "folder": str(m.get("folder") or "INBOX")}


def has_password():
    return bool(config.read_secret(MAIL_SECRET))


def guess_host(address):
    dom = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    return PROVIDERS.get(dom, f"imap.{dom}" if dom else "")


def clean(address, host, port, folder):
    """Checked settings or MailError: an e-mail address, a host name, 993 or 143-free ports only, a folder name."""
    address = str(address or "").strip()
    if not ADDRESS.match(address):
        raise MailError("type the mailbox's e-mail address")
    host = str(host or "").strip().lower() or guess_host(address)
    if not host:
        raise MailError("this provider has no IMAP for app passwords (Proton needs its Bridge); use another mailbox")
    if not HOST.match(host) or "." not in host:
        raise MailError("type the mail server's name, for example imap.gmail.com")
    try:
        port = int(port or 993)
    except (TypeError, ValueError):
        raise MailError("the port is a number, usually 993") from None
    if port == 143 or not 1 <= port <= 65535:
        raise MailError("use the secure port (993): plain IMAP is not used")
    folder = " ".join(str(folder or "INBOX").split())[:100] or "INBOX"
    if re.search(r'[\x00-\x1f"\\]', folder):
        raise MailError("that folder name has characters this app does not send")
    return {"address": address, "host": host, "port": port, "folder": folder}


def status():
    s = settings()
    st = _load_state()
    return {**s, "password": has_password(), "last_pull": st.get("last_pull", ""), "last_error": st.get("last_error", "")}


# ---- the connection ---------------------------------------------------------------------------------------------------
def _public(host):
    import lookups
    return lookups._public_host(host)


def _connect(s, password):
    """A signed-in IMAP4_SSL connection (certificate checked). Tests replace imaplib.IMAP4_SSL."""
    if not _public(s["host"]):
        raise MailError(f"{s['host']} is not a mail server on the public internet")
    try:
        con = imaplib.IMAP4_SSL(s["host"], s["port"], ssl_context=ssl.create_default_context(), timeout=TIMEOUT)
    except (OSError, ssl.SSLError, imaplib.IMAP4.error) as e:
        raise MailError(f"{s['host']} could not be reached ({str(e)[:80]})") from None
    try:
        con.login(s["address"], password)
    except imaplib.IMAP4.error:
        try:
            con.logout()
        except Exception:  # noqa: BLE001
            pass
        raise MailError("the mailbox refused the sign-in: check the address and make a new app password "
                        f"(not the account's own password). {GUIDE} has the steps per provider.") from None
    return con


def _examine(con, folder):
    """Open the folder read-only. -> (uidvalidity, message count)."""
    typ, data = con.select(f'"{folder}"', readonly=True)
    if typ != "OK":
        raise MailError(f"there is no folder named {folder} in that mailbox")
    count = int((data[0] or b"0").decode() or 0) if data else 0
    typ, uv = con.response("UIDVALIDITY")
    uidvalidity = (uv[0].decode() if uv and uv[0] else "0")
    return uidvalidity, count


def test():
    s = settings()
    password = config.read_secret(MAIL_SECRET)
    if not s["address"] or not password:
        raise MailError("set the mailbox and its app password first (Settings > Connections > Mail folder)")
    con = _connect(s, password)
    try:
        _uv, count = _examine(con, s["folder"])
    finally:
        _bye(con)
    return count


def _bye(con):
    for step in (con.close, con.logout):
        try:
            step()
        except Exception:  # noqa: BLE001 (closing is best effort)
            pass


# ---- state ------------------------------------------------------------------------------------------------------------
def _load_state():
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_state(state):
    done = state.get("done") or {}
    if len(done) > KEEP_IDS:
        state["done"] = dict(sorted(done.items(), key=lambda kv: kv[1])[-KEEP_IDS:])
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")


def forget():
    """Forget the app password and what was read; the settings (address, server) stay, switched off."""
    config.write_secret(MAIL_SECRET, "")
    if STATE.exists():
        STATE.unlink()
    with config.family_edit() as cfg:
        cfg["mail_folder"] = {**(cfg.get("mail_folder") or {}), "enabled": False}


# ---- reading a message ------------------------------------------------------------------------------------------------
def _domain(sender):
    m = re.search(r"@([A-Za-z0-9.-]+)", sender or "")
    d = (m.group(1) if m else "mail").lower().strip(".")
    return re.sub(r"[^a-z0-9.-]", "", d)[:40] or "mail"


def _slug(s, n=40):
    s = re.sub(r"[^A-Za-z0-9]+", "-", " ".join(str(s or "").split())).strip("-")
    return s[:n].strip("-") or "message"


def _day(msg, today):
    try:
        d = email.utils.parsedate_to_datetime(str(msg.get("date") or ""))
        return d.date() if d else today
    except (TypeError, ValueError, IndexError):
        return today


def _parts(msg):
    """(attachments [(name, bytes)], plain texts, html texts) of a parsed message."""
    files, text, html = [], [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        name = part.get_filename()
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True) or b""
        except (ValueError, TypeError):
            continue
        if name:
            files.append((str(name), payload))
        elif ctype == "text/plain":
            text.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
        elif ctype == "text/html":
            html.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    return files, text, html


class _Text(html.parser.HTMLParser):
    """Visible text of an HTML mail (scripts and styles dropped)."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
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


def _accept(name, data):
    ext = pathlib.Path(inbox_upload.clean_name(name)).suffix
    if ext not in inbox_upload.ALLOWED or ext == ".eml" or not data or len(data) > inbox_upload.MAX_BYTES:
        return False
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff", ".heic") and len(data) < MIN_IMAGE_BYTES:
        return False
    return inbox_upload.content_ok(inbox_upload.clean_name(name), data)  # bytes match the name, never a program


# ---- the pull ---------------------------------------------------------------------------------------------------------
def pull(dry_run=False, today=None, inbox=None):
    """Copy new mail of the folder into inbox/. -> {'messages','files','texts','waiting','items'}."""
    today = today or dates.today()
    s = settings()
    password = config.read_secret(MAIL_SECRET)
    if not s["address"] or not password:
        raise MailError("set the mailbox and its app password first (Settings > Connections > Mail folder)")
    state = _load_state()
    con = _connect(s, password)
    try:
        uv, _count = _examine(con, s["folder"])
        key = f"{s['address'].lower()}|{s['folder']}|{uv}"
        if state.get("key") != key:  # another mailbox, folder or a rebuilt folder: ids mean nothing any more
            state = {"key": key, "done": {}}
        since = (today - dt.timedelta(days=FIRST_DAYS)).strftime("%d-%b-%Y")
        typ, data = con.uid("SEARCH", None, "SINCE", since)
        uids = [u.decode() for u in (data[0].split() if typ == "OK" and data and data[0] else [])]
        todo = [u for u in uids if u not in state["done"]]
        res = {"messages": 0, "files": 0, "texts": 0, "items": [], "waiting": max(0, len(todo) - MAX_MESSAGES_PER_RUN)}
        for uid in todo[:MAX_MESSAGES_PER_RUN]:
            if res["files"] + res["texts"] >= MAX_FILES_PER_RUN:
                res["waiting"] += 1
                continue
            typ, size = con.uid("FETCH", uid, "(RFC822.SIZE)")
            m = re.search(rb"RFC822\.SIZE (\d+)", (size[0] if size and isinstance(size[0], bytes) else b"") or b"")
            if m and int(m.group(1)) > MAX_MESSAGE_BYTES:
                state["done"][uid] = today.isoformat()
                continue
            typ, got = con.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK: the message stays unread
            raw = next((x[1] for x in got or [] if isinstance(x, tuple) and len(x) > 1), None) if typ == "OK" else None
            if not raw:
                continue
            msg = email.message_from_bytes(raw, policy=email.policy.default)
            day, dom = _day(msg, today), _domain(str(msg.get("from") or ""))
            files, text, html = _parts(msg)
            saved = []
            for name, payload in files:
                if not _accept(name, payload):
                    continue
                fname = inbox_upload.clean_name(name)
                if not dry_run:
                    ok, out = inbox_upload.save_upload(f"{day:%Y-%m-%d}_mail_{dom}_{fname}", payload, inbox)
                    if not ok:
                        continue
                    fname = out
                saved.append(("file", fname))
            if not saved:
                body = "\n".join(text).strip()
                if not body and html:
                    body = _html_to_text("\n".join(html))
                body = body[:MAX_BODY_CHARS]
                if len(body) >= 20:
                    subject = " ".join(str(msg.get("subject") or "").split())[:160]
                    name = f"{day:%Y-%m-%d}_mail_{dom}_{_slug(subject)}.txt"
                    doc = f"Email from {dom}, {day.isoformat()}\nSubject: {subject}\n\n{body}\n"
                    if not dry_run:
                        ok, out = inbox_upload.save_upload(name, doc.encode("utf-8"), inbox)
                        if ok:
                            saved.append(("text", out))
                    else:
                        saved.append(("text", name))
            res["messages"] += 1
            for kind, name in saved:
                res["files" if kind == "file" else "texts"] += 1
                res["items"].append({"from": dom, "file": name, "kind": kind})
            if not dry_run:
                state["done"][uid] = today.isoformat()  # nothing usable in it is also "done"
    finally:
        _bye(con)
    if not dry_run:
        state["last_pull"] = dt.datetime.now().isoformat(timespec="seconds")
        state["last_error"] = ""
        _save_state(state)
    log.info("pull: %d message(s), %d file(s), %d text(s)%s", res["messages"], res["files"], res["texts"],
             " (dry run)" if dry_run else "")
    return res


def note_error(text):
    st = _load_state()
    st["last_error"] = str(text)[:300]
    _save_state(st)


# ---- command line -----------------------------------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("test")
    sub.add_parser("forget")
    p = sub.add_parser("pull")
    p.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        st = status()
        print(f"Mail folder: {'on' if st['enabled'] else 'off'} · {st['address'] or '(no mailbox)'} · {st['host']}:{st['port']} "
              f"· folder {st['folder']} · app password {'set' if st['password'] else 'not set'} · last read {st['last_pull'] or 'never'}"
              + (f" · last problem: {st['last_error']}" if st["last_error"] else ""))
        return 0
    if a.cmd == "forget":
        forget()
        print("Forgot the app password and what was read; the mail folder is off.")
        return 0
    try:
        if a.cmd == "test":
            print(f"Signed in: {test()} message(s) in the folder. Nothing was changed.")
            return 0
        if not settings()["enabled"] and not a.dry_run:
            print("The mail folder is off (Settings > Connections > Mail folder).")
            return 0
        r = pull(dry_run=a.dry_run)
    except MailError as e:
        if a.cmd == "pull" and not a.dry_run:
            note_error(e)
        print(f"Mail folder: {e}")
        return 1
    print(f"{r['messages']} message(s): {r['files']} file(s) and {r['texts']} text(s) to the inbox"
          + (f"; {r['waiting']} wait for the next run" if r["waiting"] else "") + (" (dry run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
