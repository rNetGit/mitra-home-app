"""What the Finance page of the web app shows, with no web code: the parts in their groups (Pay / Keep /
Look back, records.GROUPS) and one read-only view per part, built from the money modules
(bills, receipts, subscriptions, budget, loans, benefits, statement watch, spikes, Amazon, phone bills, tax checklist,
year-end, home office, work). Trends has its own view in webapp/app.py (trends.py). The outlook parts Spending / Bills /
Regular (OUTLOOK, `outlook`) are wall_money.py's views, the same as on the Mitra Wall and the phones. Used by webapp/app.py.

Looking up here: rows open in full on the Records page (table:id), where the Pay parts' rows can be changed
(records_edit.py); other changes go through Chat.
A view is {"tiles": [(label, value, tone)], "notes": [(tone, text)], "blocks": [block], "md": str | None,
"filters": {...}}; a block has the shape of records_data.blocks (heading, table or None, cols, rows [{id, cells}], empty).
"""
import calendar as cal
import datetime as dt
import re
import sqlite3
import sys
import urllib.parse

import config
import dates  # noqa: E402
import db
import ledger_data
import money as M
import paths
import records as R
import rule_match

ROWS_MAX = 300
WORDS_MAX = 100
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SPANS = (6, 12, 24)
DEFAULT = "home"  # the Finance home: this month + the three lanes (overview)
# parts that only fill in once statements are loaded (no statements = a note instead)
STATEMENT_PARTS = {"ledger", "trends", "deposits", "benefits", "watch", "spikes", "amazon", "year_end"}
NO_STATEMENTS = "This fills in once bank and card statements are filed. Drop them in the Inbox."
LIGHT = {"red": "over", "amber": "on course to pass", "green": "on track"}
BILL_CATS = [("Insurance", ("insurance", "premium")), ("Credit card", ("credit card", "card payment")),
             ("Utilities", ("electric", "gas", "water", "sewer", "internet", "cable", "phone")),
             ("Tax", ("tax",)), ("Loan", ("loan", "mortgage", "emi")),
             ("Subscription", ("subscription", "membership"))]


def bill_category(name):
    n = (name or "").lower()
    for cat, keys in BILL_CATS:
        if any(k in n for k in keys):
            return cat
    return "Other"


# The simple outlook (data/wall_money.py, the same pages as the Mitra Wall's Money): chips next to Overview in both views,
# the whole Money tab in the Standard (simple) view. Not Records sections and not in a lane.
OUTLOOK = [("spending", "Spending"), ("paid", "Bills"), ("regular", "Regular")]


def parts():
    """[(key, title)] in page order; Work only with the contracts pack, PayPal only once PayPal shows up in the records;
    the outlook parts last."""
    pp = None
    out = []
    for k, t in R.SECTIONS["money"]:
        if k == "work":  # Work is a Family page now (jobs and timesheets, no money)
            continue
        if k == "paypal":
            pp = has_paypal() if pp is None else pp
            if not pp:
                continue
        out.append((k, t))
    return out + OUTLOOK


def groups():
    """[(group, [(key, title)])] for the pills; parts not listed in records.GROUPS fall into the last group."""
    titles = dict(parts())
    out = [(g, [(k, titles[k]) for k in ks if k in titles]) for g, ks in R.GROUPS["money"]]
    listed = {k for _, ks in R.GROUPS["money"] for k in ks} | dict(OUTLOOK).keys()
    rest = [(k, t) for k, t in parts() if k not in listed]
    if rest and out:
        out[-1] = (out[-1][0], out[-1][1] + rest)
    return [(g, ks) for g, ks in out if ks]


def part_of(value):
    """The part asked for, kept only when it is one of the offered ones; else the default (the Finance home)."""
    return value if value in dict(parts()) else DEFAULT


def group_of(part):
    return next((g for g, ks in groups() if part in dict(ks)), "")


def title(part):
    return dict(parts()).get(part, "Overview" if part == DEFAULT else "")


# The three lanes of the Finance home, in records.GROUPS order: (group, one line about it, icon, gradient class).
LANES = {"Pay": ("Bills, subscriptions, receipts and phone bills.", "i-pay", "g-high"),
         "Keep": ("Accounts, budget, loans and card perks.", "i-keep", "g-flow"),
         "Look back": ("The Ledger, trends, statements, tax papers and year-end.", "i-back", "g-trend")}


def _safe(fn, default):
    try:
        return fn()
    except (sqlite3.Error, KeyError, TypeError, ValueError, ZeroDivisionError):
        return default


def overview(today):
    """The Finance home: {"month": trends.month_summary or None, "lanes": [lane], "attention": [(tone, text, url)]}.
    lane = {"group", "line", "icon", "g", "first", "parts", "big", "big_label", "sub", "tone"}. Read-only, no AI."""
    import budget as B
    import statement_watch as SW
    import trends as T
    lanes, attention = [], []
    try:
        con = _con()
    except sqlite3.Error:
        return {"month": None, "lanes": [], "attention": [], "as_of": None}
    try:
        t = today.isoformat()
        soon = (today + dt.timedelta(days=14)).isoformat()
        open_bills = _safe(lambda: _rows(con, "SELECT id, name, amount, due_date FROM bills WHERE status IN ('due','overdue',"
                                              "'unpaid') AND due_date <= ? ORDER BY due_date", (soon,)), [])
        late = [b for b in open_bills if b["due_date"] < t]
        upcoming = [b for b in open_bills if b["due_date"] >= t]
        unpaid = sum(b["amount"] or 0 for b in open_bills)
        for b in late[:3]:
            attention.append(("bad", f"{b['name']} {M.fmt(b['amount'] or 0)} was due {short_date(b['due_date'], today)}",
                              "/records?" + urllib.parse.urlencode({"ref": f"bills:{b['id']}"})))
        pay_sub = ", ".join(x for x in (f"{len(late)} overdue" if late else "",
                                        f"{len(upcoming)} due in 14 days" if upcoming else "") if x) or "Nothing due in 14 days"
        bal = _safe(lambda: _rows(con, "SELECT type, signed_balance FROM v_balance_latest"), [])
        pace = _safe(lambda: B.pace(con, today), {"lines": []})
        red = [r for r in pace["lines"] if r["status"] == "red"]
        amber = [r for r in pace["lines"] if r["status"] == "amber"]
        for r in red[:2]:
            attention.append(("warn", f"Budget: {r['label']} is over ({M.fmt(r['spent'], 0)} of {M.fmt(r['limit'], 0)})",
                              "/money?part=budget"))
        cash, invested, _owed = keep_split(bal)
        keep_sub = (f"Cash {M.fmt(cash, 0)} · invested {M.fmt(invested, 0)}" if invested else
                    f"{len(bal)} account{'' if len(bal) == 1 else 's'}") if bal else "No balances yet"
        if pace["lines"]:
            keep_sub += " · budget " + (f"{len(red)} over" if red else f"{len(amber)} close" if amber else "on track")
        for w in _safe(lambda: SW.watch(con, today), [])[:20]:
            if w["status"] == "overdue":
                attention.append(("warn", f"Statement for {w['account']} x{w['last4'] or ''} is overdue", "/money?part=watch"))
        rows = _safe(lambda: T.monthly(con, 12), [])  # the same span as Trends opens with
        full = [r for r in rows if r["rows"] and not r["partial"]]
        newest = full[-1] if full else None
        tot = T.totals(rows) if rows else {"months": 0}
        back_sub = (f"{newest['label']} spent {M.fmt(newest['expenses'], 0)}"
                    + (f" ({newest['vs_prev']:+.0f}% vs the month before)" if newest.get("vs_prev") is not None else "")
                    if newest else "Fills in once statements are filed")
        figures = {"Pay": (M.fmt(unpaid, 0), "open, next 14 days", pay_sub, "bad" if late else ""),
                   "Keep": (M.fmt(sum(b["signed_balance"] or 0 for b in bal), 0) if bal else "", "net balances" if bal else "", keep_sub,
                            "warn" if red else ""),
                   "Look back": (M.fmt(tot["expenses"] / tot["months"], 0) if tot.get("months") else "-",
                                 "typical month", back_sub, "")}
        for g, ks in groups():
            line, icon, grad = LANES.get(g, ("", "i-back", "g-cat"))
            big, big_label, sub, tone = figures.get(g, ("", "", "", ""))
            lanes.append({"group": g, "line": line, "icon": icon, "g": grad, "first": ks[0][0], "parts": ks,
                          "big": big, "big_label": big_label, "sub": sub, "tone": tone})
        month = _safe(lambda: T.month_summary(con, today.strftime("%Y-%m"), today=today), None)
        import keepup
        as_of = _safe(lambda: keepup.data_as_of(con, today), None)
    finally:
        con.close()
    return {"month": month, "lanes": lanes, "attention": attention[:5], "as_of": as_of}


