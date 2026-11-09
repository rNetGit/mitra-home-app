"""One-screen phone snapshot -> brief/YYYY-MM-DD_this_week.md ('what needs me this week').

  python data/make_this_week.py        then:  python data/sync_drive.py push   (phone-sized PDF in Drive Brief/)
Overdue + next 7 days (everything action_items collects: bills, renewals, cancels, spikes, ID/warranty/vehicle alerts),
subscription run-rate, and statements to drop. Aggregates only; last4 at most.
"""
import datetime as dt
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import action_items as ai  # noqa: E402
import statement_watch as sw  # noqa: E402
import subscriptions as subs  # noqa: E402
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


items = [i for i in ai.collect_items(con, today, 7) if i["kind"] != "Class"]  # classes: their own section below
over = [i for i in items if i["date"] < today]
L = [f"# This week - {today:%a %b %d}", "",
     f"**{len(over)} overdue, {len(items) - len(over)} due in the next 7 days.**", "",
     "## Needs me", "",
     tbl(["Id", "When", "Item", "Amount"],
         [(i["id"], ai.when_label(i["date"], today), f"{i['kind']}: {i['title']}", money(i["amount"]) if i["amount"] else "") for i in items]), ""]
try:
    sm = subs.summary(subs.tracked(con, today))
    L += ["## Subscriptions", "", f"{sm['count']} still charging, about {money(sm['per_month'])}/month.", ""]
except sqlite3.OperationalError as e:
    if not db.missing(e):
        raise
    pass
try:  # weekly classes and days off; the family's tradition days stay off this page (it may go to Drive)
    import activities
    import calendar_days as cdays
    week = [(o["date"], f"{o['date']:%a %b %d}", f"Class: {o['label']}") for o in
            activities.occurrences(con, today, today + dt.timedelta(days=6))]
    week += [(r["start"], cdays.span(r), f"{r['kind']}: {cdays.title(r)}") for r in
             cdays.between(today, today + dt.timedelta(days=6), con, shared=True)]
except sqlite3.OperationalError:
    week = []
if week:
    L += ["## Classes and days off", "", tbl(["When", "What"], [(w, t) for _, w, t in sorted(week)]), ""]
sw_rows = [r for r in sw.watch(con, today) if r["status"] in ("due now", "overdue")]
if sw_rows:
    L += ["## Statements to drop", "", ", ".join(f"{r['account']} x{r['last4']}" for r in sw_rows), ""]
out = paths.BRIEF / f"{today.isoformat()}_this_week.md"
out.parent.mkdir(exist_ok=True)
out.write_text("\n".join(L), encoding="utf-8")
print(out)
