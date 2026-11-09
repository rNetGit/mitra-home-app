"""Manage seasonal tasks in data/family.db.

  python data/seasonal.py list
  python data/seasonal.py done "<part of task name>" [YYYY-MM-DD] [--place TEXT] [--notes TEXT]
  python data/seasonal.py add "<name>" <category> <MM-DD start> <MM-DD end> [--lead N] [--notes TEXT]
"""
import sys
import argparse
import datetime as dt

import db  # noqa: E402
import dates  # noqa: E402

c = db.connect()
ap = argparse.ArgumentParser()
ap.add_argument("cmd", choices=["list", "done", "add"])
ap.add_argument("args", nargs="*")
ap.add_argument("--place")
ap.add_argument("--notes")
ap.add_argument("--lead", type=int, default=14)
a = ap.parse_args()

if a.cmd == "list":
    for r in c.execute("SELECT t.id,t.category,t.name,t.start_md,t.end_md,"
                       "(SELECT MAX(done_date) FROM seasonal_log l WHERE l.task_id=t.id) "
                       "FROM seasonal_tasks t WHERE active=1 ORDER BY t.start_md"):
        print(r)
elif a.cmd == "done":
    if not a.args:
        sys.exit("need a task name fragment")
    rows = c.execute("SELECT id,name FROM seasonal_tasks WHERE name LIKE ?", (f"%{a.args[0]}%",)).fetchall()
    if len(rows) != 1:
        sys.exit(f"expected exactly 1 match, got {len(rows)}: {[r[1] for r in rows]}")
    d = a.args[1] if len(a.args) > 1 else dates.today().isoformat()
    dt.date.fromisoformat(d)
    c.execute("INSERT INTO seasonal_log(task_id,done_date,place,notes) VALUES(?,?,?,?)", (rows[0][0], d, a.place, a.notes))
    c.commit()
    print("logged:", rows[0][1], d)
else:
    if len(a.args) != 4:
        sys.exit("add needs: name category start_md end_md")
    n, cat, s, e = a.args
    for md in (s, e):  # MM-DD that exists in a leap year (02-29 is allowed; 02-30 is not)
        try:
            dt.date(2024, *map(int, md.split("-")))
        except (ValueError, TypeError):
            sys.exit(f"start_md/end_md must be MM-DD, got {md!r}")
    c.execute("INSERT INTO seasonal_tasks(name,category,start_md,end_md,lead_days,notes) VALUES(?,?,?,?,?,?)",
              (n, cat, s, e, a.lead, a.notes))
    c.commit()
    print("added:", n)