OUTLOOK_VIEWS = {"spending": "spending", "paid": "bills", "regular": "regular"}  # part -> wall_money function


def outlook(today, part=None):
    """One outlook page (OUTLOOK, built by wall_money.py), or all three as {"spending", "bills", "regular"} for the
    Standard Overview. {} when the records are not there yet."""
    import wall_money as WM
    try:
        con = _con()
    except sqlite3.Error:
        return {}
    try:
        if part:
            return getattr(WM, OUTLOOK_VIEWS[part])(con, today)
        return {name: getattr(WM, name)(con, today) for name in OUTLOOK_VIEWS.values()}
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return {}
    finally:
        con.close()


def _con():
    return db.connect(paths.DB, readonly=True)


def _rows(con, sql, params=()):
    cur = con.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchmany(ROWS_MAX)]


def _cell(col, v, money_cols):
    if v is None or v == "":
        return ""
    if col in money_cols and isinstance(v, (int, float)):
        return M.fmt(v)
    if isinstance(v, str) and ISO.match(v):
        return short_date(v)  # PC tables show Oct 9, like Records
    out = R._value(col, v)
    return ISO_IN.sub(lambda m: short_date(m.group(0)), out) if isinstance(out, str) else out  # "due 2026-11-09"


# The phone list row of a block row: the first column is the title, the first of AMOUNT_COLS with a value sits on the
# right, a PILL_COLS column becomes a coloured pill and the rest is one grey line under the title.
AMOUNT_COLS = ("amount", "total", "spent", "balance", "reported", "paid", "payment", "expected", "invested", "income",
               "actual", "bill_total", "net", "price", "current_value", "premium", "average_a_month", "suggested")
PILL_COLS = ("status", "note", "result", "used")
BAD = ("overdue", "over", "missing", "late", "unpaid", "expired", "red")
WARN = ("due", "on course", "soon", "amber", "check", "watch", "expiring")
OK = ("paid", "on track", "under", "ok", "active", "green", "matched", "done")
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_IN = re.compile(r"(?<![\d-])\d{4}-\d{2}-\d{2}(?![\d-])")  # a date inside a longer text


def tone_of(text):
    t = str(text or "").lower()
    if not t:
        return ""
    for tone, keys in (("bad", BAD), ("warn", WARN), ("ok", OK)):
        if any(t == k or t.startswith(k + " ") or f" {k}" in t for k in keys):
            return tone
    return ""


def short_date(v, today=None):
    """2026-10-13 -> Oct 13 (this year) or Oct 13, 2025; anything else unchanged."""
    if not isinstance(v, str) or not ISO.match(v):
        return v
    try:
        d = dt.date.fromisoformat(v)
    except ValueError:
        return v
    today = today or dates.today()
    return f"{d:%b} {d.day}" + ("" if d.year == today.year else f", {d.year}")


def list_row(cols, raw, money_cols):
    """{"title", "amount", "pill", "tone", "meta"} for one row (see AMOUNT_COLS)."""
    if not cols:
        return {"title": "", "amount": "", "pill": "", "tone": "", "meta": ""}
    amount_col = next((c for c in AMOUNT_COLS if c in cols[1:] and raw.get(c) not in (None, "")), None)
    pill_col = next((c for c in PILL_COLS if c in cols[1:] and raw.get(c) not in (None, "")), None)
    meta = []
    for c in cols[1:]:
        if c in (amount_col, pill_col):
            continue
        v = raw.get(c)
        if v is None or v == "":
            continue
        if c in money_cols and isinstance(v, (int, float)):
            meta.append(f"{R.column_label(c)} {M.fmt(v)}")
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            meta.append(f"{R.column_label(c)} {R._value(c, v)}")
        else:
            text = ISO_IN.sub(lambda m: short_date(m.group(0)), str(R._value(c, v)))
            if text.lower() not in (str(raw.get(cols[0]) or "").lower(), "other"):  # a vendor repeating the title, "Other"
                meta.append(text)
    pill = str(R._value(pill_col, raw.get(pill_col))) if pill_col else ""
    return {"title": _cell(cols[0], raw.get(cols[0]), money_cols), "pill": pill, "tone": tone_of(pill),
            "amount": _cell(amount_col, raw.get(amount_col), money_cols) if amount_col else "",
            "meta": " · ".join(meta[:4])}


