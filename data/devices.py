"""Paired phones: one-time pairing codes, per-phone access tokens, what each phone may see, revoke.

  python data/devices.py list           paired phones (name, person, role, scopes, last seen)
  python data/devices.py revoke ID      the phone's token stops working at once

How a phone is paired (Settings > Phones, adults, on this PC only):
  1. `pair_start` makes a random secret and keeps only its SHA-256 (table device_pairings, migration 042). The QR code
     carries the secret with this PC's address, the HTTPS port and the certificate fingerprint (data/lan_tls.py).
  2. The phone checks the certificate against the fingerprint, then sends the secret to `POST /api/pair`.
     `pair_redeem` accepts a secret once, before it expires, and returns a new access token. Only the token's SHA-256
     is stored (table devices); the token itself lives in the phone's keystore.
  3. Every API request carries `Authorization: Bearer <token>`. `authenticate` finds the phone, checks it was not
     revoked and that its person is still in the household, and applies the person's live role: a phone never sees
     more than its person may, whatever its scopes say.
Revoke keeps the row, so a revoked phone is told to wipe its copy the next time it calls.

Scopes = what a phone may carry. Adults: bills, calendar, notes, lists and scans on; finance detail and ID documents off
until an adult turns them on. Children and guests (limited): their own items, the family calendar and family lists
only; money, notes, IDs and scans can never be turned on for them. What each scope carries: data/sync_data.py.
`web` lets the phone app open the full web app as its person (POST /api/session, 0.104) without typing the PIN; the
person needs a sign-in PIN, and the web app shows them exactly what their PIN would.
"""
import datetime as dt
import hashlib
import pathlib
import re
import secrets
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import db as _db  # noqa: E402

DB = paths.DB
PAIR_MINUTES = 5
MAX_DEVICES = 20
SEEN_EVERY = 60  # seconds: last_seen is written at most this often
SECRET_LEN = 22  # secrets.token_urlsafe(16)
TOKEN_LEN = 43   # secrets.token_urlsafe(32)
_URLSAFE = re.compile(r"^[A-Za-z0-9_-]+$")

# key: (label, adult default, open to limited, limited default)
SCOPES = {
    "own": ("Their own items", False, True, True),
    "bills": ("Bills and due dates", True, False, False),
    "calendar": ("Calendar", True, True, True),
    "notes": ("Notes", True, False, False),
    "lists": ("Lists", True, True, True),
    "scan": ("Send scans to the Inbox", True, False, False),
    "finance": ("Finance detail", False, False, False),
    "ids": ("ID documents", False, False, False),
    "web": ("Open the full app on the home Wi-Fi", True, True, True),
}
ROLES = ("adult", "limited")


def _now():
    return dt.datetime.now().replace(microsecond=0)


def _ts(t):
    return t.isoformat(timespec="seconds")


def _hash(s):
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def _con(path=None):
    return _db.connect(path or DB, row=True)


def allowed(role):
    """Scope keys a phone of this role may have, in display order ('own' only means something for limited)."""
    if role == "adult":
        return [k for k in SCOPES if k != "own"]
    return [k for k, v in SCOPES.items() if v[2]]


def defaults(role):
    return [k for k in allowed(role) if SCOPES[k][1 if role == "adult" else 3]]


def clean_scopes(role, keys):
    """Only known keys that this role may have, in catalogue order."""
    want = set(keys or [])
    return [k for k in allowed(role) if k in want]


def _split(s):
    return [k for k in (s or "").split(",") if k]


def member_role(name):
    """(canonical name, 'adult'|'limited') for a person of the household (not a pet), or (None, None).

    The sign-in list decides when the person has a PIN (Settings > Home Profile may make a teen limited); otherwise their role
    in the family profile: adults are adults, everyone else is limited (the safe side)."""
    want = " ".join(str(name or "").split()).lower()
    if not want:
        return None, None
    for m in config.members():
        n = (m.get("name") or "").strip()
        if n.lower() == want and m.get("role") != "pet":
            for u in config.family().get("dashboard_users") or []:
                if u.get("name") == n and u.get("pin_hash"):
                    return n, "adult" if u.get("role", "adult") == "adult" else "limited"
            return n, "adult" if m.get("role") == "adult" else "limited"
    return None, None


