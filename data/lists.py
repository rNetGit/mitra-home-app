"""Shared lists (shopping, to-do, packing) in data/family.db: tables lists + list_items (migration 029).

  python data/lists.py show [LIST] [--all]                 active lists and their open items (--all: ticked and dropped too)
  python data/lists.py new "<list>" [--kind shopping|todo|packing] [--adults]
  python data/lists.py add "<list>" "<item>" [--qty Q] [--for NAME]
  python data/lists.py done "<list>" "<item fragment>"     tick it off (undo: undo)
  python data/lists.py undo "<list>" "<item fragment>"
  python data/lists.py drop "<list>" "<item fragment>"
  python data/lists.py clear "<list>"                       hide the ticked items now (they stay in the database)
  python data/lists.py archive "<list>"
  python data/lists.py summary
  python data/lists.py brief                               write brief/lists.md (family lists, open items) for the phone
Library: lists(con, adult), items(con, list_id), find_list, find_item, summary(con, adult), brief_md(con), and the
writers new_list / add_item / set_status / clear_done / archive_list. They raise ValueError on bad input; the
dashboard goes through data/edit_actions.py (who may do what, logging). The terminal acts as an adult.
Records only: nothing is bought. Item text is checked like every other free text (no full account, card or ID
numbers, no email addresses). Ticked items stay visible for SHOW_DONE_DAYS, then only `show --all` lists them.
"""
import argparse
import datetime as dt
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import members as mem  # noqa: E402
import validators as v  # noqa: E402

DB = paths.DB
ROOT = HERE.parent
KINDS = ["shopping", "todo", "packing"]
SHOW_DONE_DAYS = 7
MAX_OPEN_PER_PERSON = 50  # limited users: open items one person may have added to one list


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _clean(validator, value, label):
    try:
        return validator(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{label}: {e}") from None


def _row(con, sql, params):
    con.row_factory = sqlite3.Row
    r = con.execute(sql, params).fetchone()
    return dict(r) if r else None


def get_list(con, list_id):
    return _row(con, "SELECT * FROM lists WHERE id=?", (list_id,))


def get_item(con, item_id):
    return _row(con, "SELECT * FROM list_items WHERE id=?", (item_id,))


def lists(con, adult=True, status="active"):
    """Lists the viewer may see, with open / ticked counts. adult=False: family lists only."""
    con.row_factory = sqlite3.Row
    q = ("SELECT l.*, SUM(i.status='open') AS open_n, SUM(i.status='done' AND i.cleared_at IS NULL) AS done_n "
         "FROM lists l LEFT JOIN list_items i ON i.list_id=l.id WHERE l.status=?")
    if not adult:
        q += " AND l.audience='family'"
    out = [dict(r) for r in con.execute(q + " GROUP BY l.id ORDER BY l.name", (status,))]
    for r in out:
        r["open_n"], r["done_n"] = r["open_n"] or 0, r["done_n"] or 0
    return out


def items(con, list_id, today=None, all=False):
    """Open items first (oldest first), then the recently ticked ones. all=True: everything, dropped included."""
    today = today or dates.today()
    con.row_factory = sqlite3.Row
    if all:
        q, a = "SELECT * FROM list_items WHERE list_id=?", (list_id,)
    else:
        since = (today - dt.timedelta(days=SHOW_DONE_DAYS)).isoformat()
        q = ("SELECT * FROM list_items WHERE list_id=? AND (status='open' OR (status='done' AND cleared_at IS NULL "
             "AND done_at >= ?))")
        a = (list_id, since)
    return [dict(r) for r in con.execute(q + " ORDER BY status='done', status='dropped', id", a)]


def find_list(con, name, adult=True):
    """Active list by exact name (any case), else by a fragment that matches exactly one."""
    s = " ".join(str(name or "").split())
    if not s:
        raise ValueError("which list?")
    rows = lists(con, adult)
    hit = [r for r in rows if r["name"].lower() == s.lower()]
    if not hit:
        hit = [r for r in rows if s.lower() in r["name"].lower()]
    if len(hit) != 1:
        names = ", ".join(r["name"] for r in rows) or "none yet"
        raise ValueError(f"no single list matches '{s}' (lists: {names})")
    return hit[0]


def find_item(con, list_id, fragment, status="open"):
    s = " ".join(str(fragment or "").split()).lower()
    if not s:
        raise ValueError("which item?")
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute("SELECT * FROM list_items WHERE list_id=? AND status=? ORDER BY id DESC",
                                         (list_id, status))]
    hit = [r for r in rows if r["text"].lower() == s] or [r for r in rows if s in r["text"].lower()]
    if not hit:
        raise ValueError(f"nothing {'open' if status == 'open' else status} on that list matches '{fragment}'")
    if len({r["text"].lower() for r in hit}) > 1:
        raise ValueError(f"'{fragment}' matches several items: " + ", ".join(sorted({r['text'] for r in hit})))
    return hit[0]


