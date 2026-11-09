"""Money > Ledger: every transaction from every account (checking, savings, credit, loan, investment) in one list,
filtered by dates, period, account, words, amount, category and type. Read-only here; changing a line's category or
type is `edit_actions.txn_update` (adults, logged). No web code: used by finance_data.view and its download.

    period_dates(period, today)   week = Monday..Sunday of this week, month, year -> (first, last) ISO days
    parse(args, today)            the filters from a query string, each checked; nothing given = this month
    ledger(con, args, today)      {"tiles", "blocks", "filters"} in the shape finance_data views return
    rows(con, f, limit, offset)   the filtered lines (also the CSV export)
    txn_detail(con, id)           one line in full for the quick-view window; neighbors(con, f, id) = its place in the filtered list

Amounts: min / max compare the size of a line whatever its sign (50 finds a 50.00 purchase and a 50.00 deposit).
Nothing is hidden: every line is listed. The tiles above it are cash flow, not the sum of the list: spending, income,
bills, investing, and money that only moved between the family's own accounts (a transfer or a card payment that has its
other side in another account within PAIR_DAYS is "matched" and counts as neither income nor spending).

    pairs(con, kind, first, last)  {line id: the other side's id} for matched transfers / card payments
    summary(con, f)                the cash-flow figures of the filtered lines
    coverage(con, f, today)        accounts whose newest line is older than the period asks for

What counts as spending is decided here once (`spend_lines`), for the Ledger, This month, Trends, the budget, the
monthly report, the Mitra Wall and the phones: a line typed spend (or no type), fee, utility, insurance or loan payment,
with its sign (a refund comes off); tax, transfers, investing and card payments are not spending. One exception: in a
month with no line on any card account (no card statement filed), a card payment out of a bank stands for that card's
spending and counts (`months_without_cards`).
"""
import calendar as cal
import datetime as dt
import re
import sqlite3
import urllib.parse

import money as M

PAGE = 50
MAX_EXPORT = 100000
WORDS_MAX = 100
PERIODS = (("week", "This week"), ("month", "This month"), ("year", "This year"))
TYPES = (("spend", "Spending"), ("income", "Income"), ("interest", "Interest"), ("transfer", "Transfers"),
         ("card_payment", "Card payments"), ("investment_transfer", "Investing"), ("tax", "Tax"), ("fee", "Fees"),
         ("utility", "Utilities"), ("insurance", "Insurance"), ("loan_payment", "Loan payments"))
SPEND_TYPES = ("spend", "fee", "utility", "insurance", "loan_payment")  # money spent (a line with no type is spending)
BILL_TYPES = ("utility", "insurance", "loan_payment")
BILL_CATEGORIES = ("utilities", "insurance", "emi payments", "cable & internet comm", "internet services", "mortgage", "rent",
                   "phone", "loans")  # a spending line in one of these also counts as a bill paid
PAIR_DAYS = 3  # a transfer out and the same cents in on another account this many days apart are one movement of money
STALE_DAYS = 7  # an account whose newest line is older than this before the period's end (or today) is not up to date
NONE = "__none__"  # the category filter's "Uncategorized"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
AMOUNT = re.compile(r"^\d{1,9}([.,]\d{1,2})?$")


def period_dates(period, today):
    if period == "week":
        first = today - dt.timedelta(days=today.weekday())
        return first.isoformat(), (first + dt.timedelta(days=6)).isoformat()
    if period == "month":
        return today.replace(day=1).isoformat(), today.replace(day=cal.monthrange(today.year, today.month)[1]).isoformat()
    if period == "year":
        return dt.date(today.year, 1, 1).isoformat(), dt.date(today.year, 12, 31).isoformat()
    return None


def _day(value):
    v = str(value or "").strip()
    if not ISO.match(v):
        return None
    try:
        return dt.date.fromisoformat(v).isoformat()
    except ValueError:
        return None


def _amount(value):
    v = str(value or "").strip()
    return float(v.replace(",", ".")) if AMOUNT.match(v) else None


def words(value):
    return " ".join(str(value or "").split())[:WORDS_MAX]


