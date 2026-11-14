"""Money > All accounts (PLAN_money_books slice 4): every account read as one, by day, week or month. Read-only, no AI.

  view(con, today, period="week", day=None, group="")
    period   day | week (Monday to Sunday) | month
    day      any date inside the period (ISO); default today
    group    "" = everything, else one account group (bank, card, investment, property, insurance, loan)
  -> {start, end, label, prev, next, money_in, money_out, moved, net_start, net_end, net_change, spark, days: [...]}

What counts:
  Moved between your own accounts = lines of type transfer / card_payment / investment_transfer. A money-out line and
  a money-in line of the same cents on two different accounts within PAIR_DAYS days are ONE move, shown once
  ("Checking -> Gold Card") and counted once. A move whose other side is not loaded (no card statement yet) is still a
  move, counted once.
  Money in  = every other line with amount > 0 (pay, interest, dividends, refunds).
  Money out = every other line with amount < 0 (spending, bills, fees, loan payments). A loan payment paired with the
  loan account's own line is shown once and counted once, in Money out.
  Net worth on a day = for each open account its latest balance on or before that day (statements, bank sync, value
  estimates; owed accounts negative; term life left out), carried forward between balances.

  python data/all_accounts.py [day|week|month] [YYYY-MM-DD]
"""
import datetime as dt
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import account_types as AT  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import money as M  # noqa: E402
import paths  # noqa: E402

PERIODS = ("day", "week", "month")
MOVE_TYPES = ("transfer", "card_payment", "investment_transfer")
PAIR_TYPES = MOVE_TYPES + ("loan_payment",)
PAIR_DAYS = 3
GROUPS = tuple(AT.GROUPS)


def bounds(period, day):
    """(start, end) dates of the period around `day`."""
    if period == "day":
        return day, day
    if period == "month":
        start = day.replace(day=1)
        nxt = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return start, nxt - dt.timedelta(days=1)
    start = day - dt.timedelta(days=day.weekday())
    return start, start + dt.timedelta(days=6)


