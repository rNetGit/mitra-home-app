"""What the Records page of the web app shows, with no web code: the areas and parts (records.SECTIONS),
read-only lists per part, one record in full (records.detail), word search (records.search) and the filed paper behind a
record (records.source_file, only inside this install's archive/). Used by webapp/app.py.

Looking up only: the add and change forms are in records_edit.py; parts without a form are changed through Chat. Finance
parts open on the Finance page (finance_data.py); a reference to a Finance row still opens here in full.
"""
import datetime as dt
import re
import sqlite3
import urllib.parse

import config
import dates
import pathlib
import db
import finance_data as FD
import home_contacts as hc
import member_info as mi
import paths
import records as R

AREAS = [k for k, _ in R.DOMAINS if k != "money"]
NAMES = dict(R.DOMAINS)
WORDS_MAX = 200
ROWS_MAX = 300
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# (domain, section) -> [(heading, table, sql, empty text)]. The first column is the row id (never shown); the others
# become the table's columns; `:today` is today's date. School keeps only the children's events (in code, `_kids_only`).
UPKEEP = ",".join(f"'{c}'" for c in R.UPKEEP)
_DAYS_SQL = "weekdays"  # 'MO,WE' -> 'Mon Wed'
for _code, _word in (("MO", "Mon"), ("TU", "Tue"), ("WE", "Wed"), ("TH", "Thu"), ("FR", "Fri"), ("SA", "Sat"),
                     ("SU", "Sun"), (",", " ")):
    _DAYS_SQL = f"replace({_DAYS_SQL}, '{_code}', '{_word}')"