def block(heading, rows, empty, table=None, cols=None, money=(), bars=None, fold=False, title=None):
    """rows = [dict]; the first key is the row id when `table` is set (never shown), the rest are columns. Each row also
    gets `list` (list_row) for the phone. bars = [{"label", "value", "of", "pct", "tone", "note"}] draws the block as
    progress bars instead; fold = shown folded under its heading. title = the column that names the row when it is not the
    first one (Bills lead with the date and status on the PC): the link on the PC table and the title on the phone."""
    money_cols = set(money) | R.MONEY_COLS
    if cols is None:
        cols = list(rows[0]) if rows else []
        if table and cols:
            cols = cols[1:]
    lead = [title] + [c for c in cols if c != title] if title in (cols or ()) else cols
    out = [{"id": r.get("id") if table else None, "cells": [_cell(c, r.get(c), money_cols) for c in cols],
            "list": list_row(lead, r, money_cols)} for r in rows[:ROWS_MAX]]
    for r in out:  # PILL_COLS cells (after the title) are drawn as coloured pills on the PC table too: {index: tone}
        r["pills"] = {i: tone_of(v) or "n" for i, (c, v) in enumerate(zip(cols, r["cells"])) if i and c in PILL_COLS and v}
    return {"heading": heading, "table": table, "cols": [R.column_label(c) for c in cols], "rows": out, "empty": empty,
            "bars": bars or [], "fold": fold, "title_ix": cols.index(title) if title in cols else 0,
            "nums": {i for i, c in enumerate(cols) if c in money_cols or c in AMOUNT_COLS}}  # right-aligned columns


def has_transactions():
    try:
        con = _con()
    except sqlite3.Error:
        return False
    try:
        return con.execute("SELECT 1 FROM transactions LIMIT 1").fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        con.close()


# ---- filters ---------------------------------------------------------------------------------------------------
def month_arg(value, choices, default):
    return value if isinstance(value, str) and MONTH.match(value) and value in choices else default


def words(value):
    return " ".join(str(value or "").split())[:WORDS_MAX]


def month_range(args, months, default):
    """(from, to) months for the From / To pickers; an older link's single `month` is both; a reversed pair is turned
    round. Each must be one of `months`, else `default`."""
    one = args.get("month")
    frm = month_arg(args.get("from") or one, months, default)
    to = month_arg(args.get("to") or one, months, default)
    return (to, frm) if frm > to else (frm, to)


def span_bounds(frm, to):
    """First and last ISO day of a month range."""
    y1, m1, y2, m2 = int(frm[:4]), int(frm[5:]), int(to[:4]), int(to[5:])
    return dt.date(y1, m1, 1).isoformat(), dt.date(y2, m2, cal.monthrange(y2, m2)[1]).isoformat()


def span_label(frm, to):
    """2026-09 -> September 2026; 2026-08..2026-09 -> Aug 2026 - Sep 2026."""
    a, b = dt.date.fromisoformat(frm + "-01"), dt.date.fromisoformat(to + "-01")
    return f"{a:%B %Y}" if frm == to else f"{a:%b %Y} - {b:%b %Y}"


def matches(text, *fields):
    """Every word of the search is somewhere in the fields (any order, any case)."""
    hay = " ".join(str(f or "") for f in fields).lower()
    return all(w in hay for w in text.lower().split())


def _months(con, sql):
    try:
        return [r[0] for r in con.execute(sql) if r[0]]
    except sqlite3.Error:
        return []


def _span(value, default=12):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return n if n in SPANS else default


def _year(value, today):
    years = [today.year, today.year - 1]
    try:
        y = int(value)
    except (TypeError, ValueError):
        return years[0], years
    return (y if y in years else years[0]), years


# ---- Pay -------------------------------------------------------------------------------------------------------
def bills(con, today, args):
    this = today.strftime("%Y-%m")
    months = sorted(set(_months(con, "SELECT DISTINCT substr(due_date,1,7) FROM bills") + [this]), reverse=True)
    frm, to = month_range(args, months, this)
    text = words(args.get("q"))
    first, last = span_bounds(frm, to)
    rows = _rows(con, "SELECT id, name, vendor, amount, due_date, status FROM bills WHERE due_date BETWEEN ? AND ? "
                      "ORDER BY due_date", (first, last))
    late = _rows(con, "SELECT id, name, vendor, amount, due_date, status FROM bills WHERE due_date < ? "
                      "AND status IN ('due','overdue','unpaid') ORDER BY due_date", (first,)) if frm <= this <= to else []
    t = today.isoformat()
    for r in rows + late:
        if r["status"] in ("due", "unpaid") and r["due_date"] < t:  # overdue comes from the date, not the stored word
            r["status"] = "overdue"
        r["category"] = bill_category(r["name"])
    cats = sorted({r["category"] for r in rows + late if r["category"]})
    cat = args.get("cat") if args.get("cat") in cats else ""
    if cat:
        rows = [r for r in rows if r["category"] == cat]
        late = [r for r in late if r["category"] == cat]
    if text:  # name, vendor, category and status
        rows = [r for r in rows if matches(text, r["name"], r["vendor"], r["category"], r["status"])]
        late = [r for r in late if matches(text, r["name"], r["vendor"], r["category"], r["status"])]
    unpaid = sum(r["amount"] or 0 for r in rows if r["status"] != "paid")
    paid = sum(r["amount"] or 0 for r in rows if r["status"] == "paid")
    cols = ["due_date", "status", "amount", "name", "vendor", "category"]  # what is scanned first: when, paid or not, how much
    blocks = []
    if late:
        blocks.append(block("Still open from earlier months", late, "", "bills", cols, title="name"))
    blocks.append(block(f"Bills due in {span_label(frm, to)}", rows,
                        "No bills match." if text or cat else "No bills due in these months.", "bills", cols, title="name"))
    notes = []
    try:
        import recurring_bills as rb
        tracked = rb.status(con, today)
    except Exception:  # noqa: BLE001 (no transactions table yet, or no tracked payees)
        tracked = []
    for r in tracked:
        for fl in r["flags"]:
            notes.append(("warn" if fl.startswith("missing") else "info", f"{r['name']}: {fl}."))
    if tracked:
        blocks.append(block("Recurring payments tracked as bills", [
            {"bill": r["name"], "every": r["frequency"], "expected": r["amount"], "last_charge": str(r["last"] or ""),
             "next_expected": str(r["next"] or ""), "open_bill": f"due {r['open_bill']['due']}" if r["open_bill"] else "none"}
            for r in tracked], "", money=("expected",)))
    return {"tiles": [("Bills", len(rows), ""), ("Unpaid", M.fmt(unpaid, 0), "warn" if unpaid else ""),
                      ("Paid", M.fmt(paid, 0), "")],
            "notes": notes, "blocks": blocks,
            "filters": {"range": True, "from": frm, "to": to, "months": months, "cats": cats, "cat": cat, "q": text,
                        "search": "Search name, vendor or category"}}


def receipts(con, today, args):
    try:
        import receipts as RC
        rows = RC.rows(con)
    except sqlite3.Error:
        return {"notes": [("info", "This part arrives with the next update.")]}
    s = {k: sum(1 for r in rows if r["status"] == k) for k in ("open", "matched", "ignored")}
    open_ = [{"id": r["id"], "date": r["receipt_date"], "store": r["merchant"], "total": r["total"],
              "note": r["match_note"] or ""} for r in rows if r["status"] == "open"]
    done = [{"id": r["id"], "date": r["receipt_date"], "store": r["merchant"], "total": r["total"],
             "charge": f"{r['txn_date'] or ''} {r['charge'] or ''}".strip(),
             "charged": -r["charge_amount"] if r["charge_amount"] else None, "account": r["account"] or "",
             "how": r["match_confidence"] or ""} for r in rows if r["status"] == "matched"]
    return {"tiles": [("Matched", s["matched"], ""), ("Waiting for a charge", s["open"], "warn" if s["open"] else ""),
                      ("No charge expected", s["ignored"], "")],
            "blocks": [block("Waiting for a charge", open_, "Every receipt has its charge.", "receipts"),
                       block("Matched", done, "No matched receipts yet.", "receipts", money=("charged",))]}


