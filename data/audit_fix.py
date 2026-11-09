"""Fixes from the data check (data/audit.py), every one recorded in `audit_fixes` (migration 056) so it can be undone.

One kind runs by itself before each check, because it cannot be wrong:
  categories            spending with no category that a category rule matches: the rule's category is filled in (and
                        payee / type only where they are empty), as apply_rules.py does for new imports
(A bank row imported twice with the same reference cannot happen: the unique index on account + ref refuses it.)
Kinds a person accepts in the Inbox (proposals source `audit`, through edit_actions): remove charges entered twice
(the first stays; links to receipts and Amazon orders and a category move to it), remove a bill listed twice. Marking a late bill paid uses edit_actions.bill_paid (undone with Not paid on the bill).

Undo puts removed rows back with their own ids, moves the links back and clears categories that were filled in, as
long as nobody changed them since. Nothing here is called with a person's wording: only ids.
"""
import datetime as dt
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import db  # noqa: E402
import rule_match  # noqa: E402

TXN_LINKS = (("receipts", "transaction_id"), ("amazon_orders", "transaction_id"))
TABLES = ("transactions", "bills")
UNDO_DAYS = 60  # Settings lists fixes this far back


class FixError(ValueError):
    pass


def _now():
    import dates
    return dates.now_iso()


def _cols(con, table):
    """Stored columns (generated columns such as amount_cents are left out)."""
    return [r[1] for r in con.execute(f"PRAGMA table_xinfo({table})") if r[6] == 0]


def record(con, action, summary, undo, by, run_id=None, key=None):
    return con.execute("INSERT INTO audit_fixes(run_id, dedupe_key, action, summary, undo, done_by, done_at) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (run_id, key, action, summary, json.dumps(undo, sort_keys=True), by or "-", _now())).lastrowid


def remove_rows(con, table, keep, drop):
    """Delete rows `drop` of `table`, keeping `keep`; links and a missing category move to `keep`. -> the undo dict."""
    if table not in TABLES:
        raise FixError("not a table the data check fixes")
    cols = _cols(con, table)
    rows = [dict(zip(cols, r)) for r in con.execute(
        f"SELECT {', '.join(cols)} FROM {table} WHERE id IN ({','.join('?' * len(drop))})", drop)]
    if len(rows) != len(drop) or not con.execute(f"SELECT 1 FROM {table} WHERE id=?", (keep,)).fetchone():
        raise FixError("those rows have changed since the check; run it again")
    links, category = [], None
    if table == "transactions":
        for t, col in TXN_LINKS:
            try:
                for (lid, old) in con.execute(f"SELECT id, {col} FROM {t} WHERE {col} IN ({','.join('?' * len(drop))})", drop).fetchall():
                    links.append([t, col, lid, old])
                    try:
                        con.execute(f"UPDATE {t} SET {col}=? WHERE id=?", (keep, lid))
                    except sqlite3.IntegrityError:  # the kept row has its own (one per charge, e.g. a receipt): unlink
                        con.execute(f"UPDATE {t} SET {col}=NULL WHERE id=?", (lid,))
            except Exception as e:  # noqa: BLE001 (pack table not there)
                if not db.missing(e):
                    raise
        cat = next((r["category"] for r in rows if (r.get("category") or "").strip()), None)
        if cat and con.execute("UPDATE transactions SET category=? WHERE id=? AND (category IS NULL OR TRIM(category)='')",
                               (cat, keep)).rowcount:
            category = cat
    con.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(drop))})", drop)
    return {"table": table, "keep": keep, "rows": rows, "links": links, "category": category}


def categorize(con, ids=None):
    """Fill the category of spending with none from the first matching rule. -> (count, undo dict)."""
    sql = "SELECT id, description, category, payee, txn_type FROM transactions WHERE manual=0 AND (category IS NULL OR TRIM(category)='')"
    args = []
    if ids is not None:
        sql += f" AND id IN ({','.join('?' * len(ids))})"
        args = list(ids)
    changed = []
    for tid, desc, cat, payee, typ in con.execute(sql, args).fetchall():
        t = rule_match.texts(desc)
        r = con.execute("SELECT category, payee, payee_type FROM category_rules WHERE category IS NOT NULL "
                        "AND TRIM(category) != '' AND (" + " OR ".join("? LIKE pattern" for _ in t) + ") "
                        "ORDER BY priority, id LIMIT 1", t).fetchone()
        if not r:
            continue
        changed.append([tid, cat, payee, typ, r[0]])
        con.execute("UPDATE transactions SET category=?, payee=COALESCE(payee, ?), txn_type=COALESCE(txn_type, ?) "
                    "WHERE id=?", (r[0], r[1], r[2], tid))
    return len(changed), {"table": "transactions", "categorized": changed}


def auto(con, run_id=None):
    """The safe fixes, each recorded. -> [summary line]."""
    lines = []
    n, u = categorize(con)
    if n:
        s = f"Filled in the category of {n} payment{'' if n == 1 else 's'} from your category rules"
        record(con, "categorize", s, u, "auto", run_id, "auto:categorize")
        lines.append(s)
    return lines


def undo(con, fix_id, by):
    """Put a fix back -> message. Raises FixError when it was undone already or the rows have changed since."""
    r = db.one(con, "SELECT * FROM audit_fixes WHERE id=?", (int(fix_id),))
    if not r:
        raise FixError("no such fix")
    if r["undone_at"]:
        raise FixError("that fix was undone already")
    u = json.loads(r["undo"])
    t = u.get("table")
    if t not in TABLES:
        raise FixError("that fix can not be undone")
    if "categorized" in u:
        back = 0
        for tid, cat, payee, typ, new in u["categorized"]:
            back += con.execute("UPDATE transactions SET category=?, payee=?, txn_type=? WHERE id=? AND category=?",
                                (cat, payee, typ, tid, new)).rowcount
        msg = f"Cleared the category on {back} payment{'' if back == 1 else 's'} again."
    else:
        cols = _cols(con, t)
        for row in u["rows"]:
            if con.execute(f"SELECT 1 FROM {t} WHERE id=?", (row["id"],)).fetchone():
                raise FixError("a removed row's place is taken; it can not be put back")
            keep = [c for c in cols if c in row]
            con.execute(f"INSERT INTO {t}({', '.join(keep)}) VALUES ({','.join('?' * len(keep))})", [row[c] for c in keep])
        for lt, col, lid, old in u.get("links") or []:
            con.execute(f"UPDATE {lt} SET {col}=? WHERE id=? AND {col}=?", (old, lid, u["keep"]))
        if u.get("category"):
            con.execute("UPDATE transactions SET category=NULL WHERE id=? AND category=?", (u["keep"], u["category"]))
        n = len(u["rows"])
        msg = "Put the removed row back." if n == 1 else f"Put the {n} removed rows back."
    con.execute("UPDATE audit_fixes SET undone_at=?, undone_by=? WHERE id=?", (_now(), by or "-", r["id"]))
    if str(r["dedupe_key"] or "").startswith("audit:"):  # the Inbox asks again (it was accepted there)
        con.execute("UPDATE proposals SET status='open', outcome=NULL, until=NULL, updated_at=? WHERE dedupe_key=?",
                    (_now(), r["dedupe_key"]))
    return msg


def recent(con, days=UNDO_DAYS):
    since = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    return db.rows(con, "SELECT id, action, summary, done_by, done_at, undone_at, undone_by FROM audit_fixes "
                        "WHERE done_at >= ? ORDER BY id DESC LIMIT 40", (since,))
