"""Month check (top of Money > Statement): is this month ready to count as final? Fixed read-only rules, no AI.

Each item is {key, label, detail, status, url}: status "ok", "todo" (something to do before the month is final) or "info"
(worth knowing). Rules: the month is over, every account that had lines the month before has lines now, nothing is left
uncategorized, no card payment stands in for a card with no statement, no bill due in the month is still open.
"""
import sqlite3

import dates
import ledger_data as L
import trends as T


def _money(x):
    s = f"{abs(x):,.2f}"
    return "$" + (s[:-3] if s.endswith(".00") else s)


def _open_bills(con, ym):
    try:
        r = con.execute("SELECT COUNT(*), COALESCE(SUM(amount),0) FROM bills WHERE substr(due_date,1,7)=? "
                        "AND status IN ('due','overdue','unpaid')", (ym,)).fetchone()
    except sqlite3.OperationalError:
        return 0, 0.0
    return r[0], r[1]


def _quiet_accounts(con, ym):
    """Accounts (not investment) with lines in the month before and none in this one."""
    prev = T.shift(ym, -1)
    try:
        rows = con.execute("""
            SELECT a.name, a.last4 FROM accounts a WHERE COALESCE(a.type,'') <> 'investment'
              AND EXISTS (SELECT 1 FROM transactions t WHERE t.account_id=a.id AND substr(t.txn_date,1,7)=?)
              AND NOT EXISTS (SELECT 1 FROM transactions t WHERE t.account_id=a.id AND substr(t.txn_date,1,7)=?)
            ORDER BY a.name""", (prev, ym)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(r[0], r[1]) for r in rows]


def checks(con, ym, today=None):
    """{month, ready, todo, lines}. A month that has not ended yet is never ready."""
    today = today or dates.today()
    label = T.label(ym)
    items = []

    running = ym >= today.strftime("%Y-%m")
    items.append({"key": "over", "label": "The month is over", "status": "todo" if running else "ok",
                  "detail": f"{label} is still running: figures will change." if running else "", "url": ""})

    quiet = _quiet_accounts(con, ym)
    items.append({"key": "accounts", "label": "Every account has lines for the month", "status": "todo" if quiet and not running else "ok",
                  "detail": ("No lines in " + label + " for " + ", ".join(f"{n} (x{l})" if l else n for n, l in quiet[:4])
                             + (f" and {len(quiet) - 4} more" if len(quiet) > 4 else "") + ". Drop the statement in the Inbox.") if quiet else "",
                  "url": "/money?part=accounts"})

    loose = [r for r in T._spend_rows(con, ym) if r["category"] == "uncategorized"]
    spent = sum(-r["amount"] for r in loose)
    items.append({"key": "uncategorized", "label": "Nothing left uncategorized", "status": "todo" if loose else "ok",
                  "detail": f"{len(loose)} charge{'s' if len(loose) != 1 else ''} ({_money(spent)}) have no category. Name each merchant once on This month."
                  if loose else "", "url": f"/money?part=month&ym={ym}"})

    last = T._end(ym)
    nocard = ym in L.months_without_cards(con, ym + "-01", last)
    stand = [r for r in L.spend_lines(con, ym + "-01", last) if r["card"]]
    stand_sum = sum(-r["cents"] for r in stand) / 100
    items.append({"key": "cards", "label": "Card spending comes from card statements", "status": "todo" if nocard and stand else "ok",
                  "detail": f"{_money(stand_sum)} of card payments stand in for card spending: no card statement for {label}." if nocard and stand else "",
                  "url": "/money?part=accounts"})

    n, amt = _open_bills(con, ym)
    items.append({"key": "bills", "label": "Bills due in the month are settled", "status": "todo" if n else "ok",
                  "detail": f"{n} bill{'s' if n != 1 else ''} ({_money(amt)}) due in {label} still open." if n else "",
                  "url": "/money?part=bills"})

    todo = sum(1 for i in items if i["status"] == "todo")
    return {"month": ym, "ready": todo == 0, "todo": todo, "lines": items}
