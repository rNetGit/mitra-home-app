"""Generate a local, self-contained Mitra Home dashboard from data/family.db.

Usage:
  python data/make_dashboard.py   -> reports/dashboard.html

Read-only on the DB. Output stays on this PC (no network, no CDN).
"""
import brand
import pathlib
import datetime as dt
import html
import db  # noqa: E402
import dates  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
con = db.connect(paths.DB, readonly=True)
today = dates.today()
e = lambda v: "" if v is None else html.escape(str(v))
money = _fmt


def q(sql, *a):
    return con.execute(sql, a).fetchall()


def days_to(d):
    try:
        return (dt.date.fromisoformat(d[:10]) - today).days
    except (TypeError, ValueError):
        return None


def tag(days):
    if days is None:
        return ""
    if days < 0:
        return f'<span class="pill bad">{-days}d overdue</span>'
    cls = "warn" if days <= 7 else "ok"
    return f'<span class="pill {cls}">in {days}d</span>'


def table(headers, rows, num=()):
    if not rows:
        return '<p class="muted">None.</p>'
    th = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        tds = "".join(
            f'<td class="{"n" if i in num else ""}">{c if isinstance(c, _Raw) else e(c)}</td>'
            for i, c in enumerate(r))
        body += f"<tr>{tds}</tr>"
    return f"<table><tr>{th}</tr>{body}</table>"


class _Raw(str):
    pass


def bars(rows, fmt=money):
    """rows: [(label, value)] -> horizontal bar list."""
    if not rows:
        return '<p class="muted">None.</p>'
    mx = max(abs(v) for _, v in rows) or 1
    out = ""
    for label, v in rows:
        w = max(1, round(100 * abs(v) / mx))
        out += (f'<div class="bar"><span class="bl">{e(label)}</span>'
                f'<span class="bt"><i style="width:{w}%"></i></span>'
                f'<span class="bv">{fmt(v)}</span></div>')
    return out


def card(title, content, wide=False):
    return f'<section class="card{" wide" if wide else ""}"><h2>{e(title)}</h2>{content}</section>'


cards = []

# --- Summary tiles
month = today.strftime("%Y-%m")
due_total = q("SELECT COALESCE(SUM(amount),0) FROM bills WHERE status IN ('due','overdue')")[0][0]
overdue_n = q("SELECT COUNT(*) FROM bills WHERE status='overdue' OR (status='due' AND due_date < ?)",
              today.isoformat())[0][0]
due30 = q("SELECT COALESCE(SUM(amount),0) FROM bills WHERE status='due' AND due_date BETWEEN ? AND ?",
          today.isoformat(), (today + dt.timedelta(days=30)).isoformat())[0][0]
invested = q("SELECT COALESCE(SUM(invested),0) FROM v_investment_flows")[0][0]
tiles = [("Unpaid bills", money(due_total)), ("Due next 30 days", money(due30)),
         ("Overdue", str(overdue_n)), ("Moved to investments (all time)", money(invested))]
tiles_html = "".join(f'<div class="tile"><div class="tv">{v}</div><div class="tl">{e(l)}</div></div>'
                     for l, v in tiles)

# --- Bills
rows = []
for n, v, a, d, s in q("SELECT name,vendor,amount,due_date,status FROM bills "
                       "WHERE status IN ('due','overdue') OR due_date >= ? ORDER BY due_date",
                       f"{month}-01"):
    st = _Raw(tag(days_to(d))) if s != "paid" else _Raw('<span class="pill">paid</span>')
    rows.append((n, v, money(a), d, st))
cards.append(card("Bills", table(["Bill", "Vendor", "Amount", "Due", "Status"], rows, num=(2,)), wide=True))

# --- Cashflow (last 12 months)
cf = q("SELECT month,income,operating_net,invested FROM v_monthly_cashflow ORDER BY month DESC LIMIT 12")[::-1]
cards.append(card("Operating net by month", bars([(m, on) for m, _, on, _ in cf])))
cards.append(card("Income by month", bars([(m, i) for m, i, _, _ in cf])))

# --- Spending by category (latest month with data)
lm = q("SELECT MAX(substr(txn_date,1,7)) FROM transactions")[0][0]
if lm:
    import ledger_data  # the one spending rule
    by = {}
    for t in ledger_data.spend_lines(con, lm + "-01", lm + "-31"):
        by[t["category"] or "Uncategorized"] = by.get(t["category"] or "Uncategorized", 0) - t["cents"]
    cat = sorted(((c, round(v / 100, 2)) for c, v in by.items()), key=lambda x: -x[1])[:12]
    cards.append(card(f"Spending by category — {lm}", bars(cat)))

# --- Card payments & investments
cp = q("SELECT month,payee,paid FROM v_card_payments ORDER BY month DESC, paid DESC LIMIT 12")
cards.append(card("Card payments (recent)", table(["Month", "Card", "Paid"],
               [(m, p, money(x)) for m, p, x in cp], num=(2,))))
