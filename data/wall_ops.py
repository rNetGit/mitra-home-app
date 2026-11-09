"""Taps an app wall made while the PC was off, applied when it next reaches the PC (POST /api/wall/push,
webapp/routes_wall_api.py; offline plan B3).

The Mitra Home app in wall mode keeps working from its copy: a child ticks a job, someone ticks or adds a list item, a
child asks for a reward. Each tap waits on the tablet with an id of its own and goes to the PC in order at the next
contact. Here every tap is applied through edit_actions as the wall (wall.actor: a limited member named after the wall),
with the same checks as a tap on the browser wall, and a receipt is kept in `wall_ops` (migration 063): a tap sent again
gets the first answer and is never applied twice. The PC wins: a refused tap goes back with its sentence.

A job tick carries the day it was made, so a job ticked at 23:58 counts for that day even when the PC hears of it days
later; it must be within the last REPLAY_DAYS, not in the future, and the job must have been due that weekday.

  python data/wall_ops.py status      receipts per wall
"""
import datetime as dt
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import dates  # noqa: E402
import db  # noqa: E402
import paths  # noqa: E402

MAX_OPS = 50
REPLAY_DAYS = 14
OPS = ("list_add", "list_tick", "routine_tick", "reward_ask", "face_set", "photo_style_set")
PENDING = "~"          # wall_ops.op prefix while a tap is being applied
PENDING_STALE = 120    # seconds: an older in-flight claim belonged to a request that died
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def _int(x):
    if isinstance(x, bool) or not isinstance(x, int):
        raise ValueError
    return x


def _done(o):
    done = o.get("done", True)
    if not isinstance(done, bool):
        raise ValueError
    return done


def _day(text, today):
    """The day a job was ticked: within the last REPLAY_DAYS and not after today. -> date, or a sentence (str)."""
    try:
        d = dt.date.fromisoformat(str(text or "")[:10])
    except ValueError:
        raise ValueError from None
    if d > today:
        return "That day has not come yet."
    if (today - d).days > REPLAY_DAYS:
        return f"Ticked more than {REPLAY_DAYS} days ago: too late to count."
    return d


def _apply(w, op, o, today):
    import edit_actions as ea
    import wall as W
    actor = W.actor(w)
    if op == "list_add":
        text = o.get("text")
        if not isinstance(text, str):
            raise ValueError
        return ea.list_item_add(actor, _int(o.get("list_id")), text[:200])
    if op == "list_tick":
        return ea.list_item_tick(actor, _int(o.get("item_id")), _done(o))
    if op == "routine_tick":
        rid = _int(o.get("routine_id"))
        d = _day(o.get("day"), today)
        if isinstance(d, str):
            return False, d
        with db.open(paths.DB, readonly=True, row=True) as con:
            r = con.execute("SELECT weekdays FROM routines WHERE id=? AND status='active'", (rid,)).fetchone()
        if r and not W._on(r["weekdays"], d):
            return False, "That job was not due that day."
        return ea.routine_tick(actor, rid, _done(o), day=d)
    if op == "reward_ask":
        member = o.get("member")
        if not isinstance(member, str):
            raise ValueError
        return ea.reward_ask(actor, _int(o.get("reward_id")), member[:60])
    if op == "face_set":
        clock = o.get("clock")
        if not isinstance(clock, str):
            raise ValueError
        return ea.wall_face_set(actor, clock[:20])
    if op == "photo_style_set":
        style = o.get("style")
        if not isinstance(style, str):
            raise ValueError
        return ea.wall_photo_style_set(actor, style[:20])
    raise ValueError


def _in_flight(row, now):
    if not str(row["op"]).startswith(PENDING):
        return False
    try:
        age = (dt.datetime.fromisoformat(now) - dt.datetime.fromisoformat(str(row["created_at"])[:19])).total_seconds()
    except ValueError:
        return False
    return age < PENDING_STALE


def push(con, w, ops, now=None, today=None):
    """Apply a wall's waiting taps in order. -> [{'id', 'status': ok|rejected|retry, 'message'[, 'repeat']}].
    `con` (row factory) keeps the receipts; each tap opens its own transaction in edit_actions."""
    import edit_actions as ea
    con.row_factory = sqlite3.Row
    now = (now or dt.datetime.now()).isoformat(timespec="seconds")
    today = today or dates.today()
    out, waiting = [], False
    for o in (ops or [])[:MAX_OPS]:
        cid = o.get("id") if isinstance(o, dict) else None
        if not isinstance(cid, str) or not _CLIENT_ID.match(cid):
            out.append({"id": cid if isinstance(cid, str) else None, "status": "rejected", "message": "Bad tap id."})
            continue
        if waiting:  # an earlier tap has to be retried: later ones wait too, so the order on the wall is kept
            out.append({"id": cid, "status": "retry", "message": "Waiting for an earlier tap."})
            continue
        old = con.execute("SELECT id, status, op, message, created_at FROM wall_ops WHERE wall_id=? AND client_id=?",
                          (w["id"], cid)).fetchone()
        if old and _in_flight(old, now):
            out.append({"id": cid, "status": "retry", "message": "Still being saved."})
            waiting = True
            continue
        if old and str(old["op"]).startswith(PENDING):  # a claim whose request died before the tap was applied
            con.execute("DELETE FROM wall_ops WHERE id=?", (old["id"],))
            con.commit()
        elif old:
            out.append({"id": cid, "status": old["status"], "repeat": True, "message": old["message"] or "Already received."})
            continue
        op = o.get("op")
        name = op if op in OPS else "unknown"
        claim = con.execute("INSERT OR IGNORE INTO wall_ops(wall_id, client_id, op, status, created_at) VALUES (?,?,?,'ok',?)",
                            (w["id"], cid, PENDING + name, now))
        con.commit()
        if claim.rowcount != 1:
            out.append({"id": cid, "status": "retry", "message": "Still being saved."})
            waiting = True
            continue
        rid = claim.lastrowid
        try:
            if op not in OPS:
                ok, msg = False, "This app version does not know that tap."
            else:
                try:
                    ok, msg = _apply(w, op, o, today)
                except ValueError:
                    ok, msg = False, "That tap is not complete."
        except BaseException:
            con.execute("DELETE FROM wall_ops WHERE id=?", (rid,))
            con.commit()
            raise
        if not ok and msg == ea.BUSY:
            con.execute("DELETE FROM wall_ops WHERE id=?", (rid,))
            con.commit()
            out.append({"id": cid, "status": "retry", "message": msg})
            waiting = True
            continue
        msg = str(msg or "")[:300]
        con.execute("UPDATE wall_ops SET op=?, status=?, message=? WHERE id=?", (name, "ok" if ok else "rejected", msg, rid))
        con.commit()
        out.append({"id": cid, "status": "ok" if ok else "rejected", "message": msg})
    return out


def status(con):
    """{wall id: {'ok': n, 'rejected': n}}"""
    out = {}
    for r in con.execute("SELECT wall_id, status, COUNT(*) FROM wall_ops WHERE op NOT LIKE '~%' GROUP BY wall_id, status"):
        out.setdefault(r[0], {})[r[1]] = r[2]
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] != ["status"]:
        print(__doc__)
        return 2
    with db.open(paths.DB, readonly=True) as con:
        st = status(con)
    for wid, s in sorted(st.items()):
        print(f"wall {wid}: {s.get('ok', 0)} applied, {s.get('rejected', 0)} refused")
    if not st:
        print("No taps from app walls yet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
