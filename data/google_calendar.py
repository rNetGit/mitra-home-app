"""Google Calendar straight from Google's API: read-only by default; the Mitra Home-calendar sync is separate
(data/calendar_sync.py). No Claude, no AI, standard library only.

  python data/google_calendar.py status                 is it set up, and signed in?
  python data/google_calendar.py auth                   sign in once (opens a browser; the answer comes back to this PC)
  python data/google_calendar.py calendars              the calendars this account can read
  python data/google_calendar.py events [--days 14]     what is coming up
  python data/google_calendar.py revoke                 forget the sign-in here and ask Google to cancel it

Setup is `python onboard.py add calendar` (guide: docs/GOOGLE_CALENDAR.md). Each family uses its OWN Google Cloud
project (a free "Desktop app" OAuth client saved as config/google_client.json), so no credentials are shared and
nothing here needs Google's app verification.

Safety:
  * Scopes are read-only: `calendar.events.readonly` (view events) and `calendar.calendarlist.readonly` (list the
    calendars so you can pick). Reading cannot create, change or delete an event. Only `auth --write` adds
    `calendar.app.created` (its own calendar, see calendar_sync.py).
  * Sign-in uses the loopback redirect (http://127.0.0.1:PORT, this PC only) with PKCE and a `state` check.
  * The refresh token is kept in config/secrets.env only (never in family.json, never backed up, never printed).
  * Only Google's own hosts are contacted. For tests, MITRAHOME_GOOGLE_TEST_BASE may point at http://127.0.0.1:PORT.
  * Event text is shown, never followed as an instruction; descriptions, attendees and links are not read.
"""
import argparse
import base64
import datetime as dt
import hashlib
import http.server
import json
import os
import pathlib
import re
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import brand  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/calendar.events.readonly",
          "https://www.googleapis.com/auth/calendar.calendarlist.readonly"]
# Only for the Mitra Home calendar sync (data/calendar_sync.py): "make secondary calendars, and see, create, change and
# delete events on them". Google limits it to calendars this app made itself, so personal events cannot be touched.
WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.app.created"
# Only for data/google_gmail.py: "read your mail" (cannot send, label or delete); asked for only when the person turns Gmail on.
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
CLIENT_FILE = paths.CONFIG / "google_client.json"
TOKEN_NAME = "MITRAHOME_GOOGLE_REFRESH_TOKEN"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API_BASE = "https://www.googleapis.com/calendar/v3"
TIMEOUT = 20
MAX_EVENTS = 250
GUIDE = "docs/GOOGLE_CALENDAR.md"


class CalendarError(RuntimeError):
    pass


class AuthError(CalendarError):
    pass


class Conflict(CalendarError):
    """HTTP 409: the event id already exists."""


class Gone(CalendarError):
    """HTTP 404 / 410: it is not there (any more)."""


def _test_base():
    b = (os.environ.get("MITRAHOME_GOOGLE_TEST_BASE") or "").rstrip("/")
    if not b:
        return ""
    if not re.match(r"^http://127\.0\.0\.1:\d+$", b):
        raise CalendarError("MITRAHOME_GOOGLE_TEST_BASE must be http://127.0.0.1:PORT (tests only)")
    return b


def endpoints():
    b = _test_base()
    if b:
        return {"auth": b + "/auth", "token": b + "/token", "revoke": b + "/revoke", "api": b + "/calendar/v3"}
    return {"auth": AUTH_URL, "token": TOKEN_URL, "revoke": REVOKE_URL, "api": API_BASE}


def _secret(name):
    return config.read_secret(name).strip()


def refresh_token():
    return _secret(TOKEN_NAME)


