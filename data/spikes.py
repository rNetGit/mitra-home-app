"""Price-change and bill-spike alerts (subscriptions are excluded; data/subscriptions.py covers those).

  python data/spikes.py          readable table of all spikes found (all history) + what alerts() would raise

Sources: (a) `bills` paid history per vendor, (b) `transactions` typed utility/insurance (per payee),
(c) policy premium step-ups via v_policy_premium_history. Bill and bank rows for the same payment are merged
(same vendor, amount within $0.01, dates within 10 days) so a payment is counted once.
Rule: latest charge >= 20% (>= $10) above the median of the prior up-to-6 charges (needs 3+ prior).
Seasonal utilities (electric/gas/water) use 35% against the trailing median and also report year-over-year
for the same month when a charge ~12 months earlier exists (label "YoY").
Policies: premium up >= 8% and >= $50 over the prior term.
alerts(con, today) -> items shaped like action_items.collect_items entries, for spikes in the last 45 days.
"""
import datetime as dt
import re
import statistics
import pathlib
import db  # noqa: E402
import dates  # noqa: E402
from money import fmt as _fmt  # noqa: E402
from dates import parse as _pd  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
PCT, MIN_ABS, SEASONAL_PCT, MIN_PRIOR, WINDOW = 20.0, 10.0, 35.0, 3, 45
SEASONAL = ("electric", "gas", "grid", "water", "oil", "propane", "fuel")
TYPES = ("utility", "insurance")


def _norm(name):
    n = re.sub(r"\bx?\d{4}\b", "", (name or "")).lower()
    n = re.sub(r"[^a-z& ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _seasonal(name):
    n = (name or "").lower()
    return any(k in n for k in SEASONAL)


def _series(con):
    """{display name: sorted [(date, amount)]} merged from bills and transactions."""
    ser = {}
    for name, vendor, amt, due, paid in con.execute(
            "SELECT name, vendor, amount, due_date, paid_date FROM bills WHERE status='paid' AND amount > 0"):
        if (name or "").lower().startswith(("credit card payment", "cancel")):
            continue
        key = vendor or name
        try:
            d = dt.date.fromisoformat(str(due or paid)[:10])
        except (ValueError, TypeError):
            continue  # a bill with a malformed date must not break the whole view
        ser.setdefault(key, []).append((d, float(amt), name))
    for payee, amt, d in con.execute(  # same payee + same day summed (e.g. two Prudential policies)
            "SELECT payee, SUM(-amount), txn_date FROM transactions "
            f"WHERE txn_type IN ({','.join('?' * len(TYPES))}) AND amount < 0 AND payee IS NOT NULL "
            "GROUP BY payee, txn_date", TYPES):
        if _pd(d):
            ser.setdefault(payee, []).append((_pd(d), float(amt), payee))
    out = {}
    for key, rows in ser.items():
        rows.sort()
        merged = []
        for d, a, label in rows:  # drop bank/bill duplicates of the same payment
            if any(abs(a - ma) < 0.01 and abs((d - md).days) <= 10 for md, ma, _ in merged):
                continue
            merged.append((d, a, label))
        out[key] = merged
    return out


def _check(name, rows, seasonal):
    if len(rows) < MIN_PRIOR + 1:
        return None
    d, latest, _ = rows[-1]
    prior = [a for _, a, _ in rows[-7:-1]]
    base = statistics.median(prior)
    if base <= 0:
        return None
    pct = 100 * (latest - base) / base
    need = SEASONAL_PCT if seasonal else PCT
    hits = []
    if pct >= need and latest - base >= MIN_ABS:
        hits.append(("trailing", base, pct))
    if seasonal:
        for pd_, pa, _ in rows[:-1]:
            if 335 <= (d - pd_).days <= 395 and pa > 0:
                yp = 100 * (latest - pa) / pa
                if yp >= PCT and latest - pa >= MIN_ABS:
                    hits.append(("YoY", pa, yp))
    return d, latest, hits


def spikes(con, today=None):
    today = today or dates.today()
    out = []
    for name, rows in _series(con).items():
        rows = [r for r in rows if r[0] <= today]
        sea = _seasonal(name) or any(_seasonal(r[2]) for r in rows[-3:])
        res = _check(name, rows, sea)
        if not res or not res[2]:
            continue
        d, latest, hits = res
        # a utility bill is a "Bill spike"; fixed-ish insurance/phone/internet increases are "Price change"
        kind = "Bill spike" if sea else "Price change"
        for how, base, pct in hits:
            lab = "same month last year" if how == "YoY" else "median of prior charges"
            note = " (seasonal; compare year over year)" if sea and how == "trailing" else ""
            out.append({"kind": kind, "name": name + (" (YoY)" if how == "YoY" else ""), "date": d,
                        "latest": round(latest, 2), "baseline": round(base, 2), "pct": round(pct, 1),
                        "detail": f"{_fmt(latest)} vs {_fmt(base)} {lab}, +{pct:.0f}%{note}"})
    for r in con.execute("SELECT kind, carrier, policy_last4, term_start, premium_total, prior_premium, change_abs, "
                         "change_pct FROM v_policy_premium_history WHERE change_pct >= 8 AND change_abs >= 50"):
        kind, carrier, l4, ts, prem, prior, ab, pct = r
        out.append({"kind": "Price change", "name": f"{carrier} {kind} policy x{l4}", "date": dt.date.fromisoformat(ts),
                    "latest": prem, "baseline": prior, "pct": pct,
                    "detail": f"premium {_fmt(prem, 0)} vs {_fmt(prior, 0)} prior term, +{_fmt(ab, 0)} (+{pct:.1f}%)"})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out


def alerts(con, today):
    items = []
    for s in spikes(con, today):
        age = (today - s["date"]).days
        lo = -30 if "policy" in s["name"] else 0  # new policy terms are known up to 30 days ahead
        if lo <= age <= WINDOW:
            items.append({"date": s["date"], "kind": "Spike", "title": f"{s['kind']}: {s['name']}",
                          "detail": s["detail"], "amount": s["latest"]})
    return items


if __name__ == "__main__":
    con = db.connect(paths.DB)
    today = dates.today()
    rows = spikes(con, today)
    if not rows:
        print("No spikes found.")
    for s in rows:
        print(f"{s['date']}  {s['kind']:<12} {s['name'][:38]:<38} ${s['latest']:>9,.2f} vs ${s['baseline']:>9,.2f} "
              f"{s['pct']:>+6.1f}%  {s['detail']}")
    al = alerts(con, today)
    print(f"\n{len(al)} alert(s) in the last {WINDOW} days (as of {today}):")
    for a in al:
        print(f"  {a['date']}  {a['title']}  -- {a['detail']}")
