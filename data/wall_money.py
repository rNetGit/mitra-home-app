"""What the Mitra Wall's money pages show behind the adult's PIN (webapp/routes_wall.py): Spending, Bills and Regular.

  * spending(con, today): money spent by category this month so far, last month and the same month a year ago. The
    lines counted are the one spending rule (ledger_data.spend_lines: spend, fee, utility, insurance, loan payment, a
    refund coming off; a card payment only in a month with no card statement), so transfers, investing and tax never
    count and a card charge is counted once.
  * bills(con, today): bills paid this month next to last month's, per payee. A bill is what the Ledger's "Bills paid"
    counts (ledger_data._is_bill). A payee paid last month and not seen yet this month is "waiting", with the day it
    came last month; open rows of the bill list due by the end of the month are listed apart.
  * regular(con, today): what keeps coming every month: tracked subscriptions (not cancelled or stopped), bills of the
    bill list that repeat, payees tracked by recurring_bills, and bill / subscription payees seen in two of the last four
    months. One row per payee (`_key` / `_same`), grouped into home and utilities, loans (mortgage, rent, car) and insurance, subscriptions.

  * for_phone(con, today): the three as one small JSON block for a phone (the pull answer's summary.money, adults with
    the finance scope only): display fields only, amounts already written in the household's currency.

The same views are the PC's Money > Spending / Bills / Regular (finance_data.OUTLOOK). Read-only, no AI. Payee names
come from the transactions' payee or description; long numbers in a description are dropped, so no account or
reference number reaches the wall or a phone.
"""
import calendar
import datetime as dt
import re
import sqlite3

import budget
import db
import ledger_data as L
from money import fmt

SUB_CATS = {"subscriptions", "subscription", "streaming"}
HOME_CATS = {"utilities", "phone", "internet services", "cable & internet comm", "water", "electricity", "gas", "trash"}
LOAN_TYPES = {"loan_payment", "insurance"}
LOAN_CATS = {"housing", "mortgage", "rent", "loans", "auto loan", "student loan", "emi payments", "insurance"}
GROUPS = (("home", "Home and utilities"), ("loans", "Loans and insurance"), ("subs", "Subscriptions"))
STOP = {"the", "city", "of", "town", "county", "bill", "payment", "payments", "autopay", "first", "inc", "llc", "co"}
PER_YEAR = {"monthly": 12, "quarterly": 4, "yearly": 1}
SEEN_MONTHS = 2  # a bill payee counts as regular when it was paid in this many of the last four months


# ---- small helpers ------------------------------------------------------------------------------------------------
def ym(d):
    return d.strftime("%Y-%m")


def shift(m, k):
    y, mo = int(m[:4]), int(m[5:7]) + k
    y, mo = y + (mo - 1) // 12, (mo - 1) % 12 + 1
    return f"{y:04d}-{mo:02d}"


def month_name(m, year=False):
    d = dt.date(int(m[:4]), int(m[5:7]), 1)
    return d.strftime("%B %Y" if year else "%B")


def month_end(m):
    y, mo = int(m[:4]), int(m[5:7])
    return f"{m}-{calendar.monthrange(y, mo)[1]:02d}"


def next_month(d, months=1):
    m = shift(ym(d), months)
    y, mo = int(m[:4]), int(m[5:7])
    return dt.date(y, mo, min(d.day, calendar.monthrange(y, mo)[1]))


def short(d):
    return f"{d:%b} {d.day}" if d else ""


def nice(name):
    """A payee as the wall shows it: long numbers dropped (no account or reference number), SHOUTING made readable."""
    s = " ".join(re.sub(r"[#*]?\d{4,}", " ", str(name or "")).split())
    if s.isupper():
        s = s.title()
    return s or "Unnamed"


def _key(name):
    """A payee's first two words that say who it is: 'VERIZON WIRELESS PAYMENTS' -> ('verizon', 'wireless')."""
    words = [w for w in re.findall(r"[a-z]+", str(name or "").lower()) if w not in STOP and len(w) > 1]
    return tuple(words[:2]) or (str(name or "").strip().lower(),)


def _same(a, b):
    """Two keys name one payee: the same two words, or one of them is a single word and the first words agree
    ('Verizon' = 'Verizon Wireless'; 'Apple iCloud' != 'Apple Music')."""
    return a == b or ((len(a) == 1 or len(b) == 1) and a[0] == b[0])


def _slot(store, name):
    """The key in `store` that already holds this payee, else its own key."""
    k = _key(name)
    return next((have for have in store if _same(have, k)), k)


def _pct(v, top):
    return max(0, min(100, round(100 * v / top))) if top and v > 0 else 0


def _day(text):
    try:
        return dt.date.fromisoformat(str(text or "")[:10])
    except ValueError:
        return None


