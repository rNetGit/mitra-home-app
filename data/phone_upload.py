"""Scans and files sent by a paired phone (`POST /api/upload`) into inbox/.

  python data/phone_upload.py list [N]     the latest files from phones (phone, when, saved or already here, size)

A phone sends one file per request: the raw bytes as the body, its own id for this send (`X-Client-Id`), the file's
SHA-256 (`X-Sha256`) and the name (`X-Filename`). `accept` then, in this order:
  1. the phone must be allowed to send scans (scope `scan`; adults only, data/devices.py);
  2. a send it already made (same client id) gets the first answer again, so a retry after a dropped connection never
     makes a second copy; the same client id with different bytes is refused;
  3. the bytes must hash to the SHA-256 the phone sent (a damaged transfer is refused, and the phone sends it again);
  4. an exact copy of a file already waiting in inbox/, already filed in archive/ or waiting for review, or already sent
     by any phone is not saved again (answer `duplicate`);
  5. at most MAX_PER_DAY saved files per phone per day;
  6. the same checks as every other upload (data/inbox_data.save_file: type, size, content matches the name, never a
     program or web page, inbox not full, never overwrites).
Nothing in the file is opened, read or run here; the inbox task files it like any other paper.
"""
import datetime as dt
import hashlib
import pathlib
import re
import sqlite3
import sys
import threading

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import db as _db  # noqa: E402
import inbox_upload  # noqa: E402

MAX_PER_DAY = 50  # saved files per phone per day
MAX_BYTES = inbox_upload.MAX_BYTES
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_LOCK = threading.Lock()  # one phone file at a time: the duplicate check and the save must not interleave


def _now():
    return dt.datetime.now().replace(microsecond=0)


def _ts(t):
    return t.isoformat(timespec="seconds")


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def limits(con, dev, now=None):
    """What a phone needs to know before it sends: size cap, accepted types, how many it may still send today."""
    if "scan" not in (dev or {}).get("scopes", []):
        return None
    return {"max_bytes": MAX_BYTES, "types": sorted(inbox_upload.ALLOWED), "per_day": MAX_PER_DAY,
            "left_today": max(0, MAX_PER_DAY - saved_today(con, dev["id"], now))}


def saved_today(con, device_id, now=None):
    day = (now or _now()).date().isoformat()
    try:
        return con.execute("SELECT COUNT(*) FROM device_uploads WHERE device_id=? AND status='saved' AND created_at >= ?",
                           (device_id, day + "T00:00:00")).fetchone()[0]
    except sqlite3.OperationalError as e:
        if _db.missing(e):
            return 0
        raise


def where_already(con, sha, size):
    """'inbox' / 'filed' / 'sent' when an exact copy is already here, else None."""
    if con.execute("SELECT 1 FROM device_uploads WHERE sha256=? LIMIT 1", (sha,)).fetchone():
        return "sent"
    import inbox_data
    for p in inbox_data.waiting_files():
        try:
            if p.is_file() and p.stat().st_size == size and _file_sha(p) == sha:
                return "inbox"
        except OSError:
            continue
    import ai_intake  # filed papers and papers waiting for review, hashes cached in logs/
    if sha in ai_intake.known_files():
        return "filed"
    return None


def _file_sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _answer(row):
    if row["status"] == "saved":
        return {"ok": True, "status": "saved", "name": row["saved_as"]}
    return {"ok": True, "status": "duplicate"}


def accept(con, dev, client_id, name, data, claimed_sha, now=None):
    """One file from a phone. -> (http status, json body). `dev` comes from devices.authenticate (live role and scopes)."""
    if "scan" not in (dev or {}).get("scopes", []) or dev.get("role") != "adult":
        return 403, {"error": "no_scope"}
    client_id, claimed_sha = str(client_id or ""), str(claimed_sha or "").lower()
    if not _CLIENT_ID.match(client_id) or not _SHA.match(claimed_sha):
        return 400, {"error": "bad_request"}
    data = data or b""
    if not data:
        return 400, {"error": "refused", "message": "the file is empty"}
    if len(data) > MAX_BYTES:
        return 413, {"error": "too_large"}
    now = now or _now()
    with _LOCK:
        prev = con.execute("SELECT status, saved_as, sha256 FROM device_uploads WHERE device_id=? AND client_id=?",
                           (dev["id"], client_id)).fetchone()
        if prev:
            if prev["sha256"] != claimed_sha:
                return 409, {"error": "client_id_reused"}
            return 200, dict(_answer(prev), repeat=True)
        sha = sha256_bytes(data)
        if sha != claimed_sha:
            return 400, {"error": "hash_mismatch"}
        seen = where_already(con, sha, len(data))
        if seen:
            _record(con, dev["id"], client_id, sha, len(data), "duplicate", None, now)
            return 200, {"ok": True, "status": "duplicate"}
        if saved_today(con, dev["id"], now) >= MAX_PER_DAY:
            return 429, {"error": "daily_limit", "per_day": MAX_PER_DAY}
        import inbox_data
        clean = inbox_upload.clean_name(name or "scan.pdf")
        ok, msg = inbox_data.save_file(f"{now:%Y-%m-%d_%H%M%S}_phone_{clean}", data)
        if not ok:
            return 400, {"error": "refused", "message": msg}
        _record(con, dev["id"], client_id, sha, len(data), "saved", msg, now)
        return 200, {"ok": True, "status": "saved", "name": msg}


def _record(con, device_id, client_id, sha, size, status, saved_as, now):
    con.execute("INSERT INTO device_uploads(device_id, client_id, sha256, size, status, saved_as, created_at) "
                "VALUES (?,?,?,?,?,?,?)", (device_id, client_id, sha, size, status, saved_as, _ts(now)))
    con.commit()


def recent(con, n=20):
    return [dict(r) for r in con.execute(
        "SELECT u.created_at, d.name AS phone, d.member, u.status, u.saved_as, u.size FROM device_uploads u "
        "JOIN devices d ON d.id = u.device_id ORDER BY u.id DESC LIMIT ?", (int(n),))]


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "list":
        with _db.open(paths.DB, readonly=True, row=True) as c:
            rows = recent(c, int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 20)
        for r in rows:
            print(f"{r['created_at']}  {r['phone']} ({r['member']})  {r['status']:<9}  {r['size']:>9} B  {r['saved_as'] or ''}")
        if not rows:
            print("No files from phones yet.")
    else:
        print(__doc__)
