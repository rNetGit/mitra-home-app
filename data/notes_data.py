"""What the Notes page shows, with no web code: the family's saved items (data/saved.py) filtered for one
viewer, the filter choices, and the pin / tag / archive / add actions through edit_actions (same checks and log as
every other change). Used by the web app (webapp/app.py).

Links are never fetched: a row carries its URL only when it is http(s) (saved.clean_url already refuses anything else).
"""
import datetime as dt
import sqlite3

import db
import dates  # noqa: E402
import edit_actions as ea
import members as mem
import paths
import saved as S

KINDS = S.KINDS
AUDIENCES = S.AUDIENCES
AUDIENCE_LABEL = {"family": "everyone", "adults": "adults only", "private": "only me"}
OPS = ("pin", "unpin", "archive", "tags")
WORDS_MAX = 200
NOTE_SHOWN = 280  # characters of a note shown before "more"


def _con():
    return db.connect(paths.DB, readonly=True)


def _search(user, **kw):
    """saved.search for this viewer; None when the table does not exist yet (an older database)."""
    try:
        con = _con()
    except sqlite3.Error:
        return None
    try:
        return S.search(con, viewer=user, **kw)
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()


def people():
    try:
        con = _con()
    except sqlite3.Error:
        return []
    try:
        return mem.names(con)
    except sqlite3.Error:
        return []
    finally:
        con.close()


def tags(user, today):
    """Every tag on an item this viewer may see (archived and ended included), for the Tag filter."""
    return sorted({t for r in (_search(user, today=today, all=True) or []) for t in r["tag_list"]})


def filters(data, user, today):
    """The filter fields from a request, each kept only when it is one of the offered choices."""
    kind = data.get("kind", "")
    tag = data.get("tag", "")
    who = data.get("who", "")
    return {"q": " ".join(str(data.get("q", "")).split())[:WORDS_MAX],
            "kind": kind if kind in KINDS else "",
            "tag": tag if tag and tag in tags(user, today) else "",
            "who": who if who and who in people() else "",
            "all": data.get("all") in ("1", "on", "true")}


KIND_LABEL = {"link": "Links", "note": "Notes", "place": "Places", "deal": "Deals", "video": "Videos", "repo": "Code",
              "article": "Articles", "social": "Posts"}
SOON_DAYS = 14


def kinds(user, today):
    """[(kind, label, count)] of the kinds this viewer has (open items only), in KINDS order, for the chip row."""
    n = {}
    for r in _search(user, today=today) or []:
        n[r["kind"]] = n.get(r["kind"], 0) + 1
    return [(k, KIND_LABEL.get(k, k.capitalize()), n[k]) for k in KINDS if n.get(k)]


def _ends(until, today):
    """(pill, tone) for a deal's end date: ended (bad), ends today / in N days within SOON_DAYS (warn), else the date."""
    try:
        d = dt.date.fromisoformat(str(until)[:10])
    except ValueError:
        return "", ""
    n = (d - today).days
    if n < 0:
        return "ended", "bad"
    if n <= SOON_DAYS:
        return ("ends today" if n == 0 else "ends tomorrow" if n == 1 else f"ends in {n} days"), "warn"
    return f"until {d:%b} {d.day}" + ("" if d.year == today.year else f", {d.year}"), ""


def _row(r, today=None):
    url = r.get("url") or ""
    note = " ".join(str(r.get("body") or "").split())
    cut = len(note) if len(note) <= NOTE_SHOWN else (note.rfind(" ", 0, NOTE_SHOWN) if " " in note[:NOTE_SHOWN] else NOTE_SHOWN)
    return {"id": r["id"], "kind": r["kind"], "title": r["title"], "pinned": bool(r["pinned"]),
            "url": url if url.startswith(("https://", "http://")) else "", "site": r.get("domain") or "",
            "tags": r["tag_list"], "where": r.get("place_address") or "", "until": r.get("expires_on") or "",
            "note": note[:cut], "more": note[cut:].strip(), "owner": r.get("owner") or "",
            "audience": AUDIENCE_LABEL.get(r["audience"], r["audience"]), "active": r["status"] == "active",
            "ends": _ends(r["expires_on"], today or dates.today()) if r.get("expires_on") else ("", "")}


def rows(user, f, today):
    """(ready?, rows) for the filters `f` (from filters()); ready is False when the saved items table is missing."""
    rs = _search(user, words=f["q"], kind=f["kind"] or None, tag=f["tag"] or None, owner=f["who"] or None,
                 today=today, all=f["all"])
    if rs is None:
        return False, []
    return True, [_row(r, today) for r in rs]


def act(user, op, item_id, tag_text=""):
    """(ok, message) for one action on one item; the item must be visible to this person (edit_actions checks)."""
    try:
        iid = int(item_id)
    except (TypeError, ValueError):
        return False, "That item no longer exists."
    if op == "pin":
        return ea.saved_pin(user, iid, True)
    if op == "unpin":
        return ea.saved_pin(user, iid, False)
    if op == "archive":
        return ea.saved_archive(user, iid)
    if op == "tags":
        return ea.saved_tags(user, iid, str(tag_text)[:500])
    return False, "Unknown action."


def add(user, data):
    """(ok, message) for the Add form; every field is validated by edit_actions / saved.add. The form's own fields are
    `new_kind` / `new_tags` so they never clash with the filter fields sent along with it."""
    kind = data.get("new_kind", "")
    aud = data.get("audience", "family")
    if aud not in AUDIENCES:
        return False, "Choose who sees it."
    until = (data.get("until") or "").strip()
    if until:
        try:
            dt.date.fromisoformat(until)
        except ValueError:
            return False, "The deal end date is not a date."
    return ea.saved_add(user, data.get("title", ""), (data.get("url") or "").strip() or None,
                        kind if kind in KINDS else None, data.get("note") or None, data.get("new_tags") or None,
                        data.get("where") or None, until or None, aud)
