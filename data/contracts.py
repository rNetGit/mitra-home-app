"""Contract tracking (end dates, rate) in data/family.db.

  python data/contracts.py list
  python data/contracts.py set <contract_no> [--end D] [--rate N] [--person NAME] [--status active|renewed|ended] [--notes T]
Library: rows(con, today), alerts(con, today). Alerts start `lead_days` (default 183, about 6 months) before the end date.
"""
import argparse
import datetime as dt
import sqlite3
import config  # optional pack: config/family.json packs.contracts
import dates  # noqa: E402
import db  # noqa: E402
from dates import parse as _d  # noqa: E402

import paths  # noqa: E402
DB = paths.DB


def rows(con, today):
    if not config.pack("contracts"):
        return []
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT * FROM contracts WHERE status='active' ORDER BY end_date"):
        r = dict(r)
        e = _d(r["end_date"])
        r["end"] = e
        r["alert_from"] = e - dt.timedelta(days=r["lead_days"] or 183) if e else None
        r["days_left"] = (e - today).days if e else None
        out.append(r)
    return out


def alerts(con, today):
    if not config.pack("contracts"):
        return []
    out = []
    for r in rows(con, today):
        e = r["end"]
        if e is None or today < r["alert_from"]:
            continue
        who = f"{r['person']} " if r["person"] else ""
        mo = max(r["days_left"], 0) / 30.4
        detail = ("Ended - confirm renewal/extension status" if r["days_left"] < 0 else
                  f"{r['days_left']} days left (~{mo:.0f} months). Ask the vendor about extension and plan the next role/income")
        out.append({"date": e, "kind": "Contract", "title": f"{who}{r['client']} contract {r['contract_no']} ends ({r['vendor']})",
                    "detail": detail, "amount": None, "ref": ("contracts", r.get("id"))})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "set"])
    ap.add_argument("contract_no", nargs="?")
    ap.add_argument("--end"), ap.add_argument("--rate", type=float), ap.add_argument("--person")
    ap.add_argument("--status"), ap.add_argument("--notes")
    a = ap.parse_args()
    con = db.connect(DB)
    today = dates.today()
    if a.cmd == "list":
        for r in rows(con, today):
            print(f"{r['contract_no']}  {r['client']} via {r['vendor']}  holder={r['person'] or '?'}  "
                  f"{r['start_date']} -> {r['end_date']} ({r['days_left']}d left)  ${r['hourly_rate']}/h  "
                  f"alerts from {r['alert_from']}")
    else:
        sets = {k: v for k, v in (("end_date", a.end), ("hourly_rate", a.rate), ("person", a.person),
                                  ("status", a.status), ("notes", a.notes)) if v is not None}
        if not a.contract_no or not sets:
            raise SystemExit("set needs <contract_no> and at least one option")
        con.execute(f"UPDATE contracts SET {', '.join(k + '=?' for k in sets)} WHERE contract_no=?",
                    (*sets.values(), a.contract_no))
        con.commit()
        print("updated", a.contract_no)


if __name__ == "__main__":
    main()