PAYPAL_NOTE = "PayPal statement"  # receipts.notes of the payments paypal_statement.py files
PAYPAL_STATE = {"matched": "matched", "open": "waiting", "ignored": "no charge expected"}


def has_paypal():
    """True when a PayPal statement was filed or a bank / card line says PayPal (the PayPal part is offered then)."""
    def look():
        con = _con()
        try:
            return bool(con.execute("SELECT 1 FROM receipts WHERE notes=? LIMIT 1", (PAYPAL_NOTE,)).fetchone()
                        or con.execute("SELECT 1 FROM transactions WHERE UPPER(description) LIKE '%PAYPAL%' LIMIT 1").fetchone())
        finally:
            con.close()
    return _safe(look, False)


def paypal(con, today, args):
    """Every payment from the filed PayPal statements, month by month, matched or not, with the card or bank charge each
    belongs to; then PayPal charges on cards and bank accounts that no statement line explains yet."""
    n = _span(args.get("months"))
    first = (today.replace(day=1) - dt.timedelta(days=31 * (n - 1))).replace(day=1).isoformat()
    rows = _rows(con, "SELECT r.id, r.merchant, r.receipt_date AS date, r.total, r.status, "
                      "a.name || ' x' || COALESCE(a.last4, '') AS paid_with, t.description AS charge, "
                      "r.match_note AS note FROM receipts r LEFT JOIN transactions t ON t.id=r.transaction_id "
                      "LEFT JOIN accounts a ON a.id=t.account_id WHERE r.notes=? AND r.receipt_date >= ? "
                      "ORDER BY r.receipt_date DESC, r.id DESC", (PAYPAL_NOTE, first))
    for r in rows:
        r["status"] = PAYPAL_STATE.get(r["status"], r["status"])
        r["paid_with"] = r["paid_with"] or ""
        r["charge"] = r["charge"] or ""
        if r["status"] == "matched":
            r["note"] = ""
    months = {}
    for r in rows:
        m = months.setdefault(r["date"][:7], {"month": r["date"][:7], "payments": 0, "total": 0.0, "matched": 0, "waiting": 0})
        m["payments"] += 1
        m["total"] = round(m["total"] + (r["total"] or 0), 2)
        m["matched"] += r["status"] == "matched"
        m["waiting"] += r["status"] == "waiting"
    loose = _rows(con, "SELECT t.id, t.description, t.txn_date AS date, t.amount, a.name || ' x' || COALESCE(a.last4, '') "
                       "AS account FROM transactions t JOIN accounts a ON a.id=t.account_id "
                       "WHERE UPPER(t.description) LIKE '%PAYPAL%' AND t.amount < 0 AND t.txn_date >= ? "
                       "AND COALESCE(t.txn_type, '') NOT IN ('transfer', 'card_payment', 'investment_transfer') "
                       "AND t.id NOT IN (SELECT transaction_id FROM receipts WHERE transaction_id IS NOT NULL) "
                       "ORDER BY t.txn_date DESC", (first,))
    waiting = sum(1 for r in rows if r["status"] == "waiting")
    notes = [] if rows else [("info", "This fills in once a PayPal statement (PDF) is filed: drop it in the Inbox. "
                                      "It is read without AI and each payment is matched to its card or bank charge.")]
    return {"tiles": [("Payments", len(rows), ""), ("Paid through PayPal", M.fmt(sum(r["total"] or 0 for r in rows), 0), ""),
                      ("Matched", sum(1 for r in rows if r["status"] == "matched"), ""),
                      ("Waiting for a charge", waiting, "warn" if waiting else "")],
            "notes": notes,
            "blocks": [block("Month by month", sorted(months.values(), key=lambda m: m["month"], reverse=True), "",
                             money=("total",)),
                       block("Payments", rows, "No PayPal payments in these months.", "receipts", money=("total",)),
                       block("PayPal charges with no statement line", loose,
                             "Every PayPal charge has its line from a PayPal statement.", "transactions", money=("amount",),
                             fold=True)],
            "filters": {"span": n}}


def mobile(con, today, args):
    import mobile_bill as MB
    n = _span(args.get("months"))
    rows = MB.months(con, n)
    if not rows:
        return {"notes": [("info", "This fills in once a phone bill (PDF with the per-line summary) is filed. Drop it in "
                                   "the Inbox; the call lists are never read.")], "filters": {"span": n}}
    newest = max(r["month"] for r in rows)
    cur = [r for r in rows if r["month"] == newest]
    lines, net = sum(r["lines"] for r in cur), sum(r["net"] or 0 for r in cur)
    people = sorted({r["person"] for r in rows}, key=str.lower)
    wide = {}
    for r in rows:
        w = wide.setdefault(r["month"], {"month": r["month"]})
        w[r["person"]] = (w.get(r["person"]) or 0) + (r["net"] or 0)
    table = [{**{"month": w["month"]}, **{p: w.get(p) for p in people},
              "total": round(sum(w.get(p) or 0 for p in people), 2)} for w in sorted(wide.values(), key=lambda w: w["month"],
                                                                                     reverse=True)]
    billrows = _rows(con, "SELECT id, bill_date, carrier, bill_total FROM mobile_bills ORDER BY bill_date DESC")
    return {"tiles": [(f"Phone bill, {newest}", M.fmt(net, 0), ""), ("Lines", lines, ""),
                      ("Per line", M.fmt(net / max(lines, 1), 0), "")],
            "notes": [("info", "Each person's net = their lines' charges, device payments and taxes, plus an equal share of "
                               "the account-wide credits and charges.")],
            "blocks": [block("Net cost per person, month by month", table, "", money=tuple(people) + ("total",)),
                       block("Phone bills filed", billrows, "", "mobile_bills")],
            "filters": {"span": n}}


# what a subscription table shows, narrow enough to sit next to the side panel: per year is in the tiles, category and
# who uses it in the row's window, the card in the cancel note, the last charge in the Ledger
SUB_COLS = ["subscription", "status", "per_month", "next_est", "decision"]


def _sub_row(r, today):
    nxt = r["next"]
    return {"id": r["id"], "subscription": r["name"], "decision": r["decision"], "status": r["status"],
            "per_month": r["per_month"], "per_year": r["per_year"], "category": r["category"], "paid_with": r["paid_with"],
            "last_charge": str(r["last_date"] or ""),
            "next_est": "" if not nxt else str(nxt) if nxt >= today else "due, no statement yet",
            "used_by": r["used_by"]}


