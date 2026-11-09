"""Records: where each kind of row lives, what to call it, and how an answer points back to it. No AI, read-only.

  python data/records.py label bills:12          what the row is called ("Electric bill, due October 2")
  python data/records.py show bills:12           its fields, source paper and history
  python data/records.py find water bill         rows and filed papers that hold every word
  python data/records.py cite "SELECT SUM(amount) FROM transactions WHERE category='Groceries'"

A reference ("ref") is `table:id` or `table:id,id,...` (at most 50 ids). The dashboard opens one with
`?page=records&ref=bills:12`; the assistant attaches refs to its answers (`refs_for_sql` works out which rows a
read-only query used). Only the tables in SECTION can be referred to: chat links, the Inbox queue, sign-in and
migration bookkeeping never show here.

The Records page groups the rows into six domains (People, Home, Vehicles, Money, Papers & IDs, Subscriptions);
SECTION says which part of which domain holds each table.
"""
import argparse
import pathlib
import datetime as dt
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402

DB = paths.DB
MAX_IDS = 50
EACH = 5  # up to this many rows are cited one by one; more become one "N payments" link

DOMAINS = [("people", "People"), ("home", "Home"), ("vehicles", "Vehicles"), ("money", "Money"),
           ("papers", "Papers & IDs")]
# Finance has a rail page of its own (dashboard_app); "subs" was a domain of its own before 0.73.0: old links still work
LEGACY_DOMAIN = {"subs": "money"}

# domain -> [(section key, title)]; the dashboard draws each section with the same code the older tabs used
SECTIONS = {
    "people": [("people", "People"), ("life", "Life items"), ("health", "Checkups and appointments"), ("school", "School"),
               ("classes", "Classes and activities"), ("dates", "Holidays and dates"), ("profiles", "Critical info")],
    "home": [("lists", "Lists"), ("meals", "Meals"), ("saved", "Saved"), ("upkeep", "Upkeep"), ("contacts", "Service contacts"), ("inventory", "Inventory"),
             ("shopping", "Shopping")],
    "vehicles": [("vehicles", "Vehicles")],
    "money": [("bills", "Bills"), ("receipts", "Receipts"), ("paypal", "PayPal"), ("budget", "Budget and loans"), ("accounts", "Accounts"),
              ("ledger", "Ledger"), ("trends", "Trends"), ("mobile", "Phone bills"), ("deposits", "Deposit sources"), ("benefits", "Card benefits"),
              ("watch", "Missing statements"), ("spikes", "Price rises"), ("tax", "Tax papers"), ("home_office", "Home office"),
              ("year_end", "Year-end"), ("work", "Work"),
              ("subs", "Subscriptions"), ("amazon", "Amazon orders")],
    "papers": [("papers", "Papers"), ("ids", "Expiries and IDs"), ("policies", "Insurance"), ("emergency", "Emergency sheet")],
}

# Finance parts grouped for the pills (Pay / Keep / Look back); parts not listed fall into the last group
GROUPS = {"money": [("Pay", ["bills", "receipts", "paypal", "mobile", "subs", "amazon"]),
                    ("Keep", ["accounts", "budget", "benefits"]),
                    ("Look back", ["ledger", "deposits", "trends", "watch", "spikes", "tax", "home_office", "year_end", "work"])]}

# raw column name -> what a person reads at the top of a table
LABELS = {
    "appt_datetime": "When", "followup_due": "Follow-up due", "due_date": "Due", "birth_year": "Born", "birth_month_day": "Birthday",
    "days_left": "Days left", "txn_date": "Date", "doc_date": "Date", "doc_type": "Type", "event_date": "Date",
    "registration_expires": "Registration", "inspection_expires": "Inspection", "warranty_end": "Warranty ends",
    "purchase_date": "Bought", "brand_model": "Brand and model", "maturity_date": "Matures", "as_of": "As of",
    "current_value": "Value now", "last4": "Last 4", "phone_last4": "Phone (last 4)", "policy_last4": "Policy (last 4)",
    "per_year": "Per year", "per_month": "Per month", "every_months": "Every (months)", "recur_months": "Every (months)",
    "last_done": "Last done", "next_due": "Next due", "operating_net": "Left after bills", "line_total": "Line total",
    "account_share": "Share of account", "bill_date": "Bill date", "total_due": "Total due", "amount_due": "Amount due",
}
NICE = {"operating_net": "Left after bills", "income": "Income", "expenses": "Spent", "left": "Left"}


