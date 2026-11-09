"""Home-office tax prep: records, both calculation methods, eligibility checklist, document list.

  python data/home_office.py profile YEAR WHO [--office-sqft N] [--home-sqft N] [--months N] [--method simplified|regular]
                                  [--exclusive 0|1] [--regular 0|1] [--principal 0|1] [--self-employed 0|1]
                                  [--income N] [--notes T]
  python data/home_office.py add YEAR CATEGORY AMOUNT [--who NAME] [--desc T] [--date D] [--direct] [--document-id N]
  python data/home_office.py list YEAR
  python data/home_office.py suggest YEAR      candidate utility/insurance/internet totals from transactions (nothing saved)
  python data/home_office.py report YEAR       reports/YYYY_home_office.md (checklist, both methods, documents to gather)

Records and arithmetic only, NOT tax advice. Whether a deduction is allowed, and the current-year rate and limits,
are for the user's tax preparer or the IRS (Pub. 587 / Form 8829 / Schedule C). Federal rules generally do not let
W-2 employees deduct home-office costs; some states differ. Store no account numbers; documents go in archive/<year>/tax/.
Library: alerts(con, today), compute(con, year, who).
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
import country  # noqa: E402
import members  # noqa: E402
import db  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = HERE.parent
DB = paths.DB
SIMPLIFIED_RATE = 5.0       # US default, kept for older callers; compute() reads the country profile
SIMPLIFIED_MAX_SQFT = 300


def rule():
    """The country's simplified home-office rule: {"method": per_area|flat_rate_weekly|none, "rate", "max_area", "label", "note"}."""
    return country.profile().get("home_office") or {"method": "none", "label": "none", "note": ""}


def area_unit():
    return country.units().get("area", "sq ft")


def simplified_amount(office_area, months, r=None):
    """What the country's simplified method gives for this office over `months` months (0 when there is none)."""
    r = r or rule()
    if r.get("method") == "per_area":
        return min(office_area or 0, r.get("max_area") or 1e9) * float(r.get("rate") or 0) * months / 12
    if r.get("method") == "flat_rate_weekly":
        return float(r.get("rate") or 0) * 52 * months / 12
    return 0.0
CATEGORIES = ["rent", "mortgage_interest", "property_tax", "insurance", "utilities", "repairs", "hoa",
              "depreciation", "internet", "phone", "supplies", "equipment", "other"]
DOCS = [
    "Lease or mortgage statement / Form 1098 (whole-home cost, shows interest paid)",
    "Property tax bill and receipt",
    "Homeowner's or renter's insurance declarations page (annual premium)",
    "Utility bills for the year (electric, gas, water, trash) - 12 months",
    "Internet and phone bills (and your business-use share)",
    "Repair and maintenance receipts (note whether they cover the whole home or only the office)",
    "Office measurement: length x width of the office and total finished home square feet (photo or sketch)",
    "A short note of how the room is used only for work, and the dates the space qualified",
    "Equipment / furniture receipts (may fall under separate business-expense or depreciation rules)",
]


def _profile(con, year, who=None):
    con.row_factory = sqlite3.Row
    try:
        sql, p = "SELECT * FROM home_office_profile WHERE tax_year=?", [year]
        if who:
            sql += " AND who=?"
            p.append(members.resolve(con, who))
        return [dict(r) for r in con.execute(sql, p)]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def compute(con, year, who):
    prof = (_profile(con, year, who) or [None])[0]
    if not prof:
        return None
    office, home, months = prof["office_sqft"] or 0, prof["home_sqft"] or 0, prof["months_used"] or 12
    exp = [dict(r) for r in con.execute("SELECT * FROM home_office_expenses WHERE tax_year=? AND (who IS NULL OR who=?)", (year, prof["who"]))]
    pct = (office / home) if home else 0.0
    r = rule()
    simplified = simplified_amount(office, months, r)
    whole = sum(e["amount"] for e in exp if not e["direct"] and e["category"] != "depreciation")
    direct = sum(e["amount"] for e in exp if e["direct"])
    deprec = sum(e["amount"] for e in exp if e["category"] == "depreciation")
    regular = whole * pct * months / 12 + direct + deprec * pct
    issues = []
    if not office or not home:
        issues.append(f"Enter office and home area in {area_unit()} (measure the space): --office-sqft / --home-sqft.")
    if prof["self_employed"] == 0:
        issues.append(r.get("employee_warning") or "Marked as NOT self-employed: check whether employees may claim home-office costs where you live.")
    elif prof["self_employed"] is None:
        issues.append("Answer: self-employed or business owner (not an employee)?")
    for key, label in (("exclusive_use", "used ONLY for business"), ("regular_use", "used on a regular basis"),
                       ("principal_place", "principal place of business or meets another qualifying use")):
        if prof[key] == 0:
            issues.append(f"Marked NOT {label}: the space may not qualify.")
        elif prof[key] is None:
            issues.append(f"Answer: is the space {label}?")
    if prof["gross_income"] is None:
        issues.append("Record gross business income: the deduction cannot exceed it.")
    return {"profile": prof, "pct": pct, "simplified": simplified, "regular": regular, "whole": whole,
            "direct": direct, "depreciation": deprec, "expenses": exp, "issues": issues, "rule": r, "unit": area_unit()}


def alerts(con, today):
    out = []
    try:
        for who, year in con.execute("SELECT who, tax_year FROM home_office_profile WHERE tax_year >= ?", (today.year - 1,)):
            c = compute(con, year, who)
            if c and c["issues"]:
                due = dt.date(year + 1, 3, 1) if year < today.year else dt.date(year, 12, 31)
                out.append({"date": max(due, today), "kind": "Tax",
                            "title": f"Home office {year} ({who}): {len(c['issues'])} open question(s)",
                            "detail": c["issues"][0], "amount": None})
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        pass
    return out