BLOCKS = {
    ("people", "people"): [
        ("People", "members", "SELECT id, name, role, relation, birth_month_day AS birthday, birth_year AS born, school, grade FROM members ORDER BY id",
         "No one here yet. Answer the setup questions again in Settings > Household profile.")],
    ("people", "life"): [
        ("Open items", "life_items", "SELECT id, title, domain AS kind, COALESCE(member, 'household') AS who, "
         "COALESCE(due_date, 'needs a date') AS due, recur_months AS every_months, amount, provider FROM life_items "
         "WHERE status = 'open' ORDER BY (due_date IS NULL), due_date, domain",
         "Nothing recorded yet. Tell Chat, e.g. \"Sam's dentist is Oct 21 at 3pm\".")],
    ("people", "health"): [
        ("Checkups and screenings", "recurring_items", "SELECT id, name, who, interval_months AS every_months, last_done, "
         "provider FROM recurring_items WHERE category = 'Health' AND COALESCE(active, 1) = 1 ORDER BY who, name",
         "No checkups recorded."),
        ("Appointments", "appointments", "SELECT id, person, purpose, provider, appt_datetime, followup_due FROM appointments "
         "ORDER BY appt_datetime DESC", "No appointments recorded."),
        ("Vaccinations", "vaccinations", "SELECT id, member AS who, vaccine, given_on AS given, COALESCE(next_due, '') AS next_due, "
         "provider FROM vaccinations WHERE status = 'active' ORDER BY member, given_on DESC, id DESC",
         "No vaccinations recorded. Add one below; a next due date puts a reminder on Today.")],
    ("people", "school"): [
        ("Upcoming milestones", "events", "SELECT id, event_date AS date, name FROM events WHERE event_date >= :today "
         "ORDER BY event_date", "No education milestones recorded.")],
    ("people", "classes"): [
        ("Every week", "activity_schedules", "SELECT id, title, COALESCE(member, 'household') AS who, " + _DAYS_SQL +
         " AS days, COALESCE(start_time || COALESCE('-' || end_time, ''), '') AS time, provider AS place, "
         "COALESCE(term_end, '') AS until FROM activity_schedules WHERE status = 'active' ORDER BY member, title",
         "No weekly classes yet. Add one below, or tell Chat, e.g. \"Sam has swimming Mon and Wed 5pm at the YMCA\"."),
        ("Ended", "activity_schedules", "SELECT id, title, COALESCE(member, 'household') AS who, " + _DAYS_SQL +
         " AS days, provider AS place FROM activity_schedules WHERE status = 'ended' ORDER BY id DESC",
         "Nothing has ended yet.")],
    ("people", "dates"): [
        ("Holidays, festivals and school days off", "calendar_days", "SELECT id, day AS date, end_day AS last_day, "
         "CASE kind WHEN 'closure' THEN 'no school' WHEN 'early' THEN 'early dismissal' ELSE kind END AS kind, name, "
         "COALESCE(member, 'household') AS who, source FROM calendar_days WHERE status = 'active' "
         "AND COALESCE(end_day, day) >= :today ORDER BY day",
         "None added yet. Public holidays come from your country's rules and show on the Calendar; add your own "
         "below."),
        ("Waiting for review in the Inbox", "calendar_days", "SELECT id, day AS date, name, COALESCE(label, source) AS "
         "source FROM calendar_days WHERE status = 'proposed' ORDER BY day", "Nothing waits for review."),
        ("Family events, anniversaries and yearly dates", "events", "SELECT id, name, event_date AS date, "
         "COALESCE(start_time || COALESCE('-' || end_time, ''), '') AS time, CASE recurs_yearly "
         "WHEN 1 THEN 'every year' ELSE 'once' END AS repeats FROM events ORDER BY substr(event_date, 6), start_time",
         "No family events or yearly dates yet. Add one below, or tell Chat, e.g. \"family dinner Friday 8 to 8:30 pm\".")],
    ("people", "profiles"): [
        ("Emergency, medical and school facts", "member_info", "SELECT id, member AS who, category, label, value, "
         "COALESCE(verified_on, 'never') AS confirmed, CASE WHEN COALESCE(verified_on, substr(created_at, 1, 10)) <= "
         ":cutoff THEN 'check it' ELSE 'ok' END AS status FROM member_info WHERE status = 'active' "
         "ORDER BY member, category, label",
         "Nothing here yet. Add the facts that matter in an emergency below: who to call, allergies, medicines, the "
         "doctor, school and pickup. Stays on this PC; no passwords or full ID numbers.")],
    ("home", "lists"): [
        ("Lists", "lists", "SELECT id, name, kind, audience, (SELECT COUNT(*) FROM list_items i WHERE i.list_id = lists.id "
         "AND i.status = 'open') AS open_items FROM lists WHERE status = 'active' ORDER BY name", "No lists yet.")],
    ("home", "meals"): [
        ("Planned meals", "meal_plan", "SELECT id, day, slot, COALESCE(title, (SELECT name FROM recipes r WHERE "
         "r.id = meal_plan.recipe_id)) AS meal FROM meal_plan WHERE day >= :today ORDER BY day, slot", "No meals planned."),
        ("Recipes", "recipes", "SELECT id, name, servings, tags FROM recipes WHERE COALESCE(status, 'active') = 'active' "
         "ORDER BY name", "No recipes yet.")],
    ("home", "upkeep"): [
        ("Home maintenance schedule", "recurring_items", f"SELECT id, name, category, who, interval_months AS every_months, "
         f"last_done, provider FROM recurring_items WHERE category IN ({UPKEEP}) AND COALESCE(active, 1) = 1 "
         "ORDER BY category, name", "No upkeep jobs recorded."),
        ("Seasonal jobs", "seasonal_tasks", "SELECT id, name, category, start_md || ' to ' || end_md AS season, who, place, "
         "(SELECT MAX(done_date) FROM seasonal_log l WHERE l.task_id = seasonal_tasks.id) AS last_done FROM seasonal_tasks "
         "WHERE COALESCE(active, 1) = 1 ORDER BY start_md, name", "No seasonal jobs."),
        ("Recently done", "recurring_log", "SELECT l.id, l.done_date AS date, r.name AS item, r.who, l.provider "
         "FROM recurring_log l JOIN recurring_items r ON r.id = l.item_id ORDER BY l.done_date DESC LIMIT 20",
         "Nothing logged yet.")],
    ("home", "contacts"): [
        ("Plumbers, furnace, garage and other help", "home_contacts", "SELECT c.id, c.name, replace(c.trade, '_', ' ') AS kind, "
         "c.phone, NULLIF(" + hc.LAST_JOB + ", '') AS last_job, CASE c.again WHEN 1 THEN 'yes' WHEN 0 THEN 'no' END AS use_again, "
         "c.rating, c.notes FROM home_contacts c WHERE c.status = 'active' ORDER BY c.trade, (c.again = 0), c.name",
         "Nobody here yet. Add the plumber, furnace company, garage, electrician or handyman you have used, so the "
         "number is at hand next time. Marking an upkeep job done with their name counts as their last job.")],
    ("home", "inventory"): [
        ("Things at home", "home_assets", "SELECT id, name, category, location AS place, brand_model, purchase_date, price, "
         "warranty_end, COALESCE(status, 'in_use') AS status FROM home_assets ORDER BY (COALESCE(status, 'in_use') != 'in_use'), "
         "name", "Nothing in the inventory yet.")],
    ("home", "shopping"): [
        ("Planned purchases", "shopping_items", "SELECT id, item, list_name AS list, status, target_date AS buy_by, est_price, "
         "store, paid FROM shopping_items ORDER BY (status = 'bought'), target_date", "No shopping items.")],
    ("vehicles", "vehicles"): [
        ("Vehicles", "vehicles", "SELECT id, trim(COALESCE(year || ' ', '') || COALESCE(make, '') || ' ' || COALESCE(model, '')) "
         "AS vehicle, owner, registration_expires, inspection_expires FROM vehicles WHERE status = 'active' ORDER BY year DESC", "No vehicles yet. Drop an insurance card or registration in the Inbox."),
        ("Service log", "vehicle_log", "SELECT l.id, l.log_date AS date, COALESCE(v.year || ' ', '') || COALESCE(v.make, '') || "
         "' ' || COALESCE(v.model, '') AS vehicle, replace(l.kind, '_', ' ') AS service, l.odometer, l.cost, l.vendor "
         "FROM vehicle_log l LEFT JOIN vehicles v ON v.id = l.vehicle_id ORDER BY l.log_date DESC LIMIT 50",
         "No service logged yet.")],
    ("papers", "papers"): [
        ("Filed papers", "documents", "SELECT id, doc_date AS date, replace(COALESCE(doc_type, ''), '_', ' ') AS type, vendor, "
         "COALESCE(notes, '') || ' ' || COALESCE(filed_path, '') AS _hay "
         "FROM documents ORDER BY doc_date DESC, id DESC LIMIT 300", "No papers filed yet. Drop bills, statements and receipts "
         "in the Inbox.")],
    ("papers", "ids"): [
        ("ID documents", "id_documents", "SELECT id, person, replace(doc_type, '_', ' ') AS document, expires, "
         "number_last4 AS last4, issuing_authority FROM id_documents WHERE COALESCE(active, 1) = 1 ORDER BY (expires IS NULL), "
         "expires", "No ID documents recorded.")],
    ("papers", "policies"): [
        ("Insurance policies", "policies", "SELECT id, carrier, kind, policy_last4, term_start, term_end, premium_total, status "
         "FROM policies ORDER BY term_end DESC", "No policies filed yet. Drop a declarations page in the Inbox.")],
}
# parts drawn elsewhere in the web app: (text, link)
ELSEWHERE = {("home", "saved"): ("Saved links, notes, places and deals are on the Notes page.", "/notes"),
             ("papers", "emergency"): ("The emergency sheet is one of the documents on Today (under Documents).", "/")}