def _spend_in(con, first, last):
    """(date, name, amount spent > 0, type, category) for every spending line between two ISO days (the one rule,
    ledger_data.spend_lines; a refund is a negative amount spent)."""
    return [(_day(r["txn_date"]), r["payee"].strip() or r["description"], -r["cents"] / 100, r["txn_type"],
             r["category"].strip().lower()) for r in L.spend_lines(con, first, last) if _day(r["txn_date"])]


def _has_lines(con, m):
    return bool(con.execute("SELECT 1 FROM transactions WHERE substr(txn_date,1,7)=? LIMIT 1", (m,)).fetchone())


def _safe(fn, default):
    try:
        return fn()
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return default


# ---- Spending -----------------------------------------------------------------------------------------------------
def spending(con, today):
    cur = ym(today)
    cols = [("now", cur), ("prev", shift(cur, -1)), ("ly", shift(cur, -12))]
    have = {k: _has_lines(con, m) for k, m in cols}
    sums, labels = {}, {}
    for k, m in cols:
        for _d, _n, amt, _ty, cat in _safe(lambda m=m: _spend_in(con, m + "-01", month_end(m)), []):
            c = cat or "uncategorized"
            sums.setdefault(c, {"now": 0.0, "prev": 0.0, "ly": 0.0})[k] += amt
            labels.setdefault(c, budget.label(c))
    rows = []
    for c, v in sums.items():
        if all(abs(v[k]) < 0.005 for k, _ in cols):
            continue
        rows.append({"cat": c, "label": "Not sorted yet" if c == "uncategorized" else labels[c][:1].upper() + labels[c][1:],
                     **{k: round(v[k], 2) for k, _ in cols}})
    rows.sort(key=lambda r: (-r["now"], -r["prev"], r["label"]))
    top = max([max(r["now"], r["prev"], r["ly"]) for r in rows] or [0])
    for r in rows:
        r.update({f"{k}_w": _pct(r[k], top) for k, _ in cols})
        r.update({f"{k}_text": fmt(r[k], 0) if have[k] else "—" for k, _ in cols})
    newest = con.execute("SELECT MAX(txn_date) FROM transactions WHERE substr(txn_date,1,7)=?", (cur,)).fetchone()[0]
    totals = {k: round(sum(r[k] for r in rows), 2) if have[k] else None for k, _ in cols}
    return {"rows": rows, "totals": totals, "have": have,
            "names": {"now": month_name(cur), "prev": month_name(cols[1][1]), "ly": month_name(cols[2][1], year=True)},
            "through": short(_day(newest)) if newest else "", "day": today.day,
            "days": calendar.monthrange(today.year, today.month)[1]}


# ---- Bills ----------------------------------------------------------------------------------------------------------
def _bill_lines(con, first, last):
    return [x for x in _spend_in(con, first, last) if L._is_bill(x[3], x[4]) and x[2] > 0]


def bills(con, today):
    cur, prev = ym(today), shift(ym(today), -1)
    by = {}
    for which, m in (("prev", prev), ("now", cur)):
        for d, name, amt, _ty, _cat in _safe(lambda m=m: _bill_lines(con, m + "-01", month_end(m)), []):
            r = by.setdefault(_slot(by, name), {"name": nice(name), "now": 0.0, "prev": 0.0, "now_day": None, "prev_day": None})
            r[which] += amt
            r[f"{which}_day"] = min(r[f"{which}_day"] or d, d)
    rows = []
    for r in by.values():
        if r["now"] and r["prev"]:
            state, change = "paid", r["now"] - r["prev"]
            note = (f"{fmt(abs(change), 2)} {'more' if change > 0 else 'less'}"
                    if abs(change) > max(1.0, 0.05 * r["prev"]) else "")
        elif r["now"]:
            state, note = "new", "not paid last month"
        else:
            expect = next_month(r["prev_day"])
            state = "waiting"
            note = f"usually around {short(expect)}" if expect >= today else f"came {short(r['prev_day'])} last month, not seen yet"
        rows.append({**r, "state": state, "note": note, "now_text": fmt(r["now"], 2) if r["now"] else "",
                     "prev_text": fmt(r["prev"], 2) if r["prev"] else "", "now_on": short(r["now_day"]),
                     "prev_on": short(r["prev_day"]), "order": (r["prev_day"] or r["now_day"]).day})
    rows.sort(key=lambda r: (r["order"], r["name"]))
    waiting = [r for r in rows if r["state"] == "waiting"]
    open_ = _safe(lambda: con.execute(
        "SELECT name, COALESCE(vendor, name), amount, due_date, status FROM bills WHERE status IN ('due','overdue') "
        "AND due_date <= ? ORDER BY due_date, name LIMIT 12", (month_end(cur),)).fetchall(), [])
    listed = [{"name": nice(v or n), "amount": fmt(a, 2) if a else "", "due": short(_day(d)),
               "late": (_day(d) or today) < today} for n, v, a, d, _s in open_]
    paid_now = [r for r in rows if r["now"]]
    paid_prev = [r for r in rows if r["prev"]]
    return {"rows": rows, "names": {"now": month_name(cur), "prev": month_name(prev)},
            "now_total": fmt(sum(r["now"] for r in paid_now), 2), "now_n": len(paid_now),
            "prev_total": fmt(sum(r["prev"] for r in paid_prev), 2), "prev_n": len(paid_prev),
            "wait_total": fmt(sum(r["prev"] for r in waiting), 2), "wait_n": len(waiting), "listed": listed}


