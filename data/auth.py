"""Dashboard users and PINs (per-person views).

  python data/auth.py set NAME [adult|limited]    ask for a PIN (hidden) and save its hash in config/family.json
  python data/auth.py list
  python data/auth.py remove NAME

Roles: `adult` sees everything; `limited` (children, teens, guests) sees only their own items, birthdays and
non-financial calendar entries. PINs are stored salted + hashed (PBKDF2), never in plain text.

Honest limits: this keeps people out of the dashboard screen on a shared PC. It is NOT strong security: anyone who can
open the files on this PC can read the database. Use an OS user account / disk encryption for that.
Legacy `dashboard_pin` (plain text in family.json) still works as one shared adult login; `set` replaces it.
"""
import getpass
import hashlib
import hmac
import json
import os
import pathlib
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402

CONFIG = paths.CONFIG / "family.json"
ITER = 200_000


def hash_pin(pin, salt=None):
    salt = salt or os.urandom(16)
    h = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, ITER)
    return f"pbkdf2${ITER}${salt.hex()}${h.hex()}"


def verify_pin(stored, pin):
    try:
        _, it, salt, h = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), bytes.fromhex(salt), int(it))
        return hmac.compare_digest(calc.hex(), h)
    except (ValueError, AttributeError):
        return False


def locked_out():
    """True when config/family.json exists but cannot be read: nobody gets in, with or without a PIN, until it is
    fixed. (An unreadable file must never look like "nobody has a PIN yet".)"""
    return config.broken("family.json")


def users():
    """[{'name','role','pin_hash'}] from config; the legacy shared PIN becomes a 'Household' adult."""
    fam = config.family()
    pets = {m.get("name") for m in fam.get("members") or [] if m.get("role") == "pet"}  # a PIN given to a pet earlier
    out = [u for u in fam.get("dashboard_users", []) if u.get("name") and u.get("pin_hash") and u["name"] not in pets]
    legacy = str(fam.get("dashboard_pin") or "")
    if legacy and not out:
        out = [{"name": "Household", "role": "adult", "pin_hash": hash_pin(legacy)}]
    return out


def login(name, pin):
    for u in users():
        if u["name"] == name and verify_pin(u["pin_hash"], pin):
            return {"name": u["name"], "role": u.get("role", "adult")}
    return None


def current(name):
    """The person's live {'name','role'} and a fingerprint of their PIN (same until the PIN changes), or None when gone.

    The web app re-checks this on every request, so a changed PIN, a removed person or a new role ends or updates an
    open session at once. The fingerprint is salt-independent for the legacy shared PIN too.
    """
    fam = config.family()
    for u in fam.get("dashboard_users", []):
        if u.get("name") == name and u.get("pin_hash"):
            return ({"name": name, "role": u.get("role", "adult")},
                    hashlib.sha256(str(u["pin_hash"]).encode("utf-8")).hexdigest())
    legacy = str(fam.get("dashboard_pin") or "")
    if legacy and name == "Household" and not [u for u in fam.get("dashboard_users", []) if u.get("name") and u.get("pin_hash")]:
        return {"name": name, "role": "adult"}, hashlib.sha256(legacy.encode("utf-8")).hexdigest()
    return None


def set_user(name, role, pin):
    if len(pin) < 4:
        raise ValueError("PIN must be at least 4 characters")
    with config.family_edit() as fam:  # a family.json that does not parse is refused, never replaced
        lst = [u for u in fam.get("dashboard_users", []) if u.get("name") != name]
        lst.append({"name": name, "role": role if role in ("adult", "limited") else "limited", "pin_hash": hash_pin(pin)})
        fam["dashboard_users"] = lst
        fam.pop("dashboard_pin", None)  # replace the legacy plain-text PIN


# ---- login throttle, file-backed (logs/login_throttle.json) so a page reload or a new tab does not reset it.
THROTTLE = paths.LOGS / "login_throttle.json"
FAILS_BEFORE_LOCK = 5          # wrong PINs within WINDOW seconds before a lock
WINDOW = 15 * 60
LOCKS = (30, 60, 120, 300, 900)  # seconds; each further lock on the same name is longer
EVERYONE = "*"                 # a second counter across all names (switching names does not help)
EVERYONE_FAILS = 15
LOCK_MEMORY = 60 * 60          # a name quiet for this long after its last lock starts again at the shortest lock
# Guesses from another device on the Wi-Fi (audit S2) also count per address, with a much steeper ladder, so one device
# gets about 25 tries a day however it switches names; this PC never trips the all-names lock (it cannot lock itself out)
SOURCE_LOCKS = (300, 900, 3600, 6 * 3600, 24 * 3600)
SOURCE_MEMORY = 24 * 3600