def parse(args, today, accounts=(), cats=(), members=()):
    """The filters, each checked. From / To win over Period; a Period alone fills them in; nothing given = this month.
    `period` in the result is the one the dates exactly match (week, month, year) or "custom"."""
    frm, to = _day(args.get("from")), _day(args.get("to"))
    named = args.get("period") if args.get("period") in dict(PERIODS) else ""
    if not frm and not to:
        frm, to = period_dates(named or "month", today)
    else:
        frm, to = frm or to, to or frm
        if frm > to:
            frm, to = to, frm
    period = next((k for k, _ in PERIODS if period_dates(k, today) == (frm, to)), "custom")
    lo, hi = _amount(args.get("min")), _amount(args.get("max"))
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    ids = {str(i) for i, _ in accounts}
    account = str(args.get("account") or "")
    cat = str(args.get("cat") or "")
    kind = str(args.get("type") or "")
    member = str(args.get("member") or "")
    try:
        page = max(1, int(args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    return {"from": frm, "to": to, "period": period, "q": words(args.get("q")), "min": lo, "max": hi,
            "account": account if account in ids else "", "cat": cat if cat == NONE or cat in set(cats) else "",
            "type": kind if kind in dict(TYPES) else "", "member": member if member in set(members) else "", "page": page}


def account_list(con):
    """[(id as text, "Name x" + last four digits)] of accounts that have lines, credit cards last."""
    try:
        return [(str(i), f"{n} x{l4 or '----'}") for i, n, l4 in con.execute(
            "SELECT a.id, a.name, a.last4 FROM accounts a WHERE EXISTS (SELECT 1 FROM transactions t WHERE t.account_id=a.id) "
            "ORDER BY a.type='credit', a.name, a.last4")]
    except sqlite3.Error:
        return []


def members(con):
    """Who made the charge (`transactions.cardholder`: the card member on a card statement), names in use."""
    try:
        return sorted({r[0] for r in con.execute("SELECT DISTINCT TRIM(cardholder) FROM transactions WHERE TRIM(COALESCE(cardholder,''))!=''")},
                      key=str.lower)
    except sqlite3.Error:
        return []


def categories(con):
    try:
        return sorted({r[0] for r in con.execute("SELECT DISTINCT category FROM transactions WHERE TRIM(COALESCE(category,''))!=''")},
                      key=str.lower)
    except sqlite3.Error:
        return []


def _like(word):
    return "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _where(f):
    sql, params = ["t.txn_date BETWEEN ? AND ?"], [f["from"], f["to"]]
    if f["account"]:
        sql.append("t.account_id=?")
        params.append(int(f["account"]))
    if f["type"]:
        sql.append("COALESCE(NULLIF(t.txn_type,''),'spend')=?")
        params.append(f["type"])
    if f["cat"] == NONE:
        sql.append("TRIM(COALESCE(t.category,''))=''")
    elif f["cat"]:
        sql.append("t.category=?")
        params.append(f["cat"])
    if f["member"]:
        sql.append("TRIM(t.cardholder)=?")
        params.append(f["member"])
    if f["min"] is not None:
        sql.append("ABS(t.amount) >= ?")
        params.append(f["min"] - 0.0049)
    if f["max"] is not None:
        sql.append("ABS(t.amount) <= ?")
        params.append(f["max"] + 0.0049)
    for w in f["q"].lower().split():
        sql.append("(LOWER(t.description) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(t.payee,'')) LIKE ? ESCAPE '\\' "
                   "OR LOWER(COALESCE(t.category,'')) LIKE ? ESCAPE '\\' OR LOWER(COALESCE(t.cardholder,'')) LIKE ? ESCAPE '\\')")
        params += [_like(w)] * 4
    return " AND ".join(sql), params


FROM = ("FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE ")


def rows(con, f, limit=None, offset=0):
    where, params = _where(f)
    sql = ("SELECT t.id, t.txn_date AS date, t.description, a.name || ' x' || COALESCE(a.last4, '----') AS account, "
           "COALESCE(NULLIF(t.category,''), 'Uncategorized') AS category, COALESCE(NULLIF(t.txn_type,''),'spend') AS type, "
           "t.amount, t.manual, COALESCE(t.category,'') AS cat_raw, COALESCE(TRIM(t.cardholder),'') AS member " + FROM + where + " ORDER BY t.txn_date DESC, t.id DESC")
    if limit:
        sql += " LIMIT ? OFFSET ?"
        params = params + [limit, offset]
    cur = con.execute(sql, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r)) for r in cur.fetchall()]


