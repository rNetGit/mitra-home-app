"""Vehicle service log, due dates, and running-cost context in data/family.db.

  python data/vehicle_log.py log "<vehicle fragment>" <kind> [--date D] [--odometer N] [--cost N] [--vendor T]
                                 [--notes T] [--document-id N]
  python data/vehicle_log.py list ["<vehicle fragment>"]
  python data/vehicle_log.py due
  python data/vehicle_log.py costs [YEAR]       logged costs per vehicle (only what was logged)
  python data/vehicle_log.py suggest [YEAR]     candidate transactions (fuel, tolls, car wash, auto service,
                                                auto insurance) as read-only running-cost context; nothing imported
  python data/vehicle_log.py alerts
Library: rows(con, today), alerts(con, today).
"""
import argparse
import calendar
import datetime as dt
import sqlite3
import sys
import db  # noqa: E402
import dates  # noqa: E402
from dates import parse as _d  # noqa: E402
from money import fmt as _fmt  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
SOON_DAYS = 30
SOON_MILES = 500


def _add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _name(v):
    return f"{v['year']} {v['make']} {v['model']}"


def rows(con, today):
    """One row per active service rule with status, plus a 'needs a first entry' row per vehicle without logs."""
    con.row_factory = sqlite3.Row
    out = []
    for v in con.execute("SELECT * FROM vehicles WHERE status='active' ORDER BY id").fetchall():
        nlogs = con.execute("SELECT COUNT(*) FROM vehicle_log WHERE vehicle_id=?", (v["id"],)).fetchone()[0]
        cur_odo = con.execute("SELECT MAX(odometer) FROM vehicle_log WHERE vehicle_id=?", (v["id"],)).fetchone()[0]
        if nlogs == 0:
            out.append({"vehicle_id": v["id"], "vehicle": _name(v), "kind": None, "last_date": None,
                        "last_odometer": None, "current_odometer": None, "every_months": None,
                        "every_miles": None, "next_due": None, "miles_left": None,
                        "status": "needs a first entry"})
            continue
        for r in con.execute("SELECT * FROM vehicle_service_rules WHERE vehicle_id=? AND active=1 ORDER BY kind",
                             (v["id"],)).fetchall():
            last = con.execute("SELECT log_date, odometer FROM vehicle_log WHERE vehicle_id=? AND kind=? "
                               "ORDER BY log_date DESC, id DESC LIMIT 1", (v["id"], r["kind"])).fetchone()
            row = {"vehicle_id": v["id"], "rule_id": r["id"], "vehicle": _name(v), "kind": r["kind"],
                   "last_date": last["log_date"] if last else None,
                   "last_odometer": last["odometer"] if last else None, "current_odometer": cur_odo,
                   "every_months": r["every_months"], "every_miles": r["every_miles"],
                   "next_due": None, "miles_left": None, "status": "no log for this service"}
            if last:
                ld = _d(last["log_date"])
                st = "ok"
                if ld and r["every_months"]:
                    row["next_due"] = _add_months(ld, r["every_months"])
                    if row["next_due"] < today:
                        st = f"overdue {(today - row['next_due']).days}d"
                    elif (row["next_due"] - today).days <= SOON_DAYS:
                        st = f"due in {(row['next_due'] - today).days}d"
                if r["every_miles"] and last["odometer"] is not None and cur_odo is not None:
                    row["miles_left"] = last["odometer"] + r["every_miles"] - cur_odo
                    if row["miles_left"] <= 0:
                        st = f"overdue by {-row['miles_left']} mi"
                    elif row["miles_left"] <= SOON_MILES and st == "ok":
                        st = f"due in {row['miles_left']} mi"
                row["status"] = st
            out.append(row)
    return out


def _dist():
    try:
        import country
        return country.units().get("distance", "mi")
    except Exception:
        return "mi"


def alerts(con, today):
    out = []
    firsts = []
    for r in rows(con, today):
        if r["kind"] is None:
            firsts.append(r["vehicle"])
        elif r["status"].startswith(("overdue", "due in")):
            d = r["next_due"] if r["next_due"] and (r["miles_left"] is None or r["miles_left"] > 0) else today
            if r["miles_left"] is not None and r["miles_left"] <= SOON_MILES and not (r["next_due"] and r["next_due"] < today):
                d = today
            out.append({"date": d, "kind": "Car", "title": f"{r['vehicle']}: {r['kind'].replace('_', ' ')} {r['status']}",
                        "detail": f"Last done {r['last_date']}"
                                  + (f" at {r['last_odometer']} {_dist()}" if r["last_odometer"] else ""), "amount": None,
                        "ref": ("vehicle_service_rules", r.get("rule_id"))})
    if firsts:
        out.append({"date": today, "kind": "Car", "title": "1 vehicle needs a first service-log entry" if len(firsts) == 1
                    else f"{len(firsts)} vehicles need a first service-log entry",
                    "detail": "; ".join(firsts) + ". Log the last service under Family > Cars.",
                    "amount": None})
    return out


