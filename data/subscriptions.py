"""Track subscriptions: live status from transactions, decisions (keep/cancel), and detection of new ones.

  python data/subscriptions.py list                      tracked subscriptions with live status and cost
  python data/subscriptions.py decide "<name>" keep|cancel|cancelled|unreviewed [--note TEXT]
  python data/subscriptions.py detect                    recurring charges not yet tracked (proposals only)
  python data/subscriptions.py accept "<merchant>"       add a detected candidate (decision starts 'unreviewed')
Status is computed from `transactions` using each subscription's match_pattern / match_payee, so it stays current
as statements are loaded: last charge, price change, 'stopped?' (no charge for 1.5+ periods up to the latest
transaction on that account), estimated next charge, monthly and yearly cost.
Decisions: unreviewed -> keep (reviewed, wanted) | cancel (user wants it cancelled; dashboard shows a cancel-before date)
| cancelled (done; if charges continue after the cancel date the dashboard flags it).
"""
import datetime as dt
import pathlib
import re
import sqlite3
import statistics
import sys
import db  # noqa: E402
import dates  # noqa: E402
from money import fmt as _fmt  # noqa: E402
from dates import parse as _pd  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
EXCL = ("investment_transfer", "transfer", "income", "card_payment", "insurance", "utility", "loan_payment",
        "tax", "interest")
# shops you visit often are never offered as subscriptions (no "shopping" or "entertainment": Prime and streaming sit there)
SHOPPING = ("groceries", "dining", "fuel", "personal care", "cash withdrawal", "pets")
STEP = {"monthly": 30, "quarterly": 91, "yearly": 365}
PER_YEAR = {"monthly": 12, "quarterly": 4, "yearly": 1}


def merchant_key(payee, desc):
    if payee:
        return payee
    words = [w for w in re.sub(r"[^A-Za-z&' ]", " ", desc or "").split() if len(w) > 1]
    return " ".join(words[:2]).title() or (desc or "")[:20]


def _charges(con, pattern, payee):
    where, params = [], []
    for p in (pattern or "").split("|"):
        if p.strip():
            where.append("UPPER(t.description) LIKE ?")
            params.append(p.strip().upper())
    if payee:
        where.append("t.payee = ?")
        params.append(payee)
    if not where:
        return []
    sql = ("SELECT t.txn_date, -t.amount, a.id, a.name, a.last4, COALESCE(t.cardholder, a.owner) "
           "FROM transactions t JOIN accounts a ON a.id=t.account_id "
           f"WHERE t.amount < 0 AND ({' OR '.join(where)}) ORDER BY t.txn_date")
    return con.execute(sql, params).fetchall()


def tracked(con, today=None):
    """Tracked subscriptions with live status computed from transactions."""
    today = today or dates.today()
    con.row_factory = sqlite3.Row
    out = []
    for s in con.execute("SELECT * FROM subscriptions ORDER BY name").fetchall():
        s = dict(s)
        ch = _charges(con, s.get("match_pattern"), s.get("match_payee"))
        freq = s.get("frequency") or "monthly"
        step = STEP.get(freq, 30)
        row = {"id": s["id"], "name": s["name"], "category": s.get("category") or "", "frequency": freq,
               "decision": s.get("decision") or "unreviewed", "price_type": s.get("price_type") or "fixed",
               "notes": s.get("notes") or "", "used_by": s.get("used_by") or "", "reviewed_on": s.get("reviewed_on"),
               "tracked_active": bool(s.get("active")), "charges": len(ch), "last_date": None, "last_amount": s.get("amount"),
               "ytd": 0.0, "paid_with": "", "holder": "", "next": None, "status": "no charges found",
               "price_note": "", "per_month": 0.0, "per_year": 0.0}
        if ch:
            last = ch[-1]
            last_date = _pd(last[0]) or today
            row.update(last_date=last_date, last_amount=round(last[1], 2), paid_with=f"{last[3]} x{last[4]}",
                       holder=last[5] or "", ytd=round(sum(c[1] for c in ch if c[0].startswith(str(today.year))), 2))
            latest = con.execute("SELECT MAX(txn_date) FROM transactions WHERE account_id=?", (last[2],)).fetchone()[0]
            latest = dt.date.fromisoformat(latest) if latest else today
            row["next"] = last_date + dt.timedelta(days=step)
            row["status"] = "active" if (latest - last_date).days <= step * 1.5 else "stopped?"
            if row["price_type"] == "fixed" and len(ch) >= 2:
                prev = ch[-2][1]
                if abs(last[1] - prev) > 0.05 * max(prev, 0.01):
                    row["price_note"] = f"price changed {prev:,.2f} -> {last[1]:,.2f}"
            basis = [c[1] for c in ch[-3:]] if row["price_type"] == "variable" else [last[1]]
            amt = statistics.mean(basis)
            row["per_year"] = round(amt * PER_YEAR.get(freq, 12), 2)
            row["per_month"] = round(row["per_year"] / 12, 2)
            # cancelled: only a charge AFTER the cancel date (reviewed_on) is a problem
            if row["decision"] == "cancelled":
                rv = row["reviewed_on"]
                if rv and _pd(rv) and last_date > _pd(rv):
                    row["status"] = "STILL CHARGING after cancel"
                else:
                    row["status"] = "cancelled"
                    row["next"] = None
        out.append(row)
    return out


def _steady(amts):
    return max(amts) - min(amts) <= max(1.0, 0.12 * statistics.mean(amts))


def _one_step(amts):
    """Index where the newest steady run starts if the amounts are steady before and after exactly one change
    (the new price held for 2+ charges, 2+ before it); else None."""
    for i in range(2, len(amts) - 1):
        if _steady(amts[:i]) and _steady(amts[i:]):
            return i
    return None