def _con():
    return db.connect(paths.DB, readonly=True)


def where(data):
    """(domain, section) from request fields, each kept only when it is one of the offered choices; Finance -> None."""
    dom = R.LEGACY_DOMAIN.get(data.get("domain"), data.get("domain"))
    if dom not in AREAS:
        return ("money", None) if dom == "money" else ("people", "people")
    keys = [k for k, _ in R.SECTIONS[dom]]
    sec = data.get("section")
    return dom, sec if sec in keys else keys[0]


def parts(dom):
    return R.SECTIONS.get(dom, [])


def words(data):
    return " ".join(str(data.get("q", "")).split())[:WORDS_MAX]


def _kids_only(rows):
    kids = [k.lower() for k in config.member_names("child")]
    return [r for r in rows if any(str(r.get("name") or "").lower().startswith(k + ":") for k in kids)]


# The phone list row of a block: heading -> (title column, date column on the right). Without an entry the first shown
# column is the title and the first DATE_COLS column with a value sits on the right.
LIST = {"Open items": ("title", "due"), "Checkups and screenings": ("name", "last_done"),
        "Appointments": ("purpose", "appt_datetime"), "Upcoming milestones": ("name", "date"),
        "Holidays, festivals and school days off": ("name", "date"), "Waiting for review in the Inbox": ("name", "date"),
        "Family events, anniversaries and yearly dates": ("name", "date"), "Emergency, medical and school facts": ("label", None),
        "Planned meals": ("meal", "day"), "Home maintenance schedule": ("name", "last_done"),
        "Recently done": ("item", "date"), "Things at home": ("name", "warranty_end"),
        "Planned purchases": ("item", "buy_by"), "Vehicles": ("vehicle", "registration_expires"),
        "Service log": ("service", "date"), "Filed papers": ("vendor", "date"), "ID documents": ("document", "expires"),
        "Insurance policies": ("carrier", "term_end")}