def subs(con, today, args):
    import subscriptions as S
    try:
        trk, cands = S.tracked(con, today), S.detect(con, today)
    except sqlite3.Error:
        trk, cands = [], []
    sm = S.summary(trk)
    notes = []
    for r in trk:
        if r["status"] == "STILL CHARGING after cancel":
            notes.append(("bad", f"{r['name']} was marked cancelled but charged {r['last_date']} on {r['paid_with']}."))
        elif r["decision"] == "cancel" and r["status"] == "active":
            notes.append(("warn", f"Cancel {r['name']} before the next charge (about {r['next']}, "
                                  f"{M.fmt(r['last_amount'])} on {r['paid_with']})."))
        if r["price_note"] and r["status"] == "active":
            notes.append(("info", f"Price change: {r['name']} {r['price_note']}."))
    unrev = [r for r in trk if r["decision"] == "unreviewed" and r["status"] == "active" and r["tracked_active"]]
    live = [r for r in trk if r["status"] != "stopped?"]
    decided = [r for r in live if r not in unrev]
    stopped = [r for r in trk if r["status"] == "stopped?"]
    m = ("per_month", "per_year")
    blocks = []
    if unrev:
        blocks.append(block("Decide: is it used? (keep or cancel)", [_sub_row(r, today) for r in
                                                                  sorted(unrev, key=lambda r: -r["per_year"])],
                            "", "subscriptions", SUB_COLS, money=m))
    blocks.append(block("Already decided" if unrev else "All tracked",
                        [_sub_row(r, today) for r in sorted(decided, key=lambda r: -r["per_year"])],
                        "No subscriptions tracked yet." if not live else "Every active subscription is waiting for a decision.",
                        "subscriptions", SUB_COLS, money=m))
    if stopped:
        blocks.append(block("No recent charge, probably ended", [_sub_row(r, today) for r in stopped], "", "subscriptions",
                            SUB_COLS, money=m))
    blocks.append(block("Other recurring payments seen (not tracked as subscriptions)", [
        {"merchant": c["merchant"], "frequency": c["frequency"], "amount": c["amount"], "charges": c["charges"],
         "last": str(c["last"]), "next_est": str(c["next"]), "per_year": c["per_year"],
         "still_active": "yes" if c["active"] else "stopped?"} for c in cands],
        "None seen.", cols=["merchant", "frequency", "amount", "per_year", "still_active"], money=("per_year",)))
    return {"tiles": [("Still charging", sm["count"], ""), ("Per month", M.fmt(sm["per_month"], 0), ""),
                      ("Per year", M.fmt(sm["per_year"], 0), ""),
                      ("Not reviewed yet", len(unrev), "warn" if unrev else "")],
            "notes": notes, "blocks": blocks}


def amazon(con, today, args):
    import amazon_match as AM
    rows, sm = AM.rows(con, today), AM.summary(con)
    notes = []
    if sm:
        notes.append(("info", f"{sm['orders']} orders, {M.fmt(sm['orders_total'])}; {sm['matched']} of {sm['payable']} "
                              "chargeable orders matched to a card charge. Unmatched orders were paid with a card whose "
                              "statements are not imported yet."))
    elif not config.pack("amazon"):
        notes.append(("info", "Amazon orders are part of the Amazon pack, turned on in Settings > Data > Advanced."))
    return {"notes": notes, "blocks": [block("Amazon orders", [
        {"id": r["id"], "date": r["order_date"], "total": r["total"], "status": r["status"], "items": r["items"],
         "card": r["card"] or "", "match": r["match_note"] or ""} for r in rows], "No orders imported.", "amazon_orders")]}


def _uncategorized(con, card, limit=15):
    """Card charges with no category, grouped by merchant (all months, or one card): the biggest first, each with the text
    a rule would match, so a person can name the category once and have it remembered. -> [{key, example, n, spent}]."""
    sql = ("SELECT t.description, t.amount FROM transactions t JOIN accounts a ON a.id=t.account_id "
           "WHERE a.type='credit' AND COALESCE(t.txn_type,'spend') NOT IN ('card_payment','transfer') "
           "AND (t.category IS NULL OR TRIM(t.category)='') AND t.amount < 0")
    params = []
    if card:
        sql += " AND a.id=?"
        params.append(int(card))
    groups = {}
    for desc, amount in con.execute(sql, params):
        key = rule_match.merchant_key(desc) or rule_match.clean(desc)[:24]
        if not key:
            continue
        g = groups.setdefault(key, {"key": key, "example": rule_match.clean(desc)[:60], "n": 0, "spent": 0.0})
        g["n"] += 1
        g["spent"] -= amount or 0
    out = sorted(groups.values(), key=lambda g: -g["spent"])
    return [{**g, "spent": round(g["spent"], 2)} for g in out[:limit]]


def _categories(con):
    """The category names in use (transactions and rules), for the picker."""
    try:
        got = {r[0] for r in con.execute("SELECT DISTINCT category FROM transactions WHERE TRIM(COALESCE(category,''))!='' "
                                         "UNION SELECT DISTINCT category FROM category_rules WHERE TRIM(COALESCE(category,''))!=''")}
    except sqlite3.Error:
        got = set()
    return sorted(got, key=str.lower)


def ledger(con, today, args):
    return ledger_data.ledger(con, args, today, sys.modules[__name__])


def watch(con, today, args):
    import statement_watch as SW
    rows = SW.watch(con, today)
    return {"blocks": [block("Statements per account", [
        {"status": r["status"], "account": f"{r['account']} x{r['last4']}", "cadence": r["cadence"],
         "last_statement": str(r["last_stmt"] or ""), "next_expected": str(r["expected"] or ""),
         "missing_months": ", ".join(r["missing"])} for r in rows], "No accounts yet.")],
        "notes": [("info", "Statement dates come from the filed papers; cadence is read from the gaps between statements.")]}


def spikes(con, today, args):
    import spikes as SP
    rows = SP.spikes(con, today)
    return {"blocks": [block("Price rises", [
        {"type": r["kind"], "what": r["name"], "date": str(r["date"]), "latest": r["latest"], "usual": r["baseline"],
         "change": f"+{r['pct']:.0f}%", "detail": r["detail"]} for r in rows], "No spikes found.",
        money=("latest", "usual"))],
        "notes": [("info", "A bill or recurring charge at least 20% and 10 above its recent median (utilities 35%, with a "
                           "year-over-year check).")]}


# ---- Keep ------------------------------------------------------------------------------------------------------
def keep_split(bal):
    """(cash, investments, owed) from the latest balances: investment accounts (brokerage, TreasuryDirect T-bills and
    I bonds, CDs held there) apart from checking and savings; anything below zero is owed. The investments table is a
    breakdown of what those accounts hold, so it is not added again."""
    cash = sum(r["signed_balance"] for r in bal if (r["signed_balance"] or 0) > 0 and r.get("type") != "investment")
    invested = sum(r["signed_balance"] for r in bal if (r["signed_balance"] or 0) > 0 and r.get("type") == "investment")
    owed = -sum(r["signed_balance"] for r in bal if (r["signed_balance"] or 0) < 0)
    return cash, invested, owed


