"""Money > Accounts as books (PLAN_money_books slice 2): every account once, grouped like the bank, and one account's
register with a running balance and a "matches bank" check. Read-only, no AI.

  overview(con, today, closed=False)   groups (bank, card, investment, insurance, loan) with subtotals, net worth,
                                        how many accounts match the bank, closed accounts apart
  account(con, acct_id, today, n=200)  header, type facts (card limit / used / due, bank in / out / moved this month),
                                        the register newest first with the balance after each line and statement-end
                                        lines, and the bank-match result

Balances come from `account_balances` (statements = `statement_end`, bank sync = `snapshot`); cards and loans are stored
as what is owed (positive). The register walks back from the newest bank balance through `transactions` (amount < 0 =
money out of the account; on a card that is a charge, so what is owed goes up).
Bank match: every pair of statement ends must differ by exactly the lines between them (to the cent). One statement end
or bank-sync balances only = nothing to compare yet ("from the bank").

  python data/books_data.py             the groups as text
  python data/books_data.py ACCOUNT_ID  one account's register (newest 40 lines)
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

CENT = 0.005
MOVED = ("transfer", "card_payment", "investment_transfer", "loan_payment")
REGISTER_MAX = 2000


def _subtype(r):
    return r["subtype"] or AT.resolve(r["type"], r["name"], r["institution"])


def _cols(con):
    return {r[1] for r in con.execute("PRAGMA table_info(accounts)")}


def _accounts(con):
    """Every account with its subtype, group and newest balance (a statement end beats a snapshot on the same day)."""
    have = _cols(con)
    want = ("subtype", "institution", "ownership", "owners", "closed_on", "credit_limit", "apr_pct", "due_day",
            "min_payment", "sort", "owner", "death_benefit", "premium")
    sel = ", ".join(c if c in have else f"NULL AS {c}" for c in want)
    cur = con.execute(f"SELECT id, name, type, last4, {sel} FROM accounts")
    names = [d[0] for d in cur.description]
    rows = [dict(zip(names, x)) for x in cur.fetchall()]
    latest = {}
    for aid, as_of, bal, kind in con.execute(
            "SELECT account_id, as_of, balance, kind FROM account_balances ORDER BY as_of, kind='statement_end'"):
        latest[aid] = (str(as_of)[:10], bal, kind)
    for r in rows:
        r["subtype"] = _subtype(r)
        r["group"] = AT.group_of(r["subtype"]) or "bank"
        r["kind_label"] = AT.label(r["subtype"])
        r["owed"] = AT.GROUPS[r["group"]]["owed"]
        r["as_of"], r["balance"], r["bal_kind"] = latest.get(r["id"], (None, None, None))
        r["owners"] = r["owners"] or r["owner"] or ""
        r["joint"] = r["ownership"] == "joint"
    _details(con, rows)
    return rows


def _table_cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _dicts(cur):
    names = [d[0] for d in cur.description]
    return [dict(zip(names, x)) for x in cur.fetchall()]


def _details(con, rows):
    """Linked loan rows (rate, payment, payoff; their balance when it is newer than the bank's) and holdings (their
    value when the account has no balance of its own) onto the account rows (migration 071, slice 3)."""
    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["loan"], r["holdings"] = None, []
    if "account_id" in _table_cols(con, "loans"):
        for ln in _dicts(con.execute("SELECT * FROM loans WHERE account_id IS NOT NULL")):
            r = by_id.get(ln["account_id"])
            if not r:
                continue
            r["loan"] = ln
            if r["apr_pct"] is None and ln["rate_pct"] is not None:
                r["apr_pct"] = ln["rate_pct"]
            if not r["min_payment"] and ln["payment"]:
                r["min_payment"] = ln["payment"]
            if not r["due_day"] and ln["payment_day"]:
                r["due_day"] = ln["payment_day"]
            when = str(ln["balance_date"] or "")[:10]
            if ln["balance"] is not None and (r["balance"] is None or (when and when > (r["as_of"] or ""))):
                r["balance"], r["as_of"], r["bal_kind"] = ln["balance"], when or None, "loan"
    if "account_id" in _table_cols(con, "investments"):
        for h in _dicts(con.execute("SELECT * FROM investments WHERE account_id IS NOT NULL")):
            r = by_id.get(h["account_id"])
            if r:
                r["holdings"].append(h)
        for r in rows:
            vals = [h["current_value"] for h in r["holdings"] if h["current_value"] is not None]
            if r["balance"] is None and vals:
                r["balance"] = round(sum(vals), 2)
                r["as_of"] = max((str(h["as_of"])[:10] for h in r["holdings"] if h["as_of"]), default=None)
                r["bal_kind"] = "holdings"


def unlinked_holdings(con):
    """Investments rows that belong to no account: listed apart, never in the totals (they may sit inside an account
    that is not linked yet, so adding them could count them twice)."""
    if "account_id" not in _table_cols(con, "investments"):
        return []
    return _dicts(con.execute("SELECT id, name, kind, invested, current_value, as_of, maturity_date FROM investments "
                              "WHERE account_id IS NULL ORDER BY name"))


def _signed(r, bal):
    """Owed accounts as a negative number, like v_balance_latest."""
    return None if bal is None else (-bal if r["owed"] else bal)


def _due(day, today):
    """The next date the due day falls on (today counts), clamped to the month's last day."""
    if not day:
        return None
    for add in (0, 1):
        y, m = today.year + (today.month + add - 1) // 12, (today.month + add - 1) % 12 + 1
        last = (dt.date(y + m // 12, m % 12 + 1, 1) - dt.timedelta(days=1)).day
        d = dt.date(y, m, min(int(day), last))
        if d >= today:
            return d
    return None


def reconcile(con, r):
    """{status ok / off / sync / none, text, gap, since} for one account (see the module text)."""
    ends = [(str(d)[:10], b) for d, b in con.execute(
        "SELECT as_of, balance FROM account_balances WHERE account_id=? AND kind='statement_end' ORDER BY as_of", (r["id"],))]
    if len(ends) < 2:
        if r.get("bal_kind") == "loan":
            return {"status": "sync", "text": f"From your loan record · {r['as_of']}" if r["as_of"] else "From your loan record"}
        if r.get("bal_kind") == "estimate":
            return {"status": "sync", "text": f"Your estimate · {r['as_of']}" if r["as_of"] else "Your estimate"}
        if r.get("bal_kind") == "holdings":
            return {"status": "sync", "text": f"From the holdings · {r['as_of']}" if r["as_of"] else "From the holdings"}
        if ends or r["balance"] is not None:
            return {"status": "sync", "text": f"From the bank · {r['as_of']}" if r["as_of"] else "From the bank"}
        return {"status": "none", "text": "No bank balance yet: add a statement"}
    worst = None
    for (d0, b0), (d1, b1) in zip(ends, ends[1:]):
        moved = con.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id=? AND txn_date>? AND txn_date<=?",
                            (r["id"], d0, d1)).fetchone()[0]
        gap = round((_signed(r, b1) - _signed(r, b0)) - moved, 2)
        if abs(gap) > CENT:
            worst = (d0, d1, gap)
    if worst is None:
        return {"status": "ok", "text": f"Matches bank · statement {ends[-1][0]}"}
    d0, d1, gap = worst
    return {"status": "off", "gap": abs(gap), "since": d0,
            "text": f"Off by {M.fmt(abs(gap))} between the statements of {d0} and {d1}"}


def overview(con, today, closed=False):
    rows = _accounts(con)
    shut = [r for r in rows if r["closed_on"]]
    rows = [r for r in rows if not r["closed_on"]] if not closed else rows
    have = owe = 0.0
    count = {"ok": 0, "off": 0, "sync": 0, "none": 0}
    groups = []
    for key, g in AT.GROUPS.items():
        mine = sorted((r for r in rows if r["group"] == key), key=lambda r: (r["sort"] is None, r["sort"] or 0, r["name"].lower()))
        if not mine:
            continue
        total = 0.0
        for r in mine:
            r["match"] = reconcile(con, r)
            count[r["match"]["status"]] += 1
            term = r["subtype"] == "life_term"
            if r["balance"] is not None and not term and not r["closed_on"]:
                total += r["balance"]
                if g["owed"]:
                    owe += r["balance"]
                else:
                    have += r["balance"]
            if key == "card" and r["credit_limit"] and r["balance"] is not None:
                r["used_pct"] = max(0, min(100, round(r["balance"] / r["credit_limit"] * 100)))
            due = _due(r["due_day"], today)
            r["due"] = due.isoformat() if due else None
            r["term"] = term
        groups.append({"key": key, "label": g["label"], "owed": g["owed"], "total": round(total, 2), "rows": mine})
    needs = []
    for g in groups:
        for r in g["rows"]:
            if r["match"]["status"] == "off":
                needs.append({"id": r["id"], "text": f"{r['name']}: off from the bank by {M.fmt(r['match']['gap'])}"})
            if r["due"] and g["key"] == "card" and r["balance"] and (dt.date.fromisoformat(r["due"]) - today).days <= 10:
                needs.append({"id": r["id"], "text": f"{r['name']} due {r['due']}"})
    return {"groups": groups, "have": round(have, 2), "owe": round(owe, 2), "net": round(have - owe, 2), "count": count,
            "accounts": sum(len(g["rows"]) for g in groups), "closed": len(shut), "needs": needs[:3],
            "more_needs": max(0, len(needs) - 3), "change": _month_change(con, today), "loose": unlinked_holdings(con)}


def _month_change(con, today):
    """Net worth now minus at the end of last month (latest balance on or before each day), or None."""
    first = today.replace(day=1)
    out = []
    for day in (first - dt.timedelta(days=1), today):
        total, seen = 0.0, False
        for aid, typ, bal in con.execute(
                "SELECT b.account_id, a.type, b.balance FROM account_balances b JOIN accounts a ON a.id=b.account_id "
                "WHERE b.as_of=(SELECT MAX(x.as_of) FROM account_balances x WHERE x.account_id=b.account_id AND x.as_of<=?) "
                "AND a.closed_on IS NULL GROUP BY b.account_id", (day.isoformat(),)):
            seen = True
            total += -bal if typ in ("credit", "loan") else bal
        out.append(total if seen else None)
    return None if None in out else round(out[1] - out[0], 2)


def _register(con, r, n):
    """Lines newest first with `after` = balance after the line (display sign: owed accounts positive) and statement-end
    markers {stmt, reported, computed, ok}."""
    lines = [dict(zip(("id", "date", "desc", "category", "type", "amount"), x)) for x in con.execute(
        "SELECT id, txn_date, description, category, txn_type, amount FROM transactions WHERE account_id=? "
        "ORDER BY txn_date DESC, id DESC LIMIT ?", (r["id"], min(int(n), REGISTER_MAX)))]
    for x in lines:
        x["date"] = str(x["date"])[:10]
        x["moved"] = x["type"] in MOVED
    if r["balance"] is None:
        return lines, False
    anchor = _signed(r, r["balance"])
    newer = con.execute("SELECT COALESCE(SUM(amount), 0) FROM transactions WHERE account_id=? AND txn_date>?",
                        (r["id"], r["as_of"])).fetchone()[0]
    cur = anchor + newer
    ends = [(str(d)[:10], b) for d, b in con.execute(
        "SELECT as_of, balance FROM account_balances WHERE account_id=? AND kind='statement_end' ORDER BY as_of DESC", (r["id"],))]
    out, sign = [], (-1 if r["owed"] else 1)
    for x in lines:
        while ends and x["date"] <= ends[0][0]:
            d, b = ends.pop(0)
            out.append({"stmt": d, "reported": b, "computed": round(cur * sign, 2), "ok": abs(cur * sign - b) <= CENT})
        x["after"] = round(cur * sign, 2)
        out.append(x)
        cur -= x["amount"]
    if ends and len(lines) < min(int(n), REGISTER_MAX):  # statement ends older than every line
        d, b = ends.pop(0)
        out.append({"stmt": d, "reported": b, "computed": round(cur * sign, 2), "ok": abs(cur * sign - b) <= CENT})
    return out, True


def account(con, acct_id, today, n=200):
    """One account's page, or None when there is no such account."""
    rows = [r for r in _accounts(con) if r["id"] == int(acct_id)]
    if not rows:
        return None
    r = rows[0]
    r["match"] = reconcile(con, r)
    due = _due(r["due_day"], today)
    r["due"] = due.isoformat() if due else None
    reg, running = _register(con, r, n)
    month = today.strftime("%Y-%m")
    facts = []
    if r["group"] == "card":
        stmt = con.execute("SELECT as_of, balance FROM account_balances WHERE account_id=? AND kind='statement_end' "
                           "ORDER BY as_of DESC LIMIT 1", (r["id"],)).fetchone()
        if r["credit_limit"]:
            facts.append(("Credit limit", M.fmt(r["credit_limit"], 0)))
            if r["balance"] is not None:
                facts.append(("Used", f"{max(0, round(r['balance'] / r['credit_limit'] * 100))}%"))
        if stmt:
            facts.append((f"Statement balance · {str(stmt[0])[:10]}", M.fmt(stmt[1])))
        if r["due"]:
            facts.append(("Payment due", r["due"]))
        if r["min_payment"]:
            facts.append(("Minimum payment", M.fmt(r["min_payment"])))
        if r["apr_pct"] is not None:
            facts.append(("APR", f"{r['apr_pct']:g}%"))
    elif r["group"] == "loan":
        facts += _loan_facts(con, r, today)
    elif r["group"] == "property":
        facts += _equity_facts(con, r)
    elif r["group"] == "insurance":
        facts.append(("Cash value", "none (term)" if r["subtype"] == "life_term" else
                      (M.fmt(r["balance"]) if r["balance"] is not None else "not recorded")))
        if r["death_benefit"]:
            facts.append(("Death benefit", M.fmt(r["death_benefit"], 0)))
        if r["premium"]:
            facts.append(("Premium a month", M.fmt(r["premium"])))
    else:
        inn, out_, moved = con.execute(
            "SELECT COALESCE(SUM(CASE WHEN amount>0 AND COALESCE(txn_type,'') NOT IN (?,?,?,?) THEN amount END), 0), "
            "COALESCE(SUM(CASE WHEN amount<0 AND COALESCE(txn_type,'') NOT IN (?,?,?,?) THEN -amount END), 0), "
            "COALESCE(SUM(CASE WHEN txn_type IN (?,?,?,?) THEN ABS(amount) END), 0) "
            "FROM transactions WHERE account_id=? AND substr(txn_date, 1, 7)=?",
            (*MOVED, *MOVED, *MOVED, r["id"], month)).fetchone()
        mon = today.strftime("%b")
        facts += [(f"Money in · {mon}", M.fmt(inn)), (f"Money out · {mon}", M.fmt(out_)),
                  (f"Moved to or from your accounts · {mon}", M.fmt(moved))]
    if r["group"] == "investment" and r["holdings"]:
        facts += _holding_facts(r)
    total = con.execute("SELECT COUNT(*) FROM transactions WHERE account_id=?", (r["id"],)).fetchone()[0]
    return {"a": r, "facts": facts, "register": reg, "running": running, "lines": total,
            "shown": sum(1 for x in reg if "stmt" not in x), "more": min(int(n), REGISTER_MAX) < total and int(n) < REGISTER_MAX}


# a home's equity counts the mortgage and home equity loans; a vehicle's counts the auto loans
SECURED = {"home": ("mortgage", "heloc"), "vehicle": ("auto",)}


def _equity_facts(con, r):
    """Your estimate, and (when it is the only one of its kind) what is owed against it and the equity."""
    out = [("Value (your estimate)", M.fmt(r["balance"], 0) if r["balance"] is not None else "not set: Edit account")]
    debts = SECURED.get(r["subtype"])
    if not debts or r["balance"] is None:
        return out
    rows = _accounts(con)
    if sum(1 for x in rows if x["subtype"] == r["subtype"] and not x["closed_on"]) != 1:
        return out  # two homes or two cars: which loan goes with which is not known
    owed = [x for x in rows if x["subtype"] in debts and not x["closed_on"] and x["balance"] is not None]
    if owed:
        total = sum(x["balance"] for x in owed)
        out.append(("Owed against it", M.fmt(total, 0)))
        out.append(("Equity", M.fmt(r["balance"] - total, 0)))
    return out


def _holding_facts(r):
    put = [h["invested"] for h in r["holdings"] if h["invested"] is not None]
    val = [h["current_value"] for h in r["holdings"] if h["current_value"] is not None]
    out = []
    if put:
        out.append(("Put in", M.fmt(sum(put))))
    if val:
        out.append(("Holdings value", M.fmt(sum(val))))
    if put and val and len(put) == len(val) == len(r["holdings"]):
        out.append(("Gain", M.fmt(sum(val) - sum(put))))
    mat = sorted(str(h["maturity_date"])[:10] for h in r["holdings"] if h["maturity_date"])
    if mat:
        out.append(("Next maturity", mat[0]))
    return out


def _loan_facts(con, r, today):
    """Rate, payment, next payment, payoff (the record's date and what the payment gives at the rate) and how much the
    balance came down this year (from the balances on record)."""
    import loans as L
    out = []
    if r["apr_pct"] is not None:
        out.append(("Rate", f"{r['apr_pct']:g}%"))
    if r["min_payment"]:
        out.append(("Payment", M.fmt(r["min_payment"])))
    if r["due"]:
        out.append(("Next payment", r["due"]))
    ln = r["loan"] or {}
    if ln.get("payoff_date"):
        out.append(("Payoff date on record", str(ln["payoff_date"])[:10]))
    po = L.payoff(r["balance"], r["apr_pct"], r["min_payment"]) if r["balance"] and r["min_payment"] else None
    if po:
        months, interest = po
        y, m = divmod(today.month - 1 + months, 12)
        out.append(("At this payment, paid off", f"{dt.date(today.year + y, m + 1, 1):%b %Y} ({months} months)"))
        out.append(("Interest still to pay", M.fmt(interest, 0)))
    elif r["balance"] and r["min_payment"]:
        out.append(("At this payment", "the payment does not cover the interest"))
    jan = f"{today.year}-01-01"
    start = con.execute("SELECT balance FROM account_balances WHERE account_id=? AND as_of<=? ORDER BY as_of DESC LIMIT 1",
                        (r["id"], jan)).fetchone() or con.execute(
        "SELECT balance FROM account_balances WHERE account_id=? AND as_of>=? ORDER BY as_of LIMIT 1", (r["id"], jan)).fetchone()
    if start and r["balance"] is not None and start[0] > r["balance"]:
        out.append((f"Paid down in {today.year}", M.fmt(start[0] - r["balance"])))
    return out


def view(today, closed=False):
    con = db.connect(paths.DB, readonly=True)
    try:
        return overview(con, today, closed)
    finally:
        con.close()


def account_view(acct_id, today, n=200):
    con = db.connect(paths.DB, readonly=True)
    try:
        return account(con, acct_id, today, n)
    finally:
        con.close()


def main(argv):
    today = dates.today()
    if argv:
        v = account_view(int(argv[0]), today, 40)
        if not v:
            print("no such account")
            return 1
        a = v["a"]
        print(f"{a['name']} ({a['kind_label']}) {M.fmt(a['balance']) if a['balance'] is not None else '-'} · {a['match']['text']}")
        for x in v["register"]:
            if "stmt" in x:
                print(f"  -- statement {x['stmt']}: bank {M.fmt(x['reported'])}, here {M.fmt(x['computed'])}")
            else:
                print(f"  {x['date']}  {x['desc'][:40]:<40} {M.fmt(x['amount']):>12} {M.fmt(x['after']) if 'after' in x else '':>12}")
        return 0
    o = view(today)
    for g in o["groups"]:
        print(f"{g['label']}: {M.fmt(g['total'])}")
        for r in g["rows"]:
            print(f"  {r['name']:<30} {r['kind_label']:<18} {M.fmt(r['balance']) if r['balance'] is not None else '-':>14}  {r['match']['status']}")
    print(f"Have {M.fmt(o['have'])} · owe {M.fmt(o['owe'])} · net {M.fmt(o['net'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
