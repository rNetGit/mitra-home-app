"""How complete the household profile is, by area, and the questions that fill it in.

Settings > Household profile shows a meter per area (People, Home, Vehicles, Money, Papers, Subscriptions) with
"Answer next". The same gaps become Inbox questions (proposals source "profile"), at most two new ones a day, each
answered in one tap (or one date). No AI.

A check counts as done when the records already hold the answer, or when its Inbox question was answered or dismissed
("Not needed", "No car"), or the first-run interview was told "no car" (household.no_vehicles). "Ask me later" snoozes the question for two weeks.

  python data/profile_gaps.py            the meter and the open gaps
"""
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402

AREAS = [("people", "People"), ("home", "Home"), ("vehicles", "Vehicles"), ("money", "Money"), ("papers", "Papers"),
         ("subs", "Subscriptions")]
SECTION = {"people": "people/people", "home": "home/upkeep", "vehicles": "vehicles/vehicles", "money": "money/accounts",
           "papers": "papers/ids", "subs": "money/subs"}
PER_DAY = 2
LATER_DAYS = 14
# gap kind -> {option: label}; the first is the suggested one. "birthday" needs a date (proposals.NEEDS).
OPTIONS = {
    "birthday": {"birthday": "Add birthday", "later": "Ask me later", "dismiss": "Not needed"},
    "tenure": {"own": "We own it", "rent": "We rent", "later": "Ask me later"},
    "place": {"later": "Ask me later", "dismiss": "Not needed"},
    "vehicles": {"papers": "Yes, I will add its papers", "dismiss": "No car", "later": "Ask me later"},
    "accounts": {"later": "Remind me in two weeks", "dismiss": "Not now"},
    "statement": {"later": "Remind me in two weeks", "dismiss": "Not now"},
    "ids": {"later": "Remind me in two weeks", "dismiss": "Not needed"},
    "insurance": {"later": "Remind me in two weeks", "dismiss": "Not needed"},
    "subs": {"dismiss": "None to track", "later": "Ask me later"},
}


def _has(con, table):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _count(con, sql, args=()):
    try:
        return con.execute(sql, args).fetchone()[0] or 0
    except Exception:  # noqa: BLE001 (a table from an optional migration may be missing)
        return 0


def _answered(con):
    """dedupe_key -> status for profile questions already decided (done or dismissed)."""
    if not _has(con, "proposals"):
        return {}
    return {k: s for k, s in con.execute(
        "SELECT dedupe_key, status FROM proposals WHERE source='profile' AND status IN ('done', 'dismissed')")}


def checks(con, today=None):
    """Every check, in the order questions are asked. Each: area, key, gap, done, summary, detail, payload."""
    today = today or dates.today()
    cfg = config.family()
    hh = cfg.get("household") or {}
    ans = _answered(con)
    out = []

    def add(area, key, gap, have, summary, detail="", payload=None):
        out.append({"area": area, "key": f"profile:{key}", "gap": gap, "done": bool(have) or f"profile:{key}" in ans,
                    "summary": summary, "detail": detail, "payload": {"gap": gap, **(payload or {})}})

    rows = con.execute("SELECT name, role, birth_month_day FROM members ORDER BY id").fetchall() if _has(con, "members") else []
    for name, role, bd in rows:
        if role == "pet":
            continue
        add("people", f"birthday:{name.lower()}", "birthday", bd, f"When is {name}'s birthday?",
            "Birthdays show up on Today a week ahead. The year is optional.", {"member": name})
    reg = cfg.get("region") or {}
    add("home", "tenure", "tenure", hh.get("tenure") in ("own", "rent"), "Do you own or rent your home?",
        "Owners get home upkeep reminders and home-insurance checks; renters get the renters-insurance ones.")
    add("home", "place", "place", reg.get("place") or reg.get("zip"), "Where do you live (town or postal code)?",
        "It picks the right seasonal reminders. Change it in Settings > Household profile > Run the setup interview again.")
    add("vehicles", "vehicles", "vehicles",
        _count(con, "SELECT COUNT(*) FROM vehicles") or hh.get("no_vehicles"), "Does the household have a car?",
        "Drop its registration or insurance card in the Inbox and the car is added from it, with its renewal dates.")
    n_acc = _count(con, "SELECT COUNT(*) FROM accounts")
    add("money", "accounts", "accounts", n_acc, "Add your first bank or card statement",
        "Download it from your bank (PDF or CSV) and drop it in the Inbox. Spending, balances and bills come from it.")
    if n_acc:
        last = con.execute("SELECT MAX(txn_date) FROM transactions").fetchone()[0] if _has(con, "transactions") else None
        fresh = bool(last) and str(last)[:10] >= (today - dt.timedelta(days=45)).isoformat()
        add("money", "statement", "statement", fresh, "Add last month's statements",
            "The newest payment on file is more than six weeks old. Drop the latest statements in the Inbox.")
    add("papers", "ids", "ids", _count(con, "SELECT COUNT(*) FROM id_documents"), "Add passports and driver's licences",
        "Only the type, the last four digits and the expiry date are kept, so you get a reminder before they run out.")
    add("papers", "insurance", "insurance", _count(con, "SELECT COUNT(*) FROM policies"), "Add your insurance papers",
        "Drop the declarations page of the car, home or renters policy in the Inbox to track renewals and coverage.")
    add("subs", "subs", "subs", _count(con, "SELECT COUNT(*) FROM subscriptions"), "Any subscriptions to track?",
        "Streaming, phone, gym, apps: they are also picked up from statements. Add one in Money > Pay > Subscriptions.")
    return out


