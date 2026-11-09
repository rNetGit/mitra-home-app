"""Telegram bot for the family (adapter over data/chat_core.py). Standard library only, no extra package.

  python data/chat_telegram.py check     is the token set and valid? prints the bot's @name (never the token)
  python data/chat_telegram.py run       answer messages until stopped (Ctrl+C); the logon task runs this
  python data/chat_telegram.py once      fetch and answer one batch, then exit (testing)

Setup: `python onboard.py add telegram` (see docs/CHAT.md). The token lives in config/secrets.env as
MITRAHOME_TELEGRAM_TOKEN and is never printed or logged.

Long polling: this PC asks Telegram for new messages; nothing on this PC is reachable from the internet, no router
or webhook setup. Telegram bot chats are NOT end-to-end encrypted: Telegram's servers see the messages and replies.
That is why children never get money information and adults get amounts only in a private chat (chat_core rules).
Text commands, plus photos and documents (PDF, images, spreadsheets) from adults in a private chat, which go to
inbox/ through chat_core.accept_file. Captions are never read. Voice, video and stickers are ignored.
"""
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import chat_core  # noqa: E402
import log as _log  # noqa: E402

TOKEN_NAME = "MITRAHOME_TELEGRAM_TOKEN"
API_NAME = "MITRAHOME_TELEGRAM_API"  # tests only: a local stand-in for api.telegram.org
OFFICIAL = "https://api.telegram.org"
STATE = paths.LOGS / "chat_telegram_state.json"
TOKEN_RE = re.compile(r"^\d{5,12}:[A-Za-z0-9_-]{30,50}$")
POLL_SECONDS = 50
MAX_REPLY = 4000  # Telegram's limit is 4096 characters
log = _log.get("chat_telegram")


class TelegramError(Exception):
    pass


def _secret(name):
    import config
    return config.read_secret(name).strip()


def token():
    return _secret(TOKEN_NAME)


def valid_token_shape(t):
    return bool(TOKEN_RE.match(t or ""))


def api_base():
    """api.telegram.org, or for tests a stand-in on this PC; anything else is refused so the token never goes elsewhere."""
    b = (_secret(API_NAME) or OFFICIAL).rstrip("/")
    if b == OFFICIAL or re.match(r"^http://127\.0\.0\.1:\d+$", b):
        return b
    raise TelegramError(f"{API_NAME} must be {OFFICIAL} (or http://127.0.0.1:PORT for tests)")


def _scrub(text, tok):
    return str(text).replace(tok, "***") if tok else str(text)