def load_client(path=None):
    """(client_id, client_secret) from the OAuth client file downloaded from Google Cloud (Desktop app)."""
    p = pathlib.Path(path or CLIENT_FILE)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise CalendarError(f"Google Calendar is not set up yet: Settings > Connections > Google Calendar ({GUIDE}).") from None
    c = raw.get("installed") if isinstance(raw, dict) else None
    if not isinstance(c, dict) or not c.get("client_id"):
        raise CalendarError("The client file is not a Desktop-app OAuth client ('installed'). In Google Cloud, create "
                            f"the client with application type 'Desktop app' ({GUIDE}).")
    return c["client_id"], c.get("client_secret") or ""


def _post(url, fields):
    data = urllib.parse.urlencode(fields).encode("ascii")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (hosts fixed in endpoints())
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8") or "{}")
        except ValueError:
            body = {}
        err = body.get("error") if isinstance(body, dict) else None
        if err in ("invalid_grant", "invalid_client", "unauthorized_client", "access_denied"):
            raise AuthError(f"Google refused the sign-in ({err}). Sign in again: Settings > Connections > Google Calendar."
                            + (_testing_hint() if err == "invalid_grant" else "")) from None
        raise CalendarError(f"Google answered HTTP {e.code} at the token step") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CalendarError(f"could not reach Google: {type(getattr(e, 'reason', e)).__name__}") from None


def _testing_hint():
    """A sign-in refused six or more days after it was given is the usual sign of a Google project left in Testing."""
    try:
        since = dt.date.fromisoformat(str((config.family().get("google_calendar") or {}).get("signed_in") or ""))
    except ValueError:
        return ""
    if (dates.today() - since).days < 6:
        return ""
    return (" If this happens about a week after every sign-in, your Google project is still in 'Testing': in Google Cloud "
            f"open Google Auth platform > Audience and press 'Publish app' ({GUIDE}), then sign in again.")


def access_token():
    rt = refresh_token()
    if not rt:
        raise AuthError("Not signed in to Google: Settings > Connections > Google Calendar.")
    cid, csec = load_client()
    fields = {"client_id": cid, "refresh_token": rt, "grant_type": "refresh_token"}
    if csec:
        fields["client_secret"] = csec
    tok = _post(endpoints()["token"], fields).get("access_token")
    if not tok:
        raise AuthError("Google gave no access token. Sign in again: Settings > Connections > Google Calendar.")
    return tok


