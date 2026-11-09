"""Everything that expires, in one place, with a reminder lead time per type.

  python data/expiries.py list                 every expiring thing: ID documents, vehicle registration and inspection,
                                               warranties, vaccinations, insurance terms; status and days left
  python data/expiries.py leads                the lead time (days before the date the reminder starts) per type
  python data/expiries.py lead TYPE DAYS       change one (saved in config/expiries.json); DAYS = "default" resets it
  python data/expiries.py soon                 only the rows inside their reminder window (expired or renew soon)

Where the dates live (nothing is copied; this module only reads them): `id_documents` (data/id_docs.py), `vehicles`
(registration_expires, inspection_expires), `home_assets` (warranty_end or purchase_date + warranty_years, data/assets.py),
`life_items` with domain vaccine (data/life.py), `policies` (term_end), `saved_items` deals with an end date
(data/saved.py; family and adults items only, ended deals drop out), `wallet_cards` with an expiry date (data/wallet.py). The existing modules keep raising the alerts the
Action tab, the digest and the .ics file show; they read their lead time from here, so one setting changes all of them.

Library: TYPES, lead_days(type), leads(), set_lead(type, days|None), rows(con, today), soon(con, today), needs_date(con, today).
"""
import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import country  # noqa: E402
import db  # noqa: E402
from dates import parse as _d  # noqa: E402

DB = paths.DB
CFG = config.CONFIG_DIR / "expiries.json"
MAX_LEAD = 730
# built-in defaults; the country profile's id_lead_days (passport 274, UK brp 180...) sit on top, config/expiries.json on top of that
DEFAULTS = {"id_document": 120, "vehicle_registration": 60, "vehicle_inspection": 45, "warranty": 90, "vaccination": 30,
            "insurance": 30, "deal": 3, "wallet_card": 30}


def _profile():
    return country.profile()


def id_types():
    """ID document types for this country, minus vehicle_registration (that is a vehicles-table type here)."""
    return [t for t in (_profile().get("id_types") or ["passport", "drivers_license", "other"]) if t != "vehicle_registration"]


def types():
    """Every type a lead time can be set for, in display order."""
    return id_types() + ["vehicle_registration", "vehicle_inspection", "warranty", "vaccination", "insurance", "deal", "wallet_card"]


TYPES = types()


def _cfg():
    try:
        d = json.loads(CFG.read_text(encoding="utf-8")) if CFG.exists() else {}
    except (OSError, ValueError):
        d = {}
    return d if isinstance(d, dict) else {}


def default_lead(typ):
    prof = _profile().get("id_lead_days") or {}
    if typ in prof:
        return int(prof[typ])
    if typ in id_types():
        return DEFAULTS["id_document"]
    return DEFAULTS.get(typ, DEFAULTS["id_document"])


def lead_days(typ):
    """Reminder lead for one type: the family's setting, else the country profile, else the built-in default."""
    own = (_cfg().get("lead_days") or {}).get(typ)
    try:
        if own is not None and 0 <= int(own) <= MAX_LEAD:
            return int(own)
    except (TypeError, ValueError):
        pass
    return default_lead(typ)


def leads():
    """[{type, lead_days, default, custom}] for every type."""
    own = _cfg().get("lead_days") or {}
    return [{"type": t, "lead_days": lead_days(t), "default": default_lead(t), "custom": t in own} for t in types()]


def set_lead(typ, days):
    """Save a lead time for one type (days None = back to the default). Returns the lead now in force."""
    if typ not in types():
        raise ValueError(f"type must be one of {types()}")
    d = _cfg()
    ld = dict(d.get("lead_days") or {})
    if days is None:
        ld.pop(typ, None)
    else:
        days = int(days)
        if not 0 <= days <= MAX_LEAD:
            raise ValueError(f"lead days must be 0 to {MAX_LEAD}")
        ld[typ] = days
    d["lead_days"] = ld
    config.write_json(CFG, d)
    return lead_days(typ)


def _status(e, today, lead):
    if e is None:
        return "needs a date", None
    left = (e - today).days
    if left < 0:
        return f"expired {-left}d ago", left
    if left <= lead:
        return f"renew soon ({left}d left)", left
    return "ok", left