def column_label(name):
    """The heading a person reads for a raw column name."""
    n = str(name)
    if n in LABELS:
        return LABELS[n]
    t = n.replace("_", " ").strip()
    return t[:1].upper() + t[1:]


# table -> (domain, section)
SECTION = {
    "members": ("people", "people"), "life_items": ("people", "life"), "recurring_items": ("people", "health"),
    "recurring_log": ("people", "health"), "appointments": ("people", "health"), "vaccinations": ("people", "health"), "events": ("people", "dates"),
    "activity_schedules": ("people", "classes"), "calendar_days": ("people", "dates"), "member_info": ("people", "profiles"),
    "lists": ("home", "lists"), "list_items": ("home", "lists"), "recipes": ("home", "meals"), "meal_plan": ("home", "meals"),
    "saved_items": ("home", "saved"), "seasonal_tasks": ("home", "upkeep"), "seasonal_log": ("home", "upkeep"),
    "home_assets": ("home", "inventory"), "shopping_items": ("home", "shopping"), "home_contacts": ("home", "contacts"),
    "vehicles": ("vehicles", "vehicles"), "vehicle_log": ("vehicles", "vehicles"),
    "bills": ("money", "bills"), "receipts": ("money", "receipts"), "loans": ("money", "budget"),
    "savings_goals": ("money", "budget"), "accounts": ("money", "accounts"), "account_balances": ("money", "accounts"), "investments": ("money", "accounts"),
    "interest_income": ("money", "accounts"), "transactions": ("money", "ledger"), "card_benefits": ("money", "benefits"),
    "home_office_expenses": ("money", "home_office"), "contracts": ("money", "work"), "work_hours": ("money", "work"),
    "work_invoices": ("money", "work"),
    "documents": ("papers", "papers"), "id_documents": ("papers", "ids"), "policies": ("papers", "policies"),
    "policy_vehicles": ("papers", "policies"), "policy_drivers": ("papers", "policies"),
    "policy_coverages": ("papers", "policies"), "policy_discounts": ("papers", "policies"), "wallet_cards": ("papers", "ids"),
    "subscriptions": ("money", "subs"), "amazon_orders": ("money", "amazon"),
    "mobile_bills": ("money", "mobile"), "mobile_bill_lines": ("money", "mobile"), "mobile_bill_items": ("money", "mobile"),
}
UPKEEP = ("Home", "Car", "Admin", "Lawn", "Winter", "Safety")  # recurring_items categories that are house jobs, not people