def totals(con, f):
    where, params = _where(f)
    n, money_in, money_out = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(CASE WHEN t.amount>0 THEN t.amount END),0), "
        "COALESCE(SUM(CASE WHEN t.amount<0 THEN t.amount END),0) " + FROM + where, params).fetchone()
    return n, money_in, money_out


def pairs(con, kind, first, last):
    """{line id: id of the other side} for lines of type `kind` (transfer or card_payment) that move money between two of the
    family's accounts: an amount out of one account and the same cents into a different account within PAIR_DAYS (the
    nearest day first). Looks PAIR_DAYS beyond each end so a movement across the edge of the period still pairs. A line
    with no partner is not in the result: its other side is not loaded (or it left the household)."""
    d1, d2 = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    lo, hi = (d1 - dt.timedelta(days=PAIR_DAYS)).isoformat(), (d2 + dt.timedelta(days=PAIR_DAYS)).isoformat()
    lines = con.execute(
        "SELECT id, account_id, txn_date, CAST(ROUND(amount*100) AS INTEGER) FROM transactions "
        "WHERE COALESCE(NULLIF(txn_type,''),'spend')=? AND txn_date BETWEEN ? AND ? AND amount != 0 ORDER BY txn_date, id",
        (kind, lo, hi)).fetchall()
    ins = [(i, a, dt.date.fromisoformat(d), c) for i, a, d, c in lines if c > 0]
    out, used = {}, set()
    for i, a, d, c in lines:
        if c >= 0:
            continue
        d = dt.date.fromisoformat(d)
        best = None
        for j, b, e, k in ins:
            if j in used or b == a or k != -c or abs((e - d).days) > PAIR_DAYS:
                continue
            if best is None or abs((e - d).days) < best[0]:
                best = (abs((e - d).days), j)
        if best:
            used.add(best[1])
            out[i], out[best[1]] = best[1], i
    return out


def _is_bill(ty, cat):
    return ty in BILL_TYPES or (ty == "spend" and (cat or "").strip().lower() in BILL_CATEGORIES)