def net_worth_history(con, today, months=12):
    """Net worth at the end of each of the last `months` months (this month: so far) from the reported balances: for each
    account its latest balance on or before that day, cards and loans as owed (keep_split). Months before any balance
    are left out. -> [{"month", "cash", "invested", "owed", "net"}], oldest first."""
    try:
        bal = con.execute("SELECT b.account_id, a.type, b.as_of, b.balance FROM account_balances b "
                          "JOIN accounts a ON a.id=b.account_id ORDER BY b.as_of").fetchall()
    except sqlite3.Error:
        return []
    out = []
    first = today.replace(day=1)
    for back in range(months - 1, -1, -1):
        y, m = first.year, first.month - back
        while m < 1:
            y, m = y - 1, m + 12
        end = today if back == 0 else (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1))
        latest = {}
        for acct, typ, as_of, balance in bal:
            if str(as_of)[:10] <= end.isoformat() and balance is not None:
                latest[acct] = {"type": typ, "signed_balance": -balance if typ in ("credit", "loan") else balance}
        if not latest:
            continue
        cash, invested, owed = keep_split(list(latest.values()))
        out.append({"month": f"{dt.date(y, m, 1):%b %Y}", "cash": cash, "invested": invested, "owed": owed,
                    "net": cash + invested - owed})
    return out


def accounts(con, today, args):
    import statement_watch as SW
    blocks, tiles = [], []
    try:
        bl = _rows(con, "SELECT account_id AS id, name || ' x' || COALESCE(last4, '') AS account, balance AS reported, type, owner, "
                        "as_of, signed_balance FROM v_balance_latest ORDER BY type, name")
    except sqlite3.Error:
        bl = []
    if bl:
        cash, invested, owed = keep_split(bl)
        tiles = [("Cash", M.fmt(cash, 0), ""), ("Investments", M.fmt(invested, 0), ""),
                 ("Cards and loans owed", M.fmt(owed, 0), ""),
                 (f"Net position · {short_date(max(str(r['as_of']) for r in bl), today)}", M.fmt(cash + invested - owed, 0), "")]
    blocks.append(block("Latest statement balances", [{k: v for k, v in r.items() if k != "signed_balance"} for r in bl],
                        "No balances recorded yet.", "accounts", money=("reported",)))
    hist = net_worth_history(con, today)
    if len(hist) >= 2:  # newest first, each with the change from the month before it
        rows = []
        for i in range(len(hist) - 1, -1, -1):
            h, d = hist[i], (hist[i]["net"] - hist[i - 1]["net"]) if i else None
            rows.append({"month": h["month"], "cash": h["cash"], "investments": h["invested"],
                         "cards_and_loans_owed": h["owed"], "net_worth": h["net"],
                         "change": "" if d is None else ("+" if d >= 0 else "-") + M.fmt(abs(d), 0)})
        blocks.append(block("Net worth by month", rows, "",
                            money=("cash", "investments", "cards_and_loans_owed", "net_worth")))
    acc = _rows(con, "SELECT a.id, a.name AS account, a.type, a.last4, a.owner, "
                     "(SELECT COUNT(*) FROM transactions t WHERE t.account_id=a.id) AS transactions, "
                     "(SELECT MAX(txn_date) FROM transactions t WHERE t.account_id=a.id) AS last_txn "
                     "FROM accounts a ORDER BY a.type, a.name")
    w = {r["last4"]: r for r in SW.watch(con, today)}
    for r in acc:
        s = w.get(r["last4"])
        r["latest_statement"] = str(s["last_stmt"]) if s and s["last_stmt"] else ""
        r["note"] = f"statement {s['status']}" if s and s["status"] in ("due now", "overdue") else ""
        if not r["note"] and r["last_txn"]:
            import keepup
            r["note"] = keepup.age_note((today - dt.date.fromisoformat(str(r["last_txn"])[:10])).days)
    blocks.append(block("Accounts and statement coverage", acc, "No accounts yet. Drop a statement in the Inbox.",
                        "accounts"))
    try:
        inv = _rows(con, "SELECT id, name, kind, invested, current_value, as_of, maturity_date FROM investments "
                         "ORDER BY maturity_date")
    except sqlite3.Error:
        inv = []
    blocks.append(block("Investments (maturity ladder)", inv, "No holdings recorded.", "investments"))
    try:
        flows = _rows(con, "SELECT month, payee, invested, cumulative_total FROM v_investment_flows "
                           "ORDER BY month DESC, payee LIMIT 36")
    except sqlite3.Error:
        flows = []
    blocks.append(block("Money moved to investments (from bank statements)", flows, "None seen.",
                        money=("cumulative_total",)))
    return {"tiles": tiles, "blocks": blocks}


TYPE_WORD = {"income": "income", "interest": "interest", "transfer": "transfer", "investment_transfer": "from investments",
             "tax": "tax refund", "spend": "refund", "card_payment": "card payment", None: "not sorted"}


def _deposit_sources(con, first, last, limit=15):
    """Money in to checking / savings between two dates, grouped by source (the text a rule would match): what each is
    counted as now, so a person can say "this is pay" or "this is money back from TreasuryDirect" once. Not sorted first,
    then the biggest. -> [{key, example, n, total, kind, kind_word, category}]."""
    groups = {}
    for desc, amount, typ, cat in con.execute(
            "SELECT t.description, t.amount, t.txn_type, t.category FROM transactions t JOIN accounts a ON a.id=t.account_id "
            "WHERE t.amount > 0 AND a.type IN ('checking','savings') AND t.txn_date BETWEEN ? AND ?", (first, last)):
        key = rule_match.merchant_key(desc) or rule_match.clean(desc)[:24]
        if not key:
            continue
        g = groups.setdefault(key, {"key": key, "example": rule_match.clean(desc)[:60], "n": 0, "total": 0.0, "kinds": {}})
        g["n"] += 1
        g["total"] += amount or 0
        g["kinds"][(typ, cat)] = g["kinds"].get((typ, cat), 0) + 1
    out = []
    for g in groups.values():
        (typ, cat), _ = max(g.pop("kinds").items(), key=lambda kv: kv[1])
        out.append({**g, "total": round(g["total"], 2), "kind": typ or "", "kind_word": TYPE_WORD.get(typ, typ),
                    "category": cat or ""})
    out.sort(key=lambda g: (g["kind"] != "", -g["total"]))
    return out[:limit]