# what one row is called: SQL expression over the row's columns (missing columns fall back to the generic label)
LABEL = {
    "members": "name",
    "life_items": "title || COALESCE(' (' || member || ')', '') || COALESCE(', due ' || due_date, '')",
    "recurring_items": "name || COALESCE(' (' || who || ')', '') || COALESCE(', last done ' || last_done, '')",
    "recurring_log": "'Done ' || done_date",
    "appointments": "COALESCE(purpose, 'Appointment') || ' (' || person || '), ' || substr(appt_datetime, 1, 10)",
    "events": "name || ', ' || event_date",
    "activity_schedules": "title || COALESCE(' (' || member || ')', '') || ', ' || weekdays",
    "calendar_days": "name || COALESCE(' (' || member || ')', '') || ', ' || day",
    "member_info": "label || ' (' || member || ')'",
    "home_contacts": "name || ' (' || replace(trade, '_', ' ') || ')'",
    "lists": "name || ' list'",
    "list_items": "text",
    "recipes": "name",
    "meal_plan": "day || ' ' || slot || ': ' || COALESCE(title, 'recipe')",
    "saved_items": "title",
    "seasonal_tasks": "name",
    "seasonal_log": "'Done ' || done_date",
    "home_assets": "name",
    "shopping_items": "item || ' (' || list_name || ')'",
    "vehicles": "COALESCE(year || ' ', '') || COALESCE(make, '') || ' ' || COALESCE(model, '')",
    "vehicle_log": "replace(kind, '_', ' ') || ', ' || log_date",
    "bills": "COALESCE(vendor, name) || COALESCE(', due ' || due_date, '')",
    "receipts": "COALESCE(merchant, 'Receipt') || COALESCE(', ' || receipt_date, '')",
    "loans": "name",
    "savings_goals": "name || ' (savings goal)'",
    "accounts": "name || COALESCE(' x' || last4, '')",
    "account_balances": "'Balance on ' || as_of",
    "investments": "name",
    "interest_income": "'Interest, ' || period_end",
    "transactions": "COALESCE(payee, description) || ', ' || txn_date",
    "card_benefits": "name",
    "home_office_expenses": "category || ', ' || COALESCE(expense_date, tax_year)",
    "contracts": "client || COALESCE(' (' || person || ')', '')",
    "work_hours": "'Hours on ' || work_date",
    "work_invoices": "'Invoice ' || period_start || ' to ' || period_end",
    "documents": "COALESCE(vendor || ' ', '') || replace(COALESCE(doc_type, 'paper'), '_', ' ') || COALESCE(', ' || doc_date, '')",
    "id_documents": "person || ' ' || replace(doc_type, '_', ' ')",
    "policies": "carrier || ' ' || kind || ' policy' || COALESCE(' x' || policy_last4, '')",
    "policy_vehicles": "COALESCE(year || ' ', '') || COALESCE(make, '') || ' ' || COALESCE(model, '')",
    "policy_drivers": "name",
    "policy_coverages": "coverage",
    "policy_discounts": "name",
    "subscriptions": "name",
    "amazon_orders": "'Amazon order, ' || order_date",
    "mobile_bills": "carrier || ' bill, ' || bill_date",
    "mobile_bill_lines": "person || COALESCE(' x' || phone_last4, '')",
    "mobile_bill_items": "label",
    "wallet_cards": "title || COALESCE(' (' || member || ')', '')",
    "vaccinations": "vaccine || ' (' || member || '), ' || given_on",
}
NOUN = {"transactions": "payments", "bills": "bills", "documents": "papers", "life_items": "items", "recurring_items": "checkups",
        "appointments": "appointments", "members": "people", "accounts": "accounts", "receipts": "receipts",
        "subscriptions": "subscriptions", "policies": "policies", "vehicles": "vehicles", "list_items": "list items",
        "activity_schedules": "classes", "calendar_days": "days", "member_info": "facts", "home_contacts": "contacts",
        "wallet_cards": "wallet cards", "vaccinations": "vaccinations"}

