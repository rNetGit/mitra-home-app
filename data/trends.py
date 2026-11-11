"""Money trends from the filed statements, no AI: month over month and this year against last year.

    python data/trends.py                 the last 12 months: income, expenses, what was left, each month against the
                                          one before and against the same month a year earlier
    python data/trends.py categories      which categories moved most, last 12 months against the 12 before

What counts (one rule everywhere, `ledger_data.spend_lines`: the Ledger, Money, Trends, the monthly report, the chat
chip, the budget, the Mitra Wall and the phones):
  * income   = rows typed income or interest, with their sign.
  * expenses = the Ledger's spending: spend (or no type), fee, utility, insurance and loan payment lines, a refund
    coming off; tax, transfers, investing and card payments are not spending. A card payment counts only in a month
    with no card transactions of its own (when the card statements are filed, the card's lines are the spend and the
    payment would count it twice).
  * The window ends at the newest month that has transactions. The calendar month still running is `partial`: shown,
    but never compared with a full month and left out of totals and sentences.
"""
import datetime as dt
import sys

import db
import dates  # noqa: E402
import ledger_data as L
import rule_match

INTERNAL = ("transfer", "investment_transfer")
TOP = 8


def shift(ym, k):
    """'2026-03' + k months."""
    y, m = int(ym[:4]), int(ym[5:7])
    i = y * 12 + m - 1 + k
    return f"{i // 12:04d}-{i % 12 + 1:02d}"


def label(ym):
    return dt.date(int(ym[:4]), int(ym[5:7]), 1).strftime("%b %Y")


def _have(con):
    return con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='transactions'").fetchone() is not None


def last_month(con):
    """Newest month with transactions, or None."""
    if not _have(con):
        return None
    r = con.execute("SELECT MAX(substr(txn_date,1,7)) FROM transactions").fetchone()
    return r[0] if r and r[0] else None