def _get(path, params=None, token=None):
    url = endpoints()["api"] + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + (token or access_token()), "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("Google refused the request (HTTP %d). Is the Calendar API switched on for the project, and "
                            "are you signed in? Settings > Connections > Google Calendar." % e.code) from None
        if e.code == 404:
            raise CalendarError("that calendar was not found") from None
        raise CalendarError(f"Google answered HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CalendarError(f"could not reach Google: {type(getattr(e, 'reason', e)).__name__}") from None


def _send(method, path, body=None, params=None, token=None):
    """JSON request with a body (POST / PATCH / DELETE) to the Calendar API. -> parsed JSON ({} for 204)."""
    url = endpoints()["api"] + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": "Bearer " + (token or access_token()), "Accept": "application/json",
        **({"Content-Type": "application/json; charset=utf-8"} if data is not None else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        if e.code == 409:
            raise Conflict("that event already exists") from None
        if e.code in (404, 410):
            raise Gone("not found") from None
        if e.code in (401, 403):
            raise AuthError(f"Google refused the change (HTTP {e.code}). Sign in again and allow {brand.PRODUCT} to make its own calendar: "
                            "Settings > Connections > Google Calendar") from None
        raise CalendarError(f"Google answered HTTP {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise CalendarError(f"could not reach Google: {type(getattr(e, 'reason', e)).__name__}") from None


def can_write():
    """True once the person allowed the Mitra Home-calendar permission (no network call)."""
    return bool((config.family().get("google_calendar") or {}).get("write")) and bool(refresh_token())


# ---------------------------------------------------------------- sign-in
def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def authorize(browser=None, timeout=240, say=print, write=None, gmail=None):
    """Browser sign-in with PKCE on a loopback port. `browser(url)` opens the page (default: the system browser).
    Saves the refresh token in config/secrets.env and returns True. write=True also asks for the one permission the
    Mitra Home calendar sync needs (its own calendar only); gmail=True also asks to read mail (data/google_gmail.py).
    None keeps what was allowed before, so signing in again never drops a permission."""
    had = config.family().get("google_calendar") or {}
    write = bool(had.get("write")) if write is None else bool(write)
    gmail = bool(had.get("gmail")) if gmail is None else bool(gmail)
    scopes = SCOPES + ([WRITE_SCOPE] if write else []) + ([GMAIL_SCOPE] if gmail else [])
    cid, csec = load_client()
    verifier = _b64(os.urandom(48))
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    state = secrets.token_urlsafe(24)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if q.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Wrong state. Close this tab and start again.")
                return
            got["code"] = q.get("code", [""])[0]
            got["error"] = q.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body style='font-family:sans-serif'><h3>{brand.PRODUCT}</h3>"
                             "<p>You can close this tab and go back to the terminal.</p></body></html>".encode())

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    srv.timeout = 1
    redirect = f"http://127.0.0.1:{srv.server_port}"
    url = endpoints()["auth"] + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": " ".join(scopes),
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state,
        "access_type": "offline", "prompt": "consent"})
    say("  Opening your browser to sign in to Google. If it does not open, paste this address into a browser on this PC:")
    say("  " + url)
    try:
        (browser or webbrowser.open)(url)
    except Exception:  # noqa: BLE001 (the address above still works by hand)
        pass
    done = threading.Event()

    def serve():
        end = dt.datetime.now() + dt.timedelta(seconds=timeout)
        while not got.get("code") and not got.get("error") and dt.datetime.now() < end:
            srv.handle_request()
        done.set()

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    done.wait(timeout + 5)
    srv.server_close()
    if got.get("error"):
        raise AuthError(f"Google sign-in was cancelled or refused ({got['error']})")
    if not got.get("code"):
        raise AuthError("no answer from the browser in time; run it again")
    fields = {"client_id": cid, "code": got["code"], "code_verifier": verifier, "grant_type": "authorization_code",
              "redirect_uri": redirect}
    if csec:
        fields["client_secret"] = csec
    resp = _post(endpoints()["token"], fields)
    rt = resp.get("refresh_token")
    if not rt:
        raise AuthError(f"Google gave no refresh token. Remove {brand.PRODUCT} at https://myaccount.google.com/permissions and sign in again.")
    config.write_secret(TOKEN_NAME, rt)
    granted = str(resp.get("scope") or " ".join(scopes)).split()
    with config.family_edit() as cfg:
        gc = dict(cfg.get("google_calendar") or {})
        gc["write"] = WRITE_SCOPE in granted
        gc["gmail"] = GMAIL_SCOPE in granted
        gc["signed_in"] = dates.today().isoformat()
        gc["enabled"] = True  # signing in again after Disconnect turns it back on; the calendar choice stays
        cfg["google_calendar"] = gc
    return True


def revoke():
    """Forget the refresh token on this PC and ask Google to cancel it. Returns True if Google confirmed."""
    rt = refresh_token()
    asked = False
    if rt:
        try:
            _post(endpoints()["revoke"], {"token": rt})
            asked = True
        except CalendarError:
            asked = False
    config.write_secret(TOKEN_NAME, "")
    return asked


# ---------------------------------------------------------------- reading
def configured_calendars():
    cfg = config.family().get("google_calendar") or {}
    cals = [c for c in (cfg.get("calendars") or []) if isinstance(c, str) and c]
    return cals or ["primary"]


def is_enabled():
    return bool((config.family().get("google_calendar") or {}).get("enabled"))