def months_without_cards(con, first, last):
    """The months (YYYY-MM) from the ISO day `first` to `last` with no line on any card account."""
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT substr(t.txn_date,1,7) FROM transactions t JOIN accounts a ON a.id=t.account_id "
        "WHERE a.type='credit' AND t.txn_date BETWEEN ? AND ?", (first, last + "T99"))}
    y, m = int(first[:4]), int(first[5:7])
    out = set()
    while f"{y:04d}-{m:02d}" <= last[:7]:
        if f"{y:04d}-{m:02d}" not in have:
            out.add(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def counts_as_spending(ty, amount, month, nocard):
    """The one rule (see the top of this file); `ty` already defaulted to 'spend', `nocard` from months_without_cards."""
    return ty in SPEND_TYPES or (ty == "card_payment" and (amount or 0) < 0 and month in nocard)


def spend_lines(con, first, last):
    """Every line that counts as spending between two ISO days, oldest first: dicts id, txn_date, payee, description,
    amount (as stored: a charge < 0, a refund > 0), cents (the same in whole cents, for exact sums), txn_type ('spend'
    when none), category ('' when none), account_id, card (True = a card payment standing for a card's spending)."""
    nocard = months_without_cards(con, first, last)
    cur = con.execute(
        "SELECT t.id, t.txn_date, COALESCE(t.payee,''), COALESCE(t.description,''), t.amount, "
        "CAST(ROUND(COALESCE(t.amount,0)*100) AS INTEGER), COALESCE(NULLIF(t.txn_type,''),'spend'), COALESCE(t.category,''), "
        "t.account_id FROM transactions t WHERE t.txn_date BETWEEN ? AND ? ORDER BY t.txn_date, t.id", (first, last + "T99"))
    out = []
    for tid, day, payee, desc, amt, cents, ty, cat, acct in cur.fetchall():
        if counts_as_spending(ty, amt, str(day)[:7], nocard):
            out.append({"id": tid, "txn_date": day, "payee": payee, "description": desc, "amount": amt or 0.0, "cents": cents,
                        "txn_type": ty, "category": cat, "account_id": acct, "card": ty == "card_payment"})
    return out


def summary(con, f, tm=None, cm=None):
    """The cash-flow figures of the filtered lines as signed sums (money out is negative): income, spending, tax, bills
    (part of spending), invested; moved = transfers that have their other side (gross out) and the ones that do not;
    cards = card payments counted once each (a matched pair is one payment); `everything` = in / out of the whole list by
    group, so the old Money in / Money out can be read back from the parts."""
    where, params = _where(f)
    got = con.execute("SELECT t.id, COALESCE(NULLIF(t.txn_type,''),'spend'), COALESCE(t.category,''), t.amount, "
                      "substr(t.txn_date,1,7) " + FROM + where, params).fetchall()
    tm = pairs(con, "transfer", f["from"], f["to"]) if tm is None else tm
    cm = pairs(con, "card_payment", f["from"], f["to"]) if cm is None else cm
    nocard = months_without_cards(con, f["from"], f["to"])
    r = {"n": len(got), "income": 0.0, "spending": 0.0, "spend_n": 0, "tax": 0.0, "bills": 0.0, "invested": 0.0,
         "moved": 0.0, "moved_open_in": 0.0, "moved_open_out": 0.0, "card_spend": 0.0, "card_spend_months": set(),
         "cards": 0.0, "cards_matched": 0.0, "cards_open_in": 0.0, "cards_open_out": 0.0}
    groups = {}

    def add(group, amount):
        g = groups.setdefault(group, [0.0, 0.0])
        g[0 if amount > 0 else 1] += amount

    for tid, ty, cat, amt, month in got:
        if ty in ("income", "interest"):
            r["income"] += amt
            add("income", amt)
        elif counts_as_spending(ty, amt, month, nocard):
            r["spending"] += amt
            r["spend_n"] += 1
            add("spending", amt)
            if _is_bill(ty, cat):
                r["bills"] += amt
            if ty == "card_payment":  # no card statement that month: the payment stands for the card's spending
                r["card_spend"] += -amt
                r["card_spend_months"].add(month)
        elif ty == "tax":
            r["tax"] += amt
            add("tax", amt)
        elif ty == "investment_transfer":
            r["invested"] += amt
            add("investing", amt)
        elif ty == "transfer":
            if tid in tm:
                if amt < 0:
                    r["moved"] += -amt
                add("moved between your accounts", amt)
            else:
                r["moved_open_in" if amt > 0 else "moved_open_out"] += amt
                add("transfers, one side only", amt)
        elif ty == "card_payment":
            if tid in cm:
                if amt < 0:
                    r["cards"] += -amt
                    r["cards_matched"] += -amt
                add("card payments, both sides", amt)
            else:
                r["cards_open_in" if amt > 0 else "cards_open_out"] += amt
                r["cards"] += abs(amt)
                add("card payments, one side only", amt)
        else:
            add(ty.replace("_", " "), amt)
    r["everything"] = groups
    return r


def coverage(con, f, today):
    """Accounts that look behind: [(label, newest line on or before the period's end, account type)] where that line is
    more than STALE_DAYS before the end of the period (or before today while the period is still running). An account
    with no line at all by then is left out (nothing to be behind on). With an account chosen, only that one."""
    until = min(dt.date.fromisoformat(f["to"]), today)
    cut = (until - dt.timedelta(days=STALE_DAYS)).isoformat()
    sql = ("SELECT a.id, a.name, a.last4, a.type, MAX(t.txn_date) FROM accounts a JOIN transactions t ON t.account_id=a.id "
           "WHERE t.txn_date <= ? " + ("AND a.id=? " if f["account"] else "") + "GROUP BY a.id ORDER BY a.type='credit', a.name")
    got = con.execute(sql, (f["to"], int(f["account"])) if f["account"] else (f["to"],)).fetchall()
    return [(f"{n} x{l4 or '----'}", last, ty) for _, n, l4, ty, last in got if last < cut and ty != "investment"]


KEYS = ("from", "to", "q", "min", "max", "account", "cat", "type", "member")  # the filters a link carries (not the page)


def txn_detail(con, txn_id):
    """One line as the quick-view window shows it, or None. The account is named with its last four digits only."""
    try:
        txn_id = int(txn_id)
    except (TypeError, ValueError):
        return None
    r = con.execute(
        "SELECT t.id, t.txn_date, t.description, t.amount, COALESCE(t.category,''), COALESCE(NULLIF(t.txn_type,''),'spend'), "
        "COALESCE(t.payee,''), COALESCE(TRIM(t.cardholder),''), COALESCE(t.ref,''), t.manual, a.name, a.last4, a.type, t.document_id "
        "FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (txn_id,)).fetchone()
    if not r:
        return None
    kinds = dict(TYPES)
    return {"id": r[0], "date": r[1], "description": r[2] or "", "amount": r[3], "amount_text": M.fmt(r[3]), "cat_raw": r[4],
            "category": r[4] or "Uncategorized", "type_key": r[5], "type": kinds.get(r[5], r[5].replace("_", " ").capitalize()),
            "payee": r[6], "member": r[7], "ref": r[8], "manual": bool(r[9]), "account": f"{r[10]} x{r[11] or '----'}",
            "account_type": r[12], "document_id": r[13]}


def neighbors(con, f, txn_id, cap=20000):
    """(position starting at 1, total, previous id, next id) of a line in the filtered list (newest first, as listed);
    (None, total, None, None) when the line is not in it. Previous = the row above, next = the row below."""
    where, params = _where(f)
    ids = [r[0] for r in con.execute("SELECT t.id " + FROM + where + " ORDER BY t.txn_date DESC, t.id DESC LIMIT ?", params + [cap])]
    try:
        i = ids.index(int(txn_id))
    except (ValueError, TypeError):
        return None, len(ids), None, None
    return i + 1, len(ids), ids[i - 1] if i > 0 else None, ids[i + 1] if i + 1 < len(ids) else None


def csv_file(con, args, today):
    """(file name, CSV bytes) of EVERY line the filters match, not just the page shown. A cell that starts with = + - @ is
    quoted so a spreadsheet keeps it as text."""
    import csv
    import io
    accounts, cats, people = account_list(con), categories(con), members(con)
    f = parse(args, today, accounts, cats, people)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "account", "description", "category", "type", "amount", "card_member", "edited"])
    for r in rows(con, f, MAX_EXPORT):
        cells = [r["date"], r["account"], r["description"], r["cat_raw"], r["type"], f"{r['amount']:.2f}", r["member"],
                 "yes" if r["manual"] else ""]
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in "=+-@" and c != cells[5] else c for c in cells])
    return f"ledger_{f['from']}_{f['to']}.csv", buf.getvalue().encode("utf-8")