def _step(period, start, back):
    if period == "day":
        return start + dt.timedelta(days=-1 if back else 1)
    if period == "week":
        return start + dt.timedelta(days=-7 if back else 7)
    if back:
        return (start - dt.timedelta(days=1)).replace(day=1)
    return (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def _label(period, start, end):
    if period == "day":
        return f"{start:%a, %b} {start.day}, {start.year}"
    if period == "month":
        return f"{start:%B %Y}"
    if start.month == end.month:
        return f"{start:%b} {start.day} – {end.day}, {end.year}"
    return f"{start:%b} {start.day} – {end:%b} {end.day}, {end.year}"


def _accounts(con):
    have = {r[1] for r in con.execute("PRAGMA table_info(accounts)")}
    sel = ", ".join(c if c in have else f"NULL AS {c}" for c in ("subtype", "institution", "closed_on"))
    out = {}
    for aid, name, typ, last4, sub, inst, closed in con.execute(f"SELECT id, name, type, last4, {sel} FROM accounts"):
        sub = sub or AT.resolve(typ, name, inst)
        out[aid] = {"id": aid, "name": name, "last4": last4, "subtype": sub, "group": AT.group_of(sub) or "bank",
                    "owed": AT.owed(sub), "closed_on": closed}
    return out


def _lines(con, start, end):
    cur = con.execute("SELECT id, account_id, txn_date, description, category, txn_type, amount FROM transactions "
                      "WHERE txn_date>=? AND txn_date<=? ORDER BY txn_date, id", (start.isoformat(), end.isoformat()))
    return [dict(zip(("id", "acct", "date", "desc", "category", "type", "amount"), r)) for r in cur.fetchall()]


def pair(lines):
    """[(out_line, in_line)] for own transfers: opposite amounts of the same cents on two accounts within PAIR_DAYS,
    both of a moving type, nearest date first; each line used once."""
    cands = [x for x in lines if x["type"] in PAIR_TYPES]
    used, pairs = set(), []
    for o in sorted((x for x in cands if x["amount"] < 0), key=lambda x: (x["date"], x["id"])):
        od = dt.date.fromisoformat(str(o["date"])[:10])
        best = None
        for i in cands:
            if i["amount"] <= 0 or i["id"] in used or i["acct"] == o["acct"]:
                continue
            if round(i["amount"] * 100) != round(-o["amount"] * 100):
                continue
            gap = abs((dt.date.fromisoformat(str(i["date"])[:10]) - od).days)
            if gap <= PAIR_DAYS and (best is None or gap < best[0]):
                best = (gap, i)
        if best:
            used.update((o["id"], best[1]["id"]))
            pairs.append((o, best[1]))
    return pairs


def net_worth_on(con, accts, days):
    """{day: net worth} from the balances on record, carried forward; None for a day before any balance."""
    rows = con.execute("SELECT account_id, as_of, balance, kind FROM account_balances ORDER BY as_of, kind='statement_end'").fetchall()
    out = {}
    for d in days:
        latest = {}
        for aid, as_of, bal, _kind in rows:
            if str(as_of)[:10] <= d.isoformat() and bal is not None:
                latest[aid] = bal
        total, seen = 0.0, False
        for aid, bal in latest.items():
            a = accts.get(aid)
            if not a or (a["closed_on"] and a["closed_on"] <= d.isoformat()) or a["subtype"] == "life_term":
                continue
            seen = True
            total += -bal if a["owed"] else bal
        out[d] = round(total, 2) if seen else None
    return out


def _spark(series):
    """SVG polyline points (0..700 x 0..60) for the net worth line; '' with fewer than two known days."""
    vals = [(i, v) for i, v in enumerate(series) if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(v for _, v in vals), max(v for _, v in vals)
    span, n = (hi - lo) or 1, max(len(series) - 1, 1)
    return " ".join(f"{i * 700 / n:.1f},{56 - (v - lo) / span * 52:.1f}" for i, v in vals)


def view(con, today, period="week", day=None, group=""):
    period = period if period in PERIODS else "week"
    group = group if group in GROUPS else ""
    try:
        anchor = dt.date.fromisoformat(day) if day else today
    except (TypeError, ValueError):
        anchor = today
    start, end = bounds(period, anchor)
    accts = _accounts(con)
    margin = dt.timedelta(days=PAIR_DAYS)
    lines = _lines(con, start - margin, end + margin)
    pairs = pair(lines)
    paired = {x["id"] for p in pairs for x in p}

    def shown(acct_ids):
        return not group or any(accts.get(a, {}).get("group") == group for a in acct_ids)

    def inside(d):
        return start.isoformat() <= str(d)[:10] <= end.isoformat()

    items = []
    money_in = money_out = moved = 0.0
    for o, i in pairs:
        when = o["date"] if inside(o["date"]) else i["date"]
        if not inside(when) or not shown((o["acct"], i["acct"])):
            continue
        loan = "loan_payment" in (o["type"], i["type"])
        amt = -o["amount"]
        if loan:
            money_out += amt
        else:
            moved += amt
        items.append({"date": str(when)[:10], "kind": "loan" if loan else "moved", "desc": o["desc"], "amount": amt,
                      "from": accts.get(o["acct"]), "to": accts.get(i["acct"]), "category": "Loan payment" if loan else "Moved"})
    for x in lines:
        if x["id"] in paired or not inside(x["date"]) or not shown((x["acct"],)):
            continue
        a = accts.get(x["acct"])
        if x["type"] in MOVE_TYPES:
            moved += abs(x["amount"])
            items.append({"date": str(x["date"])[:10], "kind": "moved1", "desc": x["desc"], "amount": abs(x["amount"]),
                          "acct": a, "category": "Moved", "out": x["amount"] < 0})
            continue
        if x["amount"] > 0:
            money_in += x["amount"]
        else:
            money_out += -x["amount"]
        items.append({"date": str(x["date"])[:10], "kind": "line", "desc": x["desc"], "amount": x["amount"], "acct": a,
                      "category": "Loan payment" if x["type"] == "loan_payment" else (x["category"] or "")})
    items.sort(key=lambda x: x["date"], reverse=True)
    days = []
    for it in items:
        if not days or days[-1]["date"] != it["date"]:
            d = dt.date.fromisoformat(it["date"])
            days.append({"date": it["date"], "label": f"{d:%a, %b} {d.day}", "net": 0.0, "items": []})
        days[-1]["items"].append(it)
        if it["kind"] == "line":
            days[-1]["net"] += it["amount"]
        elif it["kind"] == "loan":
            days[-1]["net"] -= it["amount"]
    for d in days:
        d["net"] = round(d["net"], 2)
    span = [start + dt.timedelta(days=k) for k in range((end - start).days + 1)]
    nw = net_worth_on(con, accts, [start - dt.timedelta(days=1)] + span)
    series = [nw[d] for d in span]
    before, after, since = nw[start - dt.timedelta(days=1)], series[-1], None
    if before is None:  # the first balance falls inside the period: measure from that day
        first = next((k for k, x in enumerate(series) if x is not None), None)
        if first is not None and first < len(series) - 1:
            before, since = series[first], span[first].isoformat()
    return {"period": period, "group": group, "start": start.isoformat(), "end": end.isoformat(),
            "label": _label(period, start, end), "prev": _step(period, start, True).isoformat(),
            "next": _step(period, start, False).isoformat(), "future": _step(period, start, False) > today,
            "money_in": round(money_in, 2), "money_out": round(money_out, 2), "moved": round(moved, 2),
            "net_start": before, "net_end": after, "net_since": since,
            "net_change": round(after - before, 2) if before is not None and after is not None else None,
            "spark": _spark(series) if period != "day" else "", "days": days,
            "count": sum(len(d["items"]) for d in days)}


def page(today, period="week", day=None, group=""):
    con = db.connect(paths.DB, readonly=True)
    try:
        return view(con, today, period, day, group)
    finally:
        con.close()


def main(argv):
    period = argv[0] if argv else "week"
    v = page(dates.today(), period, argv[1] if len(argv) > 1 else None)
    print(f"{v['label']}: in {M.fmt(v['money_in'])} · out {M.fmt(v['money_out'])} · moved {M.fmt(v['moved'])}"
          + (f" · net worth {M.fmt(v['net_change'])}" if v["net_change"] is not None else ""))
    for d in v["days"]:
        print(d["label"])
        for it in d["items"]:
            if it["kind"] in ("moved", "loan"):
                print(f"  ⇄ {it['desc'][:40]:<40} {it['from']['name'] if it['from'] else '?'} -> "
                      f"{it['to']['name'] if it['to'] else '?'}  {M.fmt(it['amount'])}")
            else:
                print(f"    {it['desc'][:40]:<40} {(it['acct'] or {}).get('name', '?'):<24} {M.fmt(it['amount'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