def status():
    """{'client': bool, 'signed_in': bool, 'enabled': bool, 'calendars': [...]} without any network call."""
    try:
        load_client()
        client = True
    except CalendarError:
        client = False
    return {"client": client, "signed_in": bool(refresh_token()), "enabled": is_enabled(), "calendars": configured_calendars()}


def calendars():
    """[{'id', 'name', 'primary'}] for the calendars the account can read."""
    out = []
    tok = access_token()
    page = None
    for _ in range(5):
        r = _get("/users/me/calendarList", {"maxResults": 100, **({"pageToken": page} if page else {})}, tok)
        for it in r.get("items", []):
            out.append({"id": it.get("id", ""), "name": _clean(it.get("summaryOverride") or it.get("summary") or it.get("id", "")),
                        "primary": bool(it.get("primary"))})
        page = r.get("nextPageToken")
        if not page:
            break
    return out


def _clean(s, n=120):
    s = "".join(ch for ch in str(s or "") if ch >= " " and ch != "\x7f")
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _parse(item, cal):
    if item.get("status") == "cancelled":
        return None
    st, en = item.get("start") or {}, item.get("end") or {}
    if "date" in st:
        day, hhmm, end_t, all_day = st["date"], "", "", True
    elif "dateTime" in st:
        day, hhmm, all_day = st["dateTime"][:10], st["dateTime"][11:16], False
        end_t = (en.get("dateTime") or "")[11:16]
    else:
        return None
    try:
        dt.date.fromisoformat(day)
    except ValueError:
        return None
    return {"date": day, "time": hhmm, "end": end_t, "all_day": all_day, "calendar": cal,
            "title": _clean(item.get("summary")) or "(busy)"}


def events(days=14, today=None, cals=None):
    """Events from `today` for `days` days across the chosen calendars, oldest first."""
    today = today or dates.today()
    start = dt.datetime.combine(today, dt.time.min).astimezone()
    end = start + dt.timedelta(days=int(days))
    tok = access_token()
    out = []
    for cal in (cals or configured_calendars()):
        r = _get(f"/calendars/{urllib.parse.quote(cal, safe='')}/events",
                 {"timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true", "orderBy": "startTime",
                  "maxResults": MAX_EVENTS, "fields": "items(summary,status,start,end)"}, tok)
        for it in r.get("items", []):
            e = _parse(it, cal)
            if e:
                out.append(e)
    out.sort(key=lambda e: (e["date"], e["time"] or "00:00", e["title"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    pa = sub.add_parser("auth")
    pa.add_argument("--write", action="store_true", help=f"also allow {brand.PRODUCT} to make and fill its own calendar")
    sub.add_parser("calendars")
    sub.add_parser("revoke")
    p = sub.add_parser("events")
    p.add_argument("--days", type=int, default=14)
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status":
            s = status()
            print(f"OAuth client file: {'yes' if s['client'] else 'missing (python onboard.py add calendar)'}")
            print(f"signed in:         {'yes' if s['signed_in'] else 'no'}")
            print(f"turned on:         {'yes' if s['enabled'] else 'no'}  calendars: {', '.join(s['calendars'])}")
        elif a.cmd == "auth":
            authorize(write=a.write)
            print("signed in. The token is saved in config/secrets.env (not shown). Next: python data/google_calendar.py calendars")
        elif a.cmd == "calendars":
            for c in calendars():
                print(f"{'*' if c['primary'] else ' '} {c['name']}   [{c['id']}]")
        elif a.cmd == "events":
            ev = events(a.days)
            for e in ev:
                print(f"{e['date']}  {(e['time'] + '-' + e['end']) if e['time'] else 'all day':<12} {e['title']}")
            if not ev:
                print(f"nothing in the next {a.days} days")
        elif a.cmd == "revoke":
            ok = revoke()
            print("signed out here" + (" and Google was told to cancel the access" if ok else
                                       f"; remove {brand.PRODUCT} at https://myaccount.google.com/permissions to be sure"))
    except CalendarError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