# the throttle file is read, changed and written back: one writer at a time, or parallel failures overwrite each other
_THROTTLE_LOCK = threading.RLock()
# one PIN check at a time in this process: the lock check, the slow hash and the count happen together, so a burst of
# guesses sent at once is counted guess by guess instead of every one passing the check before any failure is saved
_SIGN_IN = threading.Lock()


def attempt(name, pin, everyone=True, source=None):
    """Check a PIN under the throttle. -> (user or None, seconds still locked, lock length this failure caused)."""
    with _SIGN_IN:
        wait = locked_for(name, everyone=everyone, source=source)
        if wait:
            return None, wait, 0
        u = login(name, pin)
        if not u:
            return None, 0, record_failure(name, everyone=everyone, source=source)
        clear_failures(name)
        return u, 0, 0


def _source_key(source):
    return "@" + str(source)[:64] if source else None


def _throttle_load():
    try:
        d = json.loads(THROTTLE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _throttle_save(d):
    try:
        config.write_json(THROTTLE, d)
    except OSError:
        pass  # a read-only logs folder must not lock everyone out


def locked_for(name, now=None, everyone=True, source=None):
    """Seconds this name (or everyone, or the device at `source`) must still wait; 0 when a login attempt may be checked.
    `everyone=False` ignores the all-names lock (pairing codes; sign-in on this PC)."""
    now = now if now is not None else time.time()
    d = _throttle_load()
    wait = 0
    keys = (name, EVERYONE) if everyone else (name,)
    for key in keys + ((_source_key(source),) if source else ()):
        until = (d.get(key) or {}).get("locked_until", 0)
        wait = max(wait, int(until - now + 0.999)) if until > now else wait
    return max(wait, 0)


def record_failure(name, now=None, everyone=True, source=None):
    """Count one wrong PIN. Returns the lock length in seconds if this failure caused a lock, else 0. `everyone=False`
    keeps the failure off the all-names counter, so wrong pairing codes cannot lock PIN sign-in. `source` (another
    device's address) is counted too, with the steeper SOURCE_LOCKS."""
    with _THROTTLE_LOCK:
        return _record_failure(name, now, everyone, source)


def _record_failure(name, now, everyone, source):
    now = now if now is not None else time.time()
    d = _throttle_load()
    locked = 0
    plan = [(name, FAILS_BEFORE_LOCK, LOCKS, LOCK_MEMORY)]
    if everyone:
        plan.append((EVERYONE, EVERYONE_FAILS, LOCKS, LOCK_MEMORY))
    if source:
        plan.append((_source_key(source), FAILS_BEFORE_LOCK, SOURCE_LOCKS, SOURCE_MEMORY))
    for key, limit, ladder, memory in plan:
        e = d.setdefault(key, {"fails": [], "locks": 0, "locked_until": 0})
        if e.get("locks") and now - e.get("locked_until", 0) > memory:
            e["locks"] = 0
        e["fails"] = [t for t in e.get("fails", []) if now - t < WINDOW] + [now]
        if len(e["fails"]) >= limit:
            n = ladder[min(int(e.get("locks", 0)), len(ladder) - 1)]
            e["locked_until"] = now + n
            e["locks"] = int(e.get("locks", 0)) + 1
            e["fails"] = []
            locked = max(locked, n)
    _throttle_save(d)
    return locked


def pair_key(base, source):
    """The counter for wrong pairing codes: per device address on the Wi-Fi (one device sending bad codes must not lock
    pairing for everyone, audit L1), the shared `base` key for this PC itself."""
    return f"{base}@{str(source)[:64]}" if source else base


def clear_failures(name):
    """Forget a counter; for a pairing key ("#...") also every device's counter under it."""
    with _THROTTLE_LOCK:
        d = _throttle_load()
        gone = [k for k in d if k == name or (name.startswith("#") and "@" not in name and k.startswith(name + "@"))]
        for k in gone:
            del d[k]
        if gone:
            _throttle_save(d)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    if cmd == "set" and len(sys.argv) >= 3:
        pin = getpass.getpass(f"PIN for {sys.argv[2]}: ")
        set_user(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "limited", pin)
        print("saved")
    elif cmd == "remove" and len(sys.argv) >= 3:
        with config.family_edit() as fam:
            fam["dashboard_users"] = [u for u in fam.get("dashboard_users", []) if u.get("name") != sys.argv[2]]
        print("removed")
    else:
        for u in users():
            print(u["name"], u.get("role", "adult"))


if __name__ == "__main__":
    main()
