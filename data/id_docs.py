"""ID document expiry tracking (passports, licenses, permits) in data/family.db.

  python data/id_docs.py list
  python data/id_docs.py add <person> <doc_type> [--expires D] [--issued D] [--last4 NNNN] [--authority T]
                             [--document-id N] [--notes T]
  python data/id_docs.py set <person> <doc_type> --expires DATE [--last4 ..] [--issued ..] [--document-id N]
  python data/id_docs.py alerts
doc_type: passport|drivers_license|permit|state_id|green_card|vehicle_registration|insurance_card|other
Library: rows(con, today), alerts(con, today). Vehicle registrations (from `vehicles`) are listed read-only.
"""
import argparse
import datetime as dt
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402
import dates  # noqa: E402
import country  # noqa: E402
import db  # noqa: E402
from dates import parse as _d  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
_P = country.profile()
TYPES = list(_P.get("id_types") or ["passport", "drivers_license", "vehicle_registration", "insurance_card", "other"])
# lead times (days before expiry the reminder starts) come from data/expiries.py: the family's config/expiries.json,
# else the country profile's id_lead_days (passports ~9 months: renewals are slow, trips need 6 months validity), else 120
DEFAULT_LEAD = 120
_VEH = _P.get("vehicle") or {}


def _lead(typ):
    try:
        import expiries
        return expiries.lead_days(typ)
    except ImportError:
        return dict(_P.get("id_lead_days") or {}).get(typ, DEFAULT_LEAD)


def rows(con, today):
    con.row_factory = sqlite3.Row
    out = []
    for r in con.execute("SELECT * FROM id_documents WHERE active=1 ORDER BY person, doc_type"):
        r = dict(r)
        e = _d(r["expires"])
        lead = _lead(r["doc_type"])
        r["expires"], r["next_due"], r["lead_days"], r["read_only"] = e, e, lead, False
        if e is None:
            r["status"] = "needs a date"
        elif e < today:
            r["status"] = f"expired {(today - e).days}d ago"
        elif (e - today).days <= lead:
            r["status"] = f"renew soon ({(e - today).days}d left)"
        else:
            r["status"] = "ok"
        out.append(r)
    try:
        for v in con.execute("SELECT id,year,make,model,plate_last4,registration_expires FROM vehicles "
                             "WHERE status='active'"):
            e = _d(v["registration_expires"])
            vlead = _lead("vehicle_registration")
            if e is None:
                st = "needs a date"
            elif e < today:
                st = "expired"
            elif (e - today).days <= vlead:
                st = f"renew soon ({(e - today).days}d left)"
            else:
                st = "ok"
            out.append({"id": None, "person": f"{v['year']} {v['make']} {v['model']}",
                        "doc_type": "vehicle_registration", "number_last4": v["plate_last4"], "issued": None,
                        "expires": e, "next_due": e, "issuing_authority": f"{config.region()['state'] or ''} {_VEH.get('authority', 'licensing office')}".strip(), "document_id": None,
                        "notes": "From vehicles table (read-only)", "active": 1, "status": st,
                        "lead_days": vlead, "read_only": True})
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        pass
    return out


def alerts(con, today):
    out, missing = [], []
    for r in rows(con, today):
        if r["read_only"]:
            continue  # vehicle registrations are alerted by action_items already
        label = f"{r['person']} {r['doc_type'].replace('_', ' ')}"
        e = r["expires"]
        if e is None:
            missing.append(label)
        elif e <= today + dt.timedelta(days=r["lead_days"]):
            late = e < today
            if late:
                detail = "Overdue - renew now"
            elif r["doc_type"] == "passport":
                detail = "Renew early (passports take weeks; trips need 6 months validity)"
            else:
                detail = "Renew before it lapses"
            out.append({"date": e, "kind": "ID", "title": f"{label} {'EXPIRED' if late else 'expires'}",
                        "detail": detail, "amount": None})
    if missing:
        out.append({"date": today, "kind": "ID", "title": "1 ID document needs an expiry date" if len(missing) == 1
                    else f"{len(missing)} ID documents need an expiry date",
                    "detail": "; ".join(missing) + ". Add the dates under Family > Papers & IDs > Expiries and IDs.",
                    "amount": None})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "add", "set", "alerts"])
    ap.add_argument("args", nargs="*")
    for o in ("expires", "issued", "last4", "authority", "notes"):
        ap.add_argument("--" + o)
    ap.add_argument("--document-id", type=int)
    a = ap.parse_args()
    con = db.connect(DB)
    today = dates.today()
    if a.cmd == "list":
        for r in rows(con, today):
            print(f"{r['person']:<26} {r['doc_type']:<20} last4={r['number_last4'] or '-':<5} "
                  f"expires={str(r['expires'] or '?'):<11} {r['status']}{'  [read-only]' if r['read_only'] else ''}")
    elif a.cmd == "alerts":
        for x in alerts(con, today):
            print(x)
    else:
        if len(a.args) != 2:
            sys.exit(f"{a.cmd} needs: <person> <doc_type>")
        person, t = a.args
        if t not in TYPES:
            sys.exit(f"doc_type must be one of {TYPES}")
        for d in (a.expires, a.issued):
            if d:
                dt.date.fromisoformat(d)
        if a.last4 and not (len(a.last4) <= 4 and a.last4.isalnum()):
            sys.exit("last4 only (max 4 chars)")
        ex = con.execute("SELECT id FROM id_documents WHERE person=? AND doc_type=?", (person, t)).fetchone()
        if a.cmd == "set":
            if not ex:
                sys.exit("no such row; use add")
            if not a.expires:
                sys.exit("set needs --expires")
            con.execute("UPDATE id_documents SET expires=?, issued=COALESCE(?,issued), number_last4=COALESCE(?,number_last4),"
                        " document_id=COALESCE(?,document_id), issuing_authority=COALESCE(?,issuing_authority),"
                        " notes=COALESCE(?,notes), active=1 WHERE id=?",
                        (a.expires, a.issued, a.last4, a.document_id, a.authority, a.notes, ex[0]))
        else:
            if ex:
                sys.exit("already exists; use set")
            con.execute("INSERT INTO id_documents(person,doc_type,number_last4,issued,expires,issuing_authority,"
                        "document_id,notes) VALUES(?,?,?,?,?,?,?,?)",
                        (person, t, a.last4, a.issued, a.expires, a.authority, a.document_id, a.notes))
        con.commit()
        print(f"{a.cmd}: {person} {t}")


if __name__ == "__main__":
    main()
