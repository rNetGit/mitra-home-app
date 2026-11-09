"""Weekly family-meeting agenda -> brief/YYYY-MM-DD_family_meeting.md (phone-friendly markdown).

  python data/make_family_meeting.py              whole household
  python data/make_family_meeting.py --who Sam    one person's view (items that name them, plus household items)
Sections: decisions needed, next 14 days, birthdays/occasions, overdue, needs a date, budget, debts.
Each row has an Id: tell the assistant "done a1b2c3d4" or "snooze a1b2c3d4 7 days" to clear it (data/action_state.py).
"""
import argparse
import datetime as dt
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import action_items as ai  # noqa: E402
import budget  # noqa: E402
import life  # noqa: E402
import loans  # noqa: E402
import members  # noqa: E402
import subscriptions as subs  # noqa: E402
import db  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = HERE.parent
money = _fmt


def tbl(headers, rows):
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join("" if c is None else str(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def build(con, today, who=None):
    me = members.resolve(con, who) if who else None
    others = [n for n in members.names(con) if n != me]

    def named(person, text):  # whole-word match: "Al" must not match "Allstate"
        return re.search(r"(?<![\w])" + re.escape(person.lower()) + r"(?![\w])", text) is not None

    def mine(it):
        if not me:
            return True
        text = f"{it['title']} {it.get('detail', '')}".lower()
        if named(me, text):
            return True
        return not any(named(o, text) for o in others)  # household items (no other person named)

    items = [i for i in ai.collect_items(con, today, 60) if mine(i)]
    row = lambda i: (i.get("id", ""), ai.when_label(i["date"], today), i["kind"], i["title"], money(i["amount"]) if i["amount"] else "")
    L = [f"# Family meeting - {today:%A, %B %d, %Y}" + (f" ({me})" if me else ""), ""]

    dec = []
    try:
        for r in subs.tracked(con, today):
            if r["decision"] == "unreviewed" and r["status"] == "active" and r["tracked_active"]:
                dec.append((f"Subscription {r['name']} ~{money(r['per_year'])}/yr", "Keep or cancel?"))
            elif r["status"] == "STILL CHARGING after cancel":
                dec.append((f"{r['name']} still charging after cancel", "Dispute / contact vendor"))
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        pass
    for i in items:
        if i["kind"] == "Renewal" and "policy" in i["title"].lower() and i["date"] <= today + dt.timedelta(days=60):
            dec.append((i["title"], "Shop / compare before renewal?"))
    for l in loans.alerts(con, today):
        dec.append((l["title"], l["detail"]))
    L += ["## Decisions needed", "", tbl(["Topic", "Question"], dec), ""]

    soon = [i for i in items if i["date"] <= today + dt.timedelta(days=14) and i["date"] >= today]
    L += ["## Next 14 days", "", tbl(["Id", "When", "Type", "Item", "Amount"], [row(i) for i in soon]), ""]
    L += ["## Birthdays and occasions (30 days)", "",
          tbl(["Id", "When", "Type", "Item", "Amount"],
              [row(i) for i in items if i["kind"] in ("Birthday", "Gift", "Event") and i["date"] <= today + dt.timedelta(days=30)]), ""]
    over = [i for i in items if i["date"] < today]
    L += ["## Overdue", "", tbl(["Id", "When", "Type", "Item", "Amount"], [row(i) for i in over]), ""]

    nd = [r for r in life.needs_date(con) if not me or r["member"] in (None, me)]
    L += ["## Needs a date (tell the assistant when)", "",
          tbl(["Who", "Domain", "Item"], [(r["member"] or "household", r["domain"], r["title"]) for r in nd]), ""]

    last = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m")
    var = [v for v in budget.variance(con, last)]
    if var:
        L += [f"## Budget, {last}", "",
              tbl(["Category", "Limit", "Actual", "Over/under"],
                  [(c, money(l), money(a), ("OVER " if o > 0 else "under ") + money(abs(o))) for c, l, a, o in var]), ""]
    sm = loans.summary(con)
    if sm["count"]:
        L += ["## Debts", "", f"{sm['count']} loan(s), balance about {money(sm['debt'])}, payments about {money(sm['monthly'])}/month.", ""]
    L += ["_Records only, not advice. To clear an item: `done <Id>` or `snooze <Id> 7 days`._", ""]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--who")
    a = ap.parse_args()
    today = dates.today()
    con = db.connect(paths.DB, readonly=True)
    text = build(con, today, a.who)
    suffix = f"_{a.who.lower()}" if a.who else ""
    out = paths.BRIEF / f"{today.isoformat()}_family_meeting{suffix}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