inv = q("SELECT month,payee,invested,cumulative_payee FROM v_investment_flows ORDER BY month DESC, payee LIMIT 12")
cards.append(card("Investment transfers (recent)", table(["Month", "To", "Moved", "Cumulative"],
               [(m, p, money(x), money(c)) for m, p, x, c in inv], num=(2, 3))))

# --- Insurance
pol = q("SELECT kind,carrier,policy_last4,term_end,premium_total,change_pct FROM v_policy_premium_history "
        "WHERE term_end >= ? ORDER BY term_end", today.isoformat())
rows = [(k, c, f"x{l}", t, money(p), "" if ch is None else f"{ch:+.1f}%",
         _Raw(tag(days_to(t)))) for k, c, l, t, p, ch in pol]
cards.append(card("Insurance terms", table(["Kind", "Carrier", "Policy", "Ends", "Premium", "YoY", "Renews"],
               rows, num=(4, 5)), wide=True))

# --- Vehicles
veh = q("SELECT year,make,model,registration_expires,inspection_expires FROM vehicles WHERE status='active'")
rows = [(f"{y} {mk} {md}", rg, _Raw(tag(days_to(rg))), ins, _Raw(tag(days_to(ins))))
        for y, mk, md, rg, ins in veh]
cards.append(card("Vehicles", table(["Vehicle", "Registration", "", "Inspection", ""], rows)))

# --- Appointments / events / subscriptions
ap = q("SELECT person,provider,purpose,appt_datetime FROM appointments WHERE appt_datetime >= ? "
       "ORDER BY appt_datetime LIMIT 10", today.isoformat())
cards.append(card("Appointments", table(["Who", "Provider", "Purpose", "When"], ap)))
ev = q("SELECT name,event_date FROM events ORDER BY event_date LIMIT 10")
cards.append(card("Annual events", table(["Event", "Date"], ev)))
sub = q("SELECT name,amount,frequency,next_renewal FROM subscriptions WHERE active=1 ORDER BY next_renewal")
cards.append(card("Subscriptions", table(["Name", "Amount", "Freq", "Next renewal"],
               [(n, money(a), f, r) for n, a, f, r in sub], num=(1,))))
iv = q("SELECT name,kind,invested,current_value,as_of FROM investments ORDER BY name")
cards.append(card("Investments", table(["Name", "Kind", "Invested", "Value", "As of"],
               [(n, k, money(i), money(c), a) for n, k, i, c, a in iv], num=(2, 3))))

page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{brand.PRODUCT} dashboard</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#1c1f24;--mut:#6b7280;--bd:#e3e6ea;--ac:#3b6fd4;--ok:#1f8a4c;--warn:#b7791f;--bad:#c0392b}}
@media(prefers-color-scheme:dark){{:root{{--bg:#14161a;--card:#1d2026;--fg:#e8eaed;--mut:#9aa1ab;--bd:#2c3038;--ac:#6c9bff;--ok:#4cc38a;--warn:#e0a84a;--bad:#ef6f61}}}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif}}
header{{padding:20px 16px 4px;max-width:1200px;margin:auto}}h1{{margin:0;font-size:22px}}
.sub{{color:var(--mut)}}main{{max-width:1200px;margin:auto;padding:12px 16px 40px;display:grid;gap:14px;
grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}}
.tiles{{grid-column:1/-1;display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}}
.tile,.card{{background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:14px}}
.tv{{font-size:24px;font-weight:600}}.tl{{color:var(--mut);font-size:12px}}
.card.wide{{grid-column:1/-1}}h2{{margin:0 0 10px;font-size:14px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}}
table{{width:100%;border-collapse:collapse}}th,td{{text-align:left;padding:5px 8px;border-bottom:1px solid var(--bd)}}
th{{color:var(--mut);font-weight:500;font-size:12px}}td.n,th.n{{text-align:right;font-variant-numeric:tabular-nums}}
.pill{{padding:1px 8px;border-radius:99px;font-size:12px;border:1px solid var(--bd);color:var(--mut)}}
.pill.ok{{color:var(--ok);border-color:var(--ok)}}.pill.warn{{color:var(--warn);border-color:var(--warn)}}.pill.bad{{color:var(--bad);border-color:var(--bad)}}
.bar{{display:grid;grid-template-columns:90px 1fr 90px;gap:8px;align-items:center;margin:3px 0}}
.bl{{color:var(--mut);font-size:12px}}.bt{{background:var(--bd);height:10px;border-radius:5px;overflow:hidden}}
.bt i{{display:block;height:100%;background:var(--ac)}}.bv{{text-align:right;font-variant-numeric:tabular-nums}}
.muted{{color:var(--mut)}}
</style></head><body>
<header><h1>{brand.PRODUCT}</h1><div class="sub">Generated {today.isoformat()} · stored on this PC</div></header>
<main><div class="tiles">{tiles_html}</div>{"".join(cards)}</main></body></html>"""

out = paths.REPORTS / "dashboard.html"
out.parent.mkdir(exist_ok=True)
out.write_text(page, encoding="utf-8")
print(out)
