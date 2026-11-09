"""Manage recurring interval items (health checkups, home maintenance) in data/family.db.

  python data/recurring.py list
  python data/recurring.py done "<name fragment>" [--who NAME] [YYYY-MM-DD] [--provider TEXT] [--notes TEXT]
  python data/recurring.py set  "<name fragment>" --who NAME <last_done YYYY-MM-DD>     (same as done, no log note)
  python data/recurring.py add  "<name>" <category> <who> <interval_months> [--notes TEXT]
"""
import argparse
import datetime as dt
import sys

import db  # noqa: E402
import dates  # noqa: E402

c = db.connect()
ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["list", "done", "set", "add"])
ap.add_argument("args", nargs="*")
ap.add_argument("--who")
ap.add_argument("--provider")
ap.add_argument("--notes")
a = ap.parse_intermixed_args()  # `done "dental" --who Raj 2026-09-03` and `done "dental" 2026-09-03 --who Raj` both work

if a.cmd == "list":
    for r in c.execute("SELECT id,category,who,name,interval_months,last_done,provider FROM recurring_items "
                       "WHERE active=1 ORDER BY category, who, name"):
        print(r)
elif a.cmd in ("done", "set"):
    if not a.args:
        sys.exit("need a name fragment")
    sql, p = "SELECT id,name,who FROM recurring_items WHERE name LIKE ?", [f"%{a.args[0]}%"]
    if a.who:
        sql += " AND who=?"
        p.append(a.who)
    rows = c.execute(sql, p).fetchall()
    if len(rows) != 1:
        sys.exit(f"expected exactly 1 match, got {len(rows)}: {rows} (use --who)")
    d = a.args[1] if len(a.args) > 1 else dates.today().isoformat()
    dt.date.fromisoformat(d)
    c.execute("UPDATE recurring_items SET last_done=?, provider=COALESCE(?,provider) WHERE id=?", (d, a.provider, rows[0][0]))
    c.execute("INSERT INTO recurring_log(item_id,done_date,provider,notes) VALUES(?,?,?,?)", (rows[0][0], d, a.provider, a.notes))
    c.commit()
    print("recorded:", rows[0][1], rows[0][2], d)
else:
    if len(a.args) != 4:
        sys.exit("add needs: name category who interval_months")
    n, cat, who, iv = a.args
    c.execute("INSERT INTO recurring_items(name,category,who,interval_months,notes) VALUES(?,?,?,?,?)",
              (n, cat, who, int(iv), a.notes))
    c.commit()
    print("added:", n, who)
