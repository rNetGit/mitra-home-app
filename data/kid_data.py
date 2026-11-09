"""The web app's page for limited users (children, teens, guests): no money, no accounts, no AI, no other page.

What they see: their own jobs for today (Family > Routines, with their stars this week but never an allowance amount),
their own open items (limited_view.SAFE_DOMAINS), the family's shared lists (never adults-only ones), the family's
saved links and notes, the next two weeks and upcoming birthdays. What they may do, all through edit_actions (which
checks the role again): tick / untick their own jobs, finish their own items, add / tick / untick items on family lists
and hide ticked ones, save a family link or note (a few a day). Used by webapp/app.py.
"""
import sqlite3

import db
import dates  # noqa: E402
import edit_actions as ea
import limited_view
import paths

OPS = ("done", "tick", "untick", "add", "clear", "save", "job", "reward")
SAVED_SHOWN = 15


def _lists(con, today):
    import lists as L
    out = []
    for r in L.lists(con, False):  # adult=False: family lists only
        its = L.items(con, r["id"], today)
        out.append({"id": r["id"], "name": r["name"], "open_n": r["open_n"],
                    "items": [{"id": i["id"], "text": i["text"], "qty": i["qty"] or "", "done": i["status"] == "done",
                               "by": i["done_by"] or ""} for i in its]})
    return out


def _jobs(con, user, today):
    """This person's routines for today by part of the day, or None when they have none today. Stars only: the
    allowance (cents_week) stays with the adults."""
    import wall as W
    name = user.get("name") or ""
    factory, con.row_factory = con.row_factory, sqlite3.Row  # wall reads rows by name
    try:
        kids = W.day_view(con, today)
    finally:
        con.row_factory = factory
    for k in kids:
        if k["name"] == name:  # the same match as edit_actions.routine_tick
            return {"parts": [(p, W.PART_LABEL[p], k["parts"][p]) for p in W.PARTS if k["parts"][p]],
                    "done": k["done"], "total": k["total"], "stars_week": k["stars_week"],
                    "rewards": W.reward_view(con, name)}
    return None


def _saved(con, user, today, words):
    import saved as S
    rows = S.search(con, words=words, viewer=user, today=today) if words else S.search(con, viewer=user, today=today)
    return [{"title": r["title"], "url": r["url"] if str(r["url"] or "").startswith(("https://", "http://")) else "",
             "note": " ".join(str(r["body"] or "").split())[:200], "by": r["owner"] or "", "kind": r["kind"]}
            for r in rows[:SAVED_SHOWN]]


def view(user, today=None, words=""):
    """{'jobs', 'mine', 'week', 'birthdays', 'lists', 'saved', 'words'} for one limited person."""
    today = today or dates.today()
    words = " ".join(str(words or "").split())[:80]
    out = {"jobs": None, "mine": [], "week": [], "birthdays": [], "classes": [], "days_off": [], "lists": [], "saved": [], "words": words}
    try:
        out.update(limited_view.data(user.get("name") or "", today))
    except sqlite3.Error:
        pass
    try:
        con = db.connect(paths.DB, readonly=True)
    except sqlite3.Error:
        return out
    try:
        for key, fn in (("jobs", lambda: _jobs(con, user, today)), ("lists", lambda: _lists(con, today)),
                        ("saved", lambda: _saved(con, user, today, words))):
            try:
                out[key] = fn()
            except (sqlite3.Error, ImportError):
                pass
    finally:
        con.close()
    return out


def _id(data, key):
    try:
        return int(data.get(key, ""))
    except (TypeError, ValueError):
        return None


def act(user, op, data):
    """One change from the page -> (ok, message). Unknown ops and bad ids are refused here; roles in edit_actions."""
    if op not in OPS:
        return False, "That cannot be done here."
    if op == "save":
        title = str(data.get("title", "")).strip()
        if not title:
            return False, "Type a title first."
        return ea.saved_add(user, title[:200], str(data.get("url", "")).strip()[:2000] or None, None,
                            str(data.get("note", "")).strip()[:300] or None)
    if op == "add":
        lid, text = _id(data, "list"), str(data.get("text", "")).strip()
        if lid is None:
            return False, "That list no longer exists."
        if not text:
            return False, "Type the item first."
        return ea.list_item_add(user, lid, text[:120])
    key = {"done": "item", "tick": "item", "untick": "item", "clear": "list", "job": "job", "reward": "reward"}[op]
    n = _id(data, key)
    if n is None:
        return False, "That is no longer on the page. Reload it."
    if op == "done":
        return ea.life_done_own(user, n)
    if op == "clear":
        return ea.list_clear(user, n)
    if op == "reward":  # reward_ask lets the child ask only for themself
        return ea.reward_ask(user, n, user.get("name") or "")
    if op == "job":  # routine_tick lets only the child the job belongs to (or an adult) tick it
        return ea.routine_tick(user, n, str(data.get("done", "1")) != "0")
    return ea.list_item_tick(user, n, op == "tick")