DATE_COLS = ("due", "date", "day", "appt_datetime", "expires", "term_end", "registration_expires", "last_done", "buy_by",
             "warranty_end", "until", "birthday")
DEADLINES = {"due": "overdue", "expires": "expired", "term_end": "ended", "registration_expires": "expired",
             "inspection_expires": "expired", "buy_by": "late", "warranty_end": "ended", "followup_due": "overdue"}
PILLS = ("status", "use_again")
EVERY = ("every_months", "recur_months")
MONEY = ("amount", "price", "est_price", "cost", "premium_total")
FOLD = {"Ended", "Recently done"}  # blocks shown folded under their heading
SOON_DAYS = 30


def _deadline(col, v, today):
    """(pill, tone) for a date that runs out: past -> 'expired' (bad), within SOON_DAYS -> 'in N days' (warn)."""
    if col not in DEADLINES or not isinstance(v, str) or not ISO.match(v[:10]):
        return "", ""
    try:
        n = (dt.date.fromisoformat(v[:10]) - today).days
    except ValueError:
        return "", ""
    if n < 0:
        return DEADLINES[col], "bad"
    if n <= SOON_DAYS:
        return ("today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days"), "warn"
    return "", ""


def list_row(cols, raw, today, title=None, right=None):
    """{"title", "right", "pill", "tone", "meta"} for one row on a phone: the title column, a short date on the right
    (with an 'overdue' / 'in 12 days' pill when it is a deadline), a status pill and up to four other values as one
    grey line."""
    shown = cols[1:]
    title = title if title in shown else (shown[0] if shown else None)
    if right is None or raw.get(right) in (None, ""):
        right = next((c for c in DATE_COLS if c in shown and c != title and raw.get(c) not in (None, "")), None)
    pill, tone = "", ""
    for c in sorted((c for c in shown if c in DEADLINES), key=lambda c: c != right):
        p_, t_ = _deadline(c, raw.get(c), today)
        if t_ and (not tone or (t_ == "bad" and tone != "bad")):
            pill, tone = (p_ if c == right else f"{R.column_label(c).split()[0].lower()} {p_}"), t_
    pill_col = next((c for c in PILLS if c in shown and raw.get(c) not in (None, "")), None)
    if not pill and pill_col:
        pill = str(raw[pill_col]).replace("_", " ")
        tone = FD.tone_of(pill)
    meta = []
    for c in shown:
        v = raw.get(c)
        if c in (title, right, pill_col) or v in (None, "") or str(v).lower() in ("household", "other"):
            continue
        if c in EVERY:
            try:
                n = int(v)
            except (TypeError, ValueError):
                continue
            if n > 0:
                meta.append("every month" if n == 1 else "every year" if n == 12 else f"every {n} months")
        elif c in R.MONEY_COLS or c in MONEY:
            meta.append(str(R._value(c, v)) if c in R.MONEY_COLS else FD.M.fmt(v) if isinstance(v, (int, float)) else str(v))
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            meta.append(f"{R.column_label(c)} {R._value(c, v)}")
        elif isinstance(v, str) and ISO.match(v[:10]) and c not in ("date", "day"):
            meta.append(f"{R.column_label(c)} {FD.short_date(v[:10], today)}")
        else:
            meta.append(FD.ISO_IN.sub(lambda m: FD.short_date(m.group(0), today), str(R._value(c, v))))
    rv = raw.get(right) if right else None
    rtext = FD.short_date(rv[:10], today) + (rv[10:16].replace("T", " ") if len(rv) > 10 else "") if isinstance(rv, str) else ""
    if right == "birthday" and dates.valid_md(rv):  # "03-14" -> "Mar 14"
        rtext = dates.md_text(rv, short=True)
    text = str(R._value(title, raw.get(title))) if title and raw.get(title) not in (None, "") else ""
    text = text[:1].upper() + text[1:]
    return {"title": text, "av": next((ch.upper() for ch in text if ch.isalpha()), "?"), "right": rtext, "pill": pill, "tone": tone, "meta": " · ".join(meta[:4])}


