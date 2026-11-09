"""The Records edit forms of the web app, with no web code: which records can be changed there, the current
values for a form, the choices it offers, and the change itself through edit_actions (the same checks, rules and
logs/edits.log line as Chat's changes). Used by webapp/app.py.

People area: life items (add, change, mark done, remove), people and pets (add, change role or birthday) and checkups
(record when one was last done). Finance > Pay: bills (mark paid with a date, undo), subscriptions (add, keep / cancel /
cancelled / not reviewed with a note, tracking on or off) and receipts (add, link to one of the candidate charges, no charge
expected, unlink). Finance > Keep: budget lines (set or remove), loans (add, new balance / rate / payment / payoff date,
paid off or active again) and accounts (add, last four digits only). Home: inventory (add, change, sold / disposed / lost)
and seasonal jobs (log when one was done). Vehicles: add one, log a service on it. Papers: ID documents (add, or a new
expiry date / last four after a renewal). Lists (new list; on one list add, tick, untick and remove items, clear the ticked
ones, archive it) and meals (plan a meal or take it off the plan, save or archive a recipe, put the planned recipes'
ingredients on a shopping list). Inventory items also link their filed receipt and manual. These pages are for adults;
children and guests tick family lists on their own page (kid_data.py).
"""
import datetime as dt
import sqlite3

import activities
import assets
import db
import dates  # noqa: E402
import edit_actions as ea
import expiries
import life
import lists as L
import meals
import home_contacts as hc
import member_info as mi
import money
import members as mem
import paths
import receipts as rc

# table -> the operations its edit form offers
EDIT_OPS = {"life_items": ("save", "done", "drop"), "activity_schedules": ("save", "skip", "end"),
            "calendar_days": ("save", "drop"), "events": ("save", "drop"), "appointments": ("save", "drop"), "member_info": ("save", "verify", "drop"), "home_contacts": ("save", "used", "drop"), "members": ("save",), "recurring_items": ("done",), "vaccinations": ("drop",),
            "bills": ("paid", "unpaid"), "subscriptions": ("decide", "active"), "receipts": ("link", "ignore", "unlink"),
            "loans": ("save", "status"), "savings_goals": ("save", "status"), "home_assets": ("save", "papers", "dispose"), "seasonal_tasks": ("done",),
            "vehicles": ("service", "save"), "id_documents": ("save",),
            "lists": ("item_add", "tick", "untick", "drop", "clear", "archive"), "meal_plan": ("clear",),
            "recipes": ("archive",)}
# (domain, section) -> the table its Add form adds to, or a tuple of tables when the part has more than one Add form
ADD = {("people", "life"): "life_items", ("people", "classes"): "activity_schedules",
       ("people", "dates"): ("calendar_days", "events"), ("people", "profiles"): "member_info", ("people", "health"): "vaccinations", ("people", "people"): "members", ("money", "subs"): "subscriptions",
       ("money", "receipts"): "receipts", ("money", "budget"): ("budget", "loans", "savings_goals"), ("money", "accounts"): "accounts",
       ("money", "home_office"): "home_office_profile",
       ("home", "inventory"): "home_assets", ("home", "contacts"): "home_contacts", ("vehicles", "vehicles"): "vehicles",
       ("papers", "ids"): "id_documents", ("home", "lists"): "lists",
       ("home", "meals"): ("meal_plan", "recipes", "meal_shop")}
# parts whose rows (or Add form) can be changed here; upkeep rows are checkups' table too (recurring_items)
EDIT_PARTS = {("people", "people"), ("people", "life"), ("people", "classes"), ("people", "dates"), ("people", "profiles"), ("people", "health"), ("home", "upkeep"), ("home", "contacts"), ("money", "bills"),
              ("money", "subs"), ("money", "receipts"), ("money", "budget"), ("money", "accounts"), ("money", "home_office"), ("home", "inventory"),
              ("vehicles", "vehicles"), ("papers", "ids"), ("home", "lists"), ("home", "meals")}
ADD_TITLE = {"life_items": "Add an item", "activity_schedules": "Add a weekly class or activity",
             "calendar_days": "Add a holiday, festival or day off school",
             "events": "Add a family event or a yearly date", "members": "Add a person or pet", "member_info": "Add a fact (contact, allergy, doctor, school)", "vaccinations": "Add a vaccination", "home_contacts": "Add a plumber, furnace company, garage ...", "subscriptions": "Add a subscription",
             "receipts": "Add a receipt by hand", "budget": "Set or remove a budget line", "loans": "Add a loan",
             "savings_goals": "Add a savings goal", "home_office_profile": "Set up your home office",
             "accounts": "Add an account", "home_assets": "Add a thing to the inventory", "vehicles": "Add a vehicle",
             "id_documents": "Add an ID document", "lists": "Start a list", "meal_plan": "Plan a meal",
             "recipes": "Save a recipe", "meal_shop": "Put the planned meals on a shopping list"}