def deposits(con, today, args):
    """Deposit sources (Look back): money that came in to checking and savings, grouped by where it came from, with the
    form that says once what a source is. The deposits themselves are lines of the Ledger (a link with the same months)."""
    this = today.strftime("%Y-%m")
    months = sorted(set(_months(con, "SELECT DISTINCT substr(t.txn_date,1,7) FROM transactions t JOIN accounts a "
                                     "ON a.id=t.account_id WHERE t.amount > 0 AND a.type IN ('checking','savings')")
                        + [this]), reverse=True)
    frm, to = month_range(args, months, this)
    first, last = span_bounds(frm, to)
    sources = _safe(lambda: _deposit_sources(con, first, last), [])
    ledger_url = "/money?" + urllib.parse.urlencode({"part": "ledger", "type": "income", "from": first, "to": last})
    return {"rules": {"merchants": sources, "cats": _categories(con), "deposits": True,
                      "kinds": [(k, w) for k, (_c, w) in rule_match.DEPOSIT_KINDS.items()]},
            "go": [("See the pay in the Ledger", ledger_url)],
            "notes": [] if sources else [("info", f"No deposits to sort in {span_label(frm, to)}.")],
            "filters": {"range": True, "from": frm, "to": to, "months": months, "cats": [], "cat": "", "q": "",
                        "search": "", "nosearch": True}}


def goal_rows(con, today):
    """Active savings goals with what is saved (typed, or the followed account's latest balance), the share reached,
    what it takes a month to reach the date, and the even-pace mark ("behind" when saved is under it)."""
    try:
        rows = con.execute("SELECT g.id, g.name, g.target, g.saved, g.due_date, g.created_at, b.balance, b.as_of "
                           "FROM savings_goals g LEFT JOIN v_balance_latest b ON b.account_id=g.account_id "
                           "WHERE g.status='active' ORDER BY g.due_date IS NULL, g.due_date, g.name").fetchall()
    except sqlite3.Error:
        return []
    out = []
    for gid, name, target, typed, due, created, bal, as_of in rows:
        saved = max(0.0, float(bal)) if bal is not None else float(typed or 0)
        pct = max(0, min(100, round(saved / target * 100))) if target else 0
        left = max(0.0, target - saved)
        due_d = dates.parse(due) if due else None
        monthly, mark, behind, note = None, None, False, ""
        if left <= 0:
            note = "reached"
        elif due_d:
            months = (due_d.year - today.year) * 12 + due_d.month - today.month
            if months <= 0:
                note = f"{M.fmt(left, 0)} still to save; the date has passed"
                behind = True
            else:
                monthly = round(left / months, 2)
                note = f"{M.fmt(monthly, 0)} a month to reach it by {due_d:%b %Y}"
                start = dates.parse(str(created)[:10]) or today
                span = (due_d - start).days
                if span > 0:
                    mark = max(0, min(100, round((today - start).days / span * 100)))
                    behind = pct < mark
        else:
            note = f"{M.fmt(left, 0)} to go"
        if bal is not None:
            note += f" (balance on {as_of})"
        out.append({"id": gid, "name": name, "target": target, "saved": saved, "due": due or "", "pct": pct,
                    "monthly": monthly, "mark": mark, "behind": behind, "note": note})
    return out


def budget(con, today, args):
    import budget as B
    import loans as LN
    last = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    blocks, tiles = [], []
    try:
        p = B.pace(con, today)
    except sqlite3.Error:
        p = {"lines": [], "loaded": False}
    if p["lines"]:
        tiles = [(LIGHT[s].capitalize(), sum(1 for r in p["lines"] if r["status"] == s), "bad" if s == "red" and
                  any(r["status"] == "red" for r in p["lines"]) else "") for s in ("red", "amber", "green")]
    when = f"through {p['through']:%b %d}" if p.get("loaded") else "no transactions loaded for this month yet"
    tone = {"red": "bad", "amber": "warn", "green": "ok"}
    blocks.append(block(f"This month so far, {when}", [
        {"line": r["label"], "status": LIGHT[r["status"]], "spent": r["spent"], "limit": r["limit"],
         "expected_by_now": r["expected"], "projected": r["projected"], "used": f"{r['pct']:.0f}%"} for r in p["lines"]],
        "No budget lines yet. Set one with the form above or tell Chat.",
        money=("spent", "limit", "expected_by_now", "projected"),
        bars=[{"label": r["label"], "value": M.fmt(r["spent"], 0), "of": M.fmt(r["limit"], 0),
               "pct": max(0, min(100, round(r["pct"] or 0))), "tone": tone.get(r["status"], ""),
               "mark": max(0, min(100, round((r["expected"] or 0) / r["limit"] * 100))) if r["limit"] else None,
               "note": LIGHT[r["status"]] + (f", heading for {M.fmt(r['projected'], 0)}" if r["status"] != "green" and r["projected"] else "")}
              for r in p["lines"]]))
    try:
        v = B.variance(con, last)
    except sqlite3.Error:
        v = []
    blocks.append(block(f"Budget against actual, {last}", [
        {"category": c, "limit": lim, "actual": a, "result": ("over " if o > 0 else "under ") + M.fmt(abs(o))}
        for c, lim, a, o in v], "No budget lines yet.", money=("limit", "actual"),
        bars=[{"label": c, "value": M.fmt(a, 0), "of": M.fmt(lim, 0), "pct": max(0, min(100, round(a / lim * 100))) if lim else 100,
               "tone": "bad" if o > 0 else "ok", "mark": None, "note": ("over by " if o > 0 else "under by ") + M.fmt(abs(o), 0)}
              for c, lim, a, o in v], fold=True))
    try:
        sug = B.suggest(con, today)
    except (sqlite3.Error, KeyError, TypeError):
        sug = []
    blocks.append(block("Suggested limits from the last six full months", [
        {"category": r["category"], "months_with_spend": r["months"], "average_a_month": r["average"],
         "suggested": r["suggested"], "current_limit": r["limit"]} for r in sug],
        "Needs categorised spending from earlier months: file a few months of statements first.",
        money=("average_a_month", "suggested", "current_limit"), fold=True))
    loans = LN.rows(con)
    blocks.append(block("Loans", [
        {"id": r["id"], "loan": r["name"], "kind": r["kind"], "lender": r["lender"], "balance": r["balance"],
         "rate": f"{r['rate_pct']}%" if r["rate_pct"] is not None else "", "payment": r["payment"],
         "months_left": LN.months_left(r["balance"], r["rate_pct"], r["payment"])} for r in loans],
        "No loans recorded.", "loans"))
    goals = goal_rows(con, today)
    blocks.append(block("Savings goals", [], "No savings goals yet. Add one with the form above.",
        bars=[{"label": g["name"], "value": M.fmt(g["saved"], 0), "of": M.fmt(g["target"], 0), "pct": g["pct"],
               "tone": "ok" if g["pct"] >= 100 else "warn" if g["behind"] else "", "mark": g["mark"],
               "note": g["note"]} for g in goals]))
    if goals:
        blocks.append(block("Change a savings goal", [
            {"id": g["id"], "goal": g["name"], "saved": g["saved"], "target": g["target"], "by": g["due"] or "",
             "a_month_to_get_there": g["monthly"]} for g in goals], "", "savings_goals",
            money=("saved", "target", "a_month_to_get_there"), fold=True))
    sooner = []
    for r in loans:
        plan = LN.payoff_plan(r["balance"], r["rate_pct"], r["payment"], today=today)
        for p in plan:
            sooner.append({"loan": r["name"], "a_month": M.fmt((r["payment"] or 0) + p["extra"], 0)
                           + (f" (+{M.fmt(p['extra'], 0)})" if p["extra"] else " (now)"),
                           "paid_off": f"{p['paid_off']:%b %Y}", "interest_left": p["interest"],
                           "sooner": f"{p['months_sooner']} months" if p["extra"] and p["months_sooner"] else "",
                           "interest_saved": p["interest_saved"] if p["extra"] else None})
    if sooner:
        blocks.append(block("Paying loans off sooner", sooner, "", money=("interest_left", "interest_saved"), fold=True))
    return {"tiles": tiles, "blocks": blocks, "notes": [("info", "Payoff figures are arithmetic on the balance, rate and "
                                                                 "payment on file, not advice.")] if sooner else []}


