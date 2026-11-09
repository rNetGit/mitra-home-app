"""App actions: hide (snooze / ignore / done) items and alerts, mark a bill paid, restore. Everything is stored in the small `action_state` table (see
action_state.py) and, for bills only, the `bills` row. Keys are stable per item/alert so a hidden thing stays hidden.

Keys: items from the digests carry `key` = `<table>:<row id>:<date>` (action_state.py); alerts use alert_key().
Rules:
  * Alerts about failures that could cost you data (old backup, a stopped scheduled task) may be snoozed up to 7 days but
    never ignored for good: a real failure should come back.
  * Seasonal alerts are keyed by year, so ignoring one this year does not hide next year's.
  * "Paid" on a bill sets bills.status='paid' (undo puts it back); the bills agent does the same when it reads a receipt.
"""
import datetime as dt
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import action_state  # noqa: E402
import db  # noqa: E402
import dates  # noqa: E402

SNOOZE_ONLY = {"backup", "task"}
MAX_SNOOZE = 7
DEFAULT_SNOOZE = 7


def alert_key(kind, *parts):
    return ":".join(["alert", kind, *[str(p) for p in parts]])[:120]


def _db():
    return action_state.DB


def hidden_keys(con, today):
    """Keys currently hidden: done / ignored, or snoozed until a date on or after today."""
    try:
        rows = con.execute("SELECT key, state, until FROM action_state").fetchall()
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return set()
    out = set()
    for k, s, u in rows:
        if s in ("done", "ignored"):
            out.add(k)
        elif s == "snoozed" and u:
            try:
                if dt.date.fromisoformat(str(u)[:10]) >= today:
                    out.add(k)
            except ValueError:
                pass  # a bad date in the table must not break the dashboard
    return out


def hide(key, title, mode, days=None, today=None):
    """mode: snooze | ignore | done. Returns (ok, message)."""
    today = today or dates.today()
    parts = key.split(":")
    kind = parts[1] if key.startswith("alert:") and len(parts) > 1 else ""
    if mode == "snooze":
        n = max(1, int(days or DEFAULT_SNOOZE))
        if kind in SNOOZE_ONLY:
            n = min(n, MAX_SNOOZE)
        action_state.set_state(key, "snoozed", (today + dt.timedelta(days=n)).isoformat(), title)
        return True, f"hidden for {n} day(s)"
    if mode in ("ignore", "done"):
        if kind in SNOOZE_ONLY:
            return False, f"this alert can only be snoozed for up to {MAX_SNOOZE} days"
        action_state.set_state(key, "ignored" if mode == "ignore" else "done", None, title)
        return True, "hidden"
    return False, "unknown action"


def restore(key):
    action_state.reset(key)


def handled_rows(con, today):
    """What is hidden right now, for the Restore list: [{key, state, until, title, set_at}]."""
    try:
        rows = con.execute("SELECT key, state, until, COALESCE(title,''), COALESCE(set_at,'') FROM action_state "
                           "ORDER BY set_at DESC").fetchall()
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []
    keep = hidden_keys(con, today)
    return [{"key": k, "state": s, "until": u or "", "title": t, "set_at": a} for k, s, u, t, a in rows if k in keep]


def mark_bill_paid_by_id(bill_id, today=None):
    """Mark one open bill paid by its row id. Returns the id, or None when it is not an open bill."""
    today = today or dates.today()
    con = db.connect(_db(), timeout=10)
    try:
        n = con.execute("UPDATE bills SET status='paid', paid_date=? WHERE id=? AND status IN ('due','overdue')",
                        (today.isoformat(), bill_id)).rowcount
        con.commit()
        return bill_id if n == 1 else None
    finally:
        con.close()


def mark_bill_paid(vendor_or_name, due_iso, today=None):
    """Mark the matching open bill paid by vendor + due date (older callers). Returns its id, or None if no single
    open bill matches; the dashboard uses mark_bill_paid_by_id with the item's row id instead."""
    today = today or dates.today()
    con = db.connect(_db(), timeout=10)
    try:
        ids = [r[0] for r in con.execute(
            "SELECT id FROM bills WHERE status IN ('due','overdue') AND COALESCE(vendor,name)=? AND due_date=?",
            (vendor_or_name, due_iso))]
        if len(ids) != 1:
            return None
        con.execute("UPDATE bills SET status='paid', paid_date=? WHERE id=?", (today.isoformat(), ids[0]))
        con.commit()
        return ids[0]
    finally:
        con.close()


def undo_bill_paid(bill_id, due_iso, today=None):
    today = today or dates.today()
    status = "overdue" if due_iso < today.isoformat() else "due"
    con = db.connect(_db(), timeout=10)
    try:
        con.execute("UPDATE bills SET status=?, paid_date=NULL WHERE id=? AND status='paid'", (status, bill_id))
        con.commit()
    finally:
        con.close()
