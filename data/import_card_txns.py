"""Import card transactions into data/family.db from a normalized CSV (idempotent).

CSV columns: date (YYYY-MM-DD), description, amount (negative = purchase, positive = payment/refund),
             optional: cardholder, category, ref
Usage: python data/import_card_txns.py <csv> --last4 8926 [--document-id N] [--dry-run]
Dedupe: exact on (account, ref) when ref given; otherwise by COUNT of identical
(date, description, amount) rows already stored vs in the file (identical same-day charges are legit); a row bank sync
already brought in is skipped too (import_statement.plan).
Statement payment credits ("AUTOMATIC PAYMENT", "PAYMENT THANK YOU") are typed card_payment so
they are excluded from spend. Run data/apply_rules.py afterward for categories.
"""
import csv
import sys
import argparse
import re

ap = argparse.ArgumentParser()
ap.add_argument("csv")
ap.add_argument("--last4", required=True)
ap.add_argument("--document-id", type=int)
ap.add_argument("--dry-run", action="store_true")
a = ap.parse_args()
import db  # noqa: E402
import money  # noqa: E402
import dates  # noqa: E402

c = db.connect()
acc = c.execute("SELECT id FROM accounts WHERE last4=? AND type='credit'", (a.last4,)).fetchall()
if len(acc) != 1:
    sys.exit(f"expected exactly one credit account with last4 {a.last4}, found {len(acc)}")
aid = acc[0][0]
rows = []
with open(a.csv, newline="", encoding="utf-8-sig") as f:
    for r in csv.DictReader(f):
        d = re.sub(r"\s+", " ", r["description"]).strip()
        when = dates.parse_any(r["date"])
        if when is None:
            sys.exit(f"row with description {d!r}: cannot read the date {r['date']!r}")
        rows.append((when.isoformat(), d, money.parse(r["amount"]),
                     (r.get("cardholder") or "").strip() or None,
                     (r.get("category") or "").strip() or None,
                     (r.get("ref") or "").strip() or None))
import import_statement as im  # noqa: E402  (same dedupe as a statement import, bank-sync rows included)
parsed = [{"date": date, "desc": desc, "amount": amt, "ref": ref, "cardholder": holder, "category": cat}
          for date, desc, amt, holder, cat, ref in rows]
new, skip = im.plan(c, parsed, {"id": aid, "type": "credit"}, 1)
ins = len(new)
if not a.dry_run:
    for p in new:
        c.execute("INSERT INTO transactions(account_id,txn_date,description,amount,category,"
                  "document_id,txn_type,ref,cardholder) VALUES(?,?,?,?,?,?,?,?,?)",
                  (aid, p["date"], p["desc"], p["amount"], p["category"], a.document_id, p["txn_type"], p["ref"], p["cardholder"]))
if not a.dry_run:
    c.commit()
print(f"{'would insert' if a.dry_run else 'inserted'} {ins}, skipped {skip} (account id {aid}, x{a.last4})")
