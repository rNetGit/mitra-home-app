"""Generate Mitra Home reports from data/family.db.

Usage:
  python data/make_report.py weekly            -> reports/YYYY-MM-DD_weekly.md
  python data/make_report.py monthly [YYYY-MM] -> reports/YYYY-MM_monthly.md (default: last full month)
"""
import sqlite3
import pathlib
import sys
import datetime as dt
import db  # noqa: E402
import dates  # noqa: E402
from dates import parse as _pd  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
con = db.connect(paths.DB)
today = dates.today()
iso = lambda d: d.isoformat()
money = lambda v: f"{(v or 0):,.2f}"


def q(sql, *a):
    return con.execute(sql, a).fetchall()


def table(headers, rows):
    if not rows:
        return "_none_\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def open_questions():
    try:
        n = con.execute("SELECT COUNT(*) FROM review_queue WHERE resolved=0").fetchone()[0]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        n = 0
    return f"{n} file(s) waiting for you in the Inbox\n"


def due_section():
    con.execute("UPDATE bills SET status='overdue' WHERE status='due' AND due_date < ?", (iso(today),))
    con.commit()
    cols = ["Bill", "Vendor", "Amount", "Due", "Days"]
    def rows(lo, hi):
        return [(n, v, money(a), d, (_pd(d) - today).days)
                for n, v, a, d in q("SELECT name,vendor,amount,due_date FROM bills WHERE status IN ('due','overdue') "
                                    "AND due_date>=? AND due_date<=? ORDER BY due_date", lo, hi) if _pd(d)]
    overdue = [(n, v, money(a), d, (_pd(d) - today).days)
               for n, v, a, d in q("SELECT name,vendor,amount,due_date FROM bills WHERE status='overdue' ORDER BY due_date")
               if _pd(d)]
    s = "### Overdue\n" + table(cols, overdue)
    s += "\n### Next 7 days\n" + table(cols, rows(iso(today), iso(today + dt.timedelta(7))))
    s += "\n### Days 8-30\n" + table(cols, rows(iso(today + dt.timedelta(8)), iso(today + dt.timedelta(30))))
    return s


def upcoming_misc(days):
    end = iso(today + dt.timedelta(days))
    appts = q("SELECT appt_datetime,person,provider,purpose FROM appointments WHERE substr(appt_datetime,1,10)>=? "
              "AND substr(appt_datetime,1,10)<=? ORDER BY 1", iso(today), end)
    evs = q("SELECT event_date,name FROM events WHERE event_date>=? AND event_date<=? ORDER BY 1", iso(today), end)
    subs = q("SELECT next_renewal,name,amount FROM subscriptions WHERE active=1 AND next_renewal>=? AND next_renewal<=? ORDER BY 1",
             iso(today), end)
    return ("### Appointments\n" + table(["When", "Who", "Provider", "Purpose"], appts) +
            "\n### Events\n" + table(["Date", "Event"], evs) +
            "\n### Subscription renewals\n" + table(["Date", "Name", "Amount"], subs))


def weekly():
    s = f"# Weekly digest - {iso(today)}\n\n## Due\n{due_section()}\n## Next 14 days\n{upcoming_misc(14)}"
    s += "\n## Recent activity (last 7 days)\n"
    s += table(["Date", "Description", "Amount", "Type"],
               [(d, desc[:50], money(a), t) for d, desc, a, t in
                q("SELECT txn_date,description,amount,txn_type FROM transactions WHERE txn_date>=? ORDER BY txn_date",
                  iso(today - dt.timedelta(7)))])
    s += f"\n## Housekeeping\n- {open_questions()}"
    docs = q("SELECT COUNT(*) FROM documents WHERE ingested_at>=?", iso(today - dt.timedelta(7)))[0][0]
    s += f"- Documents filed this week: {docs}\n"
    inbox = list((paths.INBOX).glob("*"))
    s += f"- Files waiting in inbox: {len(inbox)}\n"
    return s, paths.REPORTS / f"{iso(today)}_weekly.md"


def monthly(month):
    s = f"# Monthly report - {month}\n\n"
    cf = q("SELECT income,card_payments,loans,insurance,utilities,tax_net,other_spend,uncategorized_net_out,invested,"
           "operating_net,net_change FROM v_monthly_cashflow WHERE month=?", month)
    if cf:
        h = ["Income", "Cards", "Loans", "Insurance", "Utilities", "Tax", "Other", "Uncategorized", "Invested", "Operating net", "Net change"]
        s += "## Cashflow\n" + table(h, [tuple(money(v) for v in cf[0])])
    else:
        s += "## Cashflow\n_no transactions for this month_\n"
    s += "\n## Card payments\n" + table(["Card", "Paid", "Count"], q("SELECT payee,paid,n FROM v_card_payments WHERE month=?", month))
    s += "\n## Investment flows\n" + table(["Destination", "Moved", "Cumulative (payee)", "Cumulative (total)"],
                                           q("SELECT payee,invested,cumulative_payee,cumulative_total FROM v_investment_flows WHERE month=?", month))
    s += "\n## Interest earned\n" + table(["Account", "Period end", "Amount"],
                                          q("SELECT a.name,i.period_end,i.amount FROM interest_income i LEFT JOIN accounts a ON a.id=i.account_id "
                                            "WHERE substr(i.period_end,1,7)=? ORDER BY 2", month))
    s += "\n## Bills paid / still open\n" + table(["Bill", "Amount", "Due", "Status", "Paid"],
                                                  [(n, money(a), d, st, p) for n, a, d, st, p in
                                                   q("SELECT name,amount,due_date,status,paid_date FROM bills WHERE substr(due_date,1,7)=? ORDER BY due_date", month)])
    s += "\n## Largest transactions\n" + table(["Date", "Description", "Amount", "Type"],
                                              [(d, desc[:50], money(a), t) for d, desc, a, t in
                                               q("SELECT txn_date,description,amount,txn_type FROM transactions WHERE substr(txn_date,1,7)=? "
                                                 "ORDER BY ABS(amount) DESC LIMIT 10", month)])
    import trends
    s += "\n## Trends\n" + trends.markdown(con, 12, month)
    try:
        import mobile_bill
        if con.execute("SELECT 1 FROM mobile_bills LIMIT 1").fetchone():
            s += "\n## Phone bills\n" + mobile_bill.markdown(con, month)
    except Exception:  # noqa: BLE001 (phone bill tables not migrated yet)
        pass
    try:  # the data check's score that month (data/audit.py)
        import audit
        s += "\n## Data check\n" + audit.markdown_month(con, month)
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
    unc = q("SELECT COUNT(*),COALESCE(SUM(-amount),0) FROM transactions WHERE substr(txn_date,1,7)=? AND txn_type IS NULL", month)[0]
    s += f"\n## Housekeeping\n- Uncategorized transactions: {unc[0]} (net out {money(unc[1])})\n- {open_questions()}"
    return s, paths.REPORTS / f"{month}_monthly.md"


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "weekly"
    if mode == "monthly":
        m = sys.argv[2] if len(sys.argv) > 2 else (today.replace(day=1) - dt.timedelta(1)).strftime("%Y-%m")
        text, path = monthly(m)
    else:
        text, path = weekly()
    path.write_text(text, encoding="utf-8")
    print(path)
