"""Put Mitra Home's due dates on a Google calendar of its own: bills and statement dues, ID and policy expiries,
checkups, school items, birthdays, festivals and seasonal tasks. No Claude, no AI, standard library only.

  python data/calendar_sync.py status               signed in with the permission? the calendar? what was last synced?
  python data/calendar_sync.py preview              what would be added, changed and removed (changes nothing)
  python data/calendar_sync.py apply --yes          do it
  python data/calendar_sync.py auto                 what the daily task runs: applies only if auto-sync is switched on
  python data/calendar_sync.py remove --yes         delete the Mitra Home calendar from Google again

Safety:
  * It writes ONLY to a secondary calendar named "Mitra Home" (brand.CALENDAR_NAME) that it creates itself. The permission it asks for
    (calendar.app.created) is limited by Google to calendars this app made, so your own events cannot be touched.
  * Nothing is written until you approve a preview (or switch on auto-sync in Settings).
  * Each event has a stable id derived from the item, so nothing is duplicated. A moved due date moves the event, a
    changed title, amount or reminder updates it, and a paid or hidden item is removed. Past events are left alone.
  * Titles are "Bill: Electric Co" style. Amounts are left out unless you switch them on. Only vendor names and
    titles leave this PC; no statement, account number or document.
  * Needs the sign-in with the extra permission: Settings > Connections > Google Calendar, or `google_calendar.py auth --write`.
  * An event moved or deleted in Google is not overwritten: calendar_back.py notes it and the Inbox asks an adult;
    until then this sync leaves that event alone.

Library: plan(con=None, today=None) -> dict; apply(plan) -> dict; remove() -> bool; status() -> dict.
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import brand  # noqa: E402
import config  # noqa: E402
import google_calendar as gc  # noqa: E402

STATE = paths.CONFIG / "calendar_sync.json"
CAL_NAME = brand.CALENDAR_NAME
DEFAULTS = {"horizon": 90, "kinds": None, "amounts": False, "reminder_days": 1, "auto": False}
MAX_OPS = 300
REMIND_HOUR = 9  # the reminder pops up at 9:00 on the day it is due (minutes are counted back from midnight)


def settings():
    s = dict(DEFAULTS)
    s.update({k: v for k, v in ((config.family().get("google_calendar") or {}).get("sync") or {}).items() if k in DEFAULTS})
    s["horizon"] = max(7, min(365, int(s["horizon"] or 90)))
    s["reminder_days"] = max(0, min(14, int(s["reminder_days"] or 0)))
    return s


def _state():
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(st):
    config.write_json(STATE, st)


def _waiting():
    """Event ids calendar_back.py noted as moved or deleted in Google (its file, read here so neither imports the other)."""
    try:
        d = json.loads((paths.CONFIG / "calendar_back.json").read_text(encoding="utf-8"))
        return set((d.get("changes") or {}) if isinstance(d, dict) else {})
    except (OSError, ValueError, AttributeError):
        return set()


def event_id(key):
    """Google event ids are base32hex (0-9, a-v), 5-1024 characters: the hex digest qualifies and is stable."""
    return hashlib.sha1(("familyagent:" + str(key)).encode("utf-8")).hexdigest()


def body_for(item, s):
    import action_state as _as
    key = item.get("key") or _as.key(item)
    d = item["date"]
    summary = f"{item['kind']}: {item['title']}"
    if s["amounts"] and item.get("amount") is not None:
        from money import fmt
        summary += f" ({fmt(item['amount'])})"
    desc = [x for x in (item.get("detail") or "", f"From {brand.PRODUCT}. Mark it done there, not here.") if x]
    minutes = max(0, s["reminder_days"] * 1440 - REMIND_HOUR * 60)
    body = {"id": event_id(key), "summary": summary[:200], "description": "\n".join(desc)[:1000],
            "start": {"date": d.isoformat()}, "end": {"date": (d + dt.timedelta(days=1)).isoformat()},
            "transparency": "transparent",
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutes}]},
            "extendedProperties": {"private": {"familyagent": _as.display_id(key)}}}
    sig = hashlib.sha1(json.dumps([body["summary"], body["description"], d.isoformat(), minutes], sort_keys=True).encode()).hexdigest()
    return body, sig


def plan(con=None, today=None):
    """-> {create, update, delete: [{id, date, title}], same, problems}. Changes nothing, calls nothing."""
    import action_items as ai
    import db
    today = today or dates.today()
    s = settings()
    own = con is None
    con = con or db.connect(paths.DB, readonly=True)
    try:
        items = ai.collect_items(con, today, s["horizon"])
    finally:
        if own:
            con.close()
    if s["kinds"]:
        want = {str(k).strip().lower() for k in s["kinds"]}
        items = [i for i in items if i["kind"].lower() in want]
    items = [i for i in items if i["date"] >= today]  # overdue things stay on the dashboard, not on the calendar
    # weekly classes repeat: they belong in the .ics file (one repeating event each), not as two-day copies here
    items = [i for i in items if (i.get("ref") or (None,))[0] != "activity_schedules"]
    st = _state()
    known = st.get("events") or {}
    import action_state as _as
    waiting = _waiting()  # changed in Google, waiting for an adult's answer (calendar_back.py): leave those events alone
    want_ids, out = {}, {"create": [], "update": [], "delete": [], "same": 0, "problems": [], "waiting": len(waiting)}
    for it in sorted(items, key=lambda i: (i["date"], i["kind"], i["title"])):
        body, sig = body_for(it, s)
        want_ids[body["id"]] = (body, sig)
        ref = it.get("ref") or (None, None)
        row = {"id": body["id"], "date": it["date"].isoformat(), "title": body["summary"],
               "ref": [ref[0], ref[1]] if ref[0] and ref[1] is not None else None, "key": it.get("key") or _as.key(it)}
        if body["id"] in waiting:
            continue
        if body["id"] not in known:
            out["create"].append(row)
        elif known[body["id"]].get("hash") != sig:
            out["update"].append(row)
        else:
            out["same"] += 1
    for eid, meta in known.items():
        if eid not in want_ids and eid not in waiting and str(meta.get("date", "")) >= today.isoformat():
            out["delete"].append({"id": eid, "date": meta.get("date", ""), "title": meta.get("title", "")})
    out["_bodies"] = {k: v for k, v in want_ids.items()}
    return out


def _require():
    if not gc.can_write():
        raise gc.AuthError(f"{brand.PRODUCT} is not allowed to make its own calendar yet. In the dashboard: Settings > Connections > Google "
                           "Calendar > Allow it.")


def _ours(summary, st):
    """Is this the calendar the app made? Its current name, the name it was made under (kept in the state file), or a
    name an earlier version used: a rename of the product renames the calendar in place and never makes a second one."""
    return bool(summary) and summary in {CAL_NAME, st.get("calendar_name") or "", *brand.KNOWN_CALENDAR_NAMES}


def _ensure_calendar(st, token):
    cid = st.get("calendar_id")
    if cid:
        try:
            got = gc._get(f"/calendars/{urllib.parse.quote(cid, safe='')}", None, token)
            if _ours(got.get("summary"), st):
                if got.get("summary") != CAL_NAME:
                    try:  # the product was renamed: give the calendar the new name, keep its events
                        gc._send("PATCH", f"/calendars/{urllib.parse.quote(cid, safe='')}", {"summary": CAL_NAME}, token=token)
                    except gc.CalendarError:
                        return cid  # could not rename it now; still ours, try again at the next sync
                st["calendar_name"] = CAL_NAME
                return cid
        except gc.CalendarError:
            pass
    tz = None
    try:  # the account's own time zone, so "9:00" means 9:00 where the family lives
        tz = gc._get("/users/me/calendarList/primary", None, token).get("timeZone")
    except gc.CalendarError:
        pass
    made = gc._send("POST", "/calendars", {"summary": CAL_NAME, "description": f"Due dates from {brand.PRODUCT}. Managed by the "
                                           f"{brand.PRODUCT} app on the family PC; edit things there.", **({"timeZone": tz} if tz else {})}, token=token)
    cid = made.get("id")
    if not cid or cid == "primary" or "@" in cid and cid.endswith("@gmail.com"):
        raise gc.CalendarError("Google did not return a separate calendar; nothing was written")
    st["calendar_id"] = cid
    st["calendar_name"] = CAL_NAME
    st["events"] = {}
    return cid


def apply(p=None, today=None):
    """Carry out a plan. -> {created, updated, deleted, problems}. Raises AuthError when not allowed."""
    _require()
    today = today or dates.today()
    p = p or plan(today=today)
    bodies = p.get("_bodies") or {}
    token = gc.access_token()
    st = _state()
    cid = _ensure_calendar(st, token)
    base = f"/calendars/{urllib.parse.quote(cid, safe='')}/events"
    known = st.setdefault("events", {})
    res = {"created": 0, "updated": 0, "deleted": 0, "problems": []}
    ops = 0
    for kind in ("create", "update"):
        for row in p[kind]:
            if ops >= MAX_OPS:
                res["problems"].append("stopped after %d changes; run it again for the rest" % MAX_OPS)
                break
            ops += 1
            body, sig = bodies[row["id"]]
            try:
                try:
                    if kind == "create":
                        gc._send("POST", base, body, token=token)
                    else:
                        gc._send("PATCH", f"{base}/{row['id']}", {k: v for k, v in body.items() if k != "id"}, token=token)
                except gc.Conflict:  # known to Google already (our record was lost): update it instead
                    gc._send("PATCH", f"{base}/{row['id']}", {k: v for k, v in body.items() if k != "id"}, token=token)
                except gc.Gone:  # removed by hand in Google: put it back
                    if kind == "update":
                        gc._send("POST", base, body, token=token)
                    else:
                        raise
                known[row["id"]] = {"hash": sig, "date": row["date"], "title": row["title"], "ref": row.get("ref"),
                                    "key": row.get("key")}
                res["created" if kind == "create" else "updated"] += 1
            except gc.AuthError:
                _save(st)
                raise
            except gc.CalendarError as e:
                res["problems"].append(f"{row['title']}: {e}")
    for row in p["delete"]:
        if ops >= MAX_OPS:
            break
        ops += 1
        try:
            try:
                gc._send("DELETE", f"{base}/{row['id']}", token=token)
            except gc.Gone:
                pass
            known.pop(row["id"], None)
            res["deleted"] += 1
        except gc.AuthError:
            _save(st)
            raise
        except gc.CalendarError as e:
            res["problems"].append(f"{row['title']}: {e}")
    st["last_sync"] = dt.datetime.now().isoformat(timespec="seconds")
    _save(st)
    return res


def remove():
    """Delete the Mitra Home calendar from Google and forget what was synced. -> True if there was one."""
    _require()
    st = _state()
    cid = st.get("calendar_id")
    if not cid:
        return False
    token = gc.access_token()
    try:
        got = gc._get(f"/calendars/{urllib.parse.quote(cid, safe='')}", None, token)
        if _ours(got.get("summary"), st):  # never delete anything but the calendar this app made
            gc._send("DELETE", f"/calendars/{urllib.parse.quote(cid, safe='')}", token=token)
    except gc.Gone:
        pass
    STATE.unlink(missing_ok=True)
    return True


def status():
    st = _state()
    return {"can_write": gc.can_write(), "calendar": bool(st.get("calendar_id")), "synced_events": len(st.get("events") or {}),
            "last_sync": st.get("last_sync", ""), "settings": settings()}


def summary_line(p):
    return (f"{len(p['create'])} to add, {len(p['update'])} to change, {len(p['delete'])} to remove, {p['same']} already there")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["status", "preview", "apply", "auto", "remove"])
    ap.add_argument("--yes", action="store_true", help="confirm apply / remove")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "status":
            s = status()
            print(f"allowed to make its own calendar: {'yes' if s['can_write'] else 'no (python data/google_calendar.py auth --write)'}")
            print(f"{CAL_NAME} calendar exists:      {'yes' if s['calendar'] else 'not yet'}   events synced: {s['synced_events']}")
            print(f"last sync: {s['last_sync'] or 'never'}   auto-sync: {'on' if s['settings']['auto'] else 'off'}")
        elif a.cmd == "preview":
            p = plan()
            print(summary_line(p))
            for k, label in (("create", "add"), ("update", "change"), ("delete", "remove")):
                for r in p[k]:
                    print(f"  {label:<6} {r['date']}  {r['title']}")
        elif a.cmd == "apply":
            p = plan()
            print(summary_line(p))
            if not a.yes:
                print("Nothing was written. Run again with --yes to apply.")
                return 0
            r = apply(p)
            print(f"added {r['created']}, changed {r['updated']}, removed {r['deleted']}")
            for x in r["problems"]:
                print("  problem:", x)
        elif a.cmd == "auto":
            if not settings()["auto"]:
                print("auto-sync is off (Settings > Connections > Google Calendar)")
                return 0
            try:
                r = apply()
                print(f"auto-sync: added {r['created']}, changed {r['updated']}, removed {r['deleted']}")
            except gc.AuthError as e:  # an expired sign-in must not make the whole daily task fail
                print(f"auto-sync skipped: {e}")
        elif a.cmd == "remove":
            if not a.yes:
                print(f"This deletes the {CAL_NAME} calendar from Google. Run again with --yes.")
                return 0
            print("removed" if remove() else f"there was no {CAL_NAME} calendar")
    except gc.CalendarError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