# ---- Daily ----------------------------------------------------------------------------------------------------------
def daily(con, today):
    """The wall's quick daily look at money: bills paid in the last 7 days (today included) and bills due in the next 7,
    late ones first. A bill paid is a statement line the Ledger counts as a bill (`_bill_lines`) or a bill-list row
    marked paid in that week (when no statement line names the same payee for the same amount). Display fields only:
    payee names have long numbers dropped, so no account or reference number leaves the PC."""
    first, last = today - dt.timedelta(days=6), today + dt.timedelta(days=6)
    paid = [{"name": nice(name), "amount": round(amt, 2), "on": d.isoformat()}
            for d, name, amt, _ty, _cat in _safe(lambda: _bill_lines(con, first.isoformat(), today.isoformat()), [])]
    keys = [(_key(p["name"]), p["amount"]) for p in paid]
    for name, amt, when in _safe(lambda: con.execute(
            "SELECT COALESCE(vendor, name), amount, paid_date FROM bills WHERE status = 'paid' AND paid_date BETWEEN ? AND ?",
            (first.isoformat(), today.isoformat())).fetchall(), []):
        k, a = _key(name), round(float(amt or 0), 2)
        if any(_same(k, have) and abs(a - amount) < 0.005 for have, amount in keys):
            continue
        paid.append({"name": nice(name), "amount": a, "on": str(when)[:10]})
    paid.sort(key=lambda p: (p["on"], p["name"]), reverse=True)
    coming = []
    for name, amt, due in _safe(lambda: con.execute(
            "SELECT COALESCE(vendor, name), amount, due_date FROM bills WHERE status IN ('due', 'overdue') AND due_date <= ? "
            "ORDER BY due_date, name LIMIT 30", (last.isoformat(),)).fetchall(), []):
        d = _day(due)
        if d:
            coming.append({"name": nice(name), "amount": round(float(amt or 0), 2), "due": d.isoformat(), "late": d < today})
    coming.sort(key=lambda c: (not c["late"], c["due"], c["name"]))
    return {"from": first.isoformat(), "to": last.isoformat(), "today": today.isoformat(), "paid": paid, "upcoming": coming,
            "paid_total": round(sum(p["amount"] for p in paid), 2),
            "upcoming_total": round(sum(c["amount"] for c in coming), 2),
            "late_n": sum(1 for c in coming if c["late"])}


# ---- Regular --------------------------------------------------------------------------------------------------------
def _group(ty, cat, name=""):
    if cat in SUB_CATS:
        return "subs"
    if ty in LOAN_TYPES or cat in LOAN_CATS:
        return "loans"
    return "home"


