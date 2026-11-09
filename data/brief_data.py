"""What the Brief shows, with no web code: the snapshot of computed collections, the three lists (Needs you,
Coming up, Week / Month by day) and the one-tap actions (Done, Snooze, Hide). Used by the web app (webapp/app.py).

Rows are plain dicts: src (item | seasonal | backup | task | info), date, kind, title, detail, amount, key (the alert key
Snooze / Hide use; None for rows that cannot be hidden) and sid (a stable id for widgets).
"""
import datetime as dt

import action_items as ai
import agent_profile
import dashboard_actions as da
import db
import edit_actions as ea
import paths
import statement_watch as sw
import subscriptions as subs

try:  # household add-ons: optional so the Brief still opens without them
    import contracts as contracts_mod
    import calendar_days as days_mod
except ImportError:  # pragma: no cover
    days_mod = contracts_mod = None

ROOT = paths.ROOT
HORIZON_MAX = 180
WEEK, MONTH = 7, 30


class Context:
    """today, the person, the snapshot and the special-days module; what every list below needs."""

    def __init__(self, today, user, snapshot, version=""):
        self.today, self.user, self.snap, self.version = today, user, snapshot, version
        self.days = days_mod
        self.contracts_mod = contracts_mod
        self.root = ROOT

    def items(self, horizon):
        end = self.today + dt.timedelta(days=horizon)
        return [i for i in self.snap["items"] if i["date"] <= end]


def build_snapshot(today):
    """Everything the pages compute from the database, once (the dashboard caches it per database change and day)."""
    con = db.connect(paths.DB, readonly=True)
    try:
        items = ai.collect_items(con, today, HORIZON_MAX)
        seas = ai.seasonal_rows(con, today)
        rec = ai.recurring_rows(con, today)
        watch = sw.watch(con, today)
        hidden = da.hidden_keys(con, today)
        try:
            trk = subs.tracked(con, today)
            cands = subs.detect(con, today)
        except Exception:  # noqa: BLE001
            trk, cands = [], []
        contracts = contracts_mod.rows(con, today) if contracts_mod else []
    finally:
        con.close()
    return {"items": items, "seas": seas, "rec": rec, "watch": watch, "hidden": hidden, "trk": trk, "cands": cands,
            "contracts": contracts}


def _item(i):
    ref = i.get("ref")
    return {"src": "item", "date": i["date"], "kind": i["kind"], "title": i["title"], "detail": i["detail"],
            "amount": i["amount"], "key": i["key"], "it": i, "sid": f"{ref[0]}{ref[1]}" if ref and ref[1] else i["id"]}


def _season(s, today):
    if s["state"] == "now":
        d, detail = today, f"Window open {s['start']:%b %d} to {s['end']:%b %d}."
    elif s["state"] == "missed":
        d, detail = s["end"], f"The window ended {s['end']:%b %d} and it is not logged as done."
    else:
        d, detail = s["start"], f"Window {s['start']:%b %d} to {s['end']:%b %d}."
    return {"src": "seasonal", "date": d, "kind": "Seasonal", "title": s["name"], "amount": None, "id": s["id"],
            "sid": f"seasonal{s['id']}",
            "detail": " ".join(x for x in (detail, s.get("notes") or "") if x),
            "key": da.alert_key("seasonal", s["name"], today.year)}


def _festivals(ctx, start, end):
    """Holidays, festivals and school days off that start between start and end (calendar_days.py)."""
    if not ctx.days:
        return []
    return [{"src": "info", "date": r["start"], "kind": r["kind"], "title": ctx.days.title(r), "amount": None, "key": None,
             "detail": ctx.days.span(r), "sid": f"day{r['start']:%m%d}{i}"}
            for i, r in enumerate(ctx.days.between(start, end)) if start <= r["start"] <= end]


def _watched(rows):
    prof = agent_profile.get()
    return [r for r in rows if agent_profile.watched(r["kind"], prof)]


def needs_you(ctx):
    """Overdue and due today, seasonal windows open or missed, an old backup, a scheduled task that stopped."""
    today, hidden = ctx.today, ctx.snap["hidden"]
    rows = [_item(i) for i in ctx.items(0)]
    rows += [r for r in (_season(s, today) for s in ctx.snap["seas"] if s["state"] in ("now", "missed"))
             if r["key"] not in hidden]
    for label, newest, age, _path in ai.backup_status(ROOT, today):
        k = da.alert_key("backup", label)
        if k not in hidden and (newest is None or age > 9):
            rows.append({"src": "backup", "date": today, "kind": "Backup", "key": k, "amount": None, "sid": f"bak{label}",
                         "title": f"The {label} backup is " + ("missing" if newest is None else f"{age} days old"),
                         "detail": "A copy of the family database is made every Sunday. Back up now makes one today."})
    try:
        import heartbeat as hb
        stale = hb.stale(today)
    except Exception:  # noqa: BLE001 (the brief must still open)
        stale = []
    for t, m in stale:
        k = da.alert_key("task", t)
        if k not in hidden:
            rows.append({"src": "task", "date": today, "kind": "Task", "key": k, "amount": None, "sid": f"task{t}",
                         "title": f"The {t.replace('_', ' ')} job has not run",
                         "detail": f"{m}. The health check in Settings shows why."})
    rows.sort(key=lambda r: r["date"])
    return _watched(rows)