def call(method, tok, http_timeout=POLL_SECONDS + 10, **params):
    url = f"{api_base()}/bot{tok}/{method}"
    req = urllib.request.Request(url, data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=http_timeout) as r:  # noqa: S310 (scheme checked in api_base)
            body = json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        raise TelegramError(f"{method}: HTTP {e.code} {body.get('description', '')}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TelegramError(_scrub(f"{method}: {getattr(e, 'reason', e)}", tok)) from None
    if not body.get("ok"):
        raise TelegramError(f"{method}: {body.get('description', 'not ok')}")
    return body.get("result")


def check(tok=None):
    """(ok, message). Checks the shape locally, then asks Telegram who the bot is."""
    tok = tok if tok is not None else token()
    if not tok:
        return False, "No bot token saved yet: Settings > Connections > Phone bot."
    if not valid_token_shape(tok):
        return False, "that does not look like a bot token from @BotFather (digits, a colon, then letters)"
    try:
        me = call("getMe", tok, http_timeout=15)
    except TelegramError as e:
        return False, str(e)
    if not me.get("is_bot"):
        return False, "token does not belong to a bot"
    return True, f"@{me.get('username')}"


def _load_offset():
    try:
        return int(json.loads(STATE.read_text(encoding="utf-8")).get("offset", 0))
    except (OSError, ValueError):
        return 0


def _save_offset(off):
    STATE.parent.mkdir(exist_ok=True)
    tmp = STATE.with_name(STATE.name + ".tmp")
    tmp.write_text(json.dumps({"offset": off}), encoding="utf-8")
    tmp.replace(STATE)


def download(tok, file_id):
    """Bytes of a file someone sent the bot (getFile, then the file URL on the same host)."""
    info = call("getFile", tok, http_timeout=20, file_id=file_id)
    path = (info or {}).get("file_path") or ""
    if not path or ".." in path:
        raise TelegramError("getFile: no usable file path")
    req = urllib.request.Request(f"{api_base()}/file/bot{tok}/{path}")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 (scheme checked in api_base)
            return r.read(26 * 1024 * 1024)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise TelegramError(_scrub(f"download: {getattr(e, 'reason', e)}", tok)) from None


def file_of(m):
    """(file_id, file name, size) of a photo or document in a message, else None."""
    if m.get("document"):
        d = m["document"]
        return d.get("file_id"), d.get("file_name") or "document", d.get("file_size")
    if m.get("photo"):
        big = max(m["photo"], key=lambda x: x.get("file_size") or x.get("width", 0) * x.get("height", 0))
        return big.get("file_id"), "photo.jpg", big.get("file_size")
    return None


def file_reply(update, tok, db=None, now=None):
    """(chat_id, reply) for a photo/document update, or None."""
    m = update.get("message") or {}
    f = file_of(m)
    frm = m.get("from") or {}
    if not f or not f[0] or frm.get("is_bot") or "id" not in frm:
        return None
    chat = m.get("chat") or {}

    def fetch():
        try:
            return download(tok, f[0])
        except TelegramError as e:
            log.warning("telegram: %s", e)
            return b""
    r = chat_core.accept_file("telegram", str(frm["id"]), f[1], size=f[2], private=chat.get("type") == "private",
                              db=db, now=now, fetch=fetch)
    return None if r is None else (chat["id"], r)


def reply_for(update, db=None, now=None):
    """(chat_id, reply text) for one update, or None when the bot stays silent."""
    m = update.get("message")
    if not m or not isinstance(m.get("text"), str):
        return None  # edits, photos, joins, channel posts...
    frm = m.get("from") or {}
    if frm.get("is_bot") or "id" not in frm:
        return None
    chat = m.get("chat") or {}
    private = chat.get("type") == "private"
    text = m["text"]
    if not private and not text.startswith("/"):
        return None  # in groups only commands are for the bot
    r = chat_core.handle("telegram", str(frm["id"]), text, private=private, db=db, now=now)
    if r is None:
        return None
    return chat["id"], r[:MAX_REPLY]


def once(tok, offset, timeout=POLL_SECONDS, db=None):
    """Fetch one batch, answer it, return the next offset. A reply that fails to send is logged and skipped."""
    ups = call("getUpdates", tok, http_timeout=timeout + 10, offset=offset, timeout=timeout,
               allowed_updates=["message"]) or []
    for u in ups:
        offset = max(offset, int(u["update_id"]) + 1)
        try:
            out = reply_for(u, db=db) or file_reply(u, tok, db=db)
        except Exception as e:  # one bad message must not stop the bot
            log.error("telegram: handling update failed: %s", type(e).__name__)
            out = None
        if out:
            try:
                call("sendMessage", tok, http_timeout=20, chat_id=out[0], text=out[1], disable_web_page_preview=True)
            except TelegramError as e:
                log.warning("telegram: send failed: %s", e)
        _save_offset(offset)
    return offset


def run(stop=None):
    tok = token()
    ok, msg = check(tok)
    if not ok:
        print(msg, file=sys.stderr)
        return 2
    call("deleteWebhook", tok, http_timeout=15)  # long polling does not work while a webhook is set
    print(f"Telegram bot {msg} running. Ctrl+C to stop.")
    log.info("telegram: bot %s started", msg)
    offset, wait = _load_offset(), 1
    pidf, stopf = paths.LOGS / "telegram_bot.pid", paths.LOGS / "telegram_bot.stop"
    pidf.parent.mkdir(exist_ok=True)
    stopf.unlink(missing_ok=True)  # the dashboard's Stop button leaves this file; a fresh start clears it
    try:
        while not ((stop and stop()) or stopf.exists()):
            pidf.write_text(str(os.getpid()), encoding="utf-8")  # the file's age tells the dashboard the bot is alive
            try:
                offset = once(tok, offset)
                wait = 1
            except TelegramError as e:
                log.warning("telegram: %s (retry in %ss)", e, wait)
                time.sleep(wait)
                wait = min(wait * 2, 300)
            except KeyboardInterrupt:
                break
    finally:
        pidf.unlink(missing_ok=True)
        stopf.unlink(missing_ok=True)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else ""
    if cmd == "check":
        ok, msg = check()
        print(("OK " if ok else "Not working: ") + msg)
        return 0 if ok else 1
    if cmd == "once":
        tok = token()
        ok, msg = check(tok)
        if not ok:
            print(msg, file=sys.stderr)
            return 2
        _save_offset(once(tok, _load_offset(), timeout=0))
        return 0
    if cmd == "run":
        _log.use("telegram")  # runs for days: a log file of its own (log.py)
        try:
            return run()
        except KeyboardInterrupt:
            return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