def _md(iso):
    d = dt.date.fromisoformat(iso)
    return f"{d:%b} {d.day}"


SUM_ROWS = (("income", "Income"), ("spending", "Spending"), ("tax", "Tax"), ("investing", "Invested"),
            ("moved between your accounts", "Between your accounts"), ("card payments, both sides", "Card payments, matched"),
            ("transfers, one side only", "Transfers, one side only"), ("card payments, one side only", "Card payments, one side only"))


def sums(S):
    """How the tiles add up to every line: [(label, in, out)] per group and the total, as text. Nothing is left out, so the
    totals are the old Money in / Money out."""
    g = S["everything"]
    rows = [(label, M.fmt(g[k][0]) if g[k][0] else "", M.fmt(g[k][1]) if g[k][1] else "") for k, label in SUM_ROWS if k in g]
    rows += [(k.capitalize(), M.fmt(v[0]) if v[0] else "", M.fmt(v[1]) if v[1] else "") for k, v in g.items() if k not in dict(SUM_ROWS)]
    return {"rows": rows, "in": M.fmt(sum(v[0] for v in g.values())), "out": M.fmt(sum(v[1] for v in g.values()))}


def _tiles(S, behind):
    """The cash-flow tiles and the short warnings under them for the whole (not type-filtered) list. A tile is (label, value,
    tone, small text). Spending, bills and investing read as positive amounts spent; Left over is income less spending and
    tax. The long explanation lives in the help panel (help_text `finance:ledger`)."""
    spent, bills, invested = -S["spending"], -S["bills"], -S["invested"]
    left = S["income"] + S["spending"] + S["tax"]
    income = S["income"]
    tiles = [("Income", M.fmt(income), "", "pay and interest" if income else "none in these dates"),
             ("Spending", M.fmt(spent), "", f"{S['spend_n']} charges"),
             ("Left over", M.fmt(left), "bad" if left < 0 else "good", "income less spending"),
             ("Bills paid", M.fmt(bills), "", "part of spending"),
             ("Invested", M.fmt(invested), "", "set aside"),
             ("Between your accounts", M.fmt(S["moved"]), "", "matched, nets to $0"),
             ("Card payments", M.fmt(S["cards"]), "", f"{M.fmt(S['cards_matched'])} matched")]
    if S["tax"]:
        tiles.append(("Tax", M.fmt(-S["tax"]), "", "net of refunds"))
    tiles.append(("Lines", S["n"], "", ""))
    notes = []
    if behind:  # also when nothing matches: an account with no lines in these dates is the very case to explain
        main = [b for b in behind if b[2] in ("checking", "credit")]
        rest = len(behind) - len(main)
        late = [f"{lbl} ({_md(last)})" for lbl, last, _ in main[:5]]
        late += [f"{len(main) - 5} more"] if len(main) > 5 else []
        late += [f"{rest} savings or other account{'' if rest == 1 else 's'}"] if rest else []
        notes.append(("warn", "Not up to date: " + ", ".join(late) + (". Add its latest statement." if len(behind) == 1 else ". Add their latest statements.")))
    if not S["n"]:
        return tiles, notes
    if not income and S["spending"]:
        notes.append(("warn", "No pay in these dates."))
    if S["card_spend"]:
        months = ", ".join(dt.date(int(m[:4]), int(m[5:7]), 1).strftime("%B %Y") for m in sorted(S["card_spend_months"]))
        notes.append(("info", f"Card payments of {M.fmt(S['card_spend'])} count as spending: no card statement is filed for "
                              f"{months}. Add the card's statement and its own lines count instead."))
    one = []
    if S["moved_open_out"] or S["moved_open_in"]:
        one.append(f"transfers {M.fmt(S['moved_open_out'] + S['moved_open_in'])}")
    if S["cards_open_in"]:
        one.append(f"{M.fmt(S['cards_open_in'])} paid onto cards with no bank line")
    if S["cards_open_out"]:
        one.append(f"{M.fmt(-S['cards_open_out'])} paid from a bank with no card line")
    if one:
        notes.append(("warn", "Other side not loaded: " + "; ".join(one) + "."))
    return tiles, notes


