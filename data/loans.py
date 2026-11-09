"""Loans: mortgage, auto, student, personal, HELOC.

  python data/loans.py list
  python data/loans.py add "<name>" --kind mortgage|auto|student|personal|heloc|other [--lender T] [--last4 NNNN]
                           [--balance N] [--rate PCT] [--payment N] [--day D] [--start D] [--payoff D] [--notes T]
  python data/loans.py set "<name fragment>" [--balance N] [--rate PCT] [--payment N] [--payoff D] [--status paid_off]
  python data/loans.py summary
Balances are what the user reports from statements (record the date). Account number: last4 only.
Library: rows(con, today), alerts(con, today) (payoff date in the next 12 months), payoff_plan(balance, rate, payment)
(what paying 50, 100 or 250 more a month does to the payoff date and the interest; arithmetic, not advice).
"""
import argparse
import datetime as dt
import sqlite3
import db  # noqa: E402
import dates  # noqa: E402
from dates import parse as _d  # noqa: E402

import paths  # noqa: E402
DB = paths.DB


def rows(con, today=None):
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute("SELECT * FROM loans WHERE status='active' ORDER BY kind, name")]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def months_left(balance, rate_pct, payment):
    """Whole months to pay off at the stated rate and payment; None if the payment never covers interest."""
    if not balance or not payment:
        return None
    r = (rate_pct or 0) / 100 / 12
    if r == 0:
        return int(-(-balance // payment))
    if payment <= balance * r:
        return None
    import math
    return int(math.ceil(-math.log(1 - balance * r / payment) / math.log(1 + r)))


EXTRAS = (0, 50, 100, 250)  # extra a month shown on Money > Keep > Budget and loans
MAX_MONTHS = 600


def payoff(balance, rate_pct, payment):
    """(months, total interest) paying `payment` a month at `rate_pct` a year, interest monthly; None when the payment
    never covers the interest (or 50 years are not enough)."""
    if not balance or not payment or balance <= 0 or payment <= 0:
        return None
    r = (rate_pct or 0) / 100 / 12
    left, interest = float(balance), 0.0
    for month in range(1, MAX_MONTHS + 1):
        i = left * r
        if payment <= i:
            return None
        interest += i
        left = left + i - payment
        if left <= 0.005:
            return month, round(interest, 2)
    return None


def payoff_plan(balance, rate_pct, payment, extras=EXTRAS, today=None):
    """What paying more each month does: [{"extra", "months", "paid_off" (date), "interest", "months_sooner",
    "interest_saved"}] for each extra amount, against the payment as it is (extra 0). Arithmetic only."""
    today = today or dates.today()
    base = payoff(balance, rate_pct, payment)
    out = []
    for extra in extras:
        got = payoff(balance, rate_pct, (payment or 0) + extra)
        if got is None:
            continue
        months, interest = got
        y, m = divmod(today.month - 1 + months, 12)
        out.append({"extra": extra, "months": months, "paid_off": dt.date(today.year + y, m + 1, 1), "interest": interest,
                    "months_sooner": base[0] - months if base else None,
                    "interest_saved": round(base[1] - interest, 2) if base else None})
    return out


def alerts(con, today):
    out = []
    for r in rows(con):
        d = _d(r["payoff_date"])
        if d and today <= d <= today + dt.timedelta(days=365):
            out.append({"date": d, "kind": "Loan", "title": f"{r['name']} scheduled payoff",
                        "detail": "Confirm final payment, lien release / title or mortgage satisfaction", "amount": r["balance"],
                        "ref": ("loans", r["id"])})
    return out


def summary(con):
    ls = rows(con)
    return {"count": len(ls), "debt": sum(r["balance"] or 0 for r in ls), "monthly": sum(r["payment"] or 0 for r in ls)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "add", "set", "summary"])
    ap.add_argument("name", nargs="?")
    for f in ("kind", "lender", "last4", "start", "payoff", "notes", "status"):
        ap.add_argument(f"--{f}")
    for f in ("balance", "rate", "payment"):
        ap.add_argument(f"--{f}", type=float)
    ap.add_argument("--day", type=int)
    a = ap.parse_args()
    con = db.connect(DB)
    if a.cmd == "add" and a.name:
        con.execute("INSERT INTO loans(name, lender, kind, last4, balance, balance_date, rate_pct, payment, payment_day, "
                    "start_date, payoff_date, notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (a.name, a.lender, a.kind, a.last4, a.balance, dates.today().isoformat() if a.balance else None,
                     a.rate, a.payment, a.day, a.start, a.payoff, a.notes))
        con.commit()
    elif a.cmd == "set" and a.name:
        r = con.execute("SELECT id FROM loans WHERE LOWER(name) LIKE ?", (f"%{a.name.lower()}%",)).fetchall()
        if len(r) != 1:
            raise SystemExit(f"{len(r)} matches")
        for col, val in (("balance", a.balance), ("rate_pct", a.rate), ("payment", a.payment),
                         ("payoff_date", a.payoff), ("status", a.status), ("notes", a.notes)):
            if val is not None:
                con.execute(f"UPDATE loans SET {col}=? WHERE id=?", (val, r[0][0]))
        if a.balance is not None:
            con.execute("UPDATE loans SET balance_date=? WHERE id=?", (dates.today().isoformat(), r[0][0]))
        con.commit()
    if a.cmd == "summary":
        print(summary(con))
    for r in rows(con):
        ml = months_left(r["balance"], r["rate_pct"], r["payment"])
        print(f"{r['name']:<24} {r['kind'] or '':<9} bal {r['balance'] or '?'}  rate {r['rate_pct'] or '?'}%  "
              f"pay {r['payment'] or '?'}  ~{ml if ml is not None else '?'} months left")


if __name__ == "__main__":
    main()
