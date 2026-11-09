"""What `limited` users (children, teens, guests) may see, with no money, no accounts and no AI: their own open life
items in the safe domains, upcoming birthdays and the non-financial items of the next 14 days. Read-only. Used by their
page in the web app (kid_data.py) and by the phone bot (chat_core.py).
"""
import datetime as dt
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import members  # noqa: E402
import db as _db  # noqa: E402

SAFE_DOMAINS = ("school", "activity", "chore", "gift", "travel", "pet", "medical", "other")


def data(name, today=None, db=None):
    """Plain data for the screen (also used by tests): {'mine': [...], 'birthdays': [...], 'week': [...]}."""
    today = today or dates.today()
    con = _db.connect(db or paths.DB, readonly=True)
    con.row_factory = sqlite3.Row
    try:
        ph = ",".join("?" * len(SAFE_DOMAINS))
        mine = [dict(r) for r in con.execute(
            f"SELECT id, domain, title, due_date, provider FROM life_items WHERE status='open' AND member=? "
            f"AND domain IN ({ph}) ORDER BY COALESCE(due_date,'9999')", (name, *SAFE_DOMAINS))]
        bdays = sorted(members.alerts(con, today), key=lambda a: a["date"])[:6]
        horizon = today + dt.timedelta(days=14)
        week = [dict(r) for r in con.execute(
            f"SELECT domain, title, member, due_date FROM life_items WHERE status='open' AND due_date BETWEEN ? AND ? "
            f"AND (member IS NULL OR member=?) AND domain IN ({ph}) ORDER BY due_date",
            (today.isoformat(), horizon.isoformat(), name, *SAFE_DOMAINS))]
        import activities
        import calendar_days
        classes = [{"date": o["date"], "title": o["title"] + (f" {o['time']}" if o["time"] else ""), "provider": o["provider"]}
                   for o in activities.occurrences(con, today, today + dt.timedelta(days=6), who=name)]
        days_off = [{"date": r["start"], "span": calendar_days.span(r), "kind": r["kind"], "title": calendar_days.title(r)}
                    for r in calendar_days.between(today, horizon + dt.timedelta(days=16), con, who=name)]
        return {"mine": mine, "birthdays": bdays, "week": week, "classes": classes, "days_off": days_off}
    finally:
        con.close()

