"""Card benefit tracker: was each periodic statement credit received, and is it still available this period?

  python data/benefits.py          prints period-by-period status
Periods: reset_basis 'statement' uses the card's billing cycles (table statement_cycles; cycles after the last known one are
estimated as previous close + 1 month) and 'calendar_month' uses calendar months.
States: credited | spent, no credit (purchase seen but no credit line: check enrollment) | unused (period over, credit lost)
| open (current period, still available). 'Since' = first period a credit was actually received, because earlier enrollment
is unknown; earlier periods are shown as 'before first credit'.
"""
import calendar
import datetime as dt
import pathlib
import sqlite3
import db  # noqa: E402
import dates  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402


def _d(s):
    return dt.date.fromisoformat(s)


def _add_month(d):
    y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def _sum(con, aid, patterns, sign, d0, d1):
    where, params = [], []
    for p in (patterns or "").split("|"):
        if p.strip():
            where.append("UPPER(description) LIKE ?")
            params.append(p.strip().upper())
    if not where:
        return 0.0, 0
    cmp_ = "amount > 0" if sign > 0 else "amount < 0"
    return con.execute(f"SELECT COALESCE(SUM(ABS(amount)),0), COUNT(*) FROM transactions WHERE account_id=? AND {cmp_} "
                       f"AND txn_date BETWEEN ? AND ? AND ({' OR '.join(where)})", [aid, d0, d1] + params).fetchone()


def periods(con, aid, basis, today):
    """-> [(start_date, end_date, estimated)] covering the data up to and including the period that contains today."""
    out = []
    if basis == "statement":
        rows = con.execute("SELECT period_start, period_end FROM statement_cycles WHERE account_id=? ORDER BY period_start",
                           (aid,)).fetchall()
        out = [(_d(s), _d(e), False) for s, e in rows]
        if out:
            while out[-1][1] < today:  # estimate future cycles
                end = _add_month(out[-1][1])
                out.append((out[-1][1] + dt.timedelta(days=1), end, True))
            return out
    first = con.execute("SELECT MIN(txn_date) FROM transactions WHERE account_id=?", (aid,)).fetchone()[0]
    y, m = (int(first[:4]), int(first[5:7])) if first else (today.year, 1)
    while (y, m) <= (today.year, today.month):
        out.append((dt.date(y, m, 1), dt.date(y, m, calendar.monthrange(y, m)[1]), False))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def status(con, today):
    try:
        cur = con.execute("SELECT b.*, a.name AS acct, a.last4 FROM card_benefits b JOIN accounts a ON a.id=b.account_id "
                          "WHERE b.active=1")
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall():
        b = dict(zip(cols, r))
        per = []
        for s, e, est in periods(con, b["account_id"], b["reset_basis"], today):
            cr, _ = _sum(con, b["account_id"], b["credit_pattern"], +1, s.isoformat(), e.isoformat())
            sp, n = _sum(con, b["account_id"], b["qualify_pattern"], -1, s.isoformat(), e.isoformat())
            current = s <= today <= e
            state = "credited" if cr > 0 else "open" if current else "spent, no credit" if n else "unused"
            if s > today:
                continue
            per.append({"start": s, "end": e, "estimated": est, "label": f"{s:%b %d} - {e:%b %d, %Y}" + (" (est.)" if est else ""),
                        "state": state, "credit": round(cr, 2), "spend": round(sp, 2)})
        credited = [x["start"] for x in per if x["state"] == "credited"]
        since = credited[0] if credited else None
        for x in per:
            if since and x["start"] < since and x["state"] in ("unused", "spent, no credit"):
                x["state"] = "before first credit" if x["state"] == "unused" else "spent before first credit"
        after = [x for x in per if since and x["start"] >= since and x["state"] != "open"]
        lost = [x for x in after if x["state"] in ("unused", "spent, no credit")]
        cur_p = per[-1] if per else None
        b.update(periods=per, since=since, received=round(sum(x["credit"] for x in per), 2), received_n=len(credited),
                 lost_n=len(lost), lost_amount=round(len(lost) * b["amount"], 2),
                 current_open=bool(cur_p and cur_p["state"] == "open"),
                 period_start=cur_p["start"] if cur_p else None, period_end=cur_p["end"] if cur_p else None,
                 period_estimated=bool(cur_p and cur_p["estimated"]))
        out.append(b)
    return out


if __name__ == "__main__":
    con = db.connect(paths.DB, readonly=True)
    for b in status(con, dates.today()):
        print(f"{b['acct']} x{b['last4']}: {b['name']} {_fmt(b['amount'], 0)}/{b['period']} ({b['reset_basis']})  received {b['received_n']}x "
              f"({_fmt(b['received'])}), missed since first credit: {b['lost_n']} ({_fmt(b['lost_amount'])})")
        for x in b["periods"]:
            print(f"  {x['label']:<28} {x['state']:<26} credit={x['credit']:<6} qualifying spend={x['spend']}")