def regular(con, today):
    items = {}

    def put(name, group, amount, freq="monthly", nxt=None, last=None, flag="", source="", strong=False):
        k = _slot(items, name)
        it = items.get(k)
        if it is None:
            items[k] = {"name": nice(name), "group": group, "amount": amount, "freq": freq, "next": nxt, "last": last,
                        "flags": [flag] if flag else [], "from": {source}}
            return
        if strong:  # a tracked subscription or the bill list names the payee better than a transaction does
            it["name"], it["group"] = nice(name), group
        it["amount"] = it["amount"] or amount
        it["next"] = nxt if nxt and (strong or not it["next"]) else it["next"]
        it["last"] = max(filter(None, (it["last"], last)), default=None)
        if flag and flag not in it["flags"]:
            it["flags"].append(flag)
        it["from"].add(source)

    # bills and subscriptions seen in the transactions, two of the last four months
    cur = ym(today)
    seen = {}
    for d, name, amt, ty, cat in _safe(lambda: _spend_in(con, shift(cur, -3) + "-01", month_end(cur)), []):
        if not (L._is_bill(ty, cat) or cat in SUB_CATS) or amt <= 0:
            continue
        s = seen.setdefault(_slot(seen, name), {"name": name, "months": set(), "lines": [], "ty": ty, "cat": cat})
        s["months"].add(ym(d))
        s["lines"].append((d, amt))
    for s in seen.values():
        if len(s["months"]) < SEEN_MONTHS:
            continue
        s["lines"].sort()
        last_d, last_amt = s["lines"][-1]
        put(s["name"], _group(s["ty"], s["cat"]), round(last_amt, 2), "monthly", next_month(last_d), last_d, source="seen")

    # tracked subscriptions that are still running
    import subscriptions
    for r in _safe(lambda: subscriptions.tracked(con, today), []):
        if not r["tracked_active"] or r["decision"] == "cancelled" or r["status"] in ("cancelled", "stopped?"):
            continue
        amount = r["last_amount"] or 0.0
        put(r["name"], "subs", round(amount, 2), r["frequency"] if r["frequency"] in PER_YEAR else "monthly",
            r["next"], r["last_date"], "cancel planned" if r["decision"] == "cancel" else (
                "price changed" if r["price_note"] else ""), "subscription", strong=True)

    # the bill list: bills that repeat (monthly / quarterly / yearly), the next open one
    for name, vendor, freq, amount, due in _safe(lambda: con.execute(
            "SELECT name, COALESCE(vendor, name), frequency, amount, MIN(due_date) FROM bills "
            "WHERE frequency IN ('monthly','quarterly','yearly') AND status IN ('due','overdue') "
            "GROUP BY LOWER(COALESCE(vendor, name))").fetchall(), []):
        k = _slot(items, vendor)
        group = items[k]["group"] if k in items else _group("", (name or "").lower())
        put(vendor, group, round(amount or 0, 2), freq, _day(due), None, source="bill list", strong=True)

    # payees tracked by recurring_bills (config/recurring_bills.json)
    import recurring_bills
    for r in _safe(lambda: recurring_bills.status(con, today), []):
        k = _slot(items, r["payee"])
        group = items[k]["group"] if k in items else "home"
        flag = "price up" if any(str(f).startswith("price") for f in r["flags"]) else ""
        put(r["name"], group, round(r["amount"] or 0, 2), r["frequency"] if r["frequency"] in PER_YEAR else "monthly",
            r["next"], r["last"], flag, "tracked")

    groups = []
    for g, title in GROUPS:
        rows = []
        for it in items.values():
            if it["group"] != g:
                continue
            per_month = round((it["amount"] or 0) * PER_YEAR.get(it["freq"], 12) / 12, 2)
            nxt = it["next"]
            rows.append({"name": it["name"], "amount": fmt(it["amount"], 2) if it["amount"] else "—",
                         "per_month": per_month, "freq": "" if it["freq"] == "monthly" else it["freq"],
                         "next": short(nxt), "next_late": bool(nxt and nxt < today), "flags": it["flags"]})
        rows.sort(key=lambda r: (-r["per_month"], r["name"]))
        total = round(sum(r["per_month"] for r in rows), 2)
        groups.append({"key": g, "title": title, "rows": rows, "total": fmt(total, 2), "total_raw": total})
    month = round(sum(g["total_raw"] for g in groups), 2)
    subs = next(g for g in groups if g["key"] == "subs")
    soon = sorted(((it["next"], it["name"]) for it in items.values()
                   if it["next"] and today <= it["next"] <= today + dt.timedelta(days=7)))
    return {"groups": groups, "month": fmt(month, 2), "year": fmt(month * 12, 0), "n": len(items),
            "subs_month": subs["total"], "subs_n": len(subs["rows"]),
            "soon": [{"name": n, "on": short(d)} for d, n in soon][:6]}


# ---- the phones -----------------------------------------------------------------------------------------------------
PHONE_ROWS = 40  # rows per list sent to a phone


def _pick(d, keys):
    return {k: d.get(k) for k in keys}


def for_phone(con, today):
    """{as_of, spending, bills, regular} with only what the phone draws (no dates as objects, no per-line ids)."""
    s, b, r = spending(con, today), bills(con, today), regular(con, today)
    return {
        "as_of": today.isoformat(),
        "spending": {**_pick(s, ("names", "totals", "have", "through", "day", "days")),
                     "rows": [_pick(x, ("label", "now", "prev", "ly", "now_w", "prev_w", "ly_w", "now_text", "prev_text",
                                        "ly_text")) for x in s["rows"][:PHONE_ROWS]]},
        "bills": {**_pick(b, ("names", "now_total", "now_n", "prev_total", "prev_n", "wait_total", "wait_n", "listed")),
                  "rows": [_pick(x, ("name", "state", "note", "now_text", "prev_text", "now_on", "prev_on"))
                           for x in b["rows"][:PHONE_ROWS]]},
        "regular": {**_pick(r, ("month", "year", "n", "subs_month", "subs_n", "soon")),
                    "groups": [{**_pick(g, ("key", "title", "total")),
                                "rows": [_pick(x, ("name", "amount", "per_month", "freq", "next", "next_late", "flags"))
                                         for x in g["rows"][:PHONE_ROWS]]} for g in r["groups"]]},
    }
