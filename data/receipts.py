"""Receipts matched to card and bank charges (table receipts, migration 032). No AI here: the merchant, date and total
come from intake (an e-receipt PDF read by the family's AI), the dashboard review form (a photo: a person types them),
or the command line.

  python data/receipts.py add "<merchant>" DATE TOTAL [--last4 NNNN] [--note T]
  python data/receipts.py match                     match every open receipt (also runs after each statement import)
  python data/receipts.py list [--open]
  python data/receipts.py candidates ID             charges that could belong to receipt ID
  python data/receipts.py link ID TXN_ID            link by hand (the matcher never changes it)
  python data/receipts.py unlink ID                 undo a link; the matcher leaves this receipt alone afterwards
  python data/receipts.py ignore ID                 no charge expected (cash, gift card, refunded)

Matching (a charge is a transaction with amount < 0, not already linked to another receipt):
  high    the same amount to the cent, posted -1..+5 days from the receipt date, and a merchant word in the description
  medium  the same amount and dates, no merchant word, and it is the only such charge
  low     the charge is 0-30% more than the receipt (a tip added later), dates -1..+5, a merchant word: "possible tip"
Several equally good charges: none is picked (the note says how many); link by hand.
"""
import argparse
import datetime as dt
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import db  # noqa: E402
import money as _money  # noqa: E402
import validators as v  # noqa: E402

DB = paths.DB
BEFORE, AFTER, TIP = 1, 5, 0.30
STOP = {"the", "and", "inc", "llc", "co", "corp", "store", "stores", "shop", "market", "com", "www", "pos", "purchase",
        "debit", "card", "payment", "of", "at", "to", "on", "sq", "tst", "sp", "paypal", "usa", "us"}


def _d(s):
    return dt.date.fromisoformat(str(s)[:10])


def _rows(con, sql, params=()):
    cur = con.cursor()
    cur.row_factory = sqlite3.Row
    return [dict(r) for r in cur.execute(sql, params)]


def words(s):
    """Merchant words worth comparing: lower case, 3+ letters, no filler ('the', 'store', 'pos', ...)."""
    return {w for w in re.findall(r"[a-z]{3,}", (s or "").lower()) if w not in STOP}


def add(con, merchant, date, total, last4=None, document_id=None, note=None):
    merchant = v.text(80)(merchant)
    date = v.iso_date(date)
    total = v.money(0.01, 1e7)(total)
    if last4 not in (None, ""):
        last4 = str(last4).strip()
        if not re.fullmatch(r"\d{4}", last4):
            raise ValueError("card: the last four digits only")
    else:
        last4 = None
    note = v.text(200)(note) if note else None
    cur = con.execute("INSERT INTO receipts(document_id, merchant, receipt_date, total, card_last4, notes, created_at) "
                      "VALUES (?,?,?,?,?,?,?)", (document_id, merchant, date, total, last4, note,
                                                 dt.datetime.now().isoformat(timespec="seconds")))
    rid = cur.lastrowid
    match(con, rid)
    return rid


def get(con, rid):
    r = _rows(con, "SELECT * FROM receipts WHERE id=?", (int(rid),))
    if not r:
        raise ValueError(f"no receipt {rid}")
    return r[0]


def candidates(con, r):
    """[(txn dict, confidence, note)] best first, for receipt dict r. Charges linked to another receipt are left out."""
    d0 = _d(r["receipt_date"])
    lo, hi = (d0 - dt.timedelta(days=BEFORE)).isoformat(), (d0 + dt.timedelta(days=AFTER)).isoformat()
    sql = ("SELECT t.id, t.txn_date, t.description, t.payee, t.amount, a.name AS account, a.last4 FROM transactions t "
           "LEFT JOIN accounts a ON a.id=t.account_id WHERE t.amount < 0 AND t.txn_date BETWEEN ? AND ? "
           "AND t.id NOT IN (SELECT transaction_id FROM receipts WHERE transaction_id IS NOT NULL AND id<>?)")
    params = [lo, hi, r["id"]]
    if r.get("card_last4"):
        sql += " AND (a.last4 IS NULL OR a.last4=?)"
        params.append(r["card_last4"])
    want = _money.cents(r["total"])
    mw = words(r["merchant"])
    out = []
    for t in _rows(con, sql, params):
        got = -_money.cents(t["amount"])
        hit = bool(mw & words(f"{t['description']} {t.get('payee') or ''}"))
        days = abs((_d(t["txn_date"]) - d0).days)
        if got == want:
            out.append((t, "high" if hit else "medium", ("merchant and amount" if hit else "same amount") + f", {days} day(s) apart", days))
        elif hit and want < got <= round(want * (1 + TIP)):
            out.append((t, "low", f"possible tip: charge {_money.fmt(-t['amount'])} vs receipt {_money.fmt(r['total'])}", days))
    rank = {"high": 0, "medium": 1, "low": 2}
    out.sort(key=lambda x: (rank[x[1]], x[3], x[0]["id"]))
    return [(t, c, n) for t, c, n, _ in out]