def benefits(con, today, args):
    import benefits as BN
    rows = BN.status(con, today)
    notes, blocks = [], []
    for b in rows:
        basis = "billing cycle" if b["reset_basis"] == "statement" else "month"
        name = f"{b['acct']} x{b['last4']}: {b['name']} ({M.fmt(b['amount'], 0)} per {basis})"
        if b["current_open"]:
            notes.append(("warn", f"{name}: not used yet this {basis}; use it before {b['period_end']:%b %d}."))
        blocks.append(block(f"{name} · received {b['received_n']} ({M.fmt(b['received'])}), missed {b['lost_n']}",
                            [{"billing_cycle": x["label"], "status": x["state"], "credit_received": x["credit"],
                              "qualifying_spend": x["spend"]} for x in reversed(b["periods"])], "",
                            money=("credit_received", "qualifying_spend")))
    if not rows:
        notes.append(("info", "No card benefits tracked yet."))
    return {"notes": notes, "blocks": blocks}


# ---- Look back -------------------------------------------------------------------------------------------------
def tax(con, today, args):
    import tax_prep as TP
    y, years = _year(args.get("year"), today)
    return {"md": TP.build(con, y), "filters": {"year": y, "years": years}}


def year_end(con, today, args):
    import year_end as YE
    y, years = _year(args.get("year"), today)
    return {"md": YE.build(con, y), "filters": {"year": y, "years": years}}


def home_office(con, today, args):
    import home_office as HO
    try:
        prof = con.execute("SELECT tax_year, who FROM home_office_profile ORDER BY tax_year DESC, who").fetchall()
    except sqlite3.Error:
        prof = []
    rows, notes = [], []
    for y, who in prof:
        c = HO.compute(con, int(y), who)
        rows.append({"year": y, "who": who, "business_use": f"{c['pct']:.1%}", "simplified_method": c["simplified"],
                     "regular_method": c["regular"]})
        notes += [("warn", f"{y} · {who}: {i}") for i in c["issues"]]
    notes.append(("info", "Records and arithmetic only, not tax advice."))
    return {"notes": notes, "blocks": [block("Home office", rows, "No home-office profile yet (only relevant if you are "
                                             "self-employed or run a business from home). Use \"Set up your home office\" above, or tell "
                                             "Chat, e.g. \"home office for Alex: 120 sq ft of an 1,800 sq ft home\".",
                                             money=("simplified_method", "regular_method"))]}


def work(con, today, args):
    import contracts as C
    rows = C.rows(con, today)
    try:
        inv = _rows(con, "SELECT i.id, c.client, i.period_start, i.period_end, i.hours, i.amount, i.status, i.sent_on, "
                         "i.paid_on FROM work_invoices i JOIN contracts c ON c.id=i.contract_id "
                         "ORDER BY i.period_end DESC LIMIT 60")
    except sqlite3.Error:
        inv = []
    return {"blocks": [block("Contracts", [
        {"id": r["id"], "client": r["client"], "holder": r.get("person") or "", "vendor": r.get("vendor") or "",
         "start": r.get("start_date") or "", "ends": r.get("end_date") or "", "days_left": r["days_left"],
         "rate_per_hour": r.get("hourly_rate")} for r in rows], "No contracts recorded.", "contracts",
        money=("rate_per_hour",)),
        block("Invoices", inv, "No invoices yet.", "work_invoices")]}


VIEWS = {"bills": bills, "receipts": receipts, "paypal": paypal, "mobile": mobile, "subs": subs, "amazon": amazon,
         "ledger": ledger, "watch": watch, "spikes": spikes, "accounts": accounts, "deposits": deposits, "budget": budget,
         "benefits": benefits, "tax": tax, "home_office": home_office, "year_end": year_end,
         "work": work}


DOWNLOADS = {"tax": "tax_prep", "year_end": "year_end", "ledger": "ledger"}
# parts whose tiles and notes sit in a side panel (a folded summary line on a tablet or phone), so the list comes first
SIDE_PANEL = {"ledger", "bills", "receipts", "subs", "accounts"}


def download(part, today, args):
    """(file name, media type, bytes) for the parts that can be saved as a file, else None: the tax checklist and the
    year-end summary as markdown, the Ledger's lines (with its filters) as CSV, the tax preparer's pack as a zip."""
    if part not in DOWNLOADS:
        return None
    if part == "ledger":
        if not has_transactions():
            return None
        con = _con()
        try:
            name, body = ledger_data.csv_file(con, args, today)
        finally:
            con.close()
        return name, "text/csv; charset=utf-8", body
    if part == "tax" and args.get("pack"):  # the zip for the tax preparer (tax_pack.py)
        import tax_pack
        y, _years = _year(args.get("year"), today)
        con = _con()
        try:
            name, body = tax_pack.build(con, y, today)
        finally:
            con.close()
        return name, "application/zip", body
    v = view(part, today, args)
    f = v.get("filters") or {}
    if part in ("tax", "year_end"):
        if not v.get("md"):
            return None
        return f"{f.get('year')}_{DOWNLOADS[part]}.md", "text/markdown; charset=utf-8", v["md"].encode("utf-8")
    return None


def view(part, today, args):
    """One part's read-only view (see the module text). An older database without a table shows a note, not an error."""
    base = {"tiles": [], "notes": [], "blocks": [], "md": None, "filters": {}}
    if part in STATEMENT_PARTS and not has_transactions():
        return {**base, "notes": [("info", NO_STATEMENTS)]}
    fn = VIEWS.get(part)
    if fn is None:
        return base
    try:
        con = _con()
    except sqlite3.Error:
        return {**base, "notes": [("info", "The records are not there yet.")]}
    try:
        v = {**base, **fn(con, today, args)}
        v["side"] = part in SIDE_PANEL and bool(v["tiles"])
        return v
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return {**base, "notes": [("info", "This part arrives with the next update.")]}
    finally:
        con.close()