def people():
    """[{'name','role'}] who may get a phone (household members, not pets)."""
    out = []
    for m in config.members():
        n, role = member_role(m.get("name"))
        if n:
            out.append({"name": n, "role": role})
    return out


def clean_name(name):
    """A phone's name as typed: printable, single spaces, 1..40 characters. -> str or None."""
    s = " ".join("".join(ch if ch.isprintable() else " " for ch in str(name or "")).split())[:40]
    return s or None


def live_count(con):
    return con.execute("SELECT COUNT(*) FROM devices WHERE revoked_at IS NULL").fetchone()[0]


def pair_start(con, member, name, scopes=None, by="", now=None):
    """A one-time pairing secret for a phone of `member`. -> (secret, {'member','role','name','scopes','expires_at'}).

    Only the hash is stored. An older unused code for the same person stops working. Raises ValueError with a sentence
    for the person when something is wrong."""
    who, role = member_role(member)
    if not who:
        raise ValueError("Pick a person of the household.")
    label = clean_name(name)
    if not label:
        raise ValueError("Give the phone a name, for example Ann's phone.")
    if live_count(con) >= MAX_DEVICES:
        raise ValueError(f"{MAX_DEVICES} phones are paired already. Remove one first.")
    keys = clean_scopes(role, defaults(role) if scopes is None else scopes)
    now = now or _now()
    secret = secrets.token_urlsafe(16)
    exp = now + dt.timedelta(minutes=PAIR_MINUTES)
    con.execute("UPDATE device_pairings SET used_at=? WHERE member=? AND used_at IS NULL", (_ts(now), who))
    con.execute("INSERT INTO device_pairings(secret_hash, member, role, name, scopes, created_at, created_by, expires_at) "
                "VALUES (?,?,?,?,?,?,?,?)", (_hash(secret), who, role, label, ",".join(keys), _ts(now), by or None, _ts(exp)))
    con.commit()
    return secret, {"member": who, "role": role, "name": label, "scopes": keys, "expires_at": _ts(exp)}


