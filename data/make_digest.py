"""Weekly household digest -> brief/YYYY-MM-DD_weekly_digest.md (phone-friendly markdown).

  python data/make_digest.py            then:  python data/sync_drive.py push   (copies brief/ to Drive for the phone)
Sections: Do now, Next 30 days, Holidays, festivals and days off (not the family's tradition days: this file goes
to Drive), Classes this week, Seasonal alerts, Statements to drop, Needs a date, Subscription candidates,
Card spend snapshot, Net position, Data check (score and findings), Open questions. Aggregates only: last4 for accounts, no raw statements.
"""
import datetime as dt
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import action_items as ai  # noqa: E402
import statement_watch as sw  # noqa: E402
import subscriptions as subs  # noqa: E402
import activities  # noqa: E402
import calendar_days as cdays  # noqa: E402
import db  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = HERE.parent
today = dates.today()
con = db.connect(paths.DB, readonly=True)
money = _fmt


def tbl(headers, rows):
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


L = [f"# Weekly Digest - {today:%A, %B %d, %Y}", ""]

items = [i for i in ai.collect_items(con, today, 30) if i["kind"] != activities.KIND]  # classes: their own section
soon = [i for i in items if i["date"] <= today + dt.timedelta(days=7)]
L += ["## Do now (overdue + next 7 days)", "",
      tbl(["Id", "When", "Type", "Item", "Amount"],
          [(i["id"], ai.when_label(i["date"], today), i["kind"], i["title"], money(i["amount"]) if i["amount"] else "") for i in soon]),
      "_Clear an item: tell the assistant `done <Id>` or `snooze <Id> 7 days`._", ""]
later = [i for i in items if i not in soon]
L += ["## Days 8-30", "",
      tbl(["Id", "Date", "Type", "Item", "Amount"],
          [(i["id"], i["date"].isoformat(), i["kind"], i["title"], money(i["amount"]) if i["amount"] else "") for i in later]), ""]

_f = cdays.between(today, today + dt.timedelta(days=30), con, shared=True)  # copied to Drive: no tradition days
if _f:
    L += ["## Holidays, festivals and days off, next 30 days", "",
          tbl(["Date", "Kind", "Day"], [(cdays.span(r), r["kind"], cdays.title(r)) for r in _f]), ""]
try:
    _c = activities.occurrences(con, today, today + dt.timedelta(days=6))
except sqlite3.OperationalError:
    _c = []
if _c:
    L += ["## Classes this week", "",
          tbl(["Day", "Class", "Where"], [(f"{o['date']:%a %b %d}", o["label"], o["provider"]) for o in _c]), ""]

seas = [s for s in ai.seasonal_rows(con, today) if s["state"] in ("now", "missed", "soon")]
lab = {"now": "Due now", "missed": "Missed", "soon": "Coming up"}
L += ["## Seasonal" + (f" ({config.place_label()})" if config.place_label() else ""), "",
      tbl(["Status", "Task", "Window"], [(lab[s["state"]], s["name"], f"{s['start']:%b %d} to {s['end']:%b %d}") for s in seas]), ""]

sw_rows = [r for r in sw.watch(con, today) if r["status"] in ("due now", "overdue") or r["missing"]]
L += ["## Statements to drop in the inbox", "",
      tbl(["Account", "Last statement", "Expected", "Status", "Missing months"],
          [(f"{r['account']} x{r['last4']}", r["last_stmt"], r["expected"], r["status"], ", ".join(r["missing"])) for r in sw_rows]), ""]

try:
    import benefits as ben
    bl = ben.status(con, today)
    if bl:
        L += ["## Card benefits", "",
              tbl(["Benefit", "This billing cycle", "Received", "Missed since first credit"],
                  [(f"{b['acct']} x{b['last4']}: {b['name']} {_fmt(b['amount'], 0)}/cycle",
                    f"NOT USED YET, use before {b['period_end']:%b %d}" if b["current_open"] else "done",
                    f"{b['received_n']}x ({_fmt(b['received'])})", f"{b['lost_n']} ({_fmt(b['lost_amount'])})") for b in bl]), ""]
except sqlite3.OperationalError as e:
    if not db.missing(e):
        raise
    pass

try:
    import expiries as _ex
    ex_soon, ex_need = _ex.soon(con, today), _ex.needs_date(con, today)
except Exception:  # older install without the module, or tables not migrated yet
    ex_soon, ex_need = [], []
if ex_soon or ex_need:
    L += ["## Expiring (inside its reminder window, whatever the date)", "",
          tbl(["Status", "Type", "Who", "What", "Expires"],
              [(r["status"], r["label"], r["who"], r["what"], r["expires"].isoformat()) for r in ex_soon])]
    if ex_need:
        L += [f"No date yet for {len(ex_need)}: " + "; ".join(f"{r['who']} {r['what']}".strip() for r in ex_need[:8])
              + (" ..." if len(ex_need) > 8 else "") + ". Family > Papers & IDs > Expiries and IDs."]
    L += ["_How early each type is reminded: Family > Papers & IDs > Expiries and IDs._", ""]

try:
    import assets as _assets
    inv = _assets.summary(con, today)
except Exception:  # older install without the module, or the table not migrated yet
    inv = None
if inv and inv["count"]:
    L += ["## Household inventory", "",
          f"{inv['count']} items, value {money(inv['value'])} (prices known), {inv['under_warranty']} under warranty"
          + (f", {inv['needs_receipt']} need a receipt" if inv["needs_receipt"] else "")
          + (f", {inv['no_manual']} without a manual" if inv["no_manual"] else "") + ".", ""]

