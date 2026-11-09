"""Signed-in sessions for the web app: random tokens kept in memory, never in a file.

A restart of the web app signs everyone out on purpose (nothing to steal from disk, nothing to revoke). The cookie
holds only the random token; the person's name, role and CSRF token live here.
"""
import hmac
import secrets
import threading
import time

IDLE = 8 * 60 * 60        # seconds without a request before the session ends
ABSOLUTE = 14 * 24 * 3600  # a session never lives longer than this
MAX_SESSIONS = 200        # a flood of logins cannot grow memory without limit
HANDOFF_TTL = 60          # seconds a phone app's one-time sign-in code lives
MAX_HANDOFFS = 50

_lock = threading.Lock()
_store = {}
_handoffs = {}  # one-time code -> {'user','bind','device','born'}: the phone app's way into a web session


def _now():
    return time.time()


def create(user, now=None, bind=""):
    """Start a session for {'name','role'}; returns its token. `bind` = the PIN fingerprint it was made with."""
    now = _now() if now is None else now
    token = secrets.token_urlsafe(32)
    with _lock:
        _purge(now)
        while len(_store) >= MAX_SESSIONS:
            oldest = min(_store, key=lambda t: _store[t]["seen"])
            del _store[oldest]
        _store[token] = {"user": dict(user), "csrf": secrets.token_urlsafe(24), "born": now, "seen": now, "bind": bind}
    return token


def get(token, now=None):
    """The live session for `token` (and mark it seen), or None when unknown, idle too long or too old."""
    if not token:
        return None
    now = _now() if now is None else now
    with _lock:
        s = _store.get(token)
        if not s:
            return None
        if now - s["seen"] > IDLE or now - s["born"] > ABSOLUTE:
            del _store[token]
            return None
        s["seen"] = now
        return s


def destroy(token):
    with _lock:
        _store.pop(token, None)


def csrf_ok(session, supplied):
    return bool(session) and bool(supplied) and hmac.compare_digest(str(session["csrf"]), str(supplied))


def _purge(now):
    for t in [t for t, s in _store.items() if now - s["seen"] > IDLE or now - s["born"] > ABSOLUTE]:
        del _store[t]


def handoff_create(user, bind, device, now=None):
    """A one-time code (HANDOFF_TTL seconds) that the phone app's web view trades for a session cookie."""
    now = _now() if now is None else now
    code = secrets.token_urlsafe(32)
    with _lock:
        for c in [c for c, h in _handoffs.items() if now - h["born"] > HANDOFF_TTL]:
            del _handoffs[c]
        while len(_handoffs) >= MAX_HANDOFFS:
            del _handoffs[min(_handoffs, key=lambda c: _handoffs[c]["born"])]
        _handoffs[code] = {"user": dict(user), "bind": bind, "device": int(device), "born": now}
    return code


def handoff_take(code, now=None):
    """The handoff behind `code`, used up at once; None when unknown, used or too old."""
    if not code or not isinstance(code, str):
        return None
    now = _now() if now is None else now
    with _lock:
        h = _handoffs.pop(code, None)
    if not h or now - h["born"] > HANDOFF_TTL:
        return None
    return h


def clear():
    """Test helper: forget everything."""
    with _lock:
        _store.clear()
        _handoffs.clear()