def needs_you_overdue(ctx):
    """Watched items that are overdue (the dot on Brief in the rail)."""
    prof = agent_profile.get()
    return [i for i in ctx.items(0) if i["date"] < ctx.today and agent_profile.watched(i["kind"], prof)]


def coming_up(ctx, start, end):
    """Rows dated start..end (inclusive): items, seasonal windows that open then, festivals."""
    hidden = ctx.snap["hidden"]
    rows = [_item(i) for i in ctx.items((end - ctx.today).days) if start <= i["date"]]
    rows += [r for r in (_season(s, ctx.today) for s in ctx.snap["seas"] if s["state"] in ("soon", "later"))
             if start <= r["date"] <= end and r["key"] not in hidden]
    rows += _festivals(ctx, start, end)
    rows.sort(key=lambda r: (r["date"], r["kind"]))
    return _watched(rows)


def tiles(ctx):
    """Only the numbers that are not zero, as (label, value, is_money)."""
    today = ctx.today
    prof = agent_profile.get()
    items = [i for i in ctx.items(MONTH) if agent_profile.watched(i["kind"], prof)]
    over = sum(1 for i in items if i["date"] < today)
    week = sum(1 for i in items if today <= i["date"] <= today + dt.timedelta(days=WEEK))
    bills = sum((i["amount"] or 0) for i in items if i["kind"] == "Bill" and i["date"] >= today)
    out = []
    if over:
        out.append(("Overdue", over, False))
    if week:
        out.append(("Next 7 days", week, False))
    if bills:
        out.append(("Bills due in 30 days", bills, True))
    return out


def when(r, today):
    return ai.when_label(r["date"], today) if r["src"] in ("item", "info") or r["date"] != today else "Now"


def sections(ctx, view):
    """[(heading, [rows])] for 'today', 'week' or 'month'; headings with no rows are left out."""
    today = ctx.today
    day = dt.timedelta(days=1)
    out = []
    if view == "week":
        out.append(("Overdue", [r for r in needs_you(ctx) if r["date"] < today]))
        rows = coming_up(ctx, today, today + dt.timedelta(days=WEEK - 1))
        for i in range(WEEK):
            d = today + i * day
            out.append((f"{d:%a %b %d}" + (" · today" if i == 0 else ""), [r for r in rows if r["date"] == d]))
    elif view == "month":
        out.append(("Overdue", [r for r in needs_you(ctx) if r["date"] < today]))
        rows = coming_up(ctx, today, today + dt.timedelta(days=MONTH))
        for w in range(0, MONTH + 1, WEEK):
            a, b = today + w * day, min(today + (w + WEEK - 1) * day, today + MONTH * day)
            title = "This week" if w == 0 else ("Next week" if w == WEEK else f"{a:%b %d} to {b:%b %d}")
            out.append((title, [r for r in rows if a <= r["date"] <= b]))
    else:
        out.append(("Needs you", needs_you(ctx)))
        out.append(("Coming up", coming_up(ctx, today + day, today + dt.timedelta(days=WEEK))))
    return [(h, rows) for h, rows in out if rows]


def find(ctx, key):
    """The row whose key is `key` in any list the person can see (the client names a row, the server looks it up)."""
    today = ctx.today
    for r in needs_you(ctx) + coming_up(ctx, today, today + dt.timedelta(days=MONTH)):
        if r.get("key") == key:
            return r
    return None


# ---- actions ---------------------------------------------------------------------------------------------------
def _paid(ctx, it):
    r = it.get("ref")
    if r and r[0] == "bills":
        return da.mark_bill_paid_by_id(r[1], ctx.today)
    return da.mark_bill_paid(it["title"], it["date"].isoformat(), ctx.today)


def done(ctx, r):
    """Done / Paid for one row. -> (ok, message, undo) where undo = (bill_id, due_iso, title) after a paid bill."""
    if r["src"] == "seasonal":
        ok, msg = ea.seasonal_done(ctx.user, r["id"])
        return ok, msg, None
    it = r["it"]
    ref = it.get("ref") or (None, None)
    if it["kind"] == "Bill":
        bid = _paid(ctx, it)
        if bid is None:
            return False, "This bill is no longer open.", None
        return True, f"Marked {it['title']} as paid.", (bid, it["date"].isoformat(), it["title"])
    if ref[0] == "recurring_items" and ref[1]:
        ok, msg = ea.recurring_done(ctx.user, ref[1])
        return ok, msg, None
    ok, msg = da.hide(r["key"], r["title"], "done", None, ctx.today)
    return ok, "Done." if ok else msg, None


def undo_paid(ctx, bill_id, due_iso):
    da.undo_bill_paid(bill_id, due_iso, ctx.today)