try:
    import lists as _lists
    lst = _lists.summary(con)
except Exception:  # older install without the module
    lst = []
if lst:
    L += ["## Lists", "", "; ".join(f"{n}: {k} to do" for n, k in lst) + ". Family > Home > Lists.", ""]

try:
    import saved as _saved
    sv = _saved.week_line(con, today)
except Exception:  # older install without the module or the table
    sv = None
if sv:
    L += ["## Saved", "", sv + " Family > Home > Saved.", ""]

need = [r for r in ai.recurring_rows(con, today) if r["status"] == "needs a date"]
if need:
    L += ["## Checkups and home tasks that need a date", "",
          "Tell the assistant when each was last done, e.g. '" + config.first_member() + " dental was Sep 3'.", "",
          tbl(["Item", "Who", "Every"], [(r["name"], r["who"], f"{r['interval_months']} mo") for r in need]), ""]

trk = subs.tracked(con, today)
sm = subs.summary(trk)
L += ["## Subscriptions", "",
      f"**{sm['count']} still charging, about {money(sm['per_month'])}/month ({money(sm['per_year'])}/year).**", ""]
todo = [r for r in trk if r["decision"] == "unreviewed" and r["status"] == "active" and r["tracked_active"]]
if todo:
    L += ["Not reviewed yet. Is each one used? Reply keep or cancel for each:", "",
          tbl(["Subscription", "~/month", "~/year", "Paid with", "Next ~"],
              [(r["name"], money(r["per_month"]), money(r["per_year"]), r["paid_with"],
                r["next"] if r["next"] >= today else "likely charged since (newer statement not loaded)") for r in
               sorted(todo, key=lambda r: -r["per_year"])]), ""]
cancel = [r for r in trk if r["decision"] in ("cancel", "cancelled") and r["status"] in ("active", "STILL CHARGING after cancel")]
if cancel:
    L += ["To cancel / still charging after cancel:", "",
          tbl(["Subscription", "Decision", "Status", "Next charge ~", "Paid with"],
              [(r["name"], r["decision"], r["status"], r["next"], r["paid_with"]) for r in cancel]), ""]
chg = [r for r in trk if r["price_note"] and r["status"] == "active"]
if chg:
    L += ["Price changes: " + "; ".join(f"{r['name']} ({r['price_note']})" for r in chg), ""]
stopped = [r for r in trk if r["status"] == "stopped?"]
if stopped:
    L += ["No recent charge (probably ended): " + ", ".join(r["name"] for r in stopped), ""]
try:
    import recurring_bills as rb
    rb_tracked = rb.status(con, today)
    rb_cands = [c for c in rb.detect(con, today) if c["active"]][:5]
except Exception:  # an older install without the module, or no transactions table yet
    rb_tracked, rb_cands = [], []
flagged = [(r["name"], f) for r in rb_tracked for f in r["flags"]]
if flagged or rb_cands:
    L += ["## Recurring bills", ""]
if flagged:
    L += ["Check these: " + "; ".join(f"**{n}** {f}" for n, f in flagged), ""]
if rb_cands:
    L += ["Seen in your statements, not tracked yet (decide each one in the Inbox): "
          + "; ".join(f"{c['payee']} {money(c['amount'])} {c['frequency']}" for c in rb_cands), ""]

try:
    import budget as _bud
    bl = _bud.digest_line(con, today)
except Exception:  # older install without the function, or no budget table yet
    bl = ""
if bl:
    L += ["## Budget this month", "", bl, ""]

# card spend snapshot: last full month
last_full = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
try:
    rows = con.execute("SELECT cardholder, ROUND(SUM(net_spend),2) FROM v_card_spend_monthly WHERE month=? "
                       "GROUP BY cardholder ORDER BY 2 DESC", (last_full,)).fetchall()
    tot = sum(r[1] for r in rows)
    L += [f"## Card spend, {last_full}", "", tbl(["Cardholder", "Net spend"], [(r[0], money(r[1])) for r in rows] + [("Total", money(tot))]), ""]
except sqlite3.OperationalError as e:
    if not db.missing(e):
        raise
    pass

try:
    nw = con.execute("SELECT type, ROUND(SUM(signed_balance),2) FROM v_balance_latest GROUP BY type").fetchall()
    if nw:
        total = sum(r[1] for r in nw)
        L += ["## Net position (latest statement balances)", "",
              tbl(["Type", "Amount"], [(r[0], money(r[1])) for r in nw] + [("Total", money(total))]),
              "_Cards owed are subtracted. Cards loaded from activity exports (no balance line) are not included._", ""]
except sqlite3.OperationalError as e:
    if not db.missing(e):
        raise
    pass

try:  # the weekly data check (data/audit.py runs just before this in the weekly task)
    import audit
    dc = audit.markdown_week(con, today)
    if dc:
        L += ["## Data check", "", dc, ""]
except Exception as e:  # noqa: BLE001 (an older database has no audit tables; the digest still goes out)
    if not isinstance(e, sqlite3.OperationalError) or not db.missing(e):
        raise

out = paths.BRIEF / f"{today.isoformat()}_weekly_digest.md"
out.parent.mkdir(exist_ok=True)
out.write_text("\n".join(L), encoding="utf-8")
print(out)