def _cell(col, v, today):
    """One table cell on a PC: dates short (Oct 9), money formatted, the rest as records shows it."""
    if v in (None, ""):
        return ""
    if col in MONEY and col not in R.MONEY_COLS and isinstance(v, (int, float)):
        return FD.M.fmt(v)
    if isinstance(v, str) and ISO.match(v):
        return FD.short_date(v, today)
    if isinstance(v, str) and len(v) in (16, 19) and ISO.match(v[:10]) and v[10] in " T":  # 2026-10-27 15:30 -> Oct 27, 15:30
        return f"{FD.short_date(v[:10], today)}, {v[11:16]}"
    return R._value(col, v)


def _words_of(text):
    return [w for w in str(text or "").lower().split() if w][:8]


def blocks(dom, sec, today, find=""):
    """[{"heading", "table", "cols", "rows": [{"id", "cells", "list"}], "empty", "fold", "total"}] for one part; a block
    whose table is missing (an older database) is left out. `list` is the phone row (list_row). `find` keeps the rows
    in which every word shows up in some column (and a hidden `_hay` column: notes and file name of a paper); the
    row cap then applies to the matches, so an old paper is found too."""
    out = []
    words = _words_of(find)
    try:
        con = _con()
    except sqlite3.Error:
        return out
    try:
        for heading, table, sql, empty in BLOCKS.get((dom, sec), []):
            if words:
                sql = re.sub(r"\s+LIMIT\s+\d+\s*$", "", sql)
            try:
                cur = con.execute(sql, {"today": today.isoformat(), "cutoff": mi.cutoff(today)})
            except sqlite3.Error:
                continue
            cols = [d[0] for d in cur.description]
            if words:
                allrows = [dict(zip(cols, r)) for r in cur.fetchall()]
                total = len(allrows)
                hay = lambda r: " ".join(str(v) for v in r.values() if v is not None).lower()  # noqa: E731
                rows = [r for r in allrows if all(w in hay(r) for w in words)][:ROWS_MAX]
            else:
                rows = [dict(zip(cols, r)) for r in cur.fetchmany(ROWS_MAX)]
                total = len(rows)
            if "_hay" in cols:
                cols = [c for c in cols if c != "_hay"]
                for r in rows:
                    r.pop("_hay", None)
            if (dom, sec) == ("people", "school"):
                rows = _kids_only(rows)
            title, right = LIST.get(heading, (None, None))
            out.append({"heading": heading, "table": table, "cols": [R.column_label(c) for c in cols[1:]], "empty": empty,
                        "fold": heading in FOLD and bool(rows) and not words, "total": total,
                        "rows": [{"id": r[cols[0]], "cells": [_cell(c, r[c], today) for c in cols[1:]],
                                  "list": list_row(cols, r, today, title, right)} for r in rows]})
    finally:
        con.close()
    return out