# ---------------------------------------------------------------- writers (no permission checks here)
def new_list(con, name, kind="todo", audience="family", by=None):
    name = _clean(v.text(60), name, "list name")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    if audience not in ("family", "adults"):
        raise ValueError("audience must be family or adults")
    old = _row(con, "SELECT * FROM lists WHERE name=? COLLATE NOCASE", (name,))
    if old and old["status"] == "active":
        raise ValueError(f"there is already a list called '{old['name']}'")
    if old:  # an archived list of that name comes back, with its history
        con.execute("UPDATE lists SET status='active', kind=?, audience=? WHERE id=?", (kind, audience, old["id"]))
        return old["id"]
    return con.execute("INSERT INTO lists(name, kind, audience, created_by, created_at) VALUES (?,?,?,?,?)",
                       (name, kind, audience, by or None, _now())).lastrowid


def add_item(con, list_id, text, qty=None, who=None, by=None):
    """Returns (item_id, added?). An item already open on the list is not added twice."""
    text = _clean(v.text(120), text, "item")
    qty = _clean(v.text(20), qty, "quantity") if qty not in (None, "") else None
    if who:
        name = mem.resolve(con, who)
        if name not in mem.names(con):
            raise ValueError(f"for: '{who}' is not a family member")
        who = name
    same = _row(con, "SELECT id FROM list_items WHERE list_id=? AND status='open' AND text=? COLLATE NOCASE", (list_id, text))
    if same:
        return same["id"], False
    iid = con.execute("INSERT INTO list_items(list_id, text, qty, assigned_to, added_by, added_at) VALUES (?,?,?,?,?,?)",
                      (list_id, text, qty, who or None, by or None, _now())).lastrowid
    return iid, True


def open_added_by(con, list_id, by):
    return con.execute("SELECT COUNT(*) FROM list_items WHERE list_id=? AND status='open' AND added_by=?",
                       (list_id, by)).fetchone()[0]


def set_status(con, item_id, status, by=None):
    """open -> done (tick), done -> open (untick), open/done -> dropped. Returns False when nothing changed."""
    if status == "done":
        n = con.execute("UPDATE list_items SET status='done', done_by=?, done_at=?, cleared_at=NULL "
                        "WHERE id=? AND status='open'", (by or None, _now(), item_id)).rowcount
    elif status == "open":
        n = con.execute("UPDATE list_items SET status='open', done_by=NULL, done_at=NULL, cleared_at=NULL "
                        "WHERE id=? AND status='done'", (item_id,)).rowcount
    elif status == "dropped":
        n = con.execute("UPDATE list_items SET status='dropped' WHERE id=? AND status IN ('open','done')", (item_id,)).rowcount
    else:
        raise ValueError("status must be open, done or dropped")
    return bool(n)


def clear_done(con, list_id):
    return con.execute("UPDATE list_items SET cleared_at=? WHERE list_id=? AND status='done' AND cleared_at IS NULL",
                       (_now(), list_id)).rowcount


def archive_list(con, list_id):
    return bool(con.execute("UPDATE lists SET status='archived' WHERE id=? AND status='active'", (list_id,)).rowcount)


# ---------------------------------------------------------------- read-outs
def summary(con, adult=True):
    """[(list name, open count)] for active lists with open items; [] when the tables are missing."""
    try:
        return [(r["name"], r["open_n"]) for r in lists(con, adult) if r["open_n"]]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def _line(r):
    return r["text"] + (f" ({r['qty']})" if r["qty"] else "") + (f" - {r['assigned_to']}" if r["assigned_to"] else "")


