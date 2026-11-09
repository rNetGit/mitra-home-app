"""Match amazon_orders to Amazon/AMZN card charges in `transactions` (read-only on transactions).
Usage: python data/amazon_match.py run|report
Rules: order total > 0 and status not refunded/cancelled/returned; charge amount (negative = spend) equals the
total within $0.01 and txn_date is -1..+10 days from the order date. Orders split into several charges are
matched when two or three charges within the window sum to the total (confidence 'medium', transaction_id = first).
Unmatched Amazon charges are Prime fees, Kindle/Audible, Fresh/Whole Foods, refunds, or orders missing from the PDFs.
"""
import sqlite3
import config  # optional pack: config/family.json packs.amazon
import sys
from datetime import date, timedelta
from itertools import combinations
import db  # noqa: E402
import money as _money
from money import fmt as _fmt  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
AMZ = "(UPPER(t.description) LIKE '%AMAZON%' OR UPPER(t.description) LIKE '%AMZN%' OR UPPER(COALESCE(t.payee,'')) LIKE '%AMAZON%')"


def _con(con=None):
    if con is None:
        con = db.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def _iso(s):
    return date.fromisoformat(s)


def amazon_txns(con):
    return con.execute(f"SELECT t.* FROM transactions t WHERE {AMZ} ORDER BY t.txn_date, t.id").fetchall()


def run(con=None):
    con = _con(con)
    txns = [t for t in amazon_txns(con) if t["amount"] < 0]
    used, results = set(), []
    orders = con.execute("SELECT * FROM amazon_orders ORDER BY order_date, id").fetchall()
    for o in orders:
        if o["total"] <= 0:
            res = (None, "none", "$0 order (nothing charged)")
        elif o["status"] in ("refunded", "returned", "cancelled"):
            res = (None, "none", f"{o['status']}: refunded orders may still show an original charge, not matched")
        else:
            d0 = _iso(o["order_date"])
            cand = [t for t in txns if t["id"] not in used
                    and d0 - timedelta(days=1) <= _iso(t["txn_date"]) <= d0 + timedelta(days=10)]
            exact = [t for t in cand if _money.eq(-t["amount"], o["total"])]
            if exact:
                exact.sort(key=lambda t: abs((_iso(t["txn_date"]) - d0).days))
                t = exact[0]
                conf = "high" if len(exact) == 1 else "medium"
                res = (t["id"], conf, f"charge {t['txn_date']} {_fmt(-t['amount'])}" + ("; several equal candidates" if len(exact) > 1 else ""))
            else:
                res = (None, "none", "no charge of this amount within -1..+10 days")
                for n in (2, 3):
                    hit = next((c for c in combinations(cand, n)
                                if _money.eq(_money.total(-t["amount"] for t in c), o["total"])), None)
                    if hit:
                        res = (hit[0]["id"], "medium", f"split into {n} charges: " +
                               ", ".join(f"{t['txn_date']} {_fmt(-t['amount'])}" for t in hit))
                        used.update(t["id"] for t in hit[1:])
                        break
            if res[0]:
                used.add(res[0])
        con.execute("UPDATE amazon_orders SET transaction_id=?, match_confidence=?, match_note=? WHERE id=?",
                    (res[0], res[1], res[2], o["id"]))
        results.append((o, res))
    con.commit()
    return results


def rows(con, today=None):
    if not config.pack("amazon"):
        return []
    """List of dicts for the dashboard, newest first."""
    con = _con(con)
    out = []
    q = """SELECT o.*, a.name AS acct_name, a.last4 AS acct_last4, t.cardholder AS cardholder, t.txn_date AS txn_date
           FROM amazon_orders o LEFT JOIN transactions t ON t.id=o.transaction_id
           LEFT JOIN accounts a ON a.id=t.account_id ORDER BY o.order_date DESC, o.id DESC"""
    for r in con.execute(q):
        out.append(dict(id=r["id"], order_date=r["order_date"], order_no=r["order_no"], total=r["total"], items=r["items"],
                        status=r["status"], matched=r["transaction_id"] is not None,
                        card=(f"{r['acct_name']} x{r['acct_last4']}" if r["acct_name"] else None),
                        cardholder=r["cardholder"], txn_date=r["txn_date"],
                        match_confidence=r["match_confidence"], match_note=r["match_note"]))
    return out


def unmatched_charges(con):
    con = _con(con)
    return con.execute(f"""SELECT t.id, t.txn_date, t.amount, t.description, t.cardholder, a.name AS acct_name, a.last4
        FROM transactions t LEFT JOIN accounts a ON a.id=t.account_id
        WHERE {AMZ} AND t.id NOT IN (SELECT transaction_id FROM amazon_orders WHERE transaction_id IS NOT NULL)
        ORDER BY t.txn_date""").fetchall()


def summary(con):
    if not config.pack("amazon"):
        return {}
    con = _con(con)
    o = con.execute("SELECT * FROM amazon_orders").fetchall()
    payable = [r for r in o if r["total"] > 0 and r["status"] not in ("refunded", "returned", "cancelled")]
    matched = [r for r in payable if r["transaction_id"]]
    um_o = [r for r in payable if not r["transaction_id"]]
    um_t = unmatched_charges(con)
    return dict(
        orders=len(o), orders_total=round(sum(r["total"] for r in o), 2),
        payable=len(payable), matched=len(matched),
        matched_pct=round(100 * len(matched) / len(payable)) if payable else None,
        unmatched_orders=len(um_o), unmatched_order_amount=round(sum(r["total"] for r in um_o), 2),
        unmatched_charges=sum(1 for t in um_t if t["amount"] < 0),
        unmatched_charge_amount=round(-sum(t["amount"] for t in um_t if t["amount"] < 0), 2))


def report(con=None):
    con = _con(con)
    s = summary(con)
    print(f"Amazon orders: {s['orders']} ({_fmt(s['orders_total'])}); chargeable {s['payable']}, matched {s['matched']} ({s['matched_pct']}%)")
    print(f"Unmatched orders: {s['unmatched_orders']} ({_fmt(s['unmatched_order_amount'])}); "
          f"unmatched Amazon charges: {s['unmatched_charges']} ({_fmt(s['unmatched_charge_amount'])})")
    print("\nOrders:")
    for r in rows(con):
        tag = f"-> {r['card']} {r['txn_date']} [{r['match_confidence']}]" if r["matched"] else f"UNMATCHED ({r['match_note']})"
        print(f"  {r['order_date']} ${r['total']:>7.2f} {r['status']:<9} {(r['items'] or '')[:40]:<40} {tag}")
    print("\nAmazon charges with no order (Prime, Kindle, Audible, Fresh, refunds, missing orders):")
    for t in unmatched_charges(con):
        print(f"  {t['txn_date']} {t['amount']:>8.2f} {t['description'][:48]:<48} {t['acct_name']} x{t['last4']} {t['cardholder'] or ''}")
    prime = [t for t in unmatched_charges(con) if "PRIME" in (t["description"] or "").upper()]
    if prime:
        print("\nPrime membership charges:")
        for t in prime:
            print(f"  {t['txn_date']} {t['amount']:>8.2f} {t['acct_name']} x{t['last4']} {t['cardholder'] or ''}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    c = _con()
    if cmd == "run":
        run(c)
    report(c)
