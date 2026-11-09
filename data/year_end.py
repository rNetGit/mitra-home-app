"""Year-end household summary.

  python data/year_end.py [YEAR]     -> reports/YYYY_year_end.md  (default: current year; 'year to date' if not over)
Money model (all accounts, by txn_date): income = income/interest on bank accounts; spend = spend, fee, utility,
insurance, loan_payment and untyped rows (checks etc.), net of card refunds; tax = type 'tax' (net of refunds);
invested = investment_transfer. card_payment and transfer rows are excluded so nothing is double counted
(card purchases are counted once, on the card; the bank-side card payment is dropped).
Aggregates and last4 only. Runs data/tax_prep.py for the year if reports/YYYY_tax_prep.md is missing.
"""
import datetime as dt
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
import paths  # noqa: E402
import dates  # noqa: E402
import subscriptions as subs  # noqa: E402
import db  # noqa: E402
from money import fmt as _fmt  # noqa: E402

SPENDY = "COALESCE(txn_type,'x') IN ('x','spend','fee','utility','insurance','loan_payment')"


def money(v):
    return f"-{_fmt(abs(v), 0)}" if v < 0 else f"{_fmt(v, 0)}"


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return out


def build(con, year, today=None):
    today = today or dates.today()
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    ytd = today < dt.date(year, 12, 31)
    q = lambda s, *a: con.execute(s, a).fetchall()
    A = (y0, y1)
    last = q("SELECT MAX(txn_date) FROM transactions WHERE txn_date BETWEEN ? AND ?", *A)[0][0]
    L = [f"# {year} year-end summary" + (" (year to date)" if ytd else ""), "",
         f"_Generated {today}. Transactions in the data run to {last or 'n/a'}. Source: family.db. "
         "Aggregates only; card/account numbers are last4._", ""]
    if ytd:
        L += [f"> {year} is not over: every figure is year to date, and months before the first loaded statement are missing.", ""]

    # 1. cashflow
    rows = q("""SELECT substr(t.txn_date,1,7) m,
        SUM(CASE WHEN t.txn_type IN ('income','interest') AND a.type!='credit' THEN t.amount ELSE 0 END),
        SUM(CASE WHEN COALESCE(t.txn_type,'x') IN ('x','spend','fee','utility','insurance','loan_payment')
                 THEN -t.amount ELSE 0 END),
        SUM(CASE WHEN t.txn_type='income' AND a.type='credit' THEN t.amount ELSE 0 END),
        SUM(CASE WHEN t.txn_type='tax' THEN -t.amount ELSE 0 END),
        SUM(CASE WHEN t.txn_type='investment_transfer' THEN -t.amount ELSE 0 END)
        FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.txn_date BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""", *A)
    L += ["## Income vs spend vs invested", ""]
    body, ti = [], [0.0] * 5
    for m, inc, sp, refund, tax_, inv in rows:
        sp -= refund  # card refunds typed 'income' offset spend
        net = inc - sp - tax_ - inv
        body.append((m, money(inc), money(sp), money(tax_), money(inv), money(net)))
        for i, v in enumerate((inc, sp, tax_, inv, net)):
            ti[i] += v
    body.append(("**Total**",) + tuple(f"**{money(v)}**" for v in ti))
    L += table(["Month", "Income", "Spend", "Taxes", "Invested", "Left over"], body)
    inc, sp, tax_, inv, net = ti
    L += [""]
    if inc:
        L += [f"Income {money(inc)}; spend {money(sp)}; net taxes {money(tax_)}; invested {money(inv)}. "
              f"Income minus spend and taxes: {money(inc - sp - tax_)} ({100 * (inc - sp - tax_) / inc:.0f}% of income)."]
    L += ["Spend includes insurance, utilities, loan payments and untyped checks. Card payments and account-to-account "
          "transfers are excluded (card purchases are counted once, on the card). One-off lumps (e.g. a life-insurance "
          "payment) are included; see the payee list.", ""]

    # 2. categories / payees
    L += ["## Top spend categories", ""]
    cats = q(f"""SELECT COALESCE(NULLIF(category,''),'(uncategorized)'), -SUM(amount_cents)/100.0, COUNT(*) FROM transactions
        WHERE {SPENDY} AND txn_date BETWEEN ? AND ? GROUP BY 1 HAVING -SUM(amount_cents)/100.0 > 0 ORDER BY 2 DESC LIMIT 12""", *A)
    L += table(["Category", "Net spend", "Txns"], [(c, money(v), n) for c, v, n in cats])
    L += ["", "## Top merchants / payees", ""]
    pay = q(f"""SELECT COALESCE(payee, substr(description,1,28)), -SUM(amount_cents)/100.0, COUNT(*) FROM transactions
        WHERE {SPENDY} AND txn_date BETWEEN ? AND ? GROUP BY 1 HAVING -SUM(amount_cents)/100.0 > 0 ORDER BY 2 DESC LIMIT 15""", *A)
    L += table(["Payee", "Net spend", "Txns"], [(c, money(v), n) for c, v, n in pay]) + [""]

    # 3. cards
    L += ["## Card spend by cardholder", ""]
    ch = q("""SELECT cardholder, card || ' x' || last4, SUM(charges), SUM(credits), SUM(net_spend) FROM v_card_spend_monthly
        WHERE month BETWEEN ? AND ? GROUP BY 1, 2 ORDER BY 1, 5 DESC""", y0[:7], y1[:7])
    L += table(["Cardholder", "Card", "Charges", "Credits", "Net"],
               [(a, b, money(c), money(d), money(e)) for a, b, c, d, e in ch])
    th = q("SELECT cardholder, SUM(net_spend) FROM v_card_spend_monthly WHERE month BETWEEN ? AND ? "
           "GROUP BY 1 ORDER BY 2 DESC", y0[:7], y1[:7])
    L += ["", "By person: " + ", ".join(f"{h} {money(v)}" for h, v in th) + ".", ""]

    # 4. subscriptions
    L += ["## Subscriptions (annual cost)", ""]
    sr = subs.tracked(con, today)
    s = subs.summary(sr)
    L += [f"Still charging: {s['count']} tracked subscriptions, about {money(s['per_month'])}/month, "
          f"{money(s['per_year'])}/year at current prices. Charged in {year} so far: "
          f"{money(sum(r['ytd'] for r in sr))}.", ""]
    L += table(["Subscription", "Decision", "Status", "~Per year", f"{year} charged"],
               [(r["name"], r["decision"], r["status"], money(r["per_year"]), money(r["ytd"]))
                for r in sorted(sr, key=lambda r: -r["per_year"]) if r["charges"]])
    sav = [r for r in sr if r["decision"] in ("cancel", "cancelled")]
    L += [""]
    L += [f"- Savings note: {r['name']} " + (f"is marked 'cancel' (not yet stopped): about {money(r['per_year'])}/year to save."
          if r["decision"] == "cancel" else f"was cancelled: about {money(r['per_year'])}/year no longer spent.")
          for r in sav if r["per_year"] >= 1] or ["No subscriptions are marked cancel/cancelled yet."]
    L += [""]

    # 5. insurance
    L += ["## Insurance premiums", ""]
    pol = q("""SELECT kind, carrier, policy_last4, term_start, term_end, premium_total, change_pct FROM v_policy_premium_history
        WHERE term_start <= ? AND term_end >= ? ORDER BY term_start, kind""", y1, y0)
    L += table(["Policy", "Term", "Premium", "vs prior term"],
               [(f"{c} {k} x{l}", f"{a} to {b}", money(p), f"{pc:+.1f}%" if pc is not None else "n/a")
                for k, c, l, a, b, p, pc in pol]) + [""]
    paid = q("SELECT payee, -SUM(amount_cents)/100.0, COUNT(*) FROM transactions WHERE txn_type='insurance' AND amount<0 "
             "AND txn_date BETWEEN ? AND ? GROUP BY 1 ORDER BY 2 DESC", *A)
    L += ["Insurance payments seen in bank/card data (includes life insurance and any lump sums):", ""]
    L += table(["Payee", "Paid", "Payments"], [(p, money(v), n) for p, v, n in paid]) + [""]

    # 6. interest + taxes
    L += ["## Interest income", ""]
    ii = q("SELECT COALESCE(payee,'?'), SUM(amount_cents)/100.0 FROM transactions WHERE txn_type='interest' AND txn_date BETWEEN ? AND ? "
           "GROUP BY 1 ORDER BY 2 DESC", *A)
    L += table(["Source", "Interest"], [(p, f"{_fmt(v)}") for p, v in ii])
    L += ["", f"Total bank interest: {_fmt(sum(v for _, v in ii))}. Interest from brokerage or government-bond accounts "
              "is on those accounts' own year-end statements, not here.", ""]
    L += ["## Taxes paid", ""]
    tx = q("SELECT COALESCE(payee,'?'), -SUM(amount_cents)/100.0 FROM transactions WHERE txn_type='tax' AND txn_date BETWEEN ? AND ? "
           "GROUP BY 1 ORDER BY 2 DESC", *A)
    L += table(["Payee", "Net paid (refunds negative)"], [(p, money(v)) for p, v in tx]) + ["", f"Net taxes: {money(tax_)}.", ""]
    tp = paths.REPORTS / f"{year}_tax_prep.md"
    if not tp.exists():
        subprocess.run([sys.executable, str(ROOT / "data" / "tax_prep.py"), str(year)], check=False)
    L += [f"Tax-prep checklist: `reports/{year}_tax_prep.md`" + ("" if tp.exists() else " (could not be generated)"), ""]

    # 7. archive index
    L += ["## Archive index", "", "Documents logged (documents table), by type:", ""]
    dd = q("SELECT COALESCE(doc_type,'other'), COUNT(*) FROM documents WHERE filed_path LIKE ? OR doc_date LIKE ? "
           "GROUP BY 1 ORDER BY 2 DESC", f"{year}/%", f"{year}-%")
    L += table(["Type", "Docs"], dd) + [""]
    base = paths.ARCHIVE / str(year)
    if base.exists():
        L += [f"Files under `archive/{year}/<category>`:", ""]
        for cat in sorted(p for p in base.iterdir() if p.is_dir()):
            files = sorted(f.name for f in cat.rglob("*") if f.is_file())
            L += [f"### {cat.name} ({len(files)})", ""] + [f"- {n}" for n in files] + [""]
    else:
        L += [f"_No archive/{year} folder._", ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else dates.today().year
    con = db.connect(paths.DB, readonly=True)
    out = paths.REPORTS / f"{year}_year_end.md"
    out.write_text(build(con, year), encoding="utf-8")
    print(out)
