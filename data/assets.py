"""Household inventory: appliances, systems and big purchases in home_assets (data/family.db), with purchase date,
price, warranty, the filed receipt and manual, and where each one is.

  python data/assets.py list [--all]           in-use items (--all adds sold / disposed / lost)
  python data/assets.py add "<name>" [--category appliance] [--brand-model T] [--purchase-date D] [--store T]
                            [--price N] [--serial-last4 NNNN] [--warranty-years N] [--warranty-end D]
                            [--location T] [--document-id N] [--manual-id N] [--vehicle-id N] [--notes T]
  python data/assets.py set "<asset fragment>" [same options]               change any of those fields
  python data/assets.py attach "<asset fragment>" <document_id> [--as receipt|manual]
  python data/assets.py warranty "<asset fragment>" <YYYY-MM-DD>
  python data/assets.py dispose "<asset fragment>" [--how sold|disposed|lost] [--date D]
  python data/assets.py summary                 count, value, under warranty, missing receipts and manuals
  python data/assets.py alerts
Library: rows(con, today, all=False), alerts(con, today), summary(con, today), CATEGORIES, STATUSES.
Manuals and receipts are documents filed in archive/ (intake type `manual` or `receipt`); only their ids are stored here.
"""
import argparse
import calendar
import datetime as dt
import sqlite3
import sys
import db  # noqa: E402
import dates  # noqa: E402
from dates import parse as _d  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
WARN_DAYS = 90  # fallback; the lead in force comes from data/expiries.py ("warranty")
RECEIPT_MIN_PRICE = 200
CATEGORIES = ["appliance", "hvac", "roof", "plumbing", "electrical", "electronics", "furniture", "tools", "outdoor", "vehicle", "other"]
STATUSES = ["in_use", "sold", "disposed", "lost"]
FIELDS = ("category", "brand_model", "purchase_date", "warranty_end", "notes", "store", "price", "serial_last4",
          "receipt_document_id", "warranty_years", "vehicle_id", "location", "manual_document_id")


def _lead():
    try:
        import expiries
        return expiries.lead_days("warranty")
    except ImportError:
        return WARN_DAYS


def _add_years(d, y):
    months = int(round(y * 12))
    m = d.month - 1 + months
    yr, mo = d.year + m // 12, m % 12 + 1
    return dt.date(yr, mo, min(d.day, calendar.monthrange(yr, mo)[1]))


def rows(con, today, all=False):
    con.row_factory = sqlite3.Row
    out = []
    lead = _lead()
    for r in con.execute("SELECT * FROM home_assets ORDER BY name"):
        r = dict(r)
        for k in ("location", "manual_document_id", "status", "disposed_date"):
            r.setdefault(k, None)
        r["status_row"] = r["status"] or "in_use"
        if r["status_row"] != "in_use" and not all:
            continue
        end = _d(r["warranty_end"])
        if not end and r.get("warranty_years") and _d(r["purchase_date"]):
            end = _add_years(_d(r["purchase_date"]), r["warranty_years"])
            r["warranty_end_computed"] = True
        r["expires"] = end
        r["next_due"] = end
        if r["status_row"] != "in_use":
            st = r["status_row"] + (f" {r['disposed_date']}" if r["disposed_date"] else "")
        elif end is None:
            st = "warranty unknown"
        elif end < today:
            st = "warranty expired"
        elif (end - today).days <= lead:
            st = f"warranty ends in {(end - today).days}d"
        else:
            st = "under warranty"
        r["has_receipt"] = bool(r.get("receipt_document_id"))
        r["has_manual"] = bool(r.get("manual_document_id"))
        r["needs_receipt"] = r["status_row"] == "in_use" and (r.get("price") or 0) > RECEIPT_MIN_PRICE and not r["has_receipt"]
        if r["needs_receipt"]:
            st += "; needs a receipt"
        r["status"] = st
        r["under_warranty"] = bool(end and end >= today and r["status_row"] == "in_use")
        out.append(r)
    return out


def alerts(con, today):
    out = []
    for r in rows(con, today):
        end = r["expires"]
        if end and today <= end <= today + dt.timedelta(days=_lead()):
            out.append({"date": end, "kind": "Warranty", "title": f"{r['name']} warranty ends",
                        "detail": "File any claim or extended-warranty decision before this date", "amount": None,
                        "ref": ("home_assets", r.get("id"))})
        if r["needs_receipt"]:
            out.append({"date": today, "kind": "Warranty", "title": f"{r['name']}: needs a receipt",
                        "detail": "Over $200 with no receipt attached (assets.py attach)", "amount": r["price"],
                        "ref": ("home_assets", r.get("id"))})
    return out


def summary(con, today):
    """{count, value, under_warranty, needs_receipt, no_manual, gone} over in-use items (gone = sold/disposed/lost)."""
    rs = rows(con, today, all=True)
    use = [r for r in rs if r["status_row"] == "in_use"]
    return {"count": len(use), "value": round(sum(r["price"] or 0 for r in use), 2),
            "under_warranty": sum(1 for r in use if r["under_warranty"]),
            "needs_receipt": sum(1 for r in use if r["needs_receipt"]),
            "no_manual": sum(1 for r in use if not r["has_manual"]),
            "gone": len(rs) - len(use)}


