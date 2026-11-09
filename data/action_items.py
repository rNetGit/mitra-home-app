"""Shared 'what needs attention' logic for the app (Today, Brief) and the weekly digest.

All functions take an open sqlite3 connection (read-only is fine) and today's date, and return plain
dicts/lists so callers can render them as web pages or markdown.
"""
import datetime as dt
import sqlite3
import db  # noqa: E402
from dates import parse as _d, add_months  # noqa: E402
from money import fmt as _fmt  # noqa: E402
import paths  # noqa: E402


def _rows(con, sql, params=()):
    con.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in con.execute(sql, params).fetchall()]
    except sqlite3.OperationalError as e:  # table not created yet
        if not db.missing(e):
            raise
        return []


def collect_items(con, today, horizon, raw=False):
    """Dated things due/expiring from (overdue) up to today+horizon. Each item: date, kind, title, detail, amount,
    ref = (table, row id) when it comes from one database row (None otherwise), key and id (action_state); a family event
    at a time of day also has at = (start, end or None) as 'HH:MM' (the .ics file's start and end).
    raw=True returns hidden (done/snoozed/ignored) items too."""
    end = today + dt.timedelta(days=horizon)
    items = []

    def add(d, kind, title, detail="", amount=None, ref=None, at=None):
        if d and d <= end:
            items.append({"date": d, "kind": kind, "title": title, "detail": detail, "amount": amount, "ref": ref,
                          **({"at": at} if at else {})})

    for r in _rows(con, "SELECT id, name, vendor, amount, due_date FROM bills WHERE status IN ('due','overdue')"):
        add(_d(r["due_date"]), "Bill", r["vendor"] or r["name"], r["name"], r["amount"], ("bills", r["id"]))
    for r in _rows(con, "SELECT id, person, provider, purpose, appt_datetime, followup_due FROM appointments"):
        d = _d(r["appt_datetime"])
        if d and d >= today:
            add(d, "Appointment", f"{r['purpose'] or 'Appointment'} ({r['person']})",
                f"{r['provider'] or ''} {str(r['appt_datetime'])[11:16]}".strip(), ref=("appointments", r["id"]))
        f = _d(r["followup_due"])
        if f and f >= today:
            add(f, "Appointment", f"Follow-up: {r['purpose'] or ''} ({r['person']})", r["provider"] or "", ref=("appointments", r["id"]))
    for r in _rows(con, "SELECT id, kind, carrier, policy_last4, term_end, premium_total FROM policies "
                        "WHERE status IS NULL OR status NOT IN ('expired','replaced','cancelled','superseded')"):
        add(_d(r["term_end"]), "Renewal", f"{r['carrier']} {r['kind']} policy x{r['policy_last4']} term ends",
            "Review before renewal: compare premium and coverage", r["premium_total"], ("policies", r["id"]))
    try:
        import expiries as _ex
        vlead = {"registration": _ex.lead_days("vehicle_registration"), "inspection": _ex.lead_days("vehicle_inspection")}
        wlead = _ex.lead_days("wallet_card")
    except ImportError:
        vlead = {"registration": horizon, "inspection": horizon}
        wlead = horizon
    for r in _rows(con, "SELECT id, year, make, model, registration_expires, inspection_expires FROM vehicles "
                        "WHERE status='active'"):
        for label, v in (("registration", r["registration_expires"]), ("inspection", r["inspection_expires"])):
            d = _d(v)
            if d and d - dt.timedelta(days=vlead[label]) <= today:  # inside its reminder window (data/expiries.py)
                add(d, "Renewal", f"{r['year']} {r['make']} {r['model']} {label} expires", ref=("vehicles", r["id"]))
    for r in _rows(con, "SELECT id, title, member, expires FROM wallet_cards WHERE status='active' AND expires IS NOT NULL"):
        d = _d(r["expires"])  # a membership, library or health card from the Wallet, inside its reminder window
        if d and d - dt.timedelta(days=wlead) <= today:
            add(d, "Renewal", f"{r['title']} card expires" + (f" ({r['member']})" if r["member"] else ""), "Wallet",
                ref=("wallet_cards", r["id"]))
    try:
        import subscriptions as _subs
        for s in _subs.tracked(con, today):
            sref = ("subscriptions", s["id"])
            if s["decision"] == "cancel" and s["next"] and s["status"] in ("active", "STILL CHARGING after cancel"):
                add(s["next"], "Cancel", f"CANCEL before next charge: {s['name']}",
                    f"{s['paid_with']} - you marked this to cancel", s["last_amount"], sref)
            elif s["status"] == "STILL CHARGING after cancel":
                add(today, "Cancel", f"STILL BEING CHARGED after cancel: {s['name']}",
                    f"last charge {s['last_date']} on {s['paid_with']}: dispute or contact the vendor", s["last_amount"], sref)
            elif s["tracked_active"] and s["status"] == "active" and s["next"]:
                add(s["next"], "Renewal", f"Subscription: {s['name']}", s["paid_with"], s["last_amount"], sref)
            if s["price_note"] and s["status"] == "active":
                add(today, "Subscription", f"Price change: {s['name']}", s["price_note"], s["last_amount"], sref)
    except sqlite3.OperationalError as e:  # subscription columns not migrated yet
        if not db.missing(e):
            raise
        pass
    for r in _rows(con, "SELECT id, name, current_value, invested, maturity_date FROM investments"):
        val = r["current_value"] if r["current_value"] else r["invested"]
        d = _d(r["maturity_date"])
        if d and d >= today - dt.timedelta(days=3):
            add(d, "Investment", f"{r['name']} matures", "Reinvest or withdraw?", val, ("investments", r["id"]))
    for r in _rows(con, "SELECT id, name, event_date, recurs_yearly, start_time, end_time FROM events"):
        base = _d(r["event_date"])
        if not base:
            continue
        # a time goes in the detail as 24-hour text, which Today reads for its timeline (today_data._time)
        at = (r["start_time"], r["end_time"]) if r["start_time"] else None
        detail = (r["start_time"] + (f"-{r['end_time']}" if r["end_time"] else "")) if at else ""
        if not r["recurs_yearly"]:
            if today <= base:
                add(base, "Event", r["name"], detail, ref=("events", r["id"]), at=at)
            continue
        for y in (today.year, today.year + 1):
            try:
                d = base.replace(year=y)
            except ValueError:
                d = dt.date(y, 2, 28)
            if today <= d:
                add(d, "Event", r["name"], detail, ref=("events", r["id"]), at=at)
    try:
        import benefits as _ben
        for b in _ben.status(con, today):
            if b["current_open"]:
                basis = "billing cycle" if b["reset_basis"] == "statement" else "month"
                est = " (estimated close)" if b["period_estimated"] else ""
                add(b["period_end"], "Benefit", f"Use {b['acct']} {b['name']} ({_fmt(b['amount'], 0)}) before {b['period_end']:%b %d}",
                    f"Not used yet this {basis} ({b['period_start']:%b %d} - {b['period_end']:%b %d}){est}. "
                    "Pay with the card; the credit posts the same day", b["amount"], ("card_benefits", b.get("id")))
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        pass
    # Optional modules (each exposes alerts(con, today) -> [{date, kind, title, detail, amount}]); skipped if not migrated yet.
    for modname in ("spikes", "id_docs", "assets", "vehicle_log", "contracts", "shopping", "members", "life", "loans", "home_office",
                    "saved", "work", "activities"):
        try:
            mod = __import__(modname)
            for a in mod.alerts(con, today):
                add(a["date"], a["kind"], a["title"], a.get("detail", ""), a.get("amount"), a.get("ref"))
        except ImportError:
            pass
        except sqlite3.OperationalError as e:
            if not db.missing(e):  # only "not migrated yet" is skipped; a locked database is an error, not "nothing due"
                raise
    for r in recurring_rows(con, today):
        if r["next_due"] and r["next_due"] <= end:
            add(r["next_due"], r["category"] or "Recurring", f"{r['name']} ({r['who']})", r["provider"] or "",
                ref=("recurring_items", r.get("id")))
    # warranties: assets.alerts above (kind "Warranty", lead from data/expiries.py); 0.26 and earlier also added a
    # second "Home" row here, which doubled every warranty inside 90 days.
    items.sort(key=lambda i: (i["date"], i["kind"]))
    import action_state as _as
    if raw:
        return _as.attach(items)
    return _as.filter(con, items, today)  # attaches item["key"] / item["id"]; hides done/snoozed/ignored