def detect(con, today=None):
    """Recurring merchants not yet tracked: 3+ distinct months, steady amount, regular interval."""
    today = today or dates.today()
    groups, shops = {}, {}
    for d, desc, amt, payee, typ, cat in con.execute(
            "SELECT txn_date, description, amount, payee, txn_type, category FROM transactions WHERE amount < 0"):
        if typ in EXCL:
            continue
        key = merchant_key(payee, desc)
        if not _pd(d):
            continue
        groups.setdefault(key, []).append((_pd(d), -amt))
        shops[key] = shops.get(key, True) and (cat or "").lower() in SHOPPING
    for key in [k for k, only_shop in shops.items() if only_shop]:
        del groups[key]
    known = [r for r in con.execute("SELECT name, match_pattern, match_payee FROM subscriptions")]
    known_names = {r[0].lower() for r in known}
    tracked_hits = set()
    for _, pat, payee in known:
        for d, amt, *_ in _charges(con, pat, payee):
            tracked_hits.add((dt.date.fromisoformat(d), round(amt, 2)))
    out = []
    for m, rows in groups.items():
        rows.sort()
        if m.lower() in known_names or all((d, round(a, 2)) in tracked_hits for d, a in rows):
            continue
        months = {(d.year, d.month) for d, _ in rows}
        if len(months) < 3 or len(rows) < 3:
            continue
        amts = [a for _, a in rows]
        mean = statistics.mean(amts)
        if mean < 1:
            continue
        if (max(amts) - min(amts)) > max(1.0, 0.12 * mean):
            step = _one_step(amts)  # a price rise: steady before and after one change
            if step is None:
                continue
            amts = amts[step:]
            mean = statistics.mean(amts)
        gaps = [(b[0] - a[0]).days for a, b in zip(rows, rows[1:])]
        med = statistics.median(gaps)
        if 25 <= med <= 35:
            freq = "monthly"
        elif 85 <= med <= 95:
            freq = "quarterly"
        elif 350 <= med <= 380:
            freq = "yearly"
        else:
            continue
        out.append({"merchant": m, "frequency": freq, "amount": round(mean, 2), "charges": len(rows),
                    "last": rows[-1][0], "next": rows[-1][0] + dt.timedelta(days=STEP[freq]),
                    "per_year": round(mean * PER_YEAR[freq], 2),
                    "active": (today - rows[-1][0]).days <= STEP[freq] * 1.6})
    out.sort(key=lambda x: -x["per_year"])
    return out


def summary(rows):
    """Monthly/yearly totals for tracked, still-charging subscriptions."""
    live = [r for r in rows if r["status"] in ("active", "STILL CHARGING after cancel") and r["tracked_active"]]
    return {"count": len(live), "per_month": round(sum(r["per_month"] for r in live), 2),
            "per_year": round(sum(r["per_year"] for r in live), 2)}


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    con = db.connect(paths.DB)
    if cmd == "list":
        rows = tracked(con)
        for r in rows:
            print(f"{r['status']:<14} {r['decision']:<10} {r['name'][:26]:<26} {r['frequency']:<8} ~${r['per_month']:>7,.2f}/mo "
                  f"last={r['last_date']} next~{r['next']}  {r['paid_with'][:30]}  {r['price_note']}")
        s = summary(rows)
        print(f"\nStill charging: {s['count']} subscriptions, about {_fmt(s['per_month'])}/month, {_fmt(s['per_year'])}/year")
    elif cmd == "decide":
        if len(sys.argv) < 4:
            sys.exit('usage: decide "<name>" keep|cancel|cancelled|unreviewed [--note TEXT]')
        name, dec = sys.argv[2], sys.argv[3]
        if dec not in ("keep", "cancel", "cancelled", "unreviewed"):
            sys.exit("decision must be keep|cancel|cancelled|unreviewed")
        note = sys.argv[sys.argv.index("--note") + 1] if "--note" in sys.argv else None
        rows = con.execute("SELECT id,name FROM subscriptions WHERE name LIKE ?", (f"%{name}%",)).fetchall()
        if len(rows) != 1:
            sys.exit(f"expected exactly 1 match, got {[r[1] for r in rows]}")
        con.execute("UPDATE subscriptions SET decision=?, reviewed_on=?, notes=CASE WHEN ? IS NULL THEN notes "
                    "ELSE COALESCE(notes,'') || ' | ' || ? END WHERE id=?",
                    (dec, dates.today().isoformat(), note, note, rows[0][0]))
        con.commit()
        print("updated:", rows[0][1], "->", dec)
    elif cmd == "detect":
        for r in detect(con):
            print(f"{'ACTIVE' if r['active'] else 'stale '} {r['merchant'][:34]:34} {r['frequency']:9} "
                  f"${r['amount']:>9,.2f}  n={r['charges']:<3} last={r['last']} next~{r['next']}  ~{_fmt(r['per_year'], 0)}/yr")
    elif cmd == "accept":
        name = " ".join(sys.argv[2:])
        c = [r for r in detect(con) if r["merchant"].lower() == name.lower()]
        if not c:
            sys.exit("no such candidate (run detect)")
        r = c[0]
        con.execute("INSERT INTO subscriptions(name,amount,frequency,next_renewal,active,match_pattern,match_payee,decision) "
                    "VALUES(?,?,?,?,1,?,?, 'unreviewed')",
                    (r["merchant"], r["amount"], r["frequency"], r["next"].isoformat(), "%" + r["merchant"].upper() + "%",
                     r["merchant"]))
        con.commit()
        print("added:", r["merchant"], "(check match_pattern covers the right charges)")
    else:
        sys.exit(__doc__)
