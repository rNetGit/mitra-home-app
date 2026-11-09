"""Month statement (Money > Statement): one month as a home income statement with a variance table. No AI.

Income by source, expenses grouped (Housing, Utilities, ...) with each category against last month and the same month a
year ago, then tax, saved and what is left. The variance table lists every category as budget / actual / last month with a
one-line reason for the big swings. Figures come from trends.month_summary and budget (the one spending rule,
ledger_data.spend_lines), so this page always agrees with the story card.
"""
import re
import sqlite3

import budget as B
import db
import month_check
import paths
import trends as T

# First match wins, so the narrow words come first ("home insurance" is Insurance, not Housing).
GROUPS = [
    ("Insurance", ("insurance", "premium")),
    ("Loans", ("loan", "emi=", "debt", "credit card")),
    ("Housing", ("housing", "rent", "mortgage", "home", "repair", "maintenance", "furnitur", "lawn", "hoa=", "garden", "cleaning")),
    ("Utilities", ("utilit", "electric", "gas=", "water", "sewer", "internet", "phone", "mobile", "cable", "trash", "power")),
    ("Transport", ("auto", "car=", "cars=", "vehicle", "fuel", "gasoline", "parking", "toll", "transit", "ride", "taxi", "bus=", "train=",
                   "travel")),
    ("Food", ("grocer", "dining", "restaurant", "food", "coffee", "takeout", "meal")),
    ("Health", ("health", "medical", "pharmacy", "dental", "doctor", "vision", "fitness", "gym")),
    ("Kids and school", ("childcare", "tuition", "school", "kids", "education", "activit", "daycare")),
    ("Subscriptions", ("subscription", "streaming", "membership", "software")),
    ("Shopping", ("shopping", "amazon", "cloth", "household", "gift", "entertain", "hobby")),
]
# A key matches a whole word of the category name that starts with it ("rent" finds "rental", never "parent"); a key ending in
# "=" must be the whole word ("car=" finds "car insurance" but not "personal care").
BIG_SWING_PCT = 25     # a category moved by at least this much (and BIG_SWING_MIN) against last month gets a reason
BIG_SWING_MIN = 50.0


def _hit(words, key):
    if key.endswith("="):
        return key[:-1] in words
    if " " in key:
        return False
    return any(w.startswith(key) for w in words)


def group_of(category):
    c = (category or "").lower()
    words = [w for w in re.split(r"[^a-z]+", c) if w]
    for name, keys in GROUPS:
        if any((k in c) if " " in k else _hit(words, k) for k in keys):
            return name
    return "Other"


def _cat_totals(con, ym):
    out = {}
    for r in T._spend_rows(con, ym):
        out[r["category"]] = out.get(r["category"], 0.0) - r["amount"]
    return {c: round(v, 2) for c, v in out.items()}


def _income_lines(con, ym):
    rows = db.rows(con, """
        SELECT COALESCE(NULLIF(payee,''),'Other') AS payee, SUM(amount_cents)/100.0 AS amount FROM transactions
        WHERE substr(txn_date,1,7)=? AND txn_type IN ('income','interest') AND amount > 0 GROUP BY 1 ORDER BY 2 DESC""", (ym,))
    return [{"payee": r["payee"], "amount": round(r["amount"], 2)} for r in rows]


def _money(x):
    s = f"{abs(x):,.2f}"
    return "$" + (s[:-3] if s.endswith(".00") else s)


def _reason(now, prev, limit, items, prev_label, have_prev):
    """A short plain sentence for a category that moved a lot or went over its budget; '' when nothing stands out."""
    bits = []
    if have_prev and prev is None and now > 0:
        bits.append("New this month.")
    elif prev is not None and abs(now - prev) >= BIG_SWING_MIN and prev and abs(now - prev) / prev * 100 >= BIG_SWING_PCT:
        bits.append(("Up " if now > prev else "Down ") + _money(now - prev) + f" on {prev_label}.")
    if limit and now > limit:
        bits.append(f"Over the {_money(limit)} budget by {_money(now - limit)}.")
    if bits and items and now > 0:
        top = max(items, key=lambda i: i["amount"])
        if top["amount"] > 0 and (top["payee"] or "").strip():
            bits.append(f"Biggest charge: {top['payee']} {_money(top['amount'])}.")
    return " ".join(bits)