def season_state(task, logs, today):
    """-> (state, window_start, window_end, last_done). state: done|now|soon|missed|later"""
    sm, sd = map(int, task["start_md"].split("-"))
    em, ed = map(int, task["end_md"].split("-"))
    win = None
    for y in (today.year - 1, today.year, today.year + 1):
        s = dt.date(y, sm, sd)
        e = dt.date(y + (1 if (em, ed) < (sm, sd) else 0), em, ed)
        if e + dt.timedelta(days=21) >= today:
            win = (s, e)
            break
    s, e = win
    done = [d for d in (_d(x) for x in logs.get(task["id"], []))
            if d and s - dt.timedelta(days=45) <= d <= e + dt.timedelta(days=21)]
    last = max(done) if done else None
    if done:
        return "done", s, e, last
    if s <= today <= e:
        return "now", s, e, last
    if today < s:
        return ("soon" if (s - today).days <= int(task["lead_days"] or 21) else "later"), s, e, last
    return "missed", s, e, last


def seasonal_rows(con, today):
    tasks = _rows(con, "SELECT * FROM seasonal_tasks WHERE active=1")
    logs = {}
    for r in _rows(con, "SELECT task_id, done_date FROM seasonal_log"):
        logs.setdefault(r["task_id"], []).append(r["done_date"])
    out = []
    for t in tasks:
        try:
            state, s, e, last = season_state(t, logs, today)
        except (ValueError, TypeError):
            continue  # malformed start_md/end_md on one task must not break every view
        out.append({**t, "state": state, "start": s, "end": e, "last_done": last})
    order = ["now", "missed", "soon", "later", "done"]
    out.sort(key=lambda x: (order.index(x["state"]), x["start"]))
    return out


