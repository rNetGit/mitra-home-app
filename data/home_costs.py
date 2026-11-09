"""Home costs (Money > Home costs): what the house costs to run, month by month and over the year. No AI.

Housing (rent, mortgage, repairs, upkeep), Utilities, and the insurance that names the home, taken from the same
spending lines and the same category grouping as the Statement (month_statement.group_of). Shows the last 12 months as
bars, an average a month, the year in total, each category with its share, the share of income, and how this month
compares with the average.
"""
import sqlite3

import db
import month_statement as MS
import paths
import trends as T

GROUPS = ("Housing", "Utilities")
HOME_WORDS = ("home", "house", "renter", "property", "flood", "hoa")  # an insurance category that is about the home
MONTHS = 12


def is_home(category):
    g = MS.group_of(category)
    if g in GROUPS:
        return g
    if g == "Insurance" and any(w in (category or "").lower() for w in HOME_WORDS):
        return "Insurance"
    return None


def _month_cats(con, ym):
    out = {}
    for c, v in MS._cat_totals(con, ym).items():
        g = is_home(c)
        if g and v:
            out[c] = (g, v)
    return out


def costs(con, ym=None, today=None):
    """{month, label, long, months, older, newer, partial, series [{month, label, total, rows}], this, avg, year, share,
    vs_avg, groups [{name, now, avg, year, rows [{category, now, avg, year, pct}]}]} or None without statements."""
    m = T.month_summary(con, ym, today=today)
    if not m:
        return None
    if ym is None and m["partial"] and m["older"]:
        m = T.month_summary(con, m["older"], today=today)
    ym = m["month"]
    first = T.shift(ym, -(MONTHS - 1))
    have = T._by_month(con, first, ym)
    series, per_month = [], {}
    for k in range(MONTHS - 1, -1, -1):
        mm = T.shift(ym, -k)
        row = have.get(mm) or {}
        cats = _month_cats(con, mm) if row.get("rows") else {}
        per_month[mm] = cats
        series.append({"month": mm, "label": T.label(mm)[:3], "total": round(sum(v for _, v in cats.values()), 2),
                       "rows": bool(row.get("rows")), "income": row.get("income", 0.0) if row.get("rows") else 0.0})
    counted = [s for s in series if s["rows"]]
    n = len(counted) or 1
    names = {}
    for mm, cats in per_month.items():
        for c, (g, v) in cats.items():
            e = names.setdefault(c, {"category": c, "group": g, "now": 0.0, "year": 0.0})
            e["year"] += v
            if mm == ym:
                e["now"] = v
    year = round(sum(s["total"] for s in counted), 2)
    avg = round(year / n, 2)
    this = series[-1]["total"]
    groups = {}
    for e in names.values():
        e["avg"] = round(e["year"] / n, 2)
        e["year"] = round(e["year"], 2)
        e["now"] = round(e["now"], 2)
        e["pct"] = round(e["year"] / year * 100) if year else 0
        g = groups.setdefault(e["group"], {"name": e["group"], "now": 0.0, "avg": 0.0, "year": 0.0, "rows": []})
        g["rows"].append(e)
        g["now"] += e["now"]
        g["avg"] += e["avg"]
        g["year"] += e["year"]
    glist = sorted(groups.values(), key=lambda g: -g["year"])
    for g in glist:
        g["rows"].sort(key=lambda r: -r["year"])
        for k in ("now", "avg", "year"):
            g[k] = round(g[k], 2)
        g["single"] = len(g["rows"]) == 1 and g["rows"][0]["category"].lower() == g["name"].lower()
    inc = sum(s["income"] for s in counted)
    top = max([s["total"] for s in series] + [1])
    for s in series:
        s["h"] = round(s["total"] / top * 100) if top else 0
    return {"month": ym, "label": m["label"], "long": m["long"], "months": m["months"], "older": m["older"], "newer": m["newer"],
            "partial": m["partial"], "series": series, "months_counted": len(counted), "this": this, "avg": avg, "year": year,
            "share": round(year / inc * 100) if inc else None,
            "vs_avg": round((this - avg) / avg * 100) if avg and series[-1]["rows"] else None,
            "groups": glist}


def view(ym=None, today=None):
    try:
        con = db.connect(paths.DB, readonly=True)
    except sqlite3.Error:
        return None
    try:
        return costs(con, ym, today=today)
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
