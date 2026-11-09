"""Monthly budget versus actual, from `transactions.category` (set by category_rules).

  python data/budget.py set "<category>" <monthly_limit>
  python data/budget.py allowance <member> <monthly_amount>    a budget line called allowance:<member>
  python data/budget.py list
  python data/budget.py pace                  this month so far: spent, expected by now, projected, green/amber/red
  python data/budget.py suggest               a limit per category from the last six full months of spend
  python data/budget.py report [YYYY-MM]      actual vs limit per category for a finished month, plus spend with no line
Spend = the Ledger's spending (ledger_data.spend_lines, the one rule): card purchases count once (when charged) and the
later card payment does not double-count; tax, transfers and investing are not spending; a refund comes off.

Pace: the month is measured up to the newest loaded transaction (`through`), not the calendar day, so a statement
that is not loaded yet never looks like money unspent. expected = limit x days elapsed / days in month;
projected = spent x days in month / days elapsed. red = already over the limit; amber = on course to pass it
(projected > limit); green otherwise. Allowance lines (`allowance:<name>`) are ordinary budget lines grouped under
"Allowances"; children never see them (their screen reads no money tables).

Library: variance(con, month) -> [(category, limit, actual, over)], unbudgeted(con, month),
pace(con, today) -> {"month", "through", "day", "days", "lines": [row...]}, suggest(con, today, months=6) -> [row...].
"""
import argparse
import calendar
import datetime as dt
import math
import sqlite3
import db  # noqa: E402
import dates  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
ALLOWANCE = "allowance:"
AMBER_SLACK = 1.0   # projected > limit * AMBER_SLACK -> amber (1.0 = any projected overrun)


