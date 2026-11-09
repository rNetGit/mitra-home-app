"""Shopping lists in data/family.db.

  python data/shopping.py list [LIST]
  python data/shopping.py add "<list>" "<item>" [--date D] [--price N] [--store S] [--notes T]
  python data/shopping.py bought "<list>" "<item>" [--paid N] [--date D]
  python data/shopping.py drop "<list>" "<item>"
Library: rows(con, today), alerts(con, today): one alert per list with open items, from 21 days before its target date.
Buy-side only: records what the user says was bought; never purchases anything.
"""
import argparse
import datetime as dt
import sqlite3
import config  # optional pack: config/family.json packs.shopping
import dates  # noqa: E402
import db  # noqa: E402
from dates import parse as _d  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
LEAD = 21


def rows(con, today, list_name=None):
    if not config.pack("shopping"):
        return []
    con.row_factory = sqlite3.Row
    q, a = "SELECT * FROM shopping_items", ()
    if list_name:
        q, a = q + " WHERE list_name=?", (list_name,)
    return [dict(r) for r in con.execute(q + " ORDER BY list_name, status, id", a)]


def alerts(con, today):
    if not config.pack("shopping"):
        return []
    out, lists = [], {}
    for r in rows(con, today):
        lists.setdefault(r["list_name"], []).append(r)
    for name, items in lists.items():
        todo = [i for i in items if i["status"] == "todo"]
        dates = [d for d in (_d(i["target_date"]) for i in todo) if d]
        if not todo or not dates:
            continue
        d = min(dates)
        if today < d - dt.timedelta(days=LEAD):
            continue
        out.append({"date": d, "kind": "Shopping", "title": f"{name}: {len(todo)} of {len(items)} items still to buy",
                    "detail": ", ".join(i["item"] for i in todo), "amount": None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "add", "bought", "drop"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--date"), ap.add_argument("--price", type=float), ap.add_argument("--store")
    ap.add_argument("--notes"), ap.add_argument("--paid", type=float)
    a = ap.parse_args()
    con = db.connect(DB)
    today = dates.today()
    if a.cmd == "list":
        for r in rows(con, today, a.args[0] if a.args else None):
            print(f"{r['list_name']:<20} {r['item']:<18} {r['status']:<8} by {r['target_date'] or '-':<11}"
                  f"{'est $%.2f' % r['est_price'] if r['est_price'] else ''} {r['store'] or ''}"
                  f"{'  paid $%.2f' % r['paid'] if r['paid'] else ''}")
        return
    if len(a.args) != 2:
        raise SystemExit('need "<list>" "<item>"')
    lst, item = a.args
    if a.cmd == "add":
        con.execute("INSERT INTO shopping_items(list_name,item,target_date,est_price,store,notes) VALUES(?,?,?,?,?,?)",
                    (lst, item, a.date, a.price, a.store, a.notes))
    elif a.cmd == "bought":
        con.execute("UPDATE shopping_items SET status='bought', bought_date=?, paid=COALESCE(?,paid) "
                    "WHERE list_name=? AND item=? COLLATE NOCASE", (a.date or today.isoformat(), a.paid, lst, item))
    else:
        con.execute("UPDATE shopping_items SET status='dropped' WHERE list_name=? AND item=? COLLATE NOCASE", (lst, item))
    con.commit()
    print("ok")


if __name__ == "__main__":
    main()