def find(con, frag):
    """The one in-use asset whose name contains `frag` (case-insensitive); ValueError when 0 or several match."""
    m = con.execute("SELECT id, name FROM home_assets WHERE LOWER(name) LIKE ? AND COALESCE(status,'in_use')='in_use'",
                    (f"%{frag.lower()}%",)).fetchall()
    if len(m) != 1:
        raise ValueError(f"expected exactly 1 asset match for {frag!r}, got {[x[1] for x in m]}")
    return m[0]


def _find(con, frag):
    try:
        return find(con, frag)
    except ValueError as e:
        sys.exit(str(e))


def _check_doc(con, did):
    if did is not None and not con.execute("SELECT 1 FROM documents WHERE id=?", (did,)).fetchone():
        sys.exit(f"no document {did}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "add", "set", "attach", "warranty", "dispose", "summary", "alerts"])
    ap.add_argument("args", nargs="*")
    for o in ("category", "brand-model", "purchase-date", "store", "serial-last4", "warranty-end", "notes", "location"):
        ap.add_argument("--" + o)
    for o, t in (("price", float), ("warranty-years", float), ("document-id", int), ("manual-id", int), ("vehicle-id", int)):
        ap.add_argument("--" + o, type=t)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--as", dest="as_", choices=["receipt", "manual"], default="receipt")
    ap.add_argument("--how", choices=STATUSES[1:], default="disposed")
    ap.add_argument("--date")
    a = ap.parse_args()
    con = db.connect(DB)
    today = dates.today()
    sets = {k: val for k, val in (("category", a.category), ("brand_model", a.brand_model), ("purchase_date", a.purchase_date),
                                  ("warranty_end", a.warranty_end), ("notes", a.notes), ("store", a.store), ("price", a.price),
                                  ("serial_last4", a.serial_last4), ("receipt_document_id", a.document_id),
                                  ("warranty_years", a.warranty_years), ("vehicle_id", a.vehicle_id), ("location", a.location),
                                  ("manual_document_id", a.manual_id)) if val is not None}
    for d in (a.purchase_date, a.warranty_end, a.date):
        if d:
            dt.date.fromisoformat(d)
    if a.serial_last4 and not (len(a.serial_last4) <= 4 and a.serial_last4.isalnum()):
        sys.exit("serial last4 only (max 4 characters)")
    if a.cmd == "list":
        for r in rows(con, today, all=a.all):
            print(f"{r['id']:>3} {r['name']:<28} {r['category'] or '':<11} {r['location'] or '':<12} bought={r['purchase_date'] or '?'} "
                  f"price={r['price'] if r['price'] is not None else '?'} warranty_end={r['expires'] or '?'} "
                  f"receipt={r['receipt_document_id'] or '-'} manual={r['manual_document_id'] or '-'} | {r['status']}")
    elif a.cmd == "summary":
        s = summary(con, today)
        print(f"{s['count']} items in use, value {s['value']:.2f}, {s['under_warranty']} under warranty, "
              f"{s['needs_receipt']} need a receipt, {s['no_manual']} without a manual, {s['gone']} sold/disposed/lost")
    elif a.cmd == "alerts":
        for x in alerts(con, today):
            print(x)
    elif a.cmd == "add":
        if not a.args:
            sys.exit("need a name")
        _check_doc(con, a.document_id)
        _check_doc(con, a.manual_id)
        cols = ["name"] + list(sets)
        con.execute(f"INSERT INTO home_assets({','.join(cols)}) VALUES({','.join('?' * len(cols))})", (a.args[0], *sets.values()))
        con.commit()
        print("added:", a.args[0])
    elif a.cmd == "set":
        if len(a.args) != 1 or not sets:
            sys.exit("set needs: <asset> and at least one option")
        _check_doc(con, a.document_id)
        _check_doc(con, a.manual_id)
        aid, name = _find(con, a.args[0])
        con.execute(f"UPDATE home_assets SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), aid))
        con.commit()
        print("updated:", name, ", ".join(sets))
    elif a.cmd == "attach":
        if len(a.args) != 2:
            sys.exit("attach needs: <asset> <document_id> [--as receipt|manual]")
        aid, name = _find(con, a.args[0])
        did = int(a.args[1])
        _check_doc(con, did)
        col = "manual_document_id" if a.as_ == "manual" else "receipt_document_id"
        con.execute(f"UPDATE home_assets SET {col}=? WHERE id=?", (did, aid))
        con.commit()
        print(f"attached document {did} to {name} as {a.as_}")
    elif a.cmd == "dispose":
        if len(a.args) != 1:
            sys.exit("dispose needs: <asset> [--how sold|disposed|lost] [--date YYYY-MM-DD]")
        aid, name = _find(con, a.args[0])
        con.execute("UPDATE home_assets SET status=?, disposed_date=? WHERE id=?", (a.how, a.date or today.isoformat(), aid))
        con.commit()
        print(f"{name}: {a.how} {a.date or today.isoformat()}")
    else:
        if len(a.args) != 2:
            sys.exit("warranty needs: <asset> <YYYY-MM-DD>")
        dt.date.fromisoformat(a.args[1])
        aid, name = _find(con, a.args[0])
        con.execute("UPDATE home_assets SET warranty_end=? WHERE id=?", (a.args[1], aid))
        con.commit()
        print(f"{name} warranty_end = {a.args[1]}")


if __name__ == "__main__":
    main()