def recurring_rows(con, today):
    """Recurring interval items with computed next_due (None = needs a date)."""
    out = []
    for r in _rows(con, "SELECT * FROM recurring_items WHERE active=1"):
        last = _d(r["last_done"])
        nxt = add_months(last, r["interval_months"]) if last else None
        if nxt is None:
            status = "needs a date"
        elif nxt < today:
            status = "overdue"
        elif (nxt - today).days <= 30:
            status = "due soon"
        else:
            status = "ok"
        out.append({**r, "last": last, "next_due": nxt, "status": status})
    out.sort(key=lambda x: (x["next_due"] is None, x["next_due"] or dt.date.max, x["name"]))
    return out


def backup_status(root, today):
    """Newest DB backup per destination -> [(label, newest_date or None, age_days or None, path)].
    Destinations: the same-drive folder next to the project, plus backup_dest from config/family.json."""
    import pathlib
    import config
    root = pathlib.Path(root)
    dests = [("same-drive", paths.BACKUPS)]
    other = (config.family().get("backup_dest") or "").strip()
    if other:
        dests.append(("other device", pathlib.Path(other)))
    out = []
    for label, p in dests:
        newest = None
        for f in (p / "db").glob("family_*.db*") if (p / "db").exists() else []:
            d = dt.date.fromtimestamp(f.stat().st_mtime)
            newest = d if newest is None or d > newest else newest
        out.append((label, newest, (today - newest).days if newest else None, str(p)))
    return out


def when_label(d, today):
    n = (d - today).days
    if n < 0:
        return f"OVERDUE {-n}d"
    return "Today" if n == 0 else ("Tomorrow" if n == 1 else f"in {n}d")