def _end(ym):
    """The last ISO day of a month."""
    return (dt.date(int(ym[:4]) + int(ym[5:7]) // 12, int(ym[5:7]) % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()


def _by_month(con, first, last):
    """{month: {"income", "expenses"}} for first..last (inclusive), months with nothing present as zeros. Sums in cents."""
    rows = con.execute("""
        SELECT substr(txn_date,1,7) AS m,
               SUM(CASE WHEN txn_type IN ('income','interest') THEN CAST(ROUND(COALESCE(amount,0)*100) AS INTEGER) ELSE 0 END)
        FROM transactions WHERE substr(txn_date,1,7) BETWEEN ? AND ? GROUP BY 1""", (first, last)).fetchall()
    income = {m: c or 0 for m, c in rows}
    spent = {}
    for r in L.spend_lines(con, first + "-01", _end(last)):
        m = str(r["txn_date"])[:7]
        spent[m] = spent.get(m, 0) - r["cents"]
    out = {}
    m = first
    while m <= last:
        if m in income:
            out[m] = {"income": income[m] / 100, "expenses": spent.get(m, 0) / 100, "rows": True}
        else:
            out[m] = {"income": 0.0, "expenses": 0.0, "rows": False}
        m = shift(m, 1)
    return out


def _pct(now, before):
    if not before:
        return None
    return round((now - before) / abs(before) * 100, 1)


def monthly(con, months=12, end=None, today=None):
    """Last `months` months ending at `end` (default: newest month with data). One dict per month:
    month, label, income, expenses, left (income - expenses), left_pct (of income), vs_prev (expenses change against the
    month before, %), vs_last_year (expenses change against the same month a year earlier, %), last_year (that month's
    expenses). Months with no transactions at all have rows=False (shown, not compared); the calendar month still
    running has partial=True (shown, not compared)."""
    end = end or last_month(con)
    if not end:
        return []
    today = today or dates.today()
    running = today.strftime("%Y-%m") if (today + dt.timedelta(days=1)).month == today.month else None
    first = shift(end, -(months - 1))
    data = _by_month(con, shift(first, -12), end)  # one extra year back for the comparisons
    out = []
    m = first
    while m <= end:
        cur, prev, ly = data[m], data.get(shift(m, -1)), data.get(shift(m, -12))
        part = m == running and cur["rows"]
        left = round(cur["income"] - cur["expenses"], 2)
        out.append({
            "month": m, "label": label(m), "rows": cur["rows"], "partial": part, "income": cur["income"], "expenses": cur["expenses"],
            "left": left, "left_pct": round(left / cur["income"] * 100, 1) if cur["income"] else None,
            "vs_prev": _pct(cur["expenses"], prev["expenses"]) if prev and prev["rows"] and cur["rows"] and not part else None,
            "last_year": ly["expenses"] if ly and ly["rows"] else None,
            "vs_last_year": _pct(cur["expenses"], ly["expenses"]) if ly and ly["rows"] and cur["rows"] and not part else None,
        })
        m = shift(m, 1)
    return out


def totals(rows):
    """Sums over the rows that have data: income, expenses, left, and the same for the year-earlier months that exist."""
    have = [r for r in rows if r["rows"] and not r["partial"]]
    inc, exp = sum(r["income"] for r in have), sum(r["expenses"] for r in have)
    pairs = [r for r in have if r["last_year"] is not None]
    return {"months": len(have), "income": round(inc, 2), "expenses": round(exp, 2), "left": round(inc - exp, 2),
            "compared": len(pairs), "this_year": round(sum(r["expenses"] for r in pairs), 2),
            "last_year": round(sum(r["last_year"] for r in pairs), 2)}


def categories(con, months=12, end=None, top=TOP):
    """Expenses by category: last `months` months against the `months` before. Sorted by the size of the change."""
    end = end or last_month(con)
    if not end:
        return []
    first, p_first = shift(end, -(months - 1)), shift(end, -(2 * months - 1))
    by = {}
    for t in L.spend_lines(con, p_first + "-01", _end(end)):
        c = by.setdefault(t["category"] or "uncategorized", {"category": t["category"] or "uncategorized", "now": 0, "before": 0})
        c["now" if str(t["txn_date"])[:7] >= first else "before"] -= t["cents"]
    rows = [{"category": c["category"], "now": c["now"] / 100, "before": c["before"] / 100} for c in by.values()]
    out = [{"category": r["category"], "now": round(r["now"] or 0, 2), "before": round(r["before"] or 0, 2),
            "change": round((r["now"] or 0) - (r["before"] or 0), 2), "pct": _pct(r["now"] or 0, r["before"] or 0)}
           for r in rows if (r["now"] or 0) + (r["before"] or 0) > 0]
    out.sort(key=lambda r: -abs(r["change"]))
    return out[:top]


def months_available(con):
    """Months that have transactions, newest first (the month picker)."""
    if not _have(con):
        return []
    return [r[0] for r in con.execute(
        "SELECT DISTINCT substr(txn_date,1,7) m FROM transactions WHERE txn_date IS NOT NULL ORDER BY m DESC") if r[0]]


FIXED_TYPES = ("loan_payment", "insurance", "utility")
FIXED_CATS = {"housing", "rent", "mortgage", "auto loan", "student loan", "loan", "utilities", "insurance", "subscriptions",
              "phone", "internet", "childcare", "tuition", "tax"}
SAVE_ACCOUNTS = ("savings", "investment")


def _spend_rows(con, ym):
    """Money spent in one month, one row per line (the one rule, ledger_data.spend_lines; a refund is a row with a
    positive amount), biggest charge first."""
    got = [{"txn_date": r["txn_date"], "payee": r["payee"], "description": r["description"], "amount": r["cents"] / 100,
            "category": r["category"] or "uncategorized", "txn_type": r["txn_type"]}
           for r in L.spend_lines(con, ym + "-01", _end(ym))]
    return sorted(got, key=lambda r: r["amount"])[:3000]


def _limits(con):
    try:
        return {r[0]: r[1] for r in con.execute("SELECT category, monthly_limit FROM budget") if r[1]}
    except Exception:
        return {}


def month_summary(con, ym=None, top=6, today=None):
    """One month in full for the This month story card. None without data.
    income, spent (same rules as `monthly`: a card payment counts only in a month with no card lines of its own), saved
    (investment transfers + money moved into savings or investment accounts, net), left (income - spent - saved),
    fixed / flexible spend, income sources, categories (share of spend, change against the month before, budget limit,
    every charge), six months of history, the month-end pace while the month runs, and highlights (biggest charge, top
    place and busiest day count everyday spending only, not housing, loans and bills)."""
    avail = months_available(con)
    if not avail:
        return None
    ym = ym if ym in avail else avail[0]
    today = today or dates.today()
    hist = monthly(con, months=6, end=ym, today=today)
    row = hist[-1]
    tx = _spend_rows(con, ym)
    prev_by = {}
    for r in _spend_rows(con, shift(ym, -1)):
        prev_by[r["category"]] = prev_by.get(r["category"], 0.0) - r["amount"]
    tax = con.execute(
        "SELECT COALESCE(-SUM(amount_cents),0)/100.0 FROM transactions WHERE substr(txn_date,1,7)=? AND txn_type='tax'",
        (ym,)).fetchone()[0]
    invested = con.execute(
        "SELECT COALESCE(-SUM(amount_cents),0)/100.0 FROM transactions WHERE substr(txn_date,1,7)=? AND txn_type='investment_transfer'",
        (ym,)).fetchone()[0]
    to_savings = con.execute(
        "SELECT COALESCE(SUM(t.amount_cents),0)/100.0 FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE substr(t.txn_date,1,7)=? AND t.txn_type='transfer' AND a.type IN (?,?)", (ym, *SAVE_ACCOUNTS)).fetchone()[0]
    sources = db.rows(con, """
        SELECT COALESCE(NULLIF(payee,''),'Other') AS payee, SUM(amount_cents)/100.0 AS amount FROM transactions
        WHERE substr(txn_date,1,7)=? AND txn_type IN ('income','interest') AND amount > 0 GROUP BY 1 ORDER BY 2 DESC""", (ym,))
    limits = _limits(con)
    by, payees, days_by, fixed, everyday, loose = {}, {}, {}, 0.0, [], {}
    for r in tx:
        amt = -r["amount"]
        r["payee"] = r["payee"] or rule_match.clean(r["description"])[:40]  # a bank line with no payee still names itself
        c = by.setdefault(r["category"], {"category": r["category"], "amount": 0.0, "n": 0, "items": []})
        c["amount"] += amt
        c["n"] += 1
        c["items"].append({"date": r["txn_date"], "payee": r["payee"] or "", "amount": round(amt, 2)})
        if r["category"] == "uncategorized":  # grouped by merchant, so one answer can be remembered as a rule
            key = rule_match.merchant_key(r["description"]) or rule_match.clean(r["description"])[:24]
            if key:
                g = loose.setdefault(key, {"key": key, "n": 0, "spent": 0.0})
                g["n"] += 1
                g["spent"] += amt
        if r["txn_type"] in FIXED_TYPES or r["category"].lower() in FIXED_CATS:
            fixed += amt
            continue
        everyday.append(r)
        p = payees.setdefault(r["payee"] or "", [0, 0.0])
        p[0] += 1
        p[1] += amt
        days_by[r["txn_date"]] = days_by.get(r["txn_date"], 0.0) + amt
    cats = sorted(by.values(), key=lambda c: -c["amount"])
    spent = row["expenses"]
    total = sum(c["amount"] for c in cats if c["amount"] > 0) or 1
    for c in cats:
        c["amount"] = round(c["amount"], 2)
        c["pct"] = round(c["amount"] / total * 100, 1)
        before = prev_by.get(c["category"])
        c["prev"] = round(before, 2) if before else None
        c["change"] = _pct(c["amount"], before) if before else None
        c["limit"] = limits.get(c["category"])
    plus = [c for c in cats if c["amount"] > 0]  # a category with only refunds stays in the list, not in the ring
    shown, rest = plus[:top], plus[top:]
    if rest:
        shown.append({"category": "other", "amount": round(sum(c["amount"] for c in rest), 2), "n": sum(c["n"] for c in rest),
                      "pct": round(sum(c["pct"] for c in rest), 1), "items": []})
    y, m = int(ym[:4]), int(ym[5:7])
    in_month = (dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)).day
    days = today.day if ym == today.strftime("%Y-%m") else in_month
    income = row["income"]
    saved = round(invested + to_savings, 2)
    left = round(income - spent - tax - saved, 2)
    biggest = max(everyday, key=lambda r: -r["amount"], default=None)
    merchant = max(((k, v) for k, v in payees.items() if k), key=lambda kv: (kv[1][1], kv[1][0]), default=None)
    busiest = max(days_by.items(), key=lambda kv: kv[1], default=None)
    idx = avail.index(ym)
    projected = round(spent / days * in_month, 2) if row["partial"] and days else None
    prev = hist[-2] if len(hist) > 1 else None
    return {"month": ym, "label": label(ym), "long": dt.date(y, m, 1).strftime("%B %Y"),
            "months": [(x, label(x)) for x in avail],
            "older": avail[idx + 1] if idx + 1 < len(avail) else None, "newer": avail[idx - 1] if idx else None,
            "income": income, "spent": spent, "tax": round(tax, 2), "invested": round(invested, 2), "to_savings": round(to_savings, 2),
            "saved": saved, "left": left, "left_pct": round(left / income * 100, 1) if income else None,
            "kept_pct": round((income - spent) / income * 100) if income else None,
            "fixed": round(fixed, 2), "flexible": round(max(spent - fixed, 0), 2),
            "sources": [{"payee": s["payee"], "amount": round(s["amount"], 2)} for s in sources[:4]],
            "sources_more": max(0, len(sources) - 4),
            "vs_prev": row["vs_prev"], "vs_last_year": row["vs_last_year"], "last_year": row["last_year"],
            "partial": row["partial"], "per_day": round(spent / days, 2) if days else 0, "n": sum(1 for r in tx if r["amount"] < 0),
            "projected": projected, "pace_vs_prev": _pct(projected, prev["expenses"]) if projected and prev and prev["rows"] else None,
            "prev_label": label(shift(ym, -1)),
            "history": [{"month": h["month"], "label": h["label"][:3], "income": h["income"], "spent": h["expenses"],
                         "rows": h["rows"]} for h in hist],
            "categories": shown, "all": cats,
            "loose": [{**g, "spent": round(g["spent"], 2)} for g in sorted(loose.values(), key=lambda g: -g["spent"])[:12]],
            "cat_names": sorted({c["category"] for c in cats if c["category"] != "uncategorized"}, key=str.lower),
            "biggest": {"payee": biggest["payee"] or "", "amount": round(-biggest["amount"], 2), "date": biggest["txn_date"]} if biggest else None,
            "merchant": {"payee": merchant[0], "n": merchant[1][0], "amount": round(merchant[1][1], 2)} if merchant else None,
            "busiest": {"date": busiest[0], "amount": round(busiest[1], 2)} if busiest else None}


def lines(con, months=12, end=None, today=None):
    """Plain sentences for the chat chip and the report. [] when there are no transactions."""
    rows = monthly(con, months, end, today)
    if not rows:
        return []
    from money import fmt
    t = totals(rows)
    have = [r for r in rows if r["rows"] and not r["partial"]] or [r for r in rows if r["rows"]]
    if not have:  # the months are listed (a report for a chosen month) but none of them has a statement line
        return []
    newest = have[-1]
    out = [f"{newest['label']}: {fmt(newest['income'])} in, {fmt(newest['expenses'])} out, {fmt(newest['left'])} left"
           + (f" ({newest['left_pct']:.0f}% of income)." if newest["left_pct"] is not None else ".")]
    if newest["vs_prev"] is not None:
        prev = have[-2] if len(have) > 1 else None
        how = "unchanged" if abs(newest["vs_prev"]) < 0.5 else f"{'up' if newest['vs_prev'] > 0 else 'down'} {abs(newest['vs_prev']):.0f}%"
        out.append(f"Spending {how} from {prev['label'] if prev else 'the month before'}.")
    if newest["vs_last_year"] is not None:
        how = "unchanged" if abs(newest["vs_last_year"]) < 0.5 else f"{'up' if newest['vs_last_year'] > 0 else 'down'} {abs(newest['vs_last_year']):.0f}%"
        out.append(f"Against {label(shift(newest['month'], -12))}: {how} ({fmt(newest['last_year'])} then).")
    if t["months"] > 1:
        out.append(f"Last {t['months']} months: {fmt(t['income'])} in, {fmt(t['expenses'])} out, {fmt(t['left'])} left; "
                   f"a typical month costs {fmt(t['expenses'] / t['months'])}.")
    if t["compared"] >= 3:
        p = _pct(t["this_year"], t["last_year"])
        out.append(f"The {t['compared']} months that also have a year-earlier month: {fmt(t['this_year'])} now against "
                   f"{fmt(t['last_year'])} then" + (f", {'up' if p > 0 else 'down'} {abs(p):.0f}%." if p is not None else "."))
    cats = [c for c in categories(con, months, end)[:3] if c["before"] and abs(c["pct"] or 0) >= 10]
    if cats:
        out.append("Moved most: " + "; ".join(f"{c['category']} {'up' if c['change'] > 0 else 'down'} {abs(c['pct']):.0f}%"
                                              for c in cats) + ".")
    return out


def for_markdown(line):
    """A sentence for st.markdown: two amounts on one line would otherwise be read as a maths formula ($...$)."""
    return line.replace("$", r"\$")


def markdown(con, months=12, end=None, today=None):
    """The Trends section of the monthly report."""
    rows = monthly(con, months, end, today)
    if not any(r["rows"] for r in rows):
        return "_no transactions yet_\n"
    from money import fmt
    s = "\n".join(f"- {l}" for l in lines(con, months, end, today)) + "\n\n"
    s += "| Month | Income | Expenses | Left | vs month before | Same month last year | vs last year |\n|---|---|---|---|---|---|---|\n"
    pc = lambda v: "" if v is None else f"{v:+.0f}%"
    for r in rows:
        if not r["rows"]:
            s += f"| {r['label']} | - | - | - | | | |\n"
            continue
        if r["partial"]:
            s += f"| {r['label']} (so far) | {fmt(r['income'])} | {fmt(r['expenses'])} | {fmt(r['left'])} | | | |\n"
            continue
        s += (f"| {r['label']} | {fmt(r['income'])} | {fmt(r['expenses'])} | {fmt(r['left'])} | {pc(r['vs_prev'])} | "
              f"{'' if r['last_year'] is None else fmt(r['last_year'])} | {pc(r['vs_last_year'])} |\n")
    cats = categories(con, months, end)
    if cats:
        s += "\nCategories that moved most (last 12 months against the 12 before):\n\n| Category | Now | Before | Change |\n|---|---|---|---|\n"
        for c in cats:
            s += f"| {c['category']} | {fmt(c['now'])} | {fmt(c['before'])} | {fmt(c['change'])}" + (f" ({c['pct']:+.0f}%)" if c["pct"] is not None else "") + " |\n"
    return s


if __name__ == "__main__":
    with db.open(readonly=True) as con:
        if sys.argv[1:2] == ["categories"]:
            for c in categories(con):
                print(f"{c['category']:<24} {c['now']:>12,.2f} {c['before']:>12,.2f} {c['change']:>+12,.2f}")
        else:
            print(markdown(con))
