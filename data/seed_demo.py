"""Demo data so a new family sees a populated dashboard before loading a real statement.

  python data/seed_demo.py            add synthetic rows (every one is tagged [DEMO])
  python data/seed_demo.py --remove   delete exactly the rows this script added
Synthetic names and amounts only. Refuses to run if the database already has real transactions or bills.
"""
import datetime as dt
import sqlite3
import sys

import db  # noqa: E402
import dates  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
TAG = "[DEMO]"


def remove(con):
    like = f"{TAG}%"
    n = 0
    for sql in (
        "DELETE FROM transactions WHERE description LIKE ?",
        "DELETE FROM accounts WHERE name LIKE ?",
        "DELETE FROM bills WHERE name LIKE ?",
        "DELETE FROM subscriptions WHERE name LIKE ?",
        "DELETE FROM appointments WHERE purpose LIKE ?",
        "DELETE FROM events WHERE name LIKE ?",
        "DELETE FROM life_items WHERE title LIKE ?",
        "DELETE FROM loans WHERE name LIKE ?",
        "DELETE FROM budget WHERE notes LIKE ?",
        "DELETE FROM home_office_profile WHERE notes LIKE ?",
        "DELETE FROM home_office_expenses WHERE description LIKE ?",
        "DELETE FROM activity_schedules WHERE title LIKE ?",
        "DELETE FROM calendar_days WHERE name LIKE ?",
    ):
        try:
            n += con.execute(sql, (like,)).rowcount
        except sqlite3.OperationalError:
            pass
    con.commit()
    return n


def seed(con):
    if con.execute("SELECT COUNT(*) FROM transactions WHERE description NOT LIKE ?", (TAG + "%",)).fetchone()[0] or \
       con.execute("SELECT COUNT(*) FROM bills WHERE name NOT LIKE ?", (TAG + "%",)).fetchone()[0]:
        raise SystemExit("Database already has real data; demo not added.")
    remove(con)
    today = dates.today()
    d = lambda n: (today + dt.timedelta(days=n)).isoformat()
    con.execute("INSERT INTO accounts(name, type, last4) VALUES (?,?,?)", (f"{TAG} Checking", "checking", "0000"))
    acct = con.execute("SELECT id FROM accounts WHERE name=?", (f"{TAG} Checking",)).fetchone()[0]
    for m in range(1, 4):
        first = (today.replace(day=1) - dt.timedelta(days=30 * (m - 1))).replace(day=5)
        for desc, amt, cat, typ in ((f"{TAG} GROCERY MART", -310.0 - 7 * m, "groceries", "spend"),
                                    (f"{TAG} ELECTRIC CO", -96.5, "utilities", "utility"),
                                    (f"{TAG} STREAMCO", -15.99, "subscriptions", "spend"),
                                    (f"{TAG} PAYROLL", 3200.0, "salary", "income")):
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) VALUES (?,?,?,?,?,?)",
                        (acct, first.isoformat(), desc, amt, cat, typ))
    con.execute("INSERT INTO bills(name, vendor, frequency, amount, due_date, status) VALUES (?,?,?,?,?,?)",
                (f"{TAG} Electric", "Electric Co", "monthly", 96.5, d(6), "due"))
    con.execute("INSERT INTO bills(name, vendor, frequency, amount, due_date, status) VALUES (?,?,?,?,?,?)",
                (f"{TAG} Internet", "Net Provider", "monthly", 60.0, d(-2), "due"))
    con.execute("INSERT INTO subscriptions(name, amount, frequency, active, match_pattern, decision) VALUES (?,?,?,?,?,?)",
                (f"{TAG} StreamCo", 15.99, "monthly", 1, "%STREAMCO%", "unreviewed"))
    con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES (?,?,?,?)",
                ("Sam", "Smile Dental", f"{TAG} Dental cleaning", d(9) + " 15:30"))
    con.execute("INSERT INTO events(name, event_date, recurs_yearly) VALUES (?,?,1)", (f"{TAG} Anniversary", d(20)))
    con.execute("INSERT INTO life_items(domain, member, title, due_date, recur_months, provider) VALUES (?,?,?,?,?,?)",
                ("school", "Sam", f"{TAG} Field-trip form and fee", d(5), None, "Springfield Elementary"))
    con.execute("INSERT INTO life_items(domain, title, due_date, recur_months) VALUES (?,?,?,?)",
                ("legal", f"{TAG} Review will and beneficiaries", d(40), 36))
    try:  # weekly class and a school day off (migrations 048, 049)
        con.execute("INSERT INTO activity_schedules(member, title, provider, weekdays, start_time, end_time, school_days) "
                    "VALUES (?,?,?,?,?,?,1)", ("Sam", f"{TAG} Swimming", "YMCA", "SA", "10:00", "10:45"))
        con.execute("INSERT INTO calendar_days(day, kind, name, source) VALUES (?, 'closure', ?, 'manual')",
                    (d(12), f"{TAG} Teacher work day"))
    except sqlite3.OperationalError:
        pass
    con.execute("INSERT INTO loans(name, lender, kind, balance, rate_pct, payment, payoff_date, notes) VALUES (?,?,?,?,?,?,?,?)",
                (f"{TAG} Car loan", "Credit Union", "auto", 8200.0, 5.9, 310.0, d(300), TAG))
    con.execute("INSERT OR REPLACE INTO budget(category, monthly_limit, notes) VALUES ('groceries', 300, ?)", (TAG,))
    adult = con.execute("SELECT name FROM members WHERE role='adult' ORDER BY id LIMIT 1").fetchone()
    if adult:
        con.execute("INSERT OR REPLACE INTO home_office_profile(tax_year, who, office_sqft, home_sqft, months_used, notes) VALUES (?,?,?,?,?,?)",
                    (today.year, adult[0], 120, 1800, 12, TAG))
        con.execute("INSERT INTO home_office_expenses(tax_year, who, category, description, amount) VALUES (?,?,?,?,?)",
                    (today.year, adult[0], "utilities", f"{TAG} electricity (annual)", 1160.0))
    con.commit()


if __name__ == "__main__":
    con = db.connect(DB)
    if "--remove" in sys.argv:
        print(f"removed {remove(con)} demo row(s)")
    else:
        seed(con)
        print("demo data added. Remove with: python data/seed_demo.py --remove")
