"""Vaccination history for people and pets (migration 065 `vaccinations`).

  python data/health_records.py list [--who NAME]     shots on file, newest first, with the next due date

A shot is a record of what was given and when. A next due date also keeps ONE open `life_items` row (domain vaccine,
title "<vaccine> due"), so the reminder reaches Today, the Calendar and the weekly digest through the code that already
reads life_items (life.alerts, lead from expiries.py type vaccination). Marking that reminder done writes the next
history row. Records only, no medical advice; names of vaccines, never lot numbers or diagnoses.
Library: SUFFIX, reminder_title(vaccine), vaccine_of(title), sync_reminder(con, member, vaccine, next_due, provider),
log_done(con, item, given, next_due), rows(con, who=None).
"""
import argparse
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import db  # noqa: E402

DB = paths.DB
SUFFIX = " due"


def reminder_title(vaccine):
    return f"{vaccine}{SUFFIX}"


def vaccine_of(title):
    t = (title or "").strip()
    return t[:-len(SUFFIX)].strip() if t.lower().endswith(SUFFIX) else t


def sync_reminder(con, member, vaccine, next_due, provider=None):
    """The open reminder for this person's vaccine: moved to next_due, made when missing, closed when next_due is None.
    Returns its life_items id or None."""
    title = reminder_title(vaccine)
    row = con.execute("SELECT id FROM life_items WHERE status='open' AND domain='vaccine' AND member=? AND lower(title)=lower(?)",
                      (member, title)).fetchone()
    if next_due is None:
        if row:
            con.execute("UPDATE life_items SET status='done', last_done=date('now','localtime') WHERE id=?", (row[0],))
        return None
    if row:
        con.execute("UPDATE life_items SET due_date=?, provider=COALESCE(?, provider) WHERE id=?", (next_due, provider, row[0]))
        return row[0]
    return con.execute("INSERT INTO life_items(domain, member, title, due_date, lead_days, provider) VALUES ('vaccine',?,?,?,14,?)",
                       (member, title, next_due, provider)).lastrowid


def log_done(con, item, given, next_due=None):
    """History row for a vaccine reminder marked done (a recurring one passes the date it rolled to). Not for items without
    a person: a household chore is not a shot."""
    if item["domain"] != "vaccine" or not item["member"]:
        return None
    return con.execute("INSERT INTO vaccinations(member, vaccine, given_on, next_due, provider, life_item_id) VALUES (?,?,?,?,?,?)",
                       (item["member"], vaccine_of(item["title"])[:60] or "Vaccine", given.isoformat(), next_due,
                        item["provider"], item["id"] if next_due else None)).lastrowid


def rows(con, who=None):
    con.row_factory = sqlite3.Row
    sql, p = "SELECT * FROM vaccinations WHERE status='active'", []
    if who:
        sql += " AND member=?"
        p.append(who)
    try:
        return [dict(r) for r in con.execute(sql + " ORDER BY given_on DESC, id DESC", p)]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list"])
    ap.add_argument("--who")
    a = ap.parse_args()
    con = db.connect(DB)
    for r in rows(con, a.who):
        print(f"{r['given_on']}  {r['member']:<12} {r['vaccine']:<24} next {r['next_due'] or '-'}  {r['provider'] or ''}")


if __name__ == "__main__":
    main()