def strip(dom, today):
    """The few counts at the top of an area (people, items, what is due)."""
    t, soon = today.isoformat(), (today + dt.timedelta(days=60)).isoformat()
    T = {
        "people": [("People", "SELECT COUNT(*) FROM members", ()),
                   ("Open items", "SELECT COUNT(*) FROM life_items WHERE status='open'", ()),
                   ("Appointments ahead", "SELECT COUNT(*) FROM appointments WHERE substr(appt_datetime,1,10) >= ?", (t,))],
        "home": [("Upkeep jobs", f"SELECT COUNT(*) FROM recurring_items WHERE category IN ({UPKEEP})", ()),
                 ("Things at home", "SELECT COUNT(*) FROM home_assets", ()),
                 ("Service contacts", "SELECT COUNT(*) FROM home_contacts WHERE status='active'", ()),
                 ("Recipes", "SELECT COUNT(*) FROM recipes", ())],
        "vehicles": [("Vehicles", "SELECT COUNT(*) FROM vehicles WHERE status='active'", ()),
                     ("Renewals in 60 days", "SELECT COUNT(*) FROM vehicles WHERE status='active' AND (registration_expires "
                      "BETWEEN ? AND ? OR inspection_expires BETWEEN ? AND ?)", (t, soon, t, soon))],
        "papers": [("Papers filed", "SELECT COUNT(*) FROM documents", ()),
                   ("IDs and expiries", "SELECT COUNT(*) FROM id_documents", ()),
                   ("Policies", "SELECT COUNT(*) FROM policies", ())],
    }
    out = []
    try:
        con = _con()
    except sqlite3.Error:
        return out
    try:
        for label, sql, params in T.get(dom, []):
            try:
                out.append((label, con.execute(sql, params).fetchone()[0] or 0))
            except sqlite3.Error:
                continue
    finally:
        con.close()
    return out


# The four lanes of the Records home: area -> (one line about it, icon, gradient class)
LANES = {"people": ("Family, life items, checkups, school, classes and dates.", "i-people", "g-rose"),
         "home": ("Lists, meals, upkeep, service contacts and the things you own.", "i-home", "g-flow"),
         "vehicles": ("Cars, renewals and the service log.", "i-car", "g-high"),
         "papers": ("Filed papers, IDs and insurance.", "i-paper", "g-cat")}
ATTENTION_MAX = 6