# word search: text columns per table (saved items go through saved.search, which knows who may see what)
SEARCH = {
    "members": ["name"], "life_items": ["title", "member", "provider", "domain"], "recurring_items": ["name", "who", "provider"],
    "appointments": ["person", "provider", "purpose"], "events": ["name"], "activity_schedules": ["title", "member", "provider"],
    "calendar_days": ["name", "member"], "vaccinations": ["vaccine", "member", "provider"], "recipes": ["name", "tags"], "wallet_cards": ["title", "member", "issuer", "details"], "home_contacts": ["name", "trade", "notes"],
    "home_assets": ["name", "category", "brand_model", "location", "store"], "shopping_items": ["item", "list_name", "store"],
    "vehicles": ["make", "model", "owner"], "bills": ["name", "vendor"], "receipts": ["merchant"], "loans": ["name", "lender"], "savings_goals": ["name"],
    "accounts": ["name", "owner"], "investments": ["name", "kind"], "transactions": ["description", "payee", "category"],
    "contracts": ["client", "vendor", "person"], "documents": ["vendor", "doc_type", "notes"],
    "id_documents": ["person", "doc_type"], "policies": ["carrier", "kind", "insured_names"], "subscriptions": ["name", "category"],
}
HIDDEN_COLS = {"id", "calendar_event_id", "dedupe_key", "match_pattern", "qualify_pattern", "credit_pattern", "code_hash"}
MONEY_COLS = {"amount", "price", "premium_total", "premium", "balance", "total", "cost", "paid", "est_price", "monthly_limit",
              "invested", "current_value", "payment", "hourly_rate", "gross_income", "deductible", "net",
              "line_total", "account_share", "bill_total", "total_due", "account_wide", "plan", "devices", "perks", "surcharges",
              "taxes"}
ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def words_date(text, today=None):
    """'due 2026-10-16' -> 'due October 16' (the year only when it is not this year)."""
    today = today or dates.today()

    def one(m):
        try:
            d = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return m.group(0)
        return f"{d:%B} {d.day}" + ("" if d.year == today.year else f", {d.year}")
    return ISO.sub(one, str(text))


BIRTHDAY_COLS = ("birthday", "birth_month_day")


def _value(col, v):
    if col == "season" and isinstance(v, str) and re.fullmatch(r"\d\d-\d\d to \d\d-\d\d", v):  # "03-01 to 04-15" -> "Mar 1 to Apr 15"
        import dates
        a, b = v.split(" to ")
        return f"{dates.md_text(a, short=True) or a} to {dates.md_text(b, short=True) or b}"
    if col in BIRTHDAY_COLS and isinstance(v, str):  # "03-14" -> "Mar 14"
        import dates
        return dates.md_text(v, short=True) or v
    if col in MONEY_COLS and isinstance(v, (int, float)):
        try:
            import money
            return money.fmt(v)
        except Exception:  # noqa: BLE001
            return f"{v:,.2f}"
    return str(v)[:300]
KEYWORDS = {"where", "join", "left", "right", "inner", "outer", "cross", "natural", "full", "on", "group", "order", "limit",
            "having", "union", "using", "window", "except", "intersect"}


# ------------------------------------------------------------------ refs
def ref_str(table, ids):
    ids = [int(i) for i in ids][:MAX_IDS]
    return f"{table}:{','.join(str(i) for i in ids)}"


def parse_ref(s):
    """'bills:12' or 'transactions:3,4,5' -> (table, [ids]); None when it is not a ref to a citable table."""
    m = re.fullmatch(r"([a-z_]+):(\d+(?:,\d+){0,%d})" % (MAX_IDS - 1), str(s or "").strip())
    if not m or m.group(1) not in SECTION:
        return None
    return m.group(1), [int(x) for x in m.group(2).split(",")]


def where(table, row=None):
    """-> (domain, section) for a table; checkups that are house jobs open under Home > Upkeep."""
    dom, sec = SECTION.get(table, (None, None))
    if table == "recurring_items" and row and str(row.get("category") or "") in UPKEEP:
        return "home", "upkeep"
    return dom, sec


def _cols(con, table):
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


WORK_TABLES = ("contracts", "work_hours", "work_invoices")


def _job_visible(con, row, table, user):
    """A private job (and its hours and invoices) belongs to its owner; shared jobs show to every adult."""
    if table == "contracts":
        c = row
    elif con is not None and row.get("contract_id") is not None:
        c = _row(con, "contracts", row["contract_id"])
    else:
        return True
    if c is None or (c.get("visibility") or "shared") != "private":
        return True
    return (c.get("person") or "").lower() == ((user or {}).get("name") or "").lower()


def _visible(row, table, user, con=None):
    """Private saved items and private jobs belong to their owner; adults-only saved items to adults."""
    if row is None:
        return False
    if table in WORK_TABLES:
        return _job_visible(con, row, table, user)
    if table != "saved_items":
        return True
    aud = (row.get("audience") or "family").lower()
    if aud == "private":
        return (row.get("owner") or "").lower() == ((user or {}).get("name") or "").lower()
    return aud != "adults" or (user or {}).get("role", "adult") == "adult"