def match(con, rid=None):
    """Link open receipts (auto=1, not linked) to their charge. Returns how many were linked."""
    sql = "SELECT * FROM receipts WHERE transaction_id IS NULL AND auto=1 AND status='open'"
    todo = _rows(con, sql + (" AND id=?" if rid else "") + " ORDER BY receipt_date, id", (int(rid),) if rid else ())
    n = 0
    for r in todo:
        cand = candidates(con, r)
        if not cand:
            con.execute("UPDATE receipts SET match_confidence='none', match_note=? WHERE id=?",
                        ("no charge yet (it may post after the next statement)", r["id"]))
            continue
        best = cand[0][1]
        same = [c for c in cand if c[1] == best]
        if best == "medium" and len(same) > 1 or best == "high" and len(same) > 1 and len({c[0]["txn_date"] for c in same}) == 1:
            con.execute("UPDATE receipts SET match_confidence='none', match_note=? WHERE id=?",
                        (f"{len(same)} charges fit equally; link by hand", r["id"]))
            continue
        t, conf, note = cand[0]
        con.execute("UPDATE receipts SET transaction_id=?, match_confidence=?, match_note=?, status='matched' WHERE id=?",
                    (t["id"], conf, note, r["id"]))
        n += 1
    return n


def link(con, rid, txn_id):
    r = get(con, rid)
    t = _rows(con, "SELECT id, amount FROM transactions WHERE id=?", (int(txn_id),))
    if not t:
        raise ValueError(f"no transaction {txn_id}")
    other = con.execute("SELECT id FROM receipts WHERE transaction_id=? AND id<>?", (int(txn_id), r["id"])).fetchone()
    if other:
        raise ValueError(f"that charge is already linked to receipt {other[0]}")
    con.execute("UPDATE receipts SET transaction_id=?, match_confidence='manual', match_note='linked by hand', auto=0, "
                "status='matched' WHERE id=?", (int(txn_id), r["id"]))
    return r["id"]


def unlink(con, rid):
    r = get(con, rid)
    con.execute("UPDATE receipts SET transaction_id=NULL, match_confidence='none', match_note='unlinked by hand', auto=0, "
                "status='open' WHERE id=?", (r["id"],))
    return r["id"]


def ignore(con, rid):
    r = get(con, rid)
    con.execute("UPDATE receipts SET transaction_id=NULL, match_confidence='none', match_note='no charge expected', auto=0, "
                "status='ignored' WHERE id=?", (r["id"],))
    return r["id"]


def rows(con, status=None):
    sql = ("SELECT r.*, t.txn_date, t.description AS charge, t.amount AS charge_amount, a.name AS account "
           "FROM receipts r LEFT JOIN transactions t ON t.id=r.transaction_id LEFT JOIN accounts a ON a.id=t.account_id")
    if status:
        sql += " WHERE r.status=?"
    return _rows(con, sql + " ORDER BY r.receipt_date DESC, r.id DESC", (status,) if status else ())


def summary(con):
    try:
        c = dict(con.execute("SELECT status, COUNT(*) FROM receipts GROUP BY status").fetchall())
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return {}
    return {"open": c.get("open", 0), "matched": c.get("matched", 0), "ignored": c.get("ignored", 0)}


def match_after_import(con):
    """Called by the statement importers; silent when the receipts table does not exist yet."""
    try:
        return match(con)
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="receipts matched to charges")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add")
    p.add_argument("merchant"), p.add_argument("date"), p.add_argument("total"), p.add_argument("--last4"), p.add_argument("--note")
    sub.add_parser("match")
    p = sub.add_parser("list")
    p.add_argument("--open", action="store_true")
    for name in ("candidates", "unlink", "ignore"):
        sub.add_parser(name).add_argument("id")
    p = sub.add_parser("link")
    p.add_argument("id"), p.add_argument("txn")
    a = ap.parse_args(argv)
    con = db.connect(DB)
    try:
        with con:
            if a.cmd == "add":
                rid = add(con, a.merchant, a.date, a.total, a.last4, note=a.note)
                r = get(con, rid)
                print(f"receipt {rid}: " + (f"matched ({r['match_confidence']}) to transaction {r['transaction_id']}: {r['match_note']}"
                                            if r["transaction_id"] else r["match_note"] or "open"))
            elif a.cmd == "match":
                print(f"{match(con)} receipt(s) linked; {summary(con).get('open', 0)} still open")
            elif a.cmd == "list":
                for r in rows(con, "open" if a.open else None):
                    ch = f" -> {r['txn_date']} {r['charge']} {_money.fmt(-r['charge_amount'])} ({r['match_confidence']})" if r["transaction_id"] else ""
                    print(f"{r['id']}: {r['receipt_date']} {r['merchant']} {_money.fmt(r['total'])} [{r['status']}]{ch}"
                          + (f"  {r['match_note']}" if not r["transaction_id"] and r["match_note"] else ""))
            elif a.cmd == "candidates":
                r = get(con, a.id)
                cs = candidates(con, r)
                for t, c, n in cs:
                    print(f"  txn {t['id']}: {t['txn_date']} {t['description']} {_money.fmt(-t['amount'])} ({t['account'] or '?'})  {c}: {n}")
                print(f"{len(cs)} candidate(s) for receipt {r['id']} ({r['merchant']} {_money.fmt(r['total'])} on {r['receipt_date']})")
            elif a.cmd == "link":
                print(f"receipt {link(con, a.id, a.txn)} linked to transaction {a.txn}")
            elif a.cmd == "unlink":
                print(f"receipt {unlink(con, a.id)} unlinked")
            elif a.cmd == "ignore":
                print(f"receipt {ignore(con, a.id)} marked: no charge expected")
    except ValueError as e:
        raise SystemExit(f"error: {e}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