def _vehicle(con, frag):
    m = con.execute("SELECT id, year, make, model FROM vehicles WHERE (year||' '||make||' '||model) LIKE ? "
                    "OR model LIKE ? OR make LIKE ?", (f"%{frag}%",) * 3).fetchall()
    if len(m) != 1:
        sys.exit(f"expected exactly 1 vehicle for {frag!r}, got {[tuple(x) for x in m]}")
    return m[0]


def suggest(con, year=None):
    q = ("SELECT txn_date, category, description, amount FROM transactions WHERE amount<0 AND ("
         "category IN ('fuel','tolls','tolls & fees','auto services') OR UPPER(description) LIKE '%CAR WASH%' "
         "OR (category='insurance' AND UPPER(description) LIKE '%AUTO%')) ")
    p = []
    if year:
        q += "AND substr(txn_date,1,4)=? "
        p.append(str(year))
    q += "ORDER BY txn_date"
    return con.execute(q, p).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["log", "list", "due", "costs", "suggest", "alerts"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--date")
    ap.add_argument("--odometer", type=int)
    ap.add_argument("--cost", type=float)
    ap.add_argument("--vendor")
    ap.add_argument("--notes")
    ap.add_argument("--document-id", type=int)
    a = ap.parse_args()
    con = db.connect(DB)
    today = dates.today()
    if a.cmd == "log":
        if len(a.args) != 2:
            sys.exit('log needs: "<vehicle fragment>" <kind>')
        v = _vehicle(con, a.args[0])
        d = a.date or today.isoformat()
        dt.date.fromisoformat(d)
        con.execute("INSERT INTO vehicle_log(vehicle_id,log_date,kind,odometer,cost,vendor,notes,document_id) "
                    "VALUES(?,?,?,?,?,?,?,?)", (v[0], d, a.args[1], a.odometer, a.cost, a.vendor, a.notes, a.document_id))
        con.commit()
        print(f"logged: {v[1]} {v[2]} {v[3]} {a.args[1]} {d}")
    elif a.cmd == "list":
        q = ("SELECT l.id, v.year||' '||v.make||' '||v.model, l.log_date, l.kind, l.odometer, l.cost, l.vendor, l.notes "
             "FROM vehicle_log l JOIN vehicles v ON v.id=l.vehicle_id ")
        p = []
        if a.args:
            q += "WHERE v.id=? "
            p.append(_vehicle(con, a.args[0])[0])
        for r in con.execute(q + "ORDER BY l.log_date DESC, l.id DESC", p):
            print(r)
        else:
            pass
    elif a.cmd == "due":
        for r in rows(con, today):
            print(f"{r['vehicle']:<28} {r['kind'] or '-':<13} last={r['last_date'] or '-':<11} "
                  f"next={str(r['next_due'] or '-'):<11} miles_left={r['miles_left'] if r['miles_left'] is not None else '-':<6} {r['status']}")
    elif a.cmd == "alerts":
        for x in alerts(con, today):
            print(x)
    elif a.cmd == "costs":
        y = a.args[0] if a.args else None
        q = ("SELECT v.year||' '||v.make||' '||v.model, substr(l.log_date,1,4), COUNT(*), COALESCE(SUM(l.cost),0) "
             "FROM vehicle_log l JOIN vehicles v ON v.id=l.vehicle_id ")
        p = []
        if y:
            q += "WHERE substr(l.log_date,1,4)=? "
            p.append(y)
        rs = con.execute(q + "GROUP BY 1,2 ORDER BY 2,1", p).fetchall()
        for r in rs:
            print(f"{r[1]}  {r[0]:<28} entries={r[2]:<3} logged cost={_fmt(r[3])}")
        if not rs:
            print("no logged entries")
        print("Note: logged costs only. Card transactions can't be reliably attributed to a vehicle; "
              "see `suggest` for fuel/toll/service context.")
    else:
        y = a.args[0] if a.args else None
        tot = {}
        for d, cat, desc, amt in suggest(con, y):
            label = "car wash" if "CAR WASH" in desc.upper() else ("auto insurance" if cat == "insurance" else cat)
            tot.setdefault((d[:4], label), []).append((d, desc, amt))
        for (yr, label), items in sorted(tot.items()):
            print(f"{yr}  {label:<15} n={len(items):<3} total={_fmt(-sum(i[2] for i in items))}")
        print("Read-only candidates, not attributed to any vehicle and not imported.")


if __name__ == "__main__":
    main()