def type_chips(con, f, base):
    """[(label, lines, total, link, on)] one per kind of line in these dates (every other filter kept, Type left out)."""
    where, params = _where({**f, "type": ""})
    got = {k: (n, tot) for k, n, tot in con.execute(
        "SELECT COALESCE(NULLIF(t.txn_type,''),'spend'), COUNT(*), COALESCE(SUM(t.amount),0) " + FROM + where + " GROUP BY 1", params)}
    keep = {k: v for k, v in base.items() if k != "type"}
    link = lambda kind: "/money?" + urllib.parse.urlencode({"part": "ledger", **keep, **({"type": kind} if kind else {})})
    labels = dict(TYPES)
    out = [("All", sum(n for n, _ in got.values()), "", link(""), not f["type"])]
    for k in [k for k, _ in TYPES] + sorted(set(got) - set(labels)):
        if k in got:
            out.append((labels.get(k, k.replace("_", " ").capitalize()), got[k][0], M.fmt(got[k][1]), link(k), f["type"] == k))
    return out


def ledger(con, args, today, fd):
    """The Ledger view. `fd` is finance_data (date and money formatting), passed in so this module stays free of it."""
    accounts, cats, people = account_list(con), categories(con), members(con)
    f = parse(args, today, accounts, cats, people)
    n, money_in, money_out = totals(con, f)
    pages = max(1, -(-n // PAGE))
    f["page"] = min(f["page"], pages)
    got = rows(con, f, PAGE, (f["page"] - 1) * PAGE)
    tm, cm = pairs(con, "transfer", f["from"], f["to"]), pairs(con, "card_payment", f["from"], f["to"])
    kinds = dict(TYPES)
    for r in got:
        r["type_key"] = r["type"]
        r["type"] = kinds.get(r["type"], r["type"].replace("_", " ").capitalize())
        r["amount_text"] = M.fmt(r["amount"])
        r["date"] = fd.short_date(r["date"], today)
        shared = tm if r["type_key"] == "transfer" else cm if r["type_key"] == "card_payment" else None
        r["pair"] = "" if shared is None else "matched" if r["id"] in shared else "open"
    S = summary(con, f, tm, cm)
    base = {k: v for k, v in (("from", f["from"]), ("to", f["to"]), ("q", f["q"]), ("min", f["min"]), ("max", f["max"]),
                              ("account", f["account"]), ("cat", f["cat"]), ("type", f["type"]), ("member", f["member"])) if v not in ("", None)}
    if f["type"]:  # one kind of line: plain in / out / net of exactly this list
        tiles = [("In", M.fmt(money_in), ""), ("Out", M.fmt(money_out), ""), ("Total", M.fmt(money_in + money_out), ""), ("Lines", n, "")]
        notes = []
    else:
        tiles, notes = _tiles(S, coverage(con, f, today))
    filters = {"ledger": True, "from": f["from"], "to": f["to"], "period": f["period"], "periods": PERIODS, "q": f["q"],
               "min": "" if f["min"] is None else f["min"], "max": "" if f["max"] is None else f["max"],
               "account": f["account"], "accounts": accounts, "cat": f["cat"], "cats": cats, "none": NONE,
               "type": f["type"], "types": TYPES, "member": f["member"], "members": people, "page": f["page"], "pages": pages, "today": today.isoformat(),
               "search": "Description, payee, category or card member", "base": base}
    blocks = []
    where, params = _where(f)
    who = con.execute("SELECT COALESCE(NULLIF(TRIM(t.cardholder),''), 'Not named'), "
                      "-SUM(CAST(ROUND(t.amount*100) AS INTEGER)) " + FROM + where +
                      " AND COALESCE(NULLIF(t.txn_type,''),'spend') IN (" + ",".join("?" * len(SPEND_TYPES)) + ")"
                      " GROUP BY 1 ORDER BY 2 DESC", params + list(SPEND_TYPES)).fetchall()
    if any(name != "Not named" for name, _c in who):  # what Money > Cards showed: spending per card member
        blocks.append(fd.block("By card member", [{"card_member": name, "spent": round(c / 100, 2)} for name, c in who], "",
                               money=("spent",), fold=True))
    rules = None
    if f["cat"] == NONE:  # Uncategorized: name a card merchant's category once (the form Money > Cards had)
        card = f["account"] if f["account"] and con.execute("SELECT 1 FROM accounts WHERE id=? AND type='credit'",
                                                             (int(f["account"]),)).fetchone() else ""
        merchants = fd._uncategorized(con, card)
        if merchants:
            rules = {"merchants": merchants, "cats": fd._categories(con), "back": "ledger"}
    return {"tiles": tiles, "notes": notes, "filters": filters, "blocks": blocks, "rules": rules,
            "ledger": {"rows": got, "n": n, "chips": type_chips(con, f, base), "sums": None if f["type"] else sums(S), "qs": urllib.parse.urlencode(base), "cats": cats, "types": TYPES, "members": people, "back": {**base, "page": f["page"]},
                       "empty": "Nothing matches these filters."}}