def brief_md(con, today=None):
    """Markdown of the family lists' open items (adults-only lists left out), or None when nothing is open."""
    today = today or dates.today()
    try:
        ls = [r for r in lists(con, adult=False) if r["open_n"]]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return None
    if not ls:
        return None
    out = [f"# Lists ({today:%a %b %d})", ""]
    for r in ls:
        out += [f"## {r['name']}", ""] + [f"- [ ] {_line(i)}" for i in items(con, r["id"], today) if i["status"] == "open"] + [""]
    return "\n".join(out)


def write_brief(con=None, today=None):
    """brief/lists.md for the phone (Drive push). Removes a stale file when nothing is open. Returns the path or None."""
    own = con is None
    con = con or db.connect(DB, readonly=True)
    try:
        md = brief_md(con, today)
    finally:
        if own:
            con.close()
    p = paths.BRIEF / "lists.md"
    if md is None:
        if p.exists():
            p.unlink()
        return None
    p.parent.mkdir(exist_ok=True)
    p.write_text(md, encoding="utf-8")
    return p


def main():
    ap = argparse.ArgumentParser(description="Shared lists")
    ap.add_argument("cmd", choices=["show", "new", "add", "done", "undo", "drop", "clear", "archive", "summary", "brief"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--kind", default="todo", choices=KINDS)
    ap.add_argument("--adults", action="store_true", help="new: keep the list off the limited (kid / guest) screen")
    ap.add_argument("--qty")
    ap.add_argument("--for", dest="who")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    today = dates.today()
    if a.cmd == "brief":
        p = write_brief(today=today)
        print(f"wrote {paths.rel(p)}" if p else "nothing open on the family lists; no brief/lists.md")
        return
    con = db.connect(DB)
    try:
        if a.cmd == "summary":
            s = summary(con)
            print("; ".join(f"{n}: {k} open" for n, k in s) if s else "No open items on any list.")
            return
        if a.cmd == "show":
            ls = [find_list(con, a.args[0])] if a.args else lists(con)
            for r in ls:
                tag = "" if r["audience"] == "family" else "  [adults only]"
                print(f"{r['name']} ({r['kind']}, {r['open_n']} open){tag}")
                for i in items(con, r["id"], today, all=a.all):
                    mark = {"open": "[ ]", "done": "[x]", "dropped": "[-]"}[i["status"]]
                    print(f"  {mark} {_line(i)}")
            if not ls:
                print("No lists yet. python data/lists.py new \"Groceries\" --kind shopping")
            return
        if a.cmd == "new":
            if len(a.args) != 1:
                raise ValueError('need "<list>"')
            new_list(con, a.args[0], a.kind, "adults" if a.adults else "family")
            con.commit()
            print(f"new list: {a.args[0]}")
            return
        if not a.args:
            raise ValueError('need "<list>"')
        lst = find_list(con, a.args[0])
        if a.cmd in ("clear", "archive"):
            if a.cmd == "clear":
                print(f"{clear_done(con, lst['id'])} ticked item(s) hidden on {lst['name']}")
            else:
                archive_list(con, lst["id"])
                print(f"archived: {lst['name']}")
            con.commit()
            return
        if len(a.args) != 2:
            raise ValueError('need "<list>" "<item>"')
        if a.cmd == "add":
            _, added = add_item(con, lst["id"], a.args[1], a.qty, a.who)
            con.commit()
            print(f"added to {lst['name']}: {a.args[1]}" if added else f"already on {lst['name']}: {a.args[1]}")
            return
        it = find_item(con, lst["id"], a.args[1], "done" if a.cmd == "undo" else "open")
        new, said = {"done": ("done", "ticked"), "undo": ("open", "back on the list"), "drop": ("dropped", "dropped")}[a.cmd]
        set_status(con, it["id"], new)
        con.commit()
        print(f"{said}: {it['text']}")
    except ValueError as e:
        raise SystemExit(str(e)) from None
    finally:
        con.close()


if __name__ == "__main__":
    main()