def meter(con, today=None):
    """-> [{area, label, done, total, pct, next}] where next is the first open check of the area (or None)."""
    cs = checks(con, today)
    out = []
    for area, label in AREAS:
        mine = [c for c in cs if c["area"] == area]
        done = sum(c["done"] for c in mine)
        out.append({"area": area, "label": label, "done": done, "total": len(mine),
                    "pct": round(100 * done / len(mine)) if mine else 100, "next": next((c for c in mine if not c["done"]), None)})
    return out


def overall(con, today=None):
    m = meter(con, today)
    total = sum(x["total"] for x in m)
    return round(100 * sum(x["done"] for x in m) / total) if total else 100


def proposal(c):
    """A check as a proposals row (see proposals._p)."""
    return {"dedupe_key": c["key"], "source": "profile", "kind": "question", "summary": c["summary"], "detail": c["detail"],
            "payload": json.dumps(c["payload"], sort_keys=True), "ref_table": None, "ref_id": None}


def produce(con, today):
    """Proposals producer: open gaps that are already in the Inbox stay; at most PER_DAY new ones a day."""
    if not _has(con, "proposals"):
        return
    have = {k: s for k, s in con.execute("SELECT dedupe_key, status FROM proposals WHERE source='profile'")}
    made_today = _count(con, "SELECT COUNT(*) FROM proposals WHERE source='profile' AND substr(created_at, 1, 10)=?",
                        (today.isoformat(),))
    room = max(0, PER_DAY - made_today)
    for c in checks(con, today):
        if c["done"]:
            continue
        if c["key"] in have:
            yield proposal(c)
        elif room:
            room -= 1
            yield proposal(c)


def ask_now(con, key, today=None):
    """"Answer next" in Settings: put this question in the Inbox now (outside the daily cap). -> proposal id or None."""
    today = today or dates.today()
    c = next((x for x in checks(con, today) if x["key"] == key and not x["done"]), None)
    if not c:
        return None
    import proposals
    row = con.execute("SELECT id, status FROM proposals WHERE dedupe_key=?", (key,)).fetchone()
    now = dt.datetime.now().isoformat(timespec="seconds")
    p = proposal(c)
    with con:
        if row:
            if row[1] not in proposals.LIVE or row[1] == "snoozed":
                con.execute("UPDATE proposals SET status='open', until=NULL, updated_at=? WHERE id=?", (now, row[0]))
            return row[0]
        cur = con.execute("INSERT INTO proposals(dedupe_key, source, kind, summary, detail, payload, ref_table, ref_id, "
                          "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                          (p["dedupe_key"], p["source"], p["kind"], p["summary"], p["detail"], p["payload"], None, None, now, now))
    return cur.lastrowid


def main():
    import db
    con = db.connect(paths.DB, readonly=True)
    try:
        for m in meter(con):
            print(f"{m['label']:<14} {m['done']}/{m['total']}" + (f"   next: {m['next']['summary']}" if m["next"] else ""))
        print(f"Overall {overall(con)}%")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