def _row(con, table, rid):
    cur = con.execute(f"SELECT * FROM {table} WHERE id = ?", (int(rid),))
    r = cur.fetchone()
    return dict(zip([d[0] for d in cur.description], r)) if r else None


def _generic(row):
    for k in ("name", "title", "description", "vendor", "item", "text"):
        if row.get(k):
            return str(row[k])
    return "record"


def label(con, table, rid, user=None):
    """Plain name of one row, or None when it does not exist (or is someone else's private item)."""
    if table not in SECTION:
        return None
    try:
        row = _row(con, table, rid)
    except sqlite3.Error:
        return None
    if not _visible(row, table, user, con):
        return None
    expr = LABEL.get(table)
    if expr:
        try:
            v = con.execute(f"SELECT {expr} FROM {table} WHERE id = ?", (int(rid),)).fetchone()
            if v and v[0]:
                return words_date(str(v[0]).strip())
        except sqlite3.Error:
            pass
    return _generic(row)


def cite(con, table, ids, user=None):
    """-> {"ref", "label", "table", "ids"} for one row or a group of rows; None when nothing is left to show."""
    ids = [int(i) for i in ids][:MAX_IDS]
    if table not in SECTION or not ids:
        return None
    if len(ids) == 1:
        name = label(con, table, ids[0], user)
        return {"ref": ref_str(table, ids), "label": name, "table": table, "ids": ids} if name else None
    if table == "saved_items" or table in WORK_TABLES:
        ids = [i for i in ids if label(con, table, i, user)]
        if not ids:
            return None
    return {"ref": ref_str(table, ids), "label": f"{len(ids)} {NOUN.get(table, 'records')}", "table": table, "ids": ids}


