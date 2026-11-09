"""Family-life items: school, activities, medical, prescriptions, vaccines, pets, legal reviews, travel, gifts, chores.

  python data/life.py add DOMAIN "<title>" [--who NAME] [--due YYYY-MM-DD] [--every MONTHS] [--lead DAYS]
                          [--amount N] [--provider T] [--notes T]
  python data/life.py list [DOMAIN] [--who NAME]
  python data/life.py done "<title fragment>" [YYYY-MM-DD] [--who NAME]   recurring items roll forward; one-offs close
  python data/life.py set "<title fragment>" --due YYYY-MM-DD [--who NAME]
  python data/life.py drop "<title fragment>" [--who NAME]
  python data/life.py seed                    add starter items (no dates yet) for each member; safe to re-run
DOMAIN: school|activity|medical|prescription|vaccine|pet|legal|travel|gift|chore|other
Keep health notes minimal (no diagnoses); identifiers last4 only.
Library: rows(con, today), alerts(con, today), needs_date(con).
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
import config  # noqa: E402
import members  # noqa: E402
import db  # noqa: E402
from dates import parse as _d  # noqa: E402

DB = paths.DB
DOMAINS = ["school", "activity", "medical", "prescription", "vaccine", "pet", "legal", "travel", "gift", "chore", "other"]
KIND = {d: d.capitalize() for d in DOMAINS}
KIND.update({"prescription": "Medical", "vaccine": "Medical"})

# (domain, title, every_months, applies_to) - starters with no date; "Ask the family for the date" via digest
STARTERS = [
    ("legal", "Review will, beneficiaries and power of attorney", 36, "adult"),
    ("legal", "Review emergency contacts and the emergency sheet", 12, "household"),
    ("medical", "Vaccination record check", 12, "child"),
    ("school", "School registration / forms for the new year", 12, "child"),
    ("pet", "Vet checkup", 12, "pet"),
    ("pet", "Flea / tick / heartworm prevention refill", 1, "pet"),
]


def _add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    import calendar
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def rows(con, today, domain=None, who=None):
    con.row_factory = sqlite3.Row
    sql, p = "SELECT * FROM life_items WHERE status='open'", []
    if domain:
        sql += " AND domain=?"
        p.append(domain)
    if who:
        sql += " AND member=?"
        p.append(members.resolve(con, who))
    try:
        return [dict(r) for r in con.execute(sql + " ORDER BY COALESCE(due_date,'9999'), domain, title", p)]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def _vaccine_lead():
    try:
        import expiries
        return expiries.lead_days("vaccination")
    except ImportError:
        return 14


def alerts(con, today):
    out = []
    vlead = _vaccine_lead()
    for r in rows(con, today):
        d = _d(r["due_date"])
        if not d:
            continue
        lead = r["lead_days"] or 14
        if r["domain"] == "vaccine":
            lead = max(lead, vlead)  # the per-type lead from data/expiries.py, unless this row asks for more
        start = d - dt.timedelta(days=lead)
        if today >= start:
            who = f" ({r['member']})" if r["member"] else ""
            out.append({"date": d, "kind": KIND.get(r["domain"], "Family"), "title": f"{r['title']}{who}",
                        "detail": r["provider"] or "", "amount": r["amount"], "ref": ("life_items", r["id"])})
    return out


def needs_date(con):
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM life_items WHERE status='open' AND due_date IS NULL ORDER BY domain, title")]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def seed(con):
    n = 0
    names = config.members()
    for dom, title, every, who in STARTERS:
        targets = [None] if who == "household" else [m["name"] for m in names if m.get("role", "adult") == who]
        for t in targets:
            if con.execute("SELECT 1 FROM life_items WHERE title=? AND COALESCE(member,'')=COALESCE(?,'')", (title, t)).fetchone():
                continue
            con.execute("INSERT INTO life_items(domain, member, title, recur_months) VALUES (?,?,?,?)", (dom, t, title, every))
            n += 1
    con.commit()
    return n


def _match(con, frag, who):
    sql, p = "SELECT * FROM life_items WHERE status='open' AND LOWER(title) LIKE ?", [f"%{frag.lower()}%"]
    if who:
        sql += " AND member=?"
        p.append(members.resolve(con, who))
    con.row_factory = sqlite3.Row
    return con.execute(sql, p).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["add", "list", "done", "set", "drop", "seed"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--who")
    ap.add_argument("--due")
    ap.add_argument("--every", type=int)
    ap.add_argument("--lead", type=int)
    ap.add_argument("--amount", type=float)
    ap.add_argument("--provider")
    ap.add_argument("--notes")
    a = ap.parse_args()
    con = db.connect(DB)
    today = dates.today()
    if a.cmd == "seed":
        n = seed(con)
        print(f"added {n} starter item{'' if n == 1 else 's'}")
    elif a.cmd == "add":
        if len(a.args) < 2 or a.args[0] not in DOMAINS:
            raise SystemExit(f"usage: add DOMAIN TITLE ; DOMAIN in {DOMAINS}")
        con.execute("INSERT INTO life_items(domain, member, title, due_date, recur_months, lead_days, amount, provider, notes) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (a.args[0], members.resolve(con, a.who) if a.who else None, a.args[1], a.due, a.every,
                     a.lead if a.lead is not None else 14, a.amount, a.provider, a.notes))
        con.commit()
        print("added")
    elif a.cmd in ("done", "set", "drop"):
        if not a.args:
            raise SystemExit("title fragment required")
        hits = _match(con, a.args[0], a.who)
        if len(hits) != 1:
            raise SystemExit(f"{len(hits)} matches for '{a.args[0]}'; be more specific or add --who:\n" +
                             "\n".join(f"  {h['id']} {h['member'] or ''} {h['title']}" for h in hits))
        h = hits[0]
        if a.cmd == "drop":
            con.execute("UPDATE life_items SET status='dropped' WHERE id=?", (h["id"],))
        elif a.cmd == "set":
            con.execute("UPDATE life_items SET due_date=? WHERE id=?", (a.due, h["id"]))
        else:
            when = _d(a.args[1]) if len(a.args) > 1 else today
            if when is None:
                raise SystemExit(f"date must be YYYY-MM-DD, got {a.args[1]!r}")
            if h["recur_months"]:
                con.execute("UPDATE life_items SET last_done=?, due_date=? WHERE id=?",
                            (when.isoformat(), _add_months(when, h["recur_months"]).isoformat(), h["id"]))
            else:
                con.execute("UPDATE life_items SET last_done=?, status='done' WHERE id=?", (when.isoformat(), h["id"]))
        con.commit()
        print("ok")
    else:
        for r in rows(con, today, a.args[0] if a.args else None, a.who):
            print(f"{r['id']:>3}  {r['domain']:<12} {r['member'] or 'household':<10} {r['due_date'] or 'needs a date':<12} "
                  f"{('every ' + str(r['recur_months']) + 'mo') if r['recur_months'] else '':<10} {r['title']}")


if __name__ == "__main__":
    main()