def _url(**params):
    return "/records?" + urllib.parse.urlencode(params)


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def overview(today):
    """The Records home: {"lanes": [lane], "attention": [(tone, text, url)]}. lane = {"key", "name", "line", "icon",
    "g", "parts", "big", "big_label", "sub", "tone"}. Read-only, no AI; a missing table counts as nothing."""
    t, soon = today.isoformat(), (today + dt.timedelta(days=SOON_DAYS)).isoformat()
    lanes, attention = [], []
    try:
        con = _con()
    except sqlite3.Error:
        return {"lanes": [], "attention": []}

    def one(sql, params=()):
        try:
            return con.execute(sql, params).fetchone()[0] or 0
        except sqlite3.Error:
            return 0

    def rows(sql, params=()):
        try:
            cur = con.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchmany(20)]
        except sqlite3.Error:
            return []

    try:
        late = rows("SELECT id, title, member, due_date FROM life_items WHERE status = 'open' AND due_date < ? "
                    "ORDER BY due_date", (t,))
        for r in late[:2]:
            who = f"{r['member']}: " if r["member"] else ""
            attention.append(("bad", f"{who}{r['title']} was due {FD.short_date(r['due_date'], today)}",
                              _url(ref=f"life_items:{r['id']}")))
        ids = rows("SELECT id, person, doc_type, expires FROM id_documents WHERE COALESCE(active, 1) = 1 AND expires "
                   "IS NOT NULL AND expires <= ? ORDER BY expires", (soon,))
        for r in ids[:2]:
            doc = str(r["doc_type"] or "ID").replace("_", " ")
            gone = r["expires"] < t
            attention.append(("bad" if gone else "warn", f"{r['person'] or 'Household'}'s {doc} "
                              f"{'expired' if gone else 'expires'} {FD.short_date(r['expires'], today)}",
                              _url(ref=f"id_documents:{r['id']}")))
        cars = rows("SELECT id, trim(COALESCE(year || ' ', '') || COALESCE(make, '') || ' ' || COALESCE(model, '')) AS name, "
                    "registration_expires AS reg, inspection_expires AS insp FROM vehicles WHERE status = 'active' AND "
                    "(registration_expires <= ? OR inspection_expires <= ?)", (soon, soon))
        for r in cars[:2]:
            what, when = min(((w, d) for w, d in (("registration", r["reg"]), ("inspection", r["insp"])) if d and d <= soon),
                             key=lambda x: x[1])
            attention.append(("bad" if when < t else "warn", f"{r['name'] or 'Vehicle'} {what} "
                              f"{'ran out' if when < t else 'runs out'} {FD.short_date(when, today)}",
                              _url(ref=f"vehicles:{r['id']}")))
        pol = rows("SELECT id, carrier, kind, term_end FROM policies WHERE COALESCE(status, 'active') = 'active' AND "
                   "term_end BETWEEN ? AND ? ORDER BY term_end", (t, soon))
        for r in pol[:1]:
            attention.append(("warn", f"{r['carrier'] or 'Insurance'} {r['kind'] or ''} policy ends "
                              f"{FD.short_date(r['term_end'], today)}".replace("  ", " "), _url(ref=f"policies:{r['id']}")))
        upkeep_due = one(f"SELECT COUNT(*) FROM recurring_items WHERE category IN ({UPKEEP}) AND COALESCE(active, 1) = 1 "
                         "AND interval_months > 0 AND last_done IS NOT NULL AND date(last_done, '+' || interval_months || "
                         "' months') <= ?", (t,))
        if upkeep_due:
            attention.append(("warn", f"{_plural(upkeep_due, 'upkeep job')} due", _url(domain="home", section="upkeep")))
        check = one("SELECT COUNT(*) FROM member_info WHERE status = 'active' AND COALESCE(verified_on, "
                    "substr(created_at, 1, 10)) <= ?", (mi.cutoff(today),))
        if check:
            attention.append(("warn", f"{_plural(check, 'critical fact')} to confirm",
                              _url(domain="people", section="profiles")))

        people = one("SELECT COUNT(*) FROM members")
        open_items = one("SELECT COUNT(*) FROM life_items WHERE status = 'open'")
        appts = one("SELECT COUNT(*) FROM appointments WHERE substr(appt_datetime, 1, 10) >= ?", (t,))
        things = one("SELECT COUNT(*) FROM home_assets")
        helpers = one("SELECT COUNT(*) FROM home_contacts WHERE status = 'active'")
        lists = one("SELECT COUNT(*) FROM lists WHERE status = 'active'")
        n_cars = one("SELECT COUNT(*) FROM vehicles WHERE status = 'active'")
        papers = one("SELECT COUNT(*) FROM documents")
        n_ids = one("SELECT COUNT(*) FROM id_documents WHERE COALESCE(active, 1) = 1")
        n_pol = one("SELECT COUNT(*) FROM policies WHERE COALESCE(status, 'active') = 'active'")
        figures = {
            "people": (str(open_items), "open items", ", ".join(x for x in (
                _plural(people, "person").replace("persons", "people"),
                f"{len(late)} overdue" if late else "", f"{appts} appointment{'' if appts == 1 else 's'} ahead" if appts else "")
                if x), "bad" if late else ""),
            "home": (str(upkeep_due) if upkeep_due else str(lists), "upkeep due" if upkeep_due else "lists", ", ".join(x for x in (
                _plural(lists, "list") if lists else "", _plural(things, "thing") + " in the inventory" if things else "",
                _plural(helpers, "service contact") if helpers else "") if x) or "Nothing recorded yet",
                "warn" if upkeep_due else ""),
            "vehicles": (str(n_cars), "vehicle" if n_cars == 1 else "vehicles",
                         f"{len(cars)} renewal{'' if len(cars) == 1 else 's'} in {SOON_DAYS} days" if cars
                         else "No renewals in 30 days" if n_cars else "Drop an insurance card in the Inbox",
                         "warn" if cars else ""),
            "papers": (str(papers), "papers filed", ", ".join(x for x in (
                _plural(n_ids, "ID") if n_ids else "", _plural(n_pol, "policy").replace("policys", "policies") if n_pol else "",
                f"{len(ids)} expiring" if ids else "") if x) or "Drop bills and papers in the Inbox",
                "warn" if ids else ""),
        }
        for k in AREAS:
            line, icon, grad = LANES.get(k, ("", "i-paper", "g-cat"))
            big, big_label, sub, tone = figures.get(k, ("", "", "", ""))
            lanes.append({"key": k, "name": NAMES[k], "line": line, "icon": icon, "g": grad, "parts": parts(k),
                          "big": big, "big_label": big_label, "sub": sub, "tone": tone})
    finally:
        con.close()
    order = {"bad": 0, "warn": 1}
    attention.sort(key=lambda a: order.get(a[0], 2))
    return {"lanes": lanes, "attention": attention[:ATTENTION_MAX]}