# ------------------------------------------------------------------ which rows did a query use
def _top_level(sql):
    """Positions of keywords at parenthesis depth 0 and outside quotes: [(pos, keyword lowercased, end)]."""
    out, depth, i, n, quote = [], 0, 0, len(sql), None
    kw = re.compile(r"(?i)(from|where|group\s+by|having|order\s+by|limit|union|except|intersect|window)\b")
    while i < n:
        c = sql[i]
        if quote:
            if c == quote:
                quote = None
        elif c in ("'", '"', "`"):
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and (i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")):
            m = kw.match(sql, i)
            if m:
                out.append((i, re.sub(r"\s+", " ", m.group(1).lower()), m.end()))
                i = m.end()
                continue
        i += 1
    return out


def rows_used(con, sql):
    """For a read-only SELECT, the (table, ids) of the main table's rows it read: the FROM table, filtered by the same
    WHERE (GROUP BY, ORDER BY and LIMIT dropped, so a SUM cites every row it added up). (None, []) when unclear:
    WITH queries, a sub-query in FROM, a table that is not citable."""
    s = (sql or "").strip().rstrip(";")
    if not re.match(r"(?is)^select\b", s) or ";" in s:
        return None, []
    marks = _top_level(s)
    frm = next((m for m in marks if m[1] == "from"), None)
    if not frm:
        return None, []
    stop = next((m[0] for m in marks if m[0] > frm[0] and m[1] not in ("from", "where")), len(s))
    body = s[frm[2]:stop]
    m = re.match(r"\s*([A-Za-z_]\w*)(?:\s+(?:as\s+)?([A-Za-z_]\w*))?", body, re.I)
    if not m:
        return None, []
    table = m.group(1).lower()
    alias = m.group(2) if m.group(2) and m.group(2).lower() not in KEYWORDS else m.group(1)
    if table not in SECTION:
        return None, []
    try:
        was = con.execute("PRAGMA query_only").fetchone()[0]
        con.execute("PRAGMA query_only = ON")
        try:
            ids = [r[0] for r in con.execute(f"SELECT DISTINCT {alias}.id FROM {body} LIMIT {MAX_IDS + 1}")]
        finally:
            con.execute(f"PRAGMA query_only = {int(bool(was))}")
    except sqlite3.Error:
        return None, []
    return table, [i for i in ids if isinstance(i, int)]


def refs_for_sql(con, sql, user=None):
    """Citations for one query: up to EACH rows one by one, more as one group link."""
    table, ids = rows_used(con, sql)
    if not table or not ids:
        return []
    if len(ids) <= EACH:
        return [c for c in (cite(con, table, [i], user) for i in ids) if c]
    c = cite(con, table, ids[:MAX_IDS], user)
    if c and len(ids) > MAX_IDS:
        c["label"] = f"{MAX_IDS}+ {NOUN.get(table, 'records')}"
    return [c] if c else []


def refs_for_items(con, items, user=None, limit=8):
    """Citations for action_items rows (each may carry ref = (table, id))."""
    out, seen = [], set()
    for it in items:
        r = it.get("ref") if isinstance(it, dict) else None
        if not r or not r[1] or r[0] not in SECTION or (r[0], r[1]) in seen:
            continue
        seen.add((r[0], r[1]))
        c = cite(con, r[0], [r[1]], user)
        if c:
            out.append(c)
        if len(out) >= limit:
            break
    return out


# ------------------------------------------------------------------ one row in full
def _plain(col):
    return col.replace("_", " ").replace("md", "(month-day)") if col.endswith("_md") else col.replace("_", " ")


def detail(con, table, rid, user=None):
    """-> {"label", "fields": [(name, value)], "source": {id, label, path} | None, "domain", "section", "row"} or None."""
    if table not in SECTION:
        return None
    try:
        row = _row(con, table, rid)
    except sqlite3.Error:
        return None
    if not _visible(row, table, user, con):
        return None
    fields = []
    for k, v in row.items():
        if v in (None, "") or k in HIDDEN_COLS or k.endswith("_id") or k.endswith("_cents"):
            continue
        fields.append((_plain(k), _value(k, v)))
    src = None
    doc_id = row.get("document_id") or row.get("receipt_document_id")
    if table == "documents":
        doc_id = row["id"]
    if doc_id:
        d = _row(con, "documents", doc_id) if doc_id else None
        if d:
            src = {"id": d["id"], "label": label(con, "documents", d["id"]), "path": d.get("filed_path") or ""}
    dom, sec = where(table, row)
    return {"label": label(con, table, rid, user) or _generic(row), "fields": fields, "source": src, "domain": dom,
            "section": sec, "row": row}


def source_file(path):
    """The archived file for a documents.filed_path, only when it is inside this install's archive/."""
    if not path:
        return None
    base = paths.ARCHIVE.resolve()
    for cand in (paths.HOME / path, base / path):
        try:
            p = cand.resolve()
            p.relative_to(base)
        except (OSError, ValueError):
            continue
        if p.is_file():
            return p
    return None


# edits.log action -> (table, the key that holds the row id); longest prefix wins
ACTION_TABLE = [("life_", "life_items", "id"), ("activity_", "activity_schedules", "id"),
                ("calendar_day_", "calendar_days", "id"), ("member_info_", "member_info", "id"), ("home_contact_", "home_contacts", "id"), ("loan_", "loans", "id"), ("savings_goal_", "savings_goals", "id"), ("subscription_", "subscriptions", "id"),
                ("id_doc_", "id_documents", "id"), ("asset_", "home_assets", "id"), ("list_item_", "list_items", "id"),
                ("list_", "lists", "id"), ("saved_", "saved_items", "id"), ("receipt_", "receipts", "id"),
                ("work_contract", "contracts", "id"), ("work_profile", "contracts", "id"), ("work_invoice", "work_invoices", "id"),
                ("recipe_", "recipes", "id"), ("meal_plan_set", "meal_plan", "id"), ("recurring_done", "recurring_items", "id"),
                ("recurring_stop", "recurring_items", "id"), ("seasonal_done", "seasonal_tasks", "id"),
                ("review_file", "documents", "document"), ("recurring_confirm", "bills", "bill"), ("member_", "members", "name"),
                ("txn_update", "transactions", "id")]


def history(table, rid, limit=20, name=None):
    """Changes made from the dashboard and chat to this row (logs/edits.log: when, who, what; never free text).
    Members are logged by name, so pass name= for them."""
    log = paths.LOGS / "edits.log"
    if not log.exists():
        return []
    want = str(name if table == "members" else int(rid)).lower()
    out = []
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    for line in lines:
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        hit = max((m for m in ACTION_TABLE if parts[2].startswith(m[0])), key=lambda m: len(m[0]), default=None)
        if not hit or hit[1] != table:
            continue
        m = re.search(rf"(?:^|\s){hit[2]}=(\S+)", parts[3])
        if m and m.group(1).lower() == want:
            out.append({"when": parts[0].replace("T", " ")[:16], "who": parts[1], "what": parts[2].replace("_", " ")})
    return out[-limit:][::-1]


# ------------------------------------------------------------------ search
def search(con, words, user=None, limit=30):
    """Rows whose text holds every word, plus filed papers whose content matches. -> [{ref, label, table, domain, kind}]."""
    ws = [w for w in re.findall(r"[\w'.-]+", (words or "").lower()) if len(w) > 1][:6]
    if not ws:
        return []
    out, seen = [], set()

    def add(table, rid, kind):
        if (table, rid) in seen or len(out) >= limit:
            return
        c = cite(con, table, [rid], user)
        if c:
            seen.add((table, rid))
            c.update({"domain": where(table, _row(con, table, rid))[0], "kind": kind})
            out.append(c)

    for table, cols in SEARCH.items():
        have = set(_cols(con, table))
        cols = [c for c in cols if c in have]
        if not cols:
            continue
        hay = " || ' ' || ".join(f"lower(COALESCE({c}, ''))" for c in cols)
        sql = f"SELECT id FROM {table} WHERE " + " AND ".join(f"({hay}) LIKE ?" for _ in ws) + " ORDER BY id DESC LIMIT 8"
        try:
            for (rid,) in con.execute(sql, [f"%{w}%" for w in ws]):
                add(table, rid, NOUN.get(table, table.replace("_", " ")))
        except sqlite3.Error:
            continue
    try:
        import saved
        for r in saved.search(con, viewer=user or {"name": "", "role": "adult"}, words=" ".join(ws), limit=8) or []:
            add("saved_items", r["id"], "saved")
    except Exception:  # noqa: BLE001 (saved items are optional)
        pass
    if (user or {}).get("role", "adult") == "adult":
        try:
            import archive_search
            for h in archive_search.search(con, " ".join(ws), limit=8):
                add("documents", h["id"], "papers")
        except Exception:  # noqa: BLE001
            pass
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("label", "show"):
        sub.add_parser(name).add_argument("ref")
    sub.add_parser("find").add_argument("words", nargs="+")
    sub.add_parser("cite").add_argument("sql")
    a = ap.parse_args(argv)
    con = db.connect(DB, readonly=True)
    try:
        if a.cmd in ("label", "show"):
            r = parse_ref(a.ref)
            if not r:
                print("not a reference: use table:id")
                return 1
            if a.cmd == "label":
                for i in r[1]:
                    print(f"{r[0]}:{i}  {label(con, r[0], i) or '(not found)'}")
                return 0
            d = detail(con, r[0], r[1][0])
            if not d:
                print("(not found)")
                return 1
            print(d["label"])
            for k, v in d["fields"]:
                print(f"  {k}: {v}")
            if d["source"]:
                print(f"  paper: {d['source']['label']}")
            for h in history(r[0], r[1][0], name=d["row"].get("name")):
                print(f"  {h['when']} {h['who']}: {h['what']}")
        elif a.cmd == "find":
            for h in search(con, " ".join(a.words)):
                print(f"{h['ref']:<20} {h['kind']:<12} {h['label']}")
        else:
            for c in refs_for_sql(con, a.sql):
                print(f"{c['ref']:<30} {c['label']}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

