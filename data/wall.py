"""The Mitra Wall: a tablet on the kitchen wall that shows the family week, today, chores, lists and meals.

  python data/wall.py list           paired walls (name, last seen)
  python data/wall.py revoke ID      that wall is signed out at once

A wall is the household's, not a person's. Pairing (Settings > Phones > Mitra Wall, adults, on this PC only):
  1. `pair_start` makes an 8-character code (letters and digits that cannot be mistaken for each other) and keeps only
     its SHA-256 (table wall_pairings, migration 060). The PC shows it as a QR code that opens the wall's address with the
     code filled in, and as text to type on a tablet without a camera.
  2. The tablet opens https://<PC>:<port>/wall and sends the code; `pair_redeem` accepts a code once, before it expires,
     and returns a new access token. Only the token's SHA-256 is stored (table walls); the token lives in the tablet
     browser's cookie (HttpOnly, Secure, SameSite=Strict).
  3. Every wall request carries the cookie; `authenticate` finds the wall and checks it was not revoked.
The same code can pair the Mitra Home app in wall mode instead (Settings shows a second QR with the PC's address and
key for it; migration 063): `pair_redeem(kind="app")`, the token then travels as a bearer over HTTPS pinned to the PC's
key (/api/wall/*, webapp/routes_wall_api.py) and the app works from its own copy while the PC is off. A token works
only for its own kind: an app wall's token never opens the wall pages, a browser wall's cookie never the API.
The wall acts as a limited member named after the wall (`actor`): it may tick family lists and children's routines,
nothing else; money shows only after an adult types their PIN on the wall (webapp/routes_wall.py), for a minute.

Routines: a child's repeating jobs by part of the day, each worth stars; `day_view` lists them with what is done today
and the stars of this week (Monday to Sunday). Stars become allowance at the family's rate (`star_cents`, family.json
wall.star_cents, default 25).
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
PAIR_MINUTES = 15
MAX_WALLS = 5
SEEN_EVERY = 60
TOKEN_LEN = 43  # secrets.token_urlsafe(32)
KINDS = ("browser", "app")
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O, 1/I/L
CODE_LEN = 8
_URLSAFE = re.compile(r"^[A-Za-z0-9_-]+$")

PARTS = ("morning", "afternoon", "evening")
PART_LABEL = {"morning": "Morning", "afternoon": "After school", "evening": "Evening"}
DAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
# Icons a routine may show on the wall (stroke paths, 24x24); the key is stored, never a path from a form.
ICONS = {
    "star": "M12 3l2.6 5.4 5.9.9-4.3 4.1 1 5.8L12 16.6 6.8 19.2l1-5.8L3.5 9.3l5.9-.9z",
    "bed": "M3 18v-7h18v7M3 14h18M7 11V8h5v3",
    "tooth": "M5 4h7v3H5zM8 7v13",
    "shirt": "M8 4l-5 3 2 4 2-1v10h10V10l2 1 2-4-5-3c-.6 1.8-2.2 3-4 3s-3.4-1.2-4-3z",
    "bag": "M6 8h12l1 12H5zM9 8V6a3 3 0 0 1 6 0v2M9 12h6",
    "book": "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM8 7h7",
    "music": "M9 18V6l10-2v12M9 18a2.5 2.5 0 1 1-2.5-2.5H9M19 16a2.5 2.5 0 1 1-2.5-2.5H19",
    "paw": "M8 13c-2 2-3 4-1 6 2 1 3-1 5-1s3 2 5 1c2-2 1-4-1-6-1.4-1.4-2.4-2-4-2s-2.6.6-4 2zM6 9.5h.01M10 6.5h.01M14 6.5h.01M18 9.5h.01",
    "plate": "M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM12 16a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "bin": "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
    "broom": "M14 3l-4 8M6 21l4-10 4 2-2 8zM9 21h6",
    "bath": "M4 12h16v3a5 5 0 0 1-5 5H9a5 5 0 0 1-5-5zM6 12V6a2 2 0 0 1 4 0",
    "sun": "M12 3v2M12 19v2M5 12H3M21 12h-2M12 16a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    "moon": "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z",
}
ICON_LABEL = {"star": "Star", "bed": "Bed", "tooth": "Teeth", "shirt": "Clothes", "bag": "School bag", "book": "Book",
              "music": "Music", "paw": "Pet", "plate": "Table", "bin": "Bins", "broom": "Tidy", "bath": "Bath",
              "sun": "Morning", "moon": "Bedtime"}


class WallError(ValueError):
    """A sentence for the person."""


def _now():
    return dt.datetime.now().replace(microsecond=0)


def _ts(t):
    return t.isoformat(timespec="seconds")


def _hash(s):
    return hashlib.sha256(s.encode("ascii")).hexdigest()


def _con(path=None):
    return _db.connect(path or DB, row=True)


def clean_name(name):
    s = " ".join("".join(ch if ch.isprintable() else " " for ch in str(name or "")).split())[:40]
    return s or None


def clean_code(code):
    """What a person typed (any case, spaces or a dash) -> the 8 code characters, or "" when it cannot be a code."""
    s = re.sub(r"[\s-]+", "", str(code or "")).upper()
    return s if len(s) == CODE_LEN and all(ch in CODE_ALPHABET for ch in s) else ""


def pretty_code(code):
    return f"{code[:4]}-{code[4:]}"


def live_count(con):
    return con.execute("SELECT COUNT(*) FROM walls WHERE revoked_at IS NULL").fetchone()[0]


# ---- pairing and sign-in ------------------------------------------------------------------------------------------
def pair_start(con, name, by="", now=None):
    """A one-time code for a new wall. -> (code, {'name','expires_at'}). Raises WallError. An older unused code stops."""
    label = clean_name(name)
    if not label:
        raise WallError("Give the wall a name, for example Kitchen wall.")
    if live_count(con) >= MAX_WALLS:
        raise WallError(f"{MAX_WALLS} walls are paired already. Remove one first.")
    now = now or _now()
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
    exp = now + dt.timedelta(minutes=PAIR_MINUTES)
    con.execute("UPDATE wall_pairings SET used_at=? WHERE used_at IS NULL", (_ts(now),))
    con.execute("INSERT INTO wall_pairings(code_hash, name, created_at, created_by, expires_at) VALUES (?,?,?,?,?)",
                (_hash(code), label, _ts(now), by or None, _ts(exp)))
    con.commit()
    return code, {"name": label, "expires_at": _ts(exp)}


def pair_redeem(con, code, now=None, kind="browser", version=None):
    """A code into a wall. -> (token, {'id','name','kind'}) or None (wrong, used or expired code; too many walls)."""
    if kind not in KINDS:
        return None
    code = clean_code(code)
    if not code:
        return None
    now = now or _now()
    r = con.execute("SELECT id, name, created_by, expires_at FROM wall_pairings WHERE code_hash=? AND used_at IS NULL",
                    (_hash(code),)).fetchone()
    if not r or r["expires_at"] < _ts(now):
        return None
    if con.execute("UPDATE wall_pairings SET used_at=? WHERE id=? AND used_at IS NULL", (_ts(now), r["id"])).rowcount != 1:
        return None
    if live_count(con) >= MAX_WALLS:
        con.commit()
        return None
    token = secrets.token_urlsafe(32)
    if kind == "app":
        cur = con.execute("INSERT INTO walls(name, token_hash, created_at, created_by, last_seen, kind, app_version) "
                          "VALUES (?,?,?,?,?,?,?)", (r["name"], _hash(token), _ts(now), r["created_by"], _ts(now), kind,
                                                     _version(version)))
    else:
        cur = con.execute("INSERT INTO walls(name, token_hash, created_at, created_by, last_seen) VALUES (?,?,?,?,?)",
                          (r["name"], _hash(token), _ts(now), r["created_by"], _ts(now)))
    con.execute("UPDATE wall_pairings SET wall_id=? WHERE id=?", (cur.lastrowid, r["id"]))
    con.commit()
    return token, {"id": cur.lastrowid, "name": r["name"], "kind": kind}


def _version(v):
    v = str(v or "")[:20]
    return v if re.fullmatch(r"[0-9A-Za-z.+-]{1,20}", v) else None


def authenticate(con, token, now=None, kind="browser"):
    """The wall behind a token of this kind (browser = the cookie, app = the API's bearer). -> {'id','name','kind'},
    {'revoked': True}, or None (not a wall of this household, or a token of the other kind)."""
    token = str(token or "").strip()
    if len(token) != TOKEN_LEN or not _URLSAFE.match(token):
        return None
    try:
        r = con.execute("SELECT id, name, last_seen, revoked_at, kind FROM walls WHERE token_hash=?", (_hash(token),)).fetchone()
    except sqlite3.OperationalError:  # before migration 063: every wall is a browser wall
        if kind != "browser":
            return None
        r = con.execute("SELECT id, name, last_seen, revoked_at, 'browser' AS kind FROM walls WHERE token_hash=?",
                        (_hash(token),)).fetchone()
    if not r or r["kind"] != kind:
        return None
    if r["revoked_at"]:
        return {"revoked": True}
    now = now or _now()
    if not r["last_seen"] or (now - dt.datetime.fromisoformat(r["last_seen"])).total_seconds() >= SEEN_EVERY:
        try:
            con.execute("UPDATE walls SET last_seen=? WHERE id=?", (_ts(now), r["id"]))
            con.commit()
        except sqlite3.OperationalError:
            pass  # busy: the wall still works; last_seen catches up on a later request
    return {"id": r["id"], "name": r["name"], "kind": r["kind"]}


def app_seen(con, wall_id, version=None, synced=False, now=None):
    """An app wall's contact: its version, and when it took a copy (`synced`)."""
    now = now or _now()
    con.execute("UPDATE walls SET app_version=COALESCE(?, app_version)" + (", last_sync=?" if synced else "") + " WHERE id=?",
                (_version(version), *((_ts(now),) if synced else ()), int(wall_id)))
    con.commit()


def revoke(con, wall_id, now=None):
    cur = con.execute("UPDATE walls SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (_ts(now or _now()), int(wall_id)))
    con.commit()
    return cur.rowcount == 1


STALE_DAYS = 14  # an app wall that has not taken a copy for this long gets a line on the PC's Today (offline plan D2)


def stale(con, now=None):
    """App walls whose copy is STALE_DAYS old or more (or that never took one after a day): [{'name', 'days'}]."""
    out = []
    for w in listing(con, now):
        if w["kind"] != "app":
            continue
        if w["sync_days"] is None:
            made = (now or _now()).date() - dt.date.fromisoformat(w["created"])
            if made.days >= 1:
                out.append({"name": w["name"], "days": None})
        elif w["sync_days"] >= STALE_DAYS:
            out.append({"name": w["name"], "days": w["sync_days"]})
    return out


def listing(con, now=None):
    now = now or _now()
    try:
        rows = con.execute("SELECT id, name, created_at, last_seen, kind, last_sync FROM walls WHERE revoked_at IS NULL "
                           "ORDER BY id DESC").fetchall()
    except sqlite3.OperationalError:  # before migration 063
        rows = [{**dict(r), "kind": "browser", "last_sync": None} for r in
                con.execute("SELECT id, name, created_at, last_seen FROM walls WHERE revoked_at IS NULL ORDER BY id DESC")]
    out = []
    for r in rows:
        age = None
        if r["last_sync"]:
            age = (now.date() - dt.date.fromisoformat(r["last_sync"][:10])).days
        out.append({"id": r["id"], "name": r["name"], "created": r["created_at"][:10],
                    "last_seen": (r["last_seen"] or "").replace("T", " ")[:16], "kind": r["kind"],
                    "last_sync": (r["last_sync"] or "").replace("T", " ")[:16], "sync_days": age})
    return out


def actor(w):
    """Who a wall is to edit_actions: a limited member named after the wall (family lists and routines only)."""
    return {"name": w["name"], "role": "limited", "wall": w["id"]}


# ---- routines and stars -------------------------------------------------------------------------------------------
def star_cents():
    try:
        v = int((config.family().get("wall") or {}).get("star_cents", 25))
    except (TypeError, ValueError):
        v = 25
    return max(0, min(v, 500))


def part_of(now):
    """'morning' before noon, 'afternoon' until 5 PM, else 'evening'."""
    h = now.hour
    return "morning" if h < 12 else "afternoon" if h < 17 else "evening"


def week_start(day):
    return day - dt.timedelta(days=day.weekday())


def children(con):
    """[name] of the household's children and other limited people (not adults, not pets), in family order."""
    try:
        rows = con.execute("SELECT name, role FROM members ORDER BY id").fetchall()
    except sqlite3.OperationalError as e:
        if _db.missing(e):
            return []
        raise
    return [r[0] for r in rows if (r[1] or "").lower() not in ("adult", "pet")]


def _on(weekdays, day):
    codes = [c for c in str(weekdays or "").split(",") if c]
    return not codes or DAYS[day.weekday()] in codes


def routines(con, member=None, active=True):
    sql = "SELECT id, member, part, title, icon, stars, weekdays, sort FROM routines"
    where, args = [], []
    if active:
        where.append("status='active'")
    if member:
        where.append("member=?")
        args.append(member)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY member, CASE part WHEN 'morning' THEN 0 WHEN 'afternoon' THEN 1 ELSE 2 END, sort, id"
    try:
        cur = con.execute(sql, args)  # named or plain rows: callers open the database either way
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur]
    except sqlite3.OperationalError as e:
        if _db.missing(e):
            return []
        raise


def stars_between(con, member, start, end):
    try:
        r = con.execute("SELECT COALESCE(SUM(d.stars), 0) FROM routine_done d JOIN routines r ON r.id = d.routine_id "
                        "WHERE r.member=? AND d.day BETWEEN ? AND ?", (member, start.isoformat(), end.isoformat())).fetchone()
    except sqlite3.OperationalError as e:
        if _db.missing(e):
            return 0
        raise
    return int(r[0] or 0)


def day_view(con, day, part=None):
    """The chores screen: [{'name','parts': {part: [routine + done]}, 'done','total','stars_week','cents_week'}] for every
    child with at least one routine today (in the order of the family list)."""
    done = {}
    try:
        for r in con.execute("SELECT routine_id FROM routine_done WHERE day=?", (day.isoformat(),)):
            done[r[0]] = True
    except sqlite3.OperationalError as e:
        if not _db.missing(e):
            raise
    ws, we = week_start(day), week_start(day) + dt.timedelta(days=6)
    rate = star_cents()
    out = []
    by = {}
    for r in routines(con):
        if _on(r["weekdays"], day):
            by.setdefault(r["member"], []).append(r)
    order = children(con)
    for name in order + sorted(n for n in by if n not in order):
        rs = by.get(name)
        if not rs:
            continue
        parts = {p: [] for p in PARTS}
        for r in rs:
            parts[r["part"]].append({**r, "done": r["id"] in done, "path": ICONS.get(r["icon"], ICONS["star"])})
        shown = parts[part] if part else rs
        stars = stars_between(con, name, ws, we)
        out.append({"name": name, "parts": parts, "done": sum(1 for r in shown if r.get("done", r["id"] in done)),
                    "total": len(shown), "stars_week": stars, "cents_week": stars * rate,
                    "goal": goal_view(con, name, day, rate)})
    return out


GOAL_MAX_STARS = 10000
WEEKS_PER_MONTH = 52 / 12


def goals():
    """{child: {'title','stars','since'}} from family.json wall.goals (a goal counts the stars earned since `since`)."""
    try:
        g = (config.family().get("wall") or {}).get("goals") or {}
    except Exception:  # noqa: BLE001 (an unreadable family.json shows no goals)
        return {}
    return {k: v for k, v in g.items() if isinstance(v, dict) and v.get("title") and int(v.get("stars") or 0) > 0}


def goal_view(con, member, today, rate=None):
    """The child's goal with progress, or None. -> {'title','stars','earned','left','pct','reached','cents'}"""
    g = goals().get(member)
    if not g:
        return None
    try:
        since = dt.date.fromisoformat(str(g.get("since") or "")[:10])
    except ValueError:
        since = today
    target = int(g["stars"])
    earned = stars_between(con, member, since, today)
    rate = star_cents() if rate is None else rate
    return {"title": str(g["title"]), "stars": target, "earned": earned, "left": max(target - earned, 0),
            "pct": min(100, earned * 100 // target), "reached": earned >= target, "cents": target * rate}


def week_max_stars(rows):
    """Stars a child can earn in a week if every job is done (a job on MO,WE counts twice)."""
    return sum(int(r["stars"]) * (len([c for c in str(r["weekdays"] or "").split(",") if c]) or 7) for r in rows)


# ---- rewards: what a child spends stars on ----------------------------------------------------------------------------
MAX_REWARDS = 30
REWARD_MAX_STARS = 500


def _q(con, sql, args=()):
    try:
        cur = con.execute(sql, args)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur]
    except sqlite3.OperationalError as e:
        if _db.missing(e):
            return []
        raise


def star_balance(con, member):
    """Stars a child can spend: every star earned (all time) minus the stars of their rewards asked for or given.
    The allowance is separate: it pays for the week's stars and does not use them up."""
    earned = _q(con, "SELECT COALESCE(SUM(d.stars), 0) AS n FROM routine_done d JOIN routines r ON r.id = d.routine_id "
                     "WHERE r.member=?", (member,))
    held = _q(con, "SELECT COALESCE(SUM(stars), 0) AS n FROM reward_claims WHERE member=? AND status IN ('asked', 'given')",
              (member,))
    return int((earned[0]["n"] if earned else 0) or 0) - int((held[0]["n"] if held else 0) or 0)


def rewards(con, member=None):
    """Active rewards ([{'id','title','stars','member'}]); with `member`: those for that child or for any child."""
    if member:
        return _q(con, "SELECT id, title, stars, member FROM rewards WHERE status='active' AND (member IS NULL OR member=?) "
                       "ORDER BY stars, title", (member,))
    return _q(con, "SELECT id, title, stars, member FROM rewards WHERE status='active' ORDER BY stars, title")


def reward_view(con, member):
    """A child's stars to spend and their rewards: [{..., 'can': enough stars, 'asked': a request waits}]."""
    bal = star_balance(con, member)
    waiting = {r["reward_id"] for r in _q(con, "SELECT reward_id FROM reward_claims WHERE member=? AND status='asked'",
                                          (member,))}
    return {"balance": bal, "rewards": [{**r, "can": r["stars"] <= bal and r["id"] not in waiting,
                                         "asked": r["id"] in waiting} for r in rewards(con, member)]}


def reward_requests(con):
    """Requests waiting for an adult, oldest first: [{'id','member','title','stars','asked_at'}]."""
    return _q(con, "SELECT c.id, c.member, w.title, c.stars, c.asked_at FROM reward_claims c JOIN rewards w ON w.id=c.reward_id "
                   "WHERE c.status='asked' ORDER BY c.asked_at, c.id")


DAY_SHORT = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri", "SA": "Sat", "SU": "Sun"}


def days_text(weekdays):
    codes = [c for c in str(weekdays or "").split(",") if c]
    if not codes or len(codes) == 7:
        return "Every day"
    if codes == ["MO", "TU", "WE", "TH", "FR"]:
        return "School days"
    if codes == ["SA", "SU"]:
        return "Weekends"
    return ", ".join(DAY_SHORT.get(c, c) for c in codes)


def manage(con, today):
    """Family > Routines (adults): every child with their jobs by part of the day, and the stars of this week.
    -> {'children': [{'name','parts': [(part, label, [routine])], 'n','stars_week','cents_week'}], 'rate'}"""
    rate = star_cents()
    ws = week_start(today)
    by = {}
    for r in routines(con):
        by.setdefault(r["member"], []).append({**r, "days": days_text(r["weekdays"]),
                                               "path": ICONS.get(r["icon"], ICONS["star"])})
    out = []
    for name in children(con):
        rs = by.get(name, [])
        stars = stars_between(con, name, ws, ws + dt.timedelta(days=6))
        top = week_max_stars(rs)
        out.append({"name": name, "n": len(rs), "stars_week": stars, "cents_week": stars * rate,
                    "max_week": top, "max_week_cents": top * rate,
                    "max_month": round(top * rate * WEEKS_PER_MONTH / 100, 2), "goal": goal_view(con, name, today, rate),
                    "parts": [(p, PART_LABEL[p], [r for r in rs if r["part"] == p]) for p in PARTS]})
    for k in out:
        k["rewards"] = reward_view(con, k["name"])
    return {"children": out, "rate": rate, "rewards": rewards(con), "requests": reward_requests(con)}


def tick(con, routine_id, day, by, done=True, now=None):
    """Mark a routine done (or not) on `day`. -> True when something changed. Raises WallError for a routine that is
    gone or not on that day."""
    r = con.execute("SELECT id, stars, weekdays, status FROM routines WHERE id=?", (int(routine_id),)).fetchone()
    if not r or r[3] != "active":  # by position: callers open the database with or without named rows
        raise WallError("That job is no longer on the list.")
    rid, stars, weekdays = r[0], r[1], r[2]
    if not _on(weekdays, day):
        raise WallError("That job is not for today.")
    if done:
        cur = con.execute("INSERT OR IGNORE INTO routine_done(routine_id, day, stars, done_by, done_at) VALUES (?,?,?,?,?)",
                          (rid, day.isoformat(), stars, by or None, _ts(now or _now())))
    else:
        cur = con.execute("DELETE FROM routine_done WHERE routine_id=? AND day=?", (rid, day.isoformat()))
    return cur.rowcount == 1


def clean_weekdays(value):
    """'MO,WE' / ['MO','WE'] -> 'MO,WE' in week order; '' = every day. Raises WallError for anything else."""
    items = value if isinstance(value, (list, tuple)) else str(value or "").replace(" ", "").split(",")
    want = {str(x).upper()[:2] for x in items if str(x).strip()}
    bad = want - set(DAYS)
    if bad:
        raise WallError("Days are MO, TU, WE, TH, FR, SA, SU.")
    if len(want) == len(DAYS):
        return ""
    return ",".join(d for d in DAYS if d in want)


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
            print("revoked" if revoke(con, int(argv[1])) else "no such wall")
            return 0
        if cmd == "list":
            rows = listing(con)
            for w in rows:
                print(f"{w['id']:>3}  {w['name']}  paired {w['created']}  last seen {w['last_seen'] or 'never'}")
            print(f"{len(rows)} wall(s)")
            return 0
    finally:
        con.close()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
