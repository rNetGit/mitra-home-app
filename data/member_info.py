"""Critical information about each family member (emergency contacts, medical, school and care), kept up to date.

Table member_info (migration 050). Adults add, change and confirm it in Family > People > Critical info
(edit_actions.member_info_*). A row not confirmed for REVIEW_MONTHS (family.json `info_review_months`, default 6)
is "stale": Inbox source `info_review` asks an adult to confirm or change it, one item per person.
PC only: no sync trigger, not in the phone API, not in chat (chat_core.PC_ONLY), not readable through ask_sql.
"""
import datetime as dt
import sqlite3

import config

CATEGORIES = (("emergency", "Emergency contacts"), ("medical", "Medical"), ("school", "School and care"), ("other", "Other"))
# suggested labels per category (the form's datalist; any short label is allowed)
LABELS = {"emergency": ("Contact 1", "Contact 2", "Neighbour", "Family doctor", "Phone"),
          "medical": ("Allergies", "Medicines", "Conditions", "Doctor", "Blood type", "Dentist"),
          "school": ("School", "Teacher", "Caregiver", "Authorized pickup", "School phone"),
          "other": ()}
REVIEW_MONTHS = 6
HIDDEN_TABLE = "member_info"


def review_months():
    try:
        n = int((config.family() or {}).get("info_review_months", REVIEW_MONTHS))
    except (TypeError, ValueError):
        return REVIEW_MONTHS
    return n if 1 <= n <= 36 else REVIEW_MONTHS


def cutoff(today):
    """Rows last confirmed (or, never confirmed, created) on or before this ISO date are stale."""
    m = review_months()
    y, mo = divmod(today.year * 12 + today.month - 1 - m, 12)
    mo += 1
    d = min(today.day, 28)
    return dt.date(y, mo, d).isoformat()


def stale(con, today):
    """{member: [(id, category, label)]} for active rows past the review age, members in family order."""
    try:
        rows = con.execute("SELECT id, member, category, label FROM member_info WHERE status='active' "
                           "AND COALESCE(verified_on, substr(created_at, 1, 10)) <= ? ORDER BY member, category, label",
                           (cutoff(today),)).fetchall()
    except sqlite3.OperationalError:
        return {}
    out = {}
    for rid, member, cat, label in rows:
        out.setdefault(member, []).append((rid, cat, label))
    return out


def for_sheet(con):
    """[(member, category title, label, value)] for the printed emergency sheet."""
    title = dict(CATEGORIES)
    try:
        return [(m, title[c], lb, val) for m, c, lb, val in con.execute(
            "SELECT member, category, label, value FROM member_info WHERE status='active' ORDER BY member, category, label")]
    except sqlite3.OperationalError:
        return []