DECISION_LABEL = {"unreviewed": "not reviewed yet", "keep": "keep (it is used)", "cancel": "cancel (still to do)",
                  "cancelled": "cancelled (done)"}
CANDIDATES_MAX = 5
HOUSEHOLD = "household"
FIELD_MAX = 200  # characters kept from any one form field; edit_actions checks the real limits

# inventory fields the Change form sends (asset_update names); the receipt and manual have a form of their own
ASSET_FIELDS = ("name", "category", "brand_model", "location", "purchase_date", "price", "warranty_end", "warranty_years",
                "store", "serial_last4", "notes")
# the form fields each table's forms send, all plain text
FIELDS = {"life_items": ("domain", "title", "who", "provider", "due", "every", "amount"),
          "activity_schedules": ("title", "who", "provider", "start_time", "end_time", "term_start", "term_end", "school_days",
                                 "skip") + tuple("d_" + d.lower() for d in activities.DAYS),
          "calendar_days": ("day", "end", "name", "kind", "who"),
          "events": ("name", "date", "start_time", "end_time", "repeats"),
          "appointments": ("who", "date", "time", "provider", "purpose", "followup"),
          "member_info": ("who", "category", "label", "value"),
          "vaccinations": ("who", "vaccine", "given", "next_due", "provider", "notes"),
          "home_contacts": ea.CONTACT_FIELDS,
          "members": ("name", "role", "birthday", "year", "school", "grade", "grad_year", "relation"),
          "recurring_items": ("when", "provider"),
          "bills": ("when",),
          "subscriptions": ("decision", "note", "name", "amount", "frequency", "renew"),
          "receipts": ("txn", "merchant", "date", "total", "last4"),
          "budget": ("category", "limit"),
          "loans": ("name", "kind", "lender", "balance", "rate", "payment", "payoff"),
          "savings_goals": ("name", "target", "saved", "due", "account", "how"),
          "accounts": ("name", "kind", "last4", "owner"),
          "home_office_profile": ("year", "who", "office", "home", "months", "method", "self_employed", "exclusive", "regular",
                                  "principal", "income"),
          "home_assets": ASSET_FIELDS + ("how", "when", "receipt", "manual"),
          "seasonal_tasks": ("when", "place"),
          "vehicles": ("make", "model", "year", "kind", "when", "odometer", "cost", "vendor", "vin_last4", "plate",
                       "plate_region", "owner", "primary_driver", "registration_expires", "inspection_expires",
                       "status", "notes"),
          "id_documents": ("person", "doc_type", "expires", "last4"),
          "lists": ("name", "kind", "text", "qty", "who", "item"),
          "meal_plan": ("day", "slot", "what", "note"),
          "recipes": ("name", "ingredients", "servings", "tags", "url", "notes"),
          "meal_shop": ("start", "end", "list_name")}
# fields that may be longer than FIELD_MAX (meals.add_recipe checks the real limits)
FIELD_LONG = {"ingredients": 6000, "notes": 5000}


def _con():
    return db.connect(paths.DB, readonly=True)


def _one(sql, params):
    try:
        con = _con()
    except sqlite3.Error:
        return None
    con.row_factory = sqlite3.Row
    try:
        r = con.execute(sql, params).fetchone()
        return dict(r) if r else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def add_tables(part):
    """The tables a part's Add forms add to, in order (empty when it has none)."""
    t = ADD.get(part)
    return () if t is None else t if isinstance(t, tuple) else (t,)


def adds(part, typed_in=None):
    """The Add forms of a part for a page: [{table, part, title, v}]; typed_in = {table: values kept after a refusal}."""
    return [{"table": t, "part": "/".join(part), "title": ADD_TITLE[t], "v": (typed_in or {}).get(t, {})}
            for t in add_tables(part)]