def _actuals(con, month):
    """{category: spent in the month} by the one spending rule (ledger_data.spend_lines: a refund comes off). A card
    payment standing for a card with no statement is left out: it has no category a budget line could name."""
    import ledger_data
    try:
        last = (dt.date(int(month[:4]) + int(month[5:7]) // 12, int(month[5:7]) % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
        got = {}
        for t in ledger_data.spend_lines(con, month + "-01", last):
            if t["card"]:
                continue
            c = t["category"] or "uncategorized"
            got[c] = got.get(c, 0) - t["cents"]
        return {c: round(v / 100, 2) for c, v in got.items()}
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return {}


def _limits(con):
    try:
        return list(con.execute("SELECT category, monthly_limit FROM budget ORDER BY category"))
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def variance(con, month):
    act = _actuals(con, month)
    return [(c, l, act.get(c, 0.0), act.get(c, 0.0) - l) for c, l in _limits(con)]


def unbudgeted(con, month):
    act = _actuals(con, month)
    have = {c for c, _ in _limits(con)}
    return sorted(((c, a) for c, a in act.items() if c not in have), key=lambda x: -x[1])


def is_allowance(category):
    return (category or "").lower().startswith(ALLOWANCE)


def label(category):
    """'allowance:Sam' -> 'Sam's allowance'; anything else unchanged."""
    return f"{category[len(ALLOWANCE):]}'s allowance" if is_allowance(category) else category


def _through(con, today):
    """Newest loaded transaction date within this month, else the 1st (nothing loaded yet); never after today."""
    month = today.strftime("%Y-%m")
    try:
        latest = con.execute("SELECT MAX(txn_date) FROM transactions WHERE substr(txn_date,1,7)=?", (month,)).fetchone()[0]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        latest = None
    if not latest:
        return today.replace(day=1), False
    d = dt.date.fromisoformat(latest[:10])
    return min(d, today), True


def pace(con, today=None):
    """This month so far, per budget line. Each line: category, label, limit, spent, expected, projected, status
    (green|amber|red), pct (spent / limit), allowance (bool)."""
    today = today or dates.today()
    month = today.strftime("%Y-%m")
    through, loaded = _through(con, today)
    days = calendar.monthrange(today.year, today.month)[1]
    day = through.day
    act = _actuals(con, month)
    lines = []
    for c, lim in _limits(con):
        spent = act.get(c, 0.0)
        expected = round(lim * day / days, 2)
        projected = round(spent * days / day, 2) if day else spent
        if lim > 0 and spent > lim:
            status = "red"
        elif lim > 0 and projected > lim * AMBER_SLACK and spent > 0:
            status = "amber"
        else:
            status = "green"
        lines.append({"category": c, "label": label(c), "limit": lim, "spent": spent, "expected": expected,
                      "projected": projected, "status": status, "pct": round(100 * spent / lim) if lim else None,
                      "allowance": is_allowance(c)})
    order = {"red": 0, "amber": 1, "green": 2}
    lines.sort(key=lambda r: (r["allowance"], order[r["status"]], -r["spent"]))
    return {"month": month, "through": through, "day": day, "days": days, "loaded": loaded, "lines": lines}


def _round_up(x, step=10):
    return float(int(math.ceil(x / step)) * step) if x > 0 else 0.0


def suggest(con, today=None, months=6):
    """Average monthly spend per category over the last `months` full months, rounded up to 10, next to the current
    limit. Rows: category, months (with spend), average, suggested, limit, change (suggested - limit or None)."""
    today = today or dates.today()
    first = today.replace(day=1)
    keys = []
    for _ in range(months):
        last = first - dt.timedelta(days=1)
        keys.append(last.strftime("%Y-%m"))
        first = last.replace(day=1)
    totals, seen = {}, {}
    for m in keys:
        for c, a in _actuals(con, m).items():
            totals[c] = totals.get(c, 0.0) + a
            seen[c] = seen.get(c, 0) + 1
    limits = dict(_limits(con))
    out = []
    for c, tot in totals.items():
        if c == "uncategorized" or is_allowance(c):
            continue
        avg = round(tot / months, 2)
        sug = _round_up(avg)
        lim = limits.get(c)
        out.append({"category": c, "months": seen[c], "average": avg, "suggested": sug, "limit": lim,
                    "change": round(sug - lim, 2) if lim is not None else None})
    out.sort(key=lambda r: -r["average"])
    return out


def digest_line(con, today=None):
    """One line for the weekly digest, or '' when there are no budget lines."""
    p = pace(con, today)
    if not p["lines"]:
        return ""
    from money import fmt
    red = [r for r in p["lines"] if r["status"] == "red"]
    amber = [r for r in p["lines"] if r["status"] == "amber"]
    green = [r for r in p["lines"] if r["status"] == "green"]
    parts = []
    if red:
        parts.append("over: " + ", ".join(f"**{r['label']}** {fmt(r['spent'])} of {fmt(r['limit'])}" for r in red))
    if amber:
        parts.append("on course to pass: " + ", ".join(f"{r['label']} (projected {fmt(r['projected'])} of {fmt(r['limit'])})" for r in amber))
    if green:
        parts.append(f"{len(green)} on track")
    when = f"through {p['through']:%b %d}" if p["loaded"] else "no transactions loaded for this month yet"
    return f"Budget, {today.strftime('%B') if today else p['month']} so far ({when}): " + "; ".join(parts) + "."


def main():
    ap = argparse.ArgumentParser(description="Monthly budget: limits, pace this month, suggested limits, finished-month report.")
    ap.add_argument("cmd", choices=["set", "allowance", "list", "pace", "suggest", "report"])
    ap.add_argument("a", nargs="?")
    ap.add_argument("b", nargs="?")
    x = ap.parse_args()
    con = db.connect(DB)
    today = dates.today()
    if x.cmd in ("set", "allowance"):
        if not (x.a and x.b):
            ap.error(f"usage: {x.cmd} <{'member' if x.cmd == 'allowance' else 'category'}> <monthly amount>")
        cat = (ALLOWANCE + x.a.strip()) if x.cmd == "allowance" else x.a
        try:
            amount = float(x.b)
        except ValueError:
            ap.error("amount must be a number")
        if amount < 0 or amount > 1e7:
            ap.error("amount must be between 0 and 10,000,000")
        con.execute("INSERT INTO budget(category, monthly_limit) VALUES (?,?) ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit",
                    (cat, amount))
        con.commit()
        print(f"{label(cat)}: {amount:,.2f} a month")
    elif x.cmd == "pace":
        p = pace(con, today)
        if not p["lines"]:
            print("No budget lines yet: python data/budget.py set <category> <monthly limit>  (python data/budget.py suggest helps)")
        else:
            print(f"Budget {p['month']}, through {p['through']} (day {p['day']} of {p['days']})"
                  + ("" if p["loaded"] else "; no transactions loaded for this month yet"))
            for r in p["lines"]:
                print(f"  {r['status'].upper():5} {r['label']:<24} spent {r['spent']:>9.2f} of {r['limit']:>9.2f}  "
                      f"expected by now {r['expected']:>9.2f}  projected {r['projected']:>9.2f}")
    elif x.cmd == "suggest":
        rows = suggest(con, today)
        if not rows:
            print("No categorised spend in the last six full months yet.")
        for r in rows:
            cur = f"limit {r['limit']:>9.2f}  ({'+' if r['change'] > 0 else ''}{r['change']:.2f})" if r["limit"] is not None else "no line"
            print(f"  {r['category']:<24} avg {r['average']:>9.2f}/mo over {r['months']} mo  suggest {r['suggested']:>9.2f}  {cur}")
        if rows:
            print('Apply one: python data/budget.py set "<category>" <amount>')
    elif x.cmd == "report":
        month = x.a or (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
        print(f"Budget vs actual, {month}")
        for c, l, a, o in variance(con, month):
            print(f"  {label(c):<24} limit {l:>9.2f}  actual {a:>9.2f}  {'OVER by %.2f' % o if o > 0 else 'ok'}")
        for c, a in unbudgeted(con, month)[:10]:
            print(f"  (no budget) {c:<18} actual {a:>9.2f}")
    else:
        for r in con.execute("SELECT category, monthly_limit FROM budget ORDER BY category"):
            print(r)


if __name__ == "__main__":
    main()