def search(user, text):
    """records.search for this viewer: [{ref, label, kind}]."""
    if not text:
        return []
    try:
        con = _con()
    except sqlite3.Error:
        return []
    try:
        return R.search(con, text, user)
    finally:
        con.close()


def detail(user, ref):
    """One record or a group of rows, for this viewer. -> None when the ref is not a record, else
    {"table", "one": {label, fields, paper, history, domain, section} | None, "group": [(ref, label)] | None}."""
    parsed = R.parse_ref(ref)
    if not parsed:
        return None
    table, ids = parsed
    try:
        con = _con()
    except sqlite3.Error:
        return {"table": table, "one": None, "group": None, "domain": None, "section": None}
    try:
        if len(ids) == 1:
            d = R.detail(con, table, ids[0], user)
            if not d:
                return {"table": table, "one": None, "group": None, "domain": None, "section": None}
            src = d["source"]
            paper = None
            if src:
                paper = {"id": src["id"], "label": src["label"], "here": bool(R.source_file(src["path"])),
                         "path": bool(src["path"]), "view": view_mime(src["path"]) is not None}
            one = {"label": d["label"], "fields": [(field_name(k), field_value(v)) for k, v in d["fields"]], "paper": paper,
                   "history": R.history(table, ids[0], name=d["row"].get("name"))}
            return {"table": table, "one": one, "group": None, "domain": d["domain"], "section": d["section"]}
        group = [(R.ref_str(table, [i]), n) for i in ids for n in [R.label(con, table, i, user)] if n]
        dom, sec = R.where(table)
        return {"table": table, "one": None, "group": group, "domain": dom, "section": sec,
                "noun": R.NOUN.get(table, "records")}
    finally:
        con.close()


FIELD_NAMES = {"domain": "Kind", "member": "For", "recur months": "Repeats every (months)", "lead days": "Remind (days before)",
               "created at": "Added", "updated at": "Changed", "birth month day": "Birthday", "birth year": "Born",
               "due date": "Due", "appt datetime": "When", "followup due": "Follow-up due", "doc date": "Date",
               "doc type": "Type", "registration expires": "Registration runs out", "inspection expires": "Inspection runs out",
               "number last4": "Number (last 4)", "policy last4": "Policy (last 4)", "term start": "Term starts",
               "term end": "Term ends", "premium total": "Premium", "interval months": "Every (months)",
               "last done": "Last done", "warranty end": "Warranty ends", "purchase date": "Bought",
               "brand model": "Brand and model", "verified on": "Confirmed", "event date": "Date", "recurs yearly": "Every year"}
DATETIME = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})(:\d{2})?$")


def field_name(k):
    """A record field's name as a person reads it (records.detail gives the column with spaces)."""
    n = FIELD_NAMES.get(str(k).lower(), str(k))
    return n[:1].upper() + n[1:]


def field_value(v):
    """Dates short (Oct 15, 2025), date-times without seconds; the rest unchanged."""
    t = str(v)
    m = DATETIME.match(t)
    if m:
        return f"{FD.short_date(m.group(1))}, {m.group(2)}"
    return FD.short_date(t) if ISO.match(t) else t


VIEW_MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}


def view_mime(path):
    """The media type a filed paper may be shown in the viewer window with (PDF and photos); None = download only."""
    return VIEW_MIME.get(pathlib.PurePath(str(path or "")).suffix.lower())


def paper(user, doc_id):
    """The archived file of one filed paper -> pathlib.Path or None (unknown id, private, or not inside archive/)."""
    try:
        did = int(doc_id)
    except (TypeError, ValueError):
        return None
    try:
        con = _con()
    except sqlite3.Error:
        return None
    try:
        d = R.detail(con, "documents", did, user)
    finally:
        con.close()
    if not d or not d["source"]:
        return None
    return R.source_file(d["source"]["path"])


def section_title(dom, sec):
    return dict(R.SECTIONS.get(dom, [])).get(sec, "")
