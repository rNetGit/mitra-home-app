"""Changes made in Google Calendar to Mitra Home's own events come back as Inbox questions, never as silent edits.

  python data/calendar_back.py look       read the Mitra Home calendar in Google and note moved or deleted events
  python data/calendar_back.py list       what waits for an answer

calendar_sync.py writes the family's due dates to a calendar of its own in Google. When someone moves one of those
events to another day in Google, or deletes it, `look` notes it in config/calendar_back.json; proposals.py then shows
one Inbox card per change (source calendar_back):
  * moved: "Use the new date" changes the record through edit_actions (a bill's due date, an appointment's day keeping
    its time, a family event, a life item); "Keep ours" puts the event back at Mitra Home's date at the next sync.
    Only those four kinds can take a new date; for anything else (a renewal, a birthday) the card offers "Keep ours".
  * deleted: "Take it off" hides the item from Today and the calendar (action_state, like the Today menu); "Put it
    back" makes the event again at the next sync.
While a change waits, calendar_sync leaves that event alone, so nothing is overwritten before an adult answers.
Events the family made themselves in Google are never read here (they stay in the read-only Google copy), and nothing
is ever written to Google by this module.
"""
import datetime as dt
import json
import pathlib
import sys
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dates  # noqa: E402
import paths  # noqa: E402

STATE = paths.CONFIG / "calendar_back.json"
MAX_PAGES = 10
MOVABLE = ("bills", "appointments", "events", "life_items")


def pending():
    """{event id: change} waiting for an answer."""
    try:
        d = json.loads(STATE.read_text(encoding="utf-8"))
        return d.get("changes") or {} if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(changes):
    config.write_json(STATE, {"changes": changes, "looked": dt.datetime.now().isoformat(timespec="seconds")})


def _date_of(start):
    v = (start or {}).get("date") or str((start or {}).get("dateTime") or "")[:10]
    try:
        return dt.date.fromisoformat(v)
    except ValueError:
        return None


def look(today=None, events=None):
    """Compare Google with what calendar_sync last wrote. -> {'moved','deleted','waiting'}. `events` = Google's event
    list (tests); otherwise read from Google (needs the sync to be set up)."""
    import calendar_sync as cs
    today = today or dates.today()
    st = cs._state()
    known = st.get("events") or {}
    if not st.get("calendar_id") or not known:
        return {"moved": 0, "deleted": 0, "waiting": len(pending())}
    if events is None:
        events = _read(st["calendar_id"], today)
    by_id = {e.get("id"): e for e in events if e.get("id")}
    changes = pending()
    found = {"moved": 0, "deleted": 0}
    for eid, meta in known.items():
        was = str(meta.get("date") or "")
        if not was or was < today.isoformat() or eid in changes:
            continue
        ev = by_id.get(eid)
        if ev is None or ev.get("status") == "cancelled":
            change = {"change": "deleted"}
        else:
            new = _date_of(ev.get("start"))
            if not new or new.isoformat() == was:
                continue
            change = {"change": "moved", "date": new.isoformat()}
        changes[eid] = {**change, "was": was, "title": meta.get("title", ""), "ref": meta.get("ref"),
                        "key": meta.get("key"), "seen": today.isoformat()}
        found[change["change"]] += 1
    _save(changes)
    return {**found, "waiting": len(changes)}


def _read(cid, today):
    """Every event of the Mitra Home calendar from today on, deleted ones included (status cancelled)."""
    import google_calendar as gc
    token = gc.access_token()
    out, page = [], None
    for _ in range(MAX_PAGES):
        params = {"showDeleted": "true", "singleEvents": "true", "maxResults": "2500",
                  "timeMin": f"{today.isoformat()}T00:00:00Z", "fields": "items(id,status,start),nextPageToken"}
        if page:
            params["pageToken"] = page
        got = gc._get(f"/calendars/{urllib.parse.quote(cid, safe='')}/events", params, token)
        out += got.get("items") or []
        page = got.get("nextPageToken")
        if not page:
            break
    return out


def can_move(change):
    ref = change.get("ref") or []
    return change.get("change") == "moved" and len(ref) == 2 and ref[0] in MOVABLE and ref[1] is not None


def target(eid):
    """(table, row id, new date) a moved event's record can take, or None."""
    ch = pending().get(eid)
    if not ch or not can_move(ch):
        return None
    return ch["ref"][0], ch["ref"][1], ch["date"]


def settle(eid, option, actor):
    """The parts of an answer that touch no record (proposals.py makes the record change for "accept" through
    edit_actions first). option: accept (done) | keep (ours goes back to Google) | hide (deleted: take it off).
    -> (ok, message)."""
    import calendar_sync as cs
    changes = pending()
    ch = changes.get(eid)
    if not ch:
        return False, "That change was already answered."
    if (actor or {}).get("role") != "adult":
        return False, "Only adults can do this."
    title = ch.get("title") or "the event"
    if option == "accept":
        msg = ""
    elif option == "hide":
        if ch.get("change") != "deleted":
            return False, "Only a deleted event can be taken off."
        import action_state
        if ch.get("key"):
            action_state.set_state(ch["key"], "ignored", title=title, note="deleted in Google Calendar")
        msg = f"Took {title} off Today and the calendar."
    elif option == "keep":
        st = cs._state()
        if eid in (st.get("events") or {}):
            st["events"][eid]["hash"] = ""  # the next sync writes Mitra Home's date (or makes the event again)
            cs._save(st)
        msg = f"Kept {title} as it is here; Google gets it back at the next sync."
    else:
        return False, "That cannot be done here."
    changes.pop(eid, None)
    _save(changes)
    return True, msg


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "list"
    if cmd == "look":
        try:
            r = look()
        except Exception as e:  # noqa: BLE001 (no sign-in, no network: say so, the daily task goes on)
            print(f"Could not read the Google calendar: {str(e)[:120]}")
            return 1
        print(f"{r['moved']} moved and {r['deleted']} deleted in Google; {r['waiting']} wait in the Inbox.")
        return 0
    if cmd == "list":
        for eid, ch in pending().items():
            print(f"{eid[:10]}  {ch['change']:<8} {ch.get('title', '')}  was {ch.get('was')}" +
                  (f" now {ch['date']}" if ch.get("date") else ""))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