def _q(con, sql, params=()):
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def rows(con, today):
    """Every expiring thing: {type, label, who, what, expires, lead_days, days_left, status, ref, source, last4}.
    Order: expired first, then by date, then the ones that need a date."""
    out = []
    veh = _profile().get("vehicle") or {}
    reg_label, ins_label = veh.get("registration_label", "registration"), veh.get("inspection_label", "inspection")

    def add(typ, who, what, expires, ref, source, last4=None):
        e = _d(expires)
        lead = lead_days(typ)
        st, left = _status(e, today, lead)
        out.append({"type": typ, "label": typ.replace("_", " "), "who": who or "", "what": what, "expires": e,
                    "lead_days": lead, "days_left": left, "status": st, "ref": ref, "source": source, "last4": last4 or ""})

    for r in _q(con, "SELECT id, person, doc_type, number_last4, expires FROM id_documents WHERE active=1 ORDER BY person, doc_type"):
        add(r["doc_type"], r["person"], r["doc_type"].replace("_", " "), r["expires"], ("id_documents", r["id"]), "id_docs.py", r["number_last4"])
    for r in _q(con, "SELECT id, year, make, model, plate_last4, registration_expires, inspection_expires FROM vehicles WHERE status='active'"):
        car = f"{r['year']} {r['make']} {r['model']}".strip()
        add("vehicle_registration", car, reg_label, r["registration_expires"], ("vehicles", r["id"]), "vehicles table", r["plate_last4"])
        add("vehicle_inspection", car, ins_label, r["inspection_expires"], ("vehicles", r["id"]), "vehicles table", r["plate_last4"])
    try:
        import assets as _assets
        for r in _assets.rows(con, today):
            add("warranty", "", f"{r['name']} warranty", r["expires"], ("home_assets", r["id"]), "assets.py")
    except (ImportError, sqlite3.OperationalError) as e:
        if isinstance(e, sqlite3.OperationalError) and not db.missing(e):
            raise
    for r in _q(con, "SELECT id, member, title, due_date FROM life_items WHERE status='open' AND domain='vaccine' ORDER BY due_date"):
        add("vaccination", r["member"] or "household", r["title"], r["due_date"], ("life_items", r["id"]), "life.py")
    for r in _q(con, "SELECT id, kind, carrier, policy_last4, term_end FROM policies "
                     "WHERE status IS NULL OR status NOT IN ('expired','replaced','cancelled','superseded')"):
        add("insurance", r["carrier"] or "", f"{r['kind'] or 'insurance'} policy", r["term_end"], ("policies", r["id"]), "insurance agent",
            r["policy_last4"])
    try:
        import saved as _saved
        for r in _saved.expiry_rows(con, today):
            add("deal", "", r["title"], r["expires_on"], ("saved_items", r["id"]), "saved.py")
    except ImportError:
        pass
    for r in _q(con, "SELECT id, title, member, number_last4, expires FROM wallet_cards WHERE status='active' "
                     "AND expires IS NOT NULL ORDER BY expires"):
        add("wallet_card", r["member"] or "household", f"{r['title']} card", r["expires"], ("wallet_cards", r["id"]),
            "wallet.py", r["number_last4"])
    out.sort(key=lambda x: (x["expires"] is None, x["expires"] or dt.date.max, x["type"], x["who"]))
    return out


def soon(con, today):
    """Rows inside their reminder window (expired or renew soon), whatever the date: the digest's 'Expiring' section."""
    return [r for r in rows(con, today) if r["expires"] is not None and r["days_left"] <= r["lead_days"]]


def needs_date(con, today):
    return [r for r in rows(con, today) if r["expires"] is None]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "leads", "lead", "soon"])
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    today = dates.today()
    if a.cmd == "lead":
        if len(a.args) != 2:
            raise SystemExit("lead needs: TYPE DAYS  (DAYS = default to reset)")
        typ, days = a.args
        try:
            now = set_lead(typ, None if days.lower() == "default" else days)
        except ValueError as e:
            raise SystemExit(str(e))
        print(f"{typ}: reminders start {now} days before the date")
        return
    if a.cmd == "leads":
        for r in leads():
            print(f"{r['type']:<22} {r['lead_days']:>4} days" + (f"  (default {r['default']})" if r["custom"] else ""))
        return
    con = db.connect(DB, readonly=True)
    try:
        rws = soon(con, today) if a.cmd == "soon" else rows(con, today)
    finally:
        con.close()
    for r in rws:
        print(f"{r['status']:<24} {r['label']:<22} {r['who']:<22} {r['what']:<30} {str(r['expires'] or '?'):<11} "
              f"lead {r['lead_days']}d  [{r['source']}]")
    if not rws:
        print("nothing" if a.cmd == "soon" else "nothing recorded yet")


if __name__ == "__main__":
    main()