def statement(con, ym=None, today=None):
    """The month statement as a dict, or None without statements. Keys: month, label, long, months, older, newer, partial,
    income {now, prev, ly, lines}, groups [{name, now, prev, ly, rows}], unitemised, expenses {now, prev, ly}, tax, net
    (income - expenses), saved, left, variance [row], budget_total, names {now, prev, ly}, have {prev, ly}.
    row = {category, group, now, prev, ly, limit, over (now - limit or None), change ($ vs prev or None), change_pct, reason}."""
    m = T.month_summary(con, ym, today=today)
    if not m:
        return None
    if ym is None and m["partial"] and m["older"]:
        m = T.month_summary(con, m["older"], today=today)  # a month still running is not a fair statement: open on the last whole one
    ym = m["month"]
    prev_ym, ly_ym = T.shift(ym, -1), T.shift(ym, -12)
    both = T._by_month(con, ly_ym, ym)
    p, ly = both.get(prev_ym) or {}, both.get(ly_ym) or {}
    have = {"prev": bool(p.get("rows")), "ly": bool(ly.get("rows"))}
    prev_cats = _cat_totals(con, prev_ym) if have["prev"] else {}
    ly_cats = _cat_totals(con, ly_ym) if have["ly"] else {}
    limits = {c: l for c, l in B._limits(con) if l and not B.is_allowance(c)}
    now_cats = {c["category"]: c for c in m["all"]}
    prev_label = T.label(prev_ym)[:3]

    names = sorted(set(now_cats) | set(limits))
    rows = []
    for c in names:
        cur = now_cats.get(c)
        now = cur["amount"] if cur else 0.0
        before = prev_cats.get(c) if have["prev"] else None
        limit = limits.get(c)
        if not now and not before and not limit:
            continue
        change = round(now - before, 2) if before is not None else None
        rows.append({"category": c, "group": group_of(c), "now": now, "prev": before, "ly": ly_cats.get(c) if have["ly"] else None,
                     "limit": limit, "over": round(now - limit, 2) if limit else None, "change": change,
                     "change_pct": T._pct(now, before) if before else None,
                     "reason": _reason(now, before, limit, cur["items"] if cur else [], prev_label, have["prev"])})
    rows.sort(key=lambda r: -r["now"])

    groups = {}
    for r in rows:
        if not r["now"] and not r["prev"]:
            continue  # a budget line with nothing spent shows in the variance table only
        g = groups.setdefault(r["group"], {"name": r["group"], "now": 0.0, "prev": 0.0, "ly": 0.0, "rows": []})
        g["now"] += r["now"]
        g["prev"] += r["prev"] or 0.0
        g["ly"] += r["ly"] or 0.0
        g["rows"].append(r)
    glist = sorted(groups.values(), key=lambda g: (g["name"] == "Other", -g["now"]))
    for g in glist:
        for k in ("now", "prev", "ly"):
            g[k] = round(g[k], 2)
    for g in glist:
        g["single"] = len(g["rows"]) == 1 and g["rows"][0]["category"].lower() == g["name"].lower()
    itemised = round(sum(r["now"] for r in rows), 2)
    unitemised = round(m["spent"] - itemised, 2)
    if abs(unitemised) < 0.5:
        unitemised = 0.0
    income_lines = _income_lines(con, ym)
    net = round(m["income"] - m["spent"], 2)
    return {"month": ym, "label": m["label"], "long": m["long"], "months": m["months"], "older": m["older"], "newer": m["newer"],
            "partial": m["partial"],
            "income": {"now": m["income"], "prev": p.get("income") if have["prev"] else None,
                       "ly": ly.get("income") if have["ly"] else None, "lines": income_lines},
            "groups": glist, "unitemised": unitemised,
            "expenses": {"now": m["spent"], "prev": p.get("expenses") if have["prev"] else None,
                         "ly": ly.get("expenses") if have["ly"] else None},
            "tax": m["tax"], "net": net, "saved": m["saved"], "left": m["left"],
            "variance": [r for r in rows if r["limit"] or r["reason"]],
            "budget_total": round(sum(r["limit"] for r in rows if r["limit"]), 2),
            "names": {"now": m["label"], "prev": T.label(prev_ym), "ly": T.label(ly_ym)}, "have": have,
            "check": month_check.checks(con, ym, today)}


def view(ym=None, today=None):
    """statement() on the live database, None when there is no data yet."""
    try:
        con = db.connect(paths.DB, readonly=True)
    except sqlite3.Error:
        return None
    try:
        return statement(con, ym, today=today)
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