def pair_redeem(con, secret, now=None):
    """Turn a pairing secret into a phone. -> (token, device dict) or None (wrong, used or expired code; person gone;
    too many phones). The secret works once."""
    secret = str(secret or "").strip()
    if len(secret) != SECRET_LEN or not _URLSAFE.match(secret):
        return None
    now = now or _now()
    r = con.execute("SELECT id, member, role, name, scopes, created_by, expires_at FROM device_pairings "
                    "WHERE secret_hash=? AND used_at IS NULL", (_hash(secret),)).fetchone()
    if not r or r["expires_at"] < _ts(now):
        return None
    if con.execute("UPDATE device_pairings SET used_at=? WHERE id=? AND used_at IS NULL",
                   (_ts(now), r["id"])).rowcount != 1:
        return None  # a second redeem of the same code, racing this one, lost the claim
    who, role = member_role(r["member"])
    if not who or live_count(con) >= MAX_DEVICES:
        con.commit()
        return None
    keys = clean_scopes(role, _split(r["scopes"]))
    token = secrets.token_urlsafe(32)
    cur = con.execute("INSERT INTO devices(name, member, role, scopes, token_hash, created_at, created_by, last_seen) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (r["name"], who, role, ",".join(keys), _hash(token), _ts(now), r["created_by"], _ts(now)))
    con.execute("UPDATE device_pairings SET device_id=? WHERE id=?", (cur.lastrowid, r["id"]))
    con.commit()
    return token, {"id": cur.lastrowid, "name": r["name"], "member": who, "role": role, "scopes": keys}


def authenticate(con, token, now=None):
    """The phone behind a bearer token. -> device dict ({'id','name','member','role','scopes'}), {'revoked': True}
    (the phone should wipe its copy), or None (not a token of this household)."""
    token = str(token or "").strip()
    if len(token) != TOKEN_LEN or not _URLSAFE.match(token):
        return None
    r = con.execute("SELECT id, name, member, scopes, last_seen, revoked_at FROM devices WHERE token_hash=?",
                    (_hash(token),)).fetchone()
    if not r:
        return None
    if r["revoked_at"]:
        return {"revoked": True}
    now = now or _now()
    if config.broken("family.json"):  # cannot tell who is in the household: say so, never revoke on a guess
        return {"unavailable": True}
    who, role = member_role(r["member"])
    if not who:  # the person left the household: the phone goes with them
        con.execute("UPDATE devices SET revoked_at=? WHERE id=?", (_ts(now), r["id"]))
        con.commit()
        try:
            import admin_actions
            admin_actions._audit({"name": "system"}, "phone_revoke_auto", f"id={r['id']} person no longer in the household")
        except Exception:  # noqa: BLE001 (the revoke stands even when the log cannot be written)
            pass
        return {"revoked": True}
    if not r["last_seen"] or (now - dt.datetime.fromisoformat(r["last_seen"])).total_seconds() >= SEEN_EVERY:
        con.execute("UPDATE devices SET last_seen=? WHERE id=?", (_ts(now), r["id"]))
        con.commit()
    return {"id": r["id"], "name": r["name"], "member": who, "role": role, "scopes": clean_scopes(role, _split(r["scopes"]))}


def web_ok(con, device_id):
    """True while a phone may keep a web session open: not revoked, its person still here, `web` still in its scopes."""
    r = con.execute("SELECT member, scopes, revoked_at FROM devices WHERE id=?", (int(device_id),)).fetchone()
    if not r or r[2]:
        return False
    who, role = member_role(r[0])
    return bool(who) and "web" in clean_scopes(role, _split(r[1]))


def revoke(con, device_id, now=None):
    """-> True when a live phone was revoked."""
    cur = con.execute("UPDATE devices SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (_ts(now or _now()), int(device_id)))
    con.commit()
    return cur.rowcount == 1


def set_scopes(con, device_id, keys):
    """What a live phone may carry, limited to what its person's role allows. -> the saved keys, or None (no such phone)."""
    r = con.execute("SELECT member FROM devices WHERE id=? AND revoked_at IS NULL", (int(device_id),)).fetchone()
    if not r:
        return None
    _, role = member_role(r["member"])
    keys = clean_scopes(role or "limited", keys)
    con.execute("UPDATE devices SET scopes=? WHERE id=?", (",".join(keys), int(device_id)))
    con.commit()
    return keys


def listing(con):
    """Live phones for Settings > Phones, newest first, with the live role and scopes, and how many were removed."""
    out = []
    for r in con.execute("SELECT id, name, member, scopes, created_at, last_seen FROM devices WHERE revoked_at IS NULL "
                         "ORDER BY id DESC"):
        who, role = member_role(r["member"])
        role = role or "limited"
        out.append({"id": r["id"], "name": r["name"], "member": who or r["member"], "role": role, "gone": not who,
                    "scopes": clean_scopes(role, _split(r["scopes"])), "allowed": allowed(role),
                    "created": r["created_at"][:10], "last_seen": (r["last_seen"] or "").replace("T", " ")[:16]})
    removed = con.execute("SELECT COUNT(*) FROM devices WHERE revoked_at IS NOT NULL").fetchone()[0]
    return out, removed


def label(key):
    return SCOPES[key][0] if key in SCOPES else key


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "list"
    try:
        con = _con()
    except sqlite3.Error as e:
        print("Could not open the database:", e)
        return 1
    try:
        if cmd == "revoke" and len(argv) > 1 and argv[1].isdigit():
            print("revoked" if revoke(con, int(argv[1])) else "no such paired phone")
            return 0
        if cmd == "list":
            rows, removed = listing(con)
            for d in rows:
                print(f"{d['id']:>3}  {d['name']}  ({d['member']}, {d['role']})  {', '.join(d['scopes']) or 'nothing'}"
                      f"  last seen {d['last_seen'] or 'never'}")
            print(f"{len(rows)} paired, {removed} removed")
            return 0
    finally:
        con.close()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