def suggest(con, year):
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    rows = list(con.execute(
        "SELECT txn_type, COALESCE(payee, substr(description,1,30)), ROUND(SUM(-amount),2), COUNT(*) FROM transactions "
        "WHERE amount<0 AND txn_type IN ('utility','insurance') AND txn_date BETWEEN ? AND ? GROUP BY 1,2 ORDER BY 3 DESC", (y0, y1)))
    return rows


def report(con, year):
    r, unit = rule(), area_unit()
    out = [f"# Home office {year}", "", "_Records and arithmetic only. Not tax advice; confirm with your preparer. "
           f"{r.get('note', '')}_", ""]
    profs = _profile(con, year)
    if not profs:
        out += ["No home-office profile yet. Run: `python data/home_office.py profile %d NAME --office-sqft N --home-sqft N`" % year, ""]
    for p in profs:
        c = compute(con, year, p["who"])
        out += [f"## {p['who']}", "",
                f"- Office {p['office_sqft'] or '?'} {unit} of {p['home_sqft'] or '?'} {unit} home = **{c['pct']:.1%}** business-use share; months qualified: {p['months_used']}",
                (f"- Simplified method ({r.get('label', '')}): **{_fmt(c['simplified'])}**" if r.get("method") != "none"
                 else f"- Simplified method: {r.get('label', 'none for this country')}"),
                f"- Regular method (actual expenses x share + direct costs): **{_fmt(c['regular'])}** "
                f"(whole-home costs {_fmt(c['whole'])}, direct {_fmt(c['direct'])}, depreciation {_fmt(c['depreciation'])})",
                f"- Chosen method on file: {p['method']}",
                "- Either method is capped by gross business income" + (f" ({_fmt(p['gross_income'])} recorded)." if p["gross_income"] is not None else " (not recorded)."), ""]
        if c["issues"]:
            out += ["### Open questions", ""] + [f"- {i}" for i in c["issues"]] + [""]
        if c["expenses"]:
            out += ["### Expenses on file", "", "| Date | Category | Description | Amount | Direct |", "|---|---|---|---|---|"]
            out += [f"| {e['expense_date'] or ''} | {e['category']} | {e['description'] or ''} | {_fmt(e['amount'])} | {'yes' if e['direct'] else ''} |"
                    for e in c["expenses"]]
            out += [""]
    sg = suggest(con, year)
    if sg:
        out += ["## Candidate costs from your transactions (not yet saved: add the ones that are whole-home costs)", "",
                "| Type | Payee | Total | Payments |", "|---|---|---|---|"] + [f"| {a} | {b} | {_fmt(c)} | {d} |" for a, b, c, d in sg] + [""]
    out += ["## Documents to gather", ""] + [f"- [ ] {d}" for d in DOCS] + [""]
    path = paths.REPORTS / f"{year}_home_office.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["profile", "add", "list", "suggest", "report"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--office-sqft", type=float)
    ap.add_argument("--home-sqft", type=float)
    ap.add_argument("--months", type=int)
    ap.add_argument("--method", choices=["simplified", "regular"])
    for f in ("exclusive", "regular", "principal", "self-employed"):
        ap.add_argument(f"--{f}", type=int, choices=[0, 1])
    ap.add_argument("--income", type=float)
    ap.add_argument("--notes")
    ap.add_argument("--who")
    ap.add_argument("--desc")
    ap.add_argument("--date")
    ap.add_argument("--direct", action="store_true")
    ap.add_argument("--document-id", type=int)
    a = ap.parse_args()
    con = db.connect(DB)
    year = int(a.args[0]) if a.args else dates.today().year
    if a.cmd == "profile":
        if len(a.args) < 2:
            raise SystemExit("usage: profile YEAR WHO [options]")
        who = members.resolve(con, a.args[1])
        con.execute("INSERT OR IGNORE INTO home_office_profile(tax_year, who) VALUES (?,?)", (year, who))
        for col, val in (("office_sqft", a.office_sqft), ("home_sqft", a.home_sqft), ("months_used", a.months),
                         ("method", a.method), ("exclusive_use", a.exclusive), ("regular_use", a.regular),
                         ("principal_place", a.principal), ("self_employed", a.self_employed),
                         ("gross_income", a.income), ("notes", a.notes)):
            if val is not None:
                con.execute(f"UPDATE home_office_profile SET {col}=? WHERE tax_year=? AND who=?", (val, year, who))
        con.commit()
        print("saved")
    elif a.cmd == "add":
        if len(a.args) < 3 or a.args[1] not in CATEGORIES:
            raise SystemExit(f"usage: add YEAR CATEGORY AMOUNT ; CATEGORY in {CATEGORIES}")
        con.execute("INSERT INTO home_office_expenses(tax_year, who, category, description, amount, expense_date, direct, document_id) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (year, members.resolve(con, a.who) if a.who else None, a.args[1], a.desc, float(a.args[2]), a.date,
                     1 if a.direct else 0, a.document_id))
        con.commit()
        print("added")
    elif a.cmd == "suggest":
        for r in suggest(con, year):
            print(*r, sep="  ")
    elif a.cmd == "report":
        print(report(con, year))
    else:
        for r in con.execute("SELECT id, who, category, description, amount, expense_date, direct FROM home_office_expenses WHERE tax_year=?", (year,)):
            print(*r, sep="  ")


if __name__ == "__main__":
    main()