def _member_ids(name):
    """[(document type, expires)] of the person's active ID documents, soonest expiry first, for the person's edit form."""
    try:
        con = _con()
    except sqlite3.Error:
        return []
    try:
        return [(t.replace("_", " "), e or "no date") for t, e in con.execute(
            "SELECT doc_type, expires FROM id_documents WHERE person=? AND COALESCE(active, 1)=1 "
            "ORDER BY (expires IS NULL), expires", (name,))]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def goal_accounts():
    """[(id, label)] of the accounts a savings goal can follow (savings, checking, investment)."""
    try:
        con = _con()
    except sqlite3.Error:
        return []
    try:
        return [(str(i), f"{n} x{l}" if l else n) for i, n, l in con.execute(
            "SELECT id, name, last4 FROM accounts WHERE type IN ('savings', 'checking', 'investment') ORDER BY type DESC, name")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def _budget_lines():
    """Existing budget lines, then categories with a suggestion and allowance:<child> lines (the form's list)."""
    try:
        con = _con()
    except sqlite3.Error:
        return []
    try:
        import budget as B
        have = [r[0] for r in con.execute("SELECT category FROM budget ORDER BY category")]
        try:
            more = [r["category"] for r in B.suggest(con, dates.today())]
        except (sqlite3.Error, KeyError, TypeError):
            more = []
        kids = [r[0] for r in con.execute("SELECT name FROM members WHERE role='child' ORDER BY name")]
        return list(dict.fromkeys(have + more + [B.ALLOWANCE + k for k in kids]))
    except sqlite3.Error:
        return []
    finally:
        con.close()


def people():
    try:
        con = _con()
    except sqlite3.Error:
        return []
    try:
        return mem.names(con)
    except sqlite3.Error:
        return []
    finally:
        con.close()


def choices():
    return {"domains": list(life.DOMAINS), "people": people(), "roles": list(ea.ROLES), "freqs": list(ea.FREQS),
            "decisions": [(d, DECISION_LABEL[d]) for d in ea.SUB_DECISIONS], "today": dates.today().isoformat(),
            "loan_kinds": list(ea.LOAN_KINDS), "account_types": list(ea.ACCOUNT_TYPES), "budget_lines": _budget_lines(), "goal_accounts": goal_accounts(),
            "asset_categories": list(assets.CATEGORIES), "asset_ends": list(assets.STATUSES[1:]),
            "services": [(k, k.replace("_", " ")) for k in ea.VEHICLE_KINDS],
            "id_types": [(k, k.replace("_", " ")) for k in expiries.id_types()],
            "list_kinds": list(L.KINDS), "slots": list(meals.SLOTS),
            "week_end": (dates.today() + dt.timedelta(days=6)).isoformat(),
            "weekdays": [(d.lower(), activities.SHORT[d]) for d in activities.DAYS],
            "info_categories": list(mi.CATEGORIES), "trades": list(hc.TRADES), "contact_names": hc.names(), "info_labels": {c: list(l) for c, l in mi.LABELS.items()},
            "day_kinds": [("holiday", "holiday"), ("festival", "festival"), ("closure", "no school"),
                          ("early", "early dismissal")]}


def _num(x):
    return "" if x in (None, "") else f"{x:g}" if isinstance(x, float) else str(x)


def values(table, rid):
    """The current values for the edit form of one row as strings, or None when it cannot be changed here (unknown
    table, gone, finished, stopped)."""
    if table not in EDIT_OPS:
        return None
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        return None
    if table == "life_items":
        r = _one("SELECT domain, member, title, due_date, recur_months, amount, provider FROM life_items "
                 "WHERE id=? AND status='open'", (rid,))
        return r and {"domain": r["domain"], "title": r["title"] or "", "who": r["member"] or HOUSEHOLD,
                      "provider": r["provider"] or "", "due": r["due_date"] or "", "every": _num(r["recur_months"]),
                      "amount": _num(r["amount"]), "repeats": bool(r["recur_months"])}
    if table == "activity_schedules":
        r = _one("SELECT * FROM activity_schedules WHERE id=? AND status='active'", (rid,))
        return r and {"title": r["title"], "who": r["member"] or HOUSEHOLD, "provider": r["provider"] or "",
                      "start_time": r["start_time"] or "", "end_time": r["end_time"] or "",
                      "term_start": r["term_start"] or "", "term_end": r["term_end"] or "",
                      "school_days": bool(r["school_days"]), "days": activities.day_codes(r["weekdays"]),
                      "skip": dates.today().isoformat()}
    if table == "calendar_days":
        r = _one("SELECT name, day, end_day, kind, member FROM calendar_days WHERE id=? AND status='active'", (rid,))
        return r and {"name": r["name"], "day": r["day"], "end": r["end_day"] or "", "kind": r["kind"],
                      "who": r["member"] or HOUSEHOLD}
    if table == "events":
        r = _one("SELECT name, event_date, recurs_yearly, start_time, end_time FROM events WHERE id=?", (rid,))
        return r and {"name": r["name"], "date": r["event_date"], "start_time": r["start_time"] or "",
                      "end_time": r["end_time"] or "", "repeats": "yearly" if r["recurs_yearly"] else "once"}
    if table == "appointments":
        r = _one("SELECT person, provider, purpose, appt_datetime, followup_due FROM appointments WHERE id=?", (rid,))
        return r and {"who": r["person"] or "", "date": str(r["appt_datetime"])[:10], "time": str(r["appt_datetime"])[11:16],
                      "provider": r["provider"] or "", "purpose": r["purpose"] or "", "followup": r["followup_due"] or ""}
    if table == "vaccinations":
        r = _one("SELECT member, vaccine, given_on, next_due FROM vaccinations WHERE id=? AND status='active'", (rid,))
        return r and {"who": r["member"], "vaccine": r["vaccine"], "given": r["given_on"], "next_due": r["next_due"] or ""}
    if table == "member_info":
        r = _one("SELECT member, category, label, value, verified_on FROM member_info WHERE id=? AND status='active'", (rid,))
        return r and {"who": r["member"], "category": r["category"], "label": r["label"], "value": r["value"],
                      "verified": r["verified_on"] or ""}
    if table == "home_contacts":
        r = _one(f"SELECT {', '.join(ea.CONTACT_FIELDS)}, {hc.LAST_JOB} AS last_job FROM home_contacts c "
                 "WHERE id=? AND status='active'", (rid,))
        return r and {k: "" if r[k] is None else str(r[k]) for k in ea.CONTACT_FIELDS + ("last_job",)}
    if table == "members":
        r = _one("SELECT name, role, birth_month_day, birth_year, school, grade, grad_year, relation FROM members WHERE id=?", (rid,))
        return r and {"name": r["name"], "role": r["role"] or "", "birthday": r["birth_month_day"] or "",
                      "year": _num(r["birth_year"]), "school": r["school"] or "", "grade": r["grade"] or "",
                      "grad_year": _num(r["grad_year"]), "relation": r["relation"] or "", "ids": _member_ids(r["name"])}
    if table == "bills":
        r = _one("SELECT status, paid_date FROM bills WHERE id=?", (rid,))
        return r and {"open": r["status"] in ("due", "overdue"), "paid_date": r["paid_date"] or "",
                      "when": dates.today().isoformat()}
    if table == "subscriptions":
        r = _one("SELECT decision, active FROM subscriptions WHERE id=?", (rid,))
        return r and {"decision": r["decision"] or "unreviewed", "active": bool(r["active"]), "note": ""}
    if table == "receipts":
        return _receipt(rid)
    if table == "loans":
        r = _one("SELECT name, balance, balance_date, rate_pct, payment, payoff_date, status FROM loans WHERE id=?", (rid,))
        return r and {"name": r["name"], "balance": _num(r["balance"]), "balance_date": r["balance_date"] or "",
                      "rate": _num(r["rate_pct"]), "payment": _num(r["payment"]), "payoff": r["payoff_date"] or "",
                      "active": r["status"] != "paid_off"}
    if table == "savings_goals":
        r = _one("SELECT name, target, saved, due_date, account_id, status FROM savings_goals WHERE id=?", (rid,))
        return r and {"name": r["name"], "target": _num(r["target"]), "saved": _num(r["saved"]), "due": r["due_date"] or "",
                      "account": str(r["account_id"] or ""), "accounts": goal_accounts(),
                      "active": r["status"] == "active", "how": "done"}
    if table == "home_assets":
        r = _one(f"SELECT {', '.join(ASSET_FIELDS)}, receipt_document_id, manual_document_id FROM home_assets "
                 "WHERE id=? AND COALESCE(status, 'in_use')='in_use'", (rid,))
        return r and {**{k: _num(r[k]) if k in ("price", "warranty_years") else r[k] or "" for k in ASSET_FIELDS},
                      "how": "disposed", "when": dates.today().isoformat(),
                      "receipt": str(r["receipt_document_id"] or ""), "manual": str(r["manual_document_id"] or ""),
                      "receipt_docs": filed_docs(("receipt", "other"), r["receipt_document_id"]),
                      "manual_docs": filed_docs(("manual", "other"), r["manual_document_id"])}
    if table == "seasonal_tasks":
        r = _one("SELECT name, place, (SELECT MAX(done_date) FROM seasonal_log l WHERE l.task_id=seasonal_tasks.id) AS last "
                 "FROM seasonal_tasks WHERE id=? AND COALESCE(active, 1)=1", (rid,))
        return r and {"name": r["name"], "place": r["place"] or "", "last_done": r["last"] or "",
                      "when": dates.today().isoformat()}
    if table == "lists":
        return _list(rid)
    if table == "meal_plan":
        r = _one("SELECT day, slot, COALESCE(title, (SELECT name FROM recipes r WHERE r.id = meal_plan.recipe_id)) AS meal "
                 "FROM meal_plan WHERE id=?", (rid,))
        return r and {"day": r["day"], "slot": r["slot"], "meal": r["meal"] or ""}
    if table == "recipes":
        r = _one("SELECT name FROM recipes WHERE id=? AND COALESCE(status, 'active')='active'", (rid,))
        return r and {"name": r["name"]}
    if table == "id_documents":
        r = _one("SELECT person, doc_type, expires, number_last4 FROM id_documents WHERE id=? AND COALESCE(active, 1)=1",
                 (rid,))
        return r and {"person": r["person"] or "", "doc_type": r["doc_type"] or "", "expires": r["expires"] or "",
                      "last4": r["number_last4"] or ""}
    if table == "vehicles":
        r = _one("SELECT (SELECT MAX(odometer) FROM vehicle_log l WHERE l.vehicle_id=vehicles.id) AS odo, "
                 "year, make, model, vin_last4, plate, plate_last4, plate_region, owner, primary_driver, "
                 "registration_expires, inspection_expires, status, notes FROM vehicles "
                 "WHERE id=? AND COALESCE(status, 'active')='active'", (rid,))
        return r and {"kind": "oil_change", "when": dates.today().isoformat(), "odometer": "", "cost": "", "vendor": "",
                      "last_odometer": _num(r["odo"]), "year": _num(r["year"]), "make": r["make"] or "",
                      "model": r["model"] or "", "vin_last4": r["vin_last4"] or "", "plate": r["plate"] or "",
                      "plate_last4": r["plate_last4"] or "", "plate_region": r["plate_region"] or "",
                      "owner": r["owner"] or "", "primary_driver": r["primary_driver"] or "",
                      "registration_expires": r["registration_expires"] or "",
                      "inspection_expires": r["inspection_expires"] or "", "status": r["status"] or "active",
                      "notes": r["notes"] or ""}
    r = _one("SELECT name, who, last_done, provider FROM recurring_items WHERE id=? AND COALESCE(active, 1)=1", (rid,))
    return r and {"name": r["name"], "who": r["who"] or "", "last_done": r["last_done"] or "",
                  "when": dates.today().isoformat(), "provider": r["provider"] or ""}


def _list(rid):
    """An active list with its items as shown (open first, then the recently ticked), or None."""
    try:
        con = _con()
    except sqlite3.Error:
        return None
    try:
        r = L.get_list(con, rid)
        if not r or r["status"] != "active":
            return None
        its = L.items(con, rid)
    except sqlite3.Error:
        return None
    finally:
        con.close()
    return {"name": r["name"], "kind": r["kind"], "adults": r["audience"] == "adults", "text": "", "qty": "", "who": "",
            "items": [{"id": i["id"], "text": i["text"], "qty": i["qty"] or "", "who": i["assigned_to"] or "",
                       "done": i["status"] == "done"} for i in its]}


def _receipt(rid):
    """A receipt's status and, while it waits for a charge, its best candidate charges [(txn id, text)]."""
    try:
        con = _con()
    except sqlite3.Error:
        return None
    try:
        r = rc.get(con, rid)
        cands = rc.candidates(con, r)[:CANDIDATES_MAX] if r["status"] == "open" else []
    except (ValueError, sqlite3.Error):
        return None
    finally:
        con.close()
    return {"status": r["status"], "txn": "",
            "candidates": [(t["id"], f"{t['txn_date']} · {t['description']} · {money.fmt(-t['amount'])}"
                            f"{' · ' + t['account'] if t['account'] else ''} ({conf}: {note})") for t, conf, note in cands]}


def typed(table, data):
    """The fields of this table's forms that were sent (to show them again after a refusal), each cut to FIELD_MAX."""
    return {k: str(data[k])[:FIELD_LONG.get(k, FIELD_MAX)] for k in FIELDS.get(table, ()) if k in data}


def filed_docs(kinds, keep=None, limit=60):
    """Recent filed papers of these types, newest first, as [(id string, label)]; `keep` (the one linked now) is always
    in the list. Labels are date, vendor and type only."""
    try:
        con = _con()
    except sqlite3.Error:
        return []
    try:
        marks = ",".join("?" * len(kinds))
        rows = con.execute(f"SELECT id, doc_date, vendor, doc_type FROM documents WHERE doc_type IN ({marks}) OR id=? "
                           "ORDER BY doc_date DESC, id DESC LIMIT ?", (*kinds, keep or -1, limit)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        con.close()
    return [(str(r[0]), f"{r[1] or '?'} {r[2] or ''} ({r[3]})".replace("  ", " ")) for r in rows]


def _fields(table, data):
    return {**{k: "" for k in FIELDS[table]}, **typed(table, data)}


def _blank(s):
    s = str(s or "").strip()
    return "" if s in ("", "0") else s


def _who(s):
    s = str(s or "").strip()
    return None if s in ("", HOUSEHOLD) else s


def _activity_form(f):
    """activity_add / activity_update arguments from the class form (the day boxes become 'MO,WE')."""
    days = ",".join(d for d in activities.DAYS if f.get("d_" + d.lower()) in ("1", "on", "yes"))
    return {"title": f["title"], "weekdays": days, "who": _who(f["who"]), "provider": f["provider"].strip(),
            "start_time": f["start_time"].strip(), "end_time": f["end_time"].strip(),
            "term_start": f["term_start"].strip(), "term_end": f["term_end"].strip(),
            "school_days": f["school_days"] in ("1", "on", "yes")}


def edit(user, table, op, rid, data):
    """(ok, message, gone) for one operation on one row; gone = the row has left its list (removed or finished)."""
    if op not in EDIT_OPS.get(table, ()):
        return False, "That change is not offered here.", False
    before = values(table, rid)
    if before is None:
        return False, "That record is not there any more, or it is already finished.", True
    rid = int(rid)
    f = _fields(table, data)
    if table == "life_items":
        if op == "save":
            ok, msg = ea.life_update(user, rid, title=f["title"], who=_who(f["who"]), due=f["due"].strip(),
                                     every=_blank(f["every"]), amount=_blank(f["amount"]), provider=f["provider"].strip())
            return ok, msg, False
        if op == "done":
            ok, msg = ea.life_done(user, rid)
            return ok, msg, ok and not before["repeats"]
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, remove this item' first.", False
        ok, msg = ea.life_drop(user, rid)
        return ok, msg, ok
    if table == "activity_schedules":
        if op == "save":
            ok, msg = ea.activity_update(user, rid, **_activity_form(f))
            return ok, msg, False
        if op == "skip":
            ok, msg = ea.activity_skip(user, rid, f["skip"].strip())
            return ok, msg, False
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, the season is over' first.", False
        ok, msg = ea.activity_end(user, rid)
        return ok, msg, ok
    if table == "events":
        if op == "save":
            ok, msg = ea.event_update(user, rid, f["name"], f["date"].strip(), yearly=f["repeats"] == "yearly",
                                      start_time=f["start_time"].strip() or None, end_time=f["end_time"].strip() or None)
            return ok, msg, False
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, remove this event' first.", False
        ok, msg = ea.event_drop(user, rid)
        return ok, msg, ok
    if table == "appointments":
        if op == "save":
            when = f"{f['date'].strip()} {f['time'].strip()}".strip()
            ok, msg = ea.appointment_update(user, rid, _who(f["who"]), when, f["provider"].strip() or None,
                                            f["purpose"].strip() or None, f["followup"].strip() or None)
            return ok, msg, False
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, remove this appointment' first.", False
        ok, msg = ea.appointment_drop(user, rid)
        return ok, msg, ok
    if table == "calendar_days":
        if op == "save":
            ok, msg = ea.calendar_day_update(user, rid, f["day"].strip(), f["name"], f["kind"] or "holiday",
                                             f["end"].strip() or None, _who(f["who"]))
            return ok, msg, False
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, remove this day' first.", False
        ok, msg = ea.calendar_day_drop(user, rid)
        return ok, msg, ok
    if table == "vaccinations":
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, remove this' first.", False
        ok, msg = ea.vaccination_drop(user, rid)
        return ok, msg, ok
    if table == "member_info":
        if op == "verify":
            ok, msg = ea.member_info_verify(user, [rid])
            return ok, msg, False
        if op == "drop":
            if data.get("sure") not in ("1", "on", "yes"):
                return False, "Tick 'Yes, remove this' first.", False
            ok, msg = ea.member_info_drop(user, rid)
            return ok, msg, ok
        ok, msg = ea.member_info_update(user, rid, label=f["label"], value=f["value"], category=f["category"])
        return ok, msg, False
    if table == "home_contacts":
        if op == "used":
            ok, msg = ea.home_contact_used(user, rid)
            return ok, msg, False
        if op == "drop":
            if data.get("sure") not in ("1", "on", "yes"):
                return False, "Tick 'Yes, remove this contact' first.", False
            ok, msg = ea.home_contact_drop(user, rid)
            return ok, msg, ok
        ok, msg = ea.home_contact_update(user, rid, **f)
        return ok, msg, False
    if table == "members":
        ok, msg = ea.member_update(user, before["name"], role=f["role"], birthday=f["birthday"].strip(),
                                   year=f["year"].strip(), new_name=f["name"].strip(), school=f["school"].strip(),
                                   grade=f["grade"].strip(), grad_year=f["grad_year"].strip(), relation=f["relation"].strip())
        return ok, msg, False
    if table == "recurring_items":
        ok, msg = ea.recurring_done(user, rid, f["when"].strip() or None, f["provider"].strip() or None)
        return ok, msg, False
    if table == "bills":
        ok, msg = ea.bill_paid(user, rid, f["when"].strip() or None) if op == "paid" else ea.bill_unpaid(user, rid)
        return ok, msg, False
    if table == "subscriptions":
        if op == "decide":
            ok, msg = ea.subscription_decide(user, rid, f["decision"], f["note"].strip() or None)
        else:
            ok, msg = ea.subscription_set_active(user, rid, not before["active"])
        return ok, msg, False
    if table == "savings_goals":
        if op == "save":
            ok, msg = ea.savings_goal_update(user, rid, saved=f["saved"].strip(), target=f["target"].strip(), due=f["due"].strip(),
                                     account=f["account"].strip())
            return ok, msg, False
        if before["active"]:
            ok, msg = ea.savings_goal_update(user, rid, status="dropped" if f["how"] == "dropped" else "done")
        else:
            ok, msg = ea.savings_goal_update(user, rid, status="active")
        return ok, msg, ok and before["active"]
    if table == "loans":
        if op == "save":
            ok, msg = ea.loan_update(user, rid, balance=f["balance"].strip(), rate=f["rate"].strip(),
                                     payment=f["payment"].strip(), payoff=f["payoff"].strip())
            return ok, msg, False
        if before["active"] and data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, it is paid off' first.", False
        ok, msg = ea.loan_update(user, rid, status="paid_off" if before["active"] else "active")
        return ok, msg, ok and before["active"]
    if table == "home_assets":
        if op == "save":
            ok, msg = ea.asset_update(user, rid, **{k: f[k].strip() for k in ASSET_FIELDS})
            return ok, msg, False
        if op == "papers":
            allowed = {i for i, _ in before["receipt_docs"]} | {i for i, _ in before["manual_docs"]} | {""}
            rec, man = f["receipt"].strip(), f["manual"].strip()
            if rec not in allowed or man not in allowed:
                return False, "Pick the paper from the list.", False
            ok, msg = ea.asset_update(user, rid, receipt_document_id=rec, manual_document_id=man)
            return ok, msg, False
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, it is gone' first.", False
        ok, msg = ea.asset_dispose(user, rid, f["how"] or "disposed", f["when"].strip() or None)
        return ok, msg, ok
    if table == "seasonal_tasks":
        ok, msg = ea.seasonal_done(user, rid, f["when"].strip() or None, f["place"].strip() or None)
        return ok, msg, False
    if table == "lists":
        if op == "item_add":
            ok, msg = ea.list_item_add(user, rid, f["text"], f["qty"].strip() or None, _who(f["who"]))
            return ok, msg, False
        if op == "clear":
            ok, msg = ea.list_clear(user, rid)
            return ok, msg, False
        if op == "archive":
            if data.get("sure") not in ("1", "on", "yes"):
                return False, "Tick 'Yes, archive this list' first.", False
            ok, msg = ea.list_archive(user, rid)
            return ok, msg, ok
        if f["item"] not in {str(i["id"]) for i in before["items"]}:
            return False, "That item is not on this list any more.", False
        item = int(f["item"])
        if op == "drop":
            ok, msg = ea.list_item_drop(user, item)
        else:
            ok, msg = ea.list_item_tick(user, item, op == "tick")
        return ok, msg, False
    if table == "meal_plan":
        ok, msg = ea.meal_plan_clear(user, before["day"], before["slot"])
        return ok, msg, ok
    if table == "recipes":
        if data.get("sure") not in ("1", "on", "yes"):
            return False, "Tick 'Yes, archive this recipe' first.", False
        ok, msg = ea.recipe_archive(user, before["name"])
        return ok, msg, ok
    if table == "id_documents":
        ok, msg = ea.id_doc_set(user, before["person"], before["doc_type"], f["expires"].strip(), f["last4"].strip() or None)
        return ok, msg, False
    if table == "vehicles" and op == "save":
        ok, msg = ea.vehicle_update(user, rid, **{k: f[k].strip() for k in (
            "year", "make", "model", "vin_last4", "plate", "plate_region", "owner", "primary_driver",
            "registration_expires", "inspection_expires", "status", "notes")})
        return ok, msg, False
    if table == "vehicles":
        ok, msg = ea.vehicle_service(user, rid, f["kind"], f["when"].strip() or None, _blank(f["odometer"]) or None,
                                     _blank(f["cost"]) or None, f["vendor"].strip() or None)
        return ok, msg, False
    if (op == "unlink") == (before["status"] == "open"):
        return False, "That receipt has changed; open it again.", False
    if op == "link":
        if f["txn"] not in {str(t) for t, _ in before["candidates"]}:
            return False, "Pick one of the charges shown.", False
        ok, msg = ea.receipt_link(user, rid, int(f["txn"]))
    elif op == "ignore":
        ok, msg = ea.receipt_ignore(user, rid)
    else:
        ok, msg = ea.receipt_unlink(user, rid)
    return ok, msg, False


def add(user, part, data):
    """(ok, message) for an Add form of a part ((domain, section) in ADD); data["table"] picks the form when the part has
    more than one (the first otherwise)."""
    tables = add_tables(part)
    if not tables:
        return False, "Nothing can be added here."
    table = data.get("table") or tables[0]
    if table not in tables:
        return False, "Nothing can be added here."
    f = _fields(table, data)
    if table == "life_items":
        return ea.life_add(user, f["domain"], f["title"], _who(f["who"]), f["due"].strip() or None,
                           _blank(f["every"]) or None, _blank(f["amount"]) or None, f["provider"].strip() or None)
    if table == "activity_schedules":
        form = _activity_form(f)
        return ea.activity_add(user, form.pop("title"), form.pop("weekdays"), **form)
    if table == "calendar_days":
        return ea.calendar_day_add(user, f["day"].strip(), f["name"], f["kind"] or "holiday", f["end"].strip() or None,
                                   _who(f["who"]))
    if table == "events":
        return ea.event_add(user, f["name"], f["date"].strip(), yearly=f["repeats"] == "yearly",
                            start_time=f["start_time"].strip() or None, end_time=f["end_time"].strip() or None)
    if table == "home_contacts":
        return ea.home_contact_add(user, **f)
    if table == "vaccinations":
        return ea.vaccination_add(user, _who(f["who"]), f["vaccine"], f["given"].strip(), f["next_due"].strip() or None,
                                  f["provider"].strip() or None, f["notes"].strip() or None)
    if table == "member_info":
        return ea.member_info_add(user, _who(f["who"]), f["category"], f["label"], f["value"])
    if table == "subscriptions":
        return ea.subscription_add(user, f["name"], _blank(f["amount"]) or None, f["frequency"] or "monthly",
                                   f["renew"].strip() or None)
    if table == "receipts":
        return ea.receipt_add(user, f["merchant"], f["date"].strip(), f["total"].strip(), f["last4"].strip() or None)
    if table == "budget":
        category = f["category"].strip()
        if data.get("remove") in ("1", "on", "yes"):
            return ea.budget_delete(user, category)
        return ea.budget_set(user, category, f["limit"].strip())
    if table == "loans":
        return ea.loan_add(user, f["name"], f["kind"] or "other", f["lender"].strip() or None, f["balance"].strip() or None,
                           f["rate"].strip() or None, f["payment"].strip() or None, f["payoff"].strip() or None)
    if table == "home_office_profile":
        return ea.home_office_set(user, f["year"].strip(), f["who"], f["office"].strip() or None, f["home"].strip() or None,
                                  f["months"].strip() or None, f["method"] or None, f["self_employed"], f["exclusive"],
                                  f["regular"], f["principal"], f["income"].strip() or None)
    if table == "savings_goals":
        return ea.savings_goal_add(user, f["name"], f["target"].strip(), f["due"].strip() or None, f["saved"].strip() or None,
                           f["account"].strip() or None)
    if table == "home_assets":
        return ea.asset_add(user, f["name"], **{k: f[k].strip() for k in ASSET_FIELDS[1:] if f[k].strip()})
    if table == "lists":
        return ea.list_new(user, f["name"], f["kind"] or "todo", data.get("adults") in ("1", "on", "yes"))
    if table == "meal_plan":
        return ea.meal_plan_set(user, f["day"].strip(), f["slot"], f["what"], f["note"].strip() or None)
    if table == "recipes":
        return ea.recipe_save(user, f["name"], f["ingredients"], f["servings"].strip() or None, f["tags"].strip() or None,
                              f["url"].strip() or None, f["notes"].strip() or None)
    if table == "meal_shop":
        return ea.meal_shop(user, f["start"].strip() or None, f["end"].strip() or None, f["list_name"].strip() or "Groceries")
    if table == "id_documents":
        return ea.id_doc_set(user, f["person"], f["doc_type"], f["expires"].strip(), f["last4"].strip() or None)
    if table == "vehicles":
        return ea.vehicle_add(user, f["make"], f["model"], f["year"].strip() or None)
    if table == "accounts":
        return ea.account_add(user, f["name"], f["kind"], f["last4"].strip() or None, f["owner"].strip() or None)
    return ea.member_add(user, f["name"], f["role"], f["birthday"].strip(), f["year"].strip())
