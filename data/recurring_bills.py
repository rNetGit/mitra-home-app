"""Recurring bills found in your own transactions: proposals, confirm or dismiss, missing-charge and price-rise flags.

  python data/recurring_bills.py detect                   payees charged at a steady interval for 3+ cycles, not tracked yet
  python data/recurring_bills.py confirm "<payee>" [--name NAME]
                                                          track it as a bill: the next expected charge becomes a `bills` row
  python data/recurring_bills.py dismiss "<payee>"        never propose this payee again (undo: edit config/recurring_bills.json)
  python data/recurring_bills.py status                   tracked payees: last charge, next expected, MISSING / PRICE RISE flags
  python data/recurring_bills.py sync                     match new charges to open bills (mark paid), add the next cycle row

No AI, no network, no database migration: tracked and dismissed payees live in `config/recurring_bills.json`; the bill
rows are ordinary `bills` rows (status due -> paid when the charge appears, then the next cycle is added). The weekly
task runs `sync` before the digest, so a confirmed bill keeps rolling forward on its own as statements are loaded.

A candidate is a payee with three or more charges whose gaps are monthly (25-35 days), quarterly (85-95) or yearly
(350-380). Amounts may vary (utilities do); the expected amount is the median of the last three charges. A charge that
is more than 10% above the median of the earlier ones is flagged as a price rise; an expected charge that has not
appeared 7 days after its date, although newer transactions are loaded, is flagged as missing.

Library: detect(con, today) -> [candidate]; confirm(con, payee, today, name=None) -> bill id; dismiss(payee);
status(con, today) -> [tracked row with flags]; sync(con, today) -> [action strings].
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import subscriptions as subs  # noqa: E402
from dates import add_months, parse as _pd  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = HERE.parent
CONF = paths.CONFIG / "recurring_bills.json"
NOT_BILLS = ("investment_transfer", "transfer", "income", "card_payment", "interest")
# shops you visit often are not bills (a payee whose charges all sit in these categories is never proposed)
SHOPPING = subs.SHOPPING + ("shopping", "travel", "entertainment")
MONTHS = {"monthly": 1, "quarterly": 3, "yearly": 12}
GRACE = 7          # days after the expected date before a charge counts as missing
RISE = 0.10        # price rise = last charge more than 10% above the median of the earlier ones
MATCH_BEFORE, MATCH_AFTER = 20, 45   # a charge this many days around a bill's due date settles it


# ---------------------------------------------------------------- config
def load():
    try:
        d = json.loads(CONF.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("tracked", [])
    d.setdefault("ignored", [])
    return d


def save(d):
    config.write_json(CONF, d)


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _pattern(payee):
    """A LIKE pattern from the payee words, so 'Water Works' matches 'CITY WATER WORKS 0423'."""
    words = [w for w in re.sub(r"[^A-Za-z0-9&']", " ", payee or "").split() if w]
    return "%" + "%".join(w.upper() for w in words) + "%" if words else ""


def _freq_of(gaps):
    med = statistics.median(gaps)
    if 25 <= med <= 35:
        return "monthly"
    if 85 <= med <= 95:
        return "quarterly"
    if 350 <= med <= 380:
        return "yearly"
    return None


def _expected(amounts):
    return round(statistics.median(amounts[-3:]), 2)


def _rise(amounts):
    """'price rise 40.00 -> 48.00' when the last charge is RISE above the median of the earlier ones (up to 6)."""
    if len(amounts) < 3:
        return ""
    base = statistics.median(amounts[-7:-1])
    last = amounts[-1]
    if base > 0 and last > base * (1 + RISE) and last - base >= 1.0:
        return f"price rise {base:,.2f} -> {last:,.2f}"
    return ""


# ---------------------------------------------------------------- charges
def _charges(con, entry):
    """[(date, amount)] for a tracked entry (pattern + payee), oldest first."""
    return [(dt.date.fromisoformat(r[0]), round(r[1], 2)) for r in subs._charges(con, entry.get("pattern"), entry.get("payee"))]


def _groups(con):
    """Spend transactions grouped by payee key -> [(date, amount)] sorted; transfers, income, card payments left out."""
    groups, payees, shops = {}, {}, {}
    for d, desc, amt, payee, typ, cat in con.execute(
            "SELECT txn_date, description, amount, payee, txn_type, category FROM transactions WHERE amount < 0 ORDER BY txn_date"):
        if typ in NOT_BILLS:
            continue
        key = subs.merchant_key(payee, desc)
        if not _pd(d):
            continue
        groups.setdefault(key, []).append((_pd(d), round(-amt, 2)))
        shops[key] = shops.get(key, True) and (cat or "").lower() in SHOPPING
        if payee:
            payees[key] = payee
    for key in [k for k, only_shop in shops.items() if only_shop]:
        del groups[key]
    for rows in groups.values():
        rows.sort()
    return groups, payees


def _subscription_hits(con):
    out = set()
    for pat, payee in con.execute("SELECT match_pattern, match_payee FROM subscriptions"):
        for d, amt, *_ in subs._charges(con, pat, payee):
            if _pd(d):
                out.add((_pd(d), round(amt, 2)))
    return out


# ---------------------------------------------------------------- public
def detect(con, today=None):
    """Candidates not yet tracked or dismissed: payee, frequency, amount (median of last 3), charges, last, next, variable, rise."""
    today = today or dates.today()
    conf = load()
    skip = {_norm(t["payee"]) for t in conf["tracked"]} | {_norm(p) for p in conf["ignored"]}
    sub_hits = _subscription_hits(con)
    groups, payees = _groups(con)
    out = []
    for key, rows in groups.items():
        if _norm(key) in skip or len(rows) < 3:
            continue
        if all((d, a) in sub_hits for d, a in rows):
            continue
        if len({(d.year, d.month) for d, _ in rows}) < 3:
            continue
        freq = _freq_of([(b[0] - a[0]).days for a, b in zip(rows, rows[1:])])
        if not freq:
            continue
        amts = [a for _, a in rows]
        mean = statistics.mean(amts)
        if mean < 1:
            continue
        last_d = rows[-1][0]
        out.append({"payee": key, "match_payee": payees.get(key), "frequency": freq, "amount": _expected(amts),
                    "variable": (max(amts) - min(amts)) > max(1.0, 0.12 * mean), "charges": len(rows),
                    "last": last_d, "next": add_months(last_d, MONTHS[freq]), "rise": _rise(amts),
                    "active": (today - last_d).days <= 31 * MONTHS[freq] * 1.6})
    out.sort(key=lambda c: (-c["active"], -c["amount"] * 12 / MONTHS[c["frequency"]]))
    return out


def _find(cands, payee):
    hits = [c for c in cands if _norm(c["payee"]) == _norm(payee)]
    return hits[0] if hits else None


def confirm(con, payee, today=None, name=None):
    """Track a candidate and add its next expected charge as a bills row. Returns the bill id. ValueError if unknown."""
    today = today or dates.today()
    conf = load()
    if any(_norm(t["payee"]) == _norm(payee) for t in conf["tracked"]):
        raise ValueError(f"{payee} is already tracked")
    c = _find(detect(con, today), payee)
    if not c:
        raise ValueError(f"no candidate called {payee!r} (run detect)")
    entry = {"payee": c["payee"], "name": (name or c["payee"]).strip()[:80], "frequency": c["frequency"],
             "amount": c["amount"], "pattern": _pattern(c["payee"]), "payee_field": c["match_payee"],
             "since": today.isoformat()}
    conf["tracked"].append(entry)
    conf["ignored"] = [p for p in conf["ignored"] if _norm(p) != _norm(payee)]
    save(conf)
    sync(con, today, only=entry["payee"])
    row = con.execute("SELECT id FROM bills WHERE COALESCE(vendor, name)=? AND status IN ('due','overdue') ORDER BY due_date DESC LIMIT 1",
                      (entry["payee"],)).fetchone()
    return row[0] if row else None


def dismiss(payee):
    """Never propose this payee again. Returns True if it was a new entry."""
    conf = load()
    if any(_norm(p) == _norm(payee) for p in conf["ignored"]):
        return False
    conf["ignored"].append(payee.strip())
    conf["tracked"] = [t for t in conf["tracked"] if _norm(t["payee"]) != _norm(payee)]
    save(conf)
    return True


def _entry_charges(con, entry):
    e = {"pattern": entry.get("pattern") or _pattern(entry["payee"]), "payee": entry.get("payee_field")}
    return _charges(con, e)


def status(con, today=None):
    """Tracked payees with live facts: last charge, next expected, open bill, flags ('missing', 'price rise ...')."""
    today = today or dates.today()
    latest = con.execute("SELECT MAX(txn_date) FROM transactions").fetchone()[0]
    latest = dt.date.fromisoformat(latest) if latest else today
    out = []
    for t in load()["tracked"]:
        ch = _entry_charges(con, t)
        months = MONTHS.get(t.get("frequency"), 1)
        row = {"payee": t["payee"], "name": t.get("name") or t["payee"], "frequency": t.get("frequency") or "monthly",
               "amount": t.get("amount"), "charges": len(ch), "last": None, "last_amount": None, "next": None,
               "open_bill": None, "flags": []}
        if ch:
            row["last"], row["last_amount"] = ch[-1]
            row["amount"] = _expected([a for _, a in ch])
            row["next"] = add_months(ch[-1][0], months)
            r = _rise([a for _, a in ch])
            if r:
                row["flags"].append(r)
            if latest > row["next"] + dt.timedelta(days=GRACE) and today > row["next"] + dt.timedelta(days=GRACE):
                row["flags"].append(f"missing: expected about {row['next']}, newer transactions loaded up to {latest}")
        ob = con.execute("SELECT id, due_date, amount FROM bills WHERE COALESCE(vendor, name)=? AND status IN ('due','overdue') "
                         "ORDER BY due_date LIMIT 1", (t["payee"],)).fetchone()
        if ob:
            row["open_bill"] = {"id": ob[0], "due": ob[1], "amount": ob[2]}
        out.append(row)
    return out


def sync(con, today=None, only=None):
    """Settle open bills of tracked payees from charges, then make sure one next-cycle row exists. Returns actions."""
    today = today or dates.today()
    actions = []
    for t in load()["tracked"]:
        if only and _norm(t["payee"]) != _norm(only):
            continue
        payee, freq = t["payee"], t.get("frequency") or "monthly"
        months = MONTHS.get(freq, 1)
        ch = _entry_charges(con, t)
        used = {r[0] for r in con.execute("SELECT paid_date FROM bills WHERE COALESCE(vendor, name)=? AND paid_date IS NOT NULL", (payee,))}
        for bid, due in con.execute("SELECT id, due_date FROM bills WHERE COALESCE(vendor, name)=? AND status IN ('due','overdue') "
                                    "ORDER BY due_date", (payee,)).fetchall():
            d0 = dt.date.fromisoformat(due[:10])
            hit = next((c for c in ch if d0 - dt.timedelta(days=MATCH_BEFORE) <= c[0] <= d0 + dt.timedelta(days=MATCH_AFTER)
                        and c[0].isoformat() not in used), None)
            if hit:
                con.execute("UPDATE bills SET status='paid', paid_date=?, amount=? WHERE id=?", (hit[0].isoformat(), hit[1], bid))
                used.add(hit[0].isoformat())
                actions.append(f"{payee}: bill due {due[:10]} paid {hit[0]} ({_fmt(hit[1])})")
        open_left = con.execute("SELECT COUNT(*) FROM bills WHERE COALESCE(vendor, name)=? AND status IN ('due','overdue')", (payee,)).fetchone()[0]
        if open_left or not ch:
            continue
        nxt = add_months(ch[-1][0], months)
        amount = _expected([a for _, a in ch])
        exists = con.execute("SELECT 1 FROM bills WHERE COALESCE(vendor, name)=? AND due_date=?", (payee, nxt.isoformat())).fetchone()
        if exists:
            continue
        con.execute("INSERT INTO bills(name, vendor, frequency, amount, due_date, status) VALUES (?,?,?,?,?,'due')",
                    (t.get("name") or payee, payee, freq, amount, nxt.isoformat()))
        actions.append(f"{payee}: next bill {nxt} ({_fmt(amount)}, {freq})")
    con.commit()
    return actions


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="Recurring bills from your transactions (no AI).")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("detect", help="payees charged at a steady interval, not tracked yet")
    c = sub.add_parser("confirm", help="track a candidate as a bill")
    c.add_argument("payee")
    c.add_argument("--name", help="bill name (default: the payee)")
    d = sub.add_parser("dismiss", help="never propose this payee again")
    d.add_argument("payee")
    sub.add_parser("status", help="tracked payees with flags")
    sub.add_parser("sync", help="settle open bills from charges and add the next cycle")
    a = ap.parse_args(argv)
    if not a.cmd:
        ap.print_help()
        return 0
    today = dates.today()
    con = db.connect(paths.DB)
    try:
        if a.cmd == "detect":
            cands = detect(con, today)
            if not cands:
                print("No new recurring payees found (3+ charges at a monthly, quarterly or yearly interval).")
            for x in cands:
                print(f"{'ACTIVE' if x['active'] else 'stale '} {x['payee'][:34]:34} {x['frequency']:9} ~{_fmt(x['amount']):>10}"
                      f"{' (varies)' if x['variable'] else '':9} n={x['charges']:<3} last={x['last']} next~{x['next']}"
                      f"{'  ' + x['rise'] if x['rise'] else ''}")
            if cands:
                print('\nTrack one: python data/recurring_bills.py confirm "<payee>"   Ignore: ... dismiss "<payee>"')
        elif a.cmd == "confirm":
            try:
                bid = confirm(con, a.payee, today, a.name)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
            print(f"tracking {a.payee}; next bill row id {bid}. It is settled and rolled forward by `sync` (weekly task).")
        elif a.cmd == "dismiss":
            print(f"{a.payee}: {'will not be proposed again' if dismiss(a.payee) else 'was already dismissed'}")
        elif a.cmd == "status":
            rows = status(con, today)
            if not rows:
                print("Nothing tracked yet: run detect, then confirm.")
            for r in rows:
                ob = r["open_bill"]
                print(f"{r['name'][:30]:30} {r['frequency']:9} ~{_fmt(r['amount'] or 0):>10} last={r['last']} next~{r['next']} "
                      f"open bill={'#' + str(ob['id']) + ' due ' + ob['due'] if ob else 'none'}"
                      f"{'  ** ' + '; '.join(r['flags']) if r['flags'] else ''}")
        elif a.cmd == "sync":
            acts = sync(con, today)
            print("\n".join(acts) if acts else "nothing to do")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
