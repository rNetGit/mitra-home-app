"""Sync with paired phones: what changed since the phone last asked (pull) and the small edits a phone queued (push).

  python data/sync_data.py status        change log size, oldest entry, edits received from phones
  python data/sync_data.py triggers      put the change-log triggers back (a migration that rebuilds a table drops them)
  python data/sync_data.py prune         forget change-log entries older than 90 days (run by the daily task)

Change log (table sync_log, migration 044): triggers on every table a phone may carry write (table, rowid, op) on
each insert, update and delete, whoever made the change (web app, agents, scripts, the terminal). No content is
logged, only which row changed. Entries older than KEEP_DAYS are pruned; a phone that has not synced for that long
starts over with a full copy.

Pull (`GET /api/sync/pull?cursor=`): the cursor is opaque to the phone. It carries the change-log position and a
signature of the phone's person, live role and scopes. No cursor, a cursor from another signature (an adult changed
the phone's scopes, the person's role changed), a pruned position or a position past the end of the log (the
database was restored from a backup) all mean `reset`: the phone wipes its copy and takes a full one, page by page.
Otherwise the phone gets, per table, the rows that changed and may be seen (`upsert`) and the ids it must forget
(`delete`: removed rows and rows it may no longer see). Rows are re-read when sent, so the phone always gets the
current version; sending a row twice is harmless.

What a phone may carry (SOURCES), always within its person's live role (data/devices.py):
  people    members' names, role, birthday month-day          everyone
  own       their own open life items in the safe domains     limited (children, guests)
  calendar  adults: appointments, events, open life items;    limited: their own appointments
            weekly classes (activities) and holidays / school days off (days): adults all, limited their own and the
            household's; the tradition or school a day came from (calendar_days.label, source) never leaves the PC
  lists     active lists and their items (adult lists only for adults)
  bills     bills and subscriptions                           adults
  notes     saved links and notes the person may see          adults
  finance   accounts (last4 only), budget, transactions (the first copy carries the last SNAPSHOT_TXN_DAYS days); the
            last page of a pull also carries summary.money = wall_money.for_phone (Money > Spending / Bills / Regular as
            the PC counts them; webapp/routes_phone.py)
  ids       ID documents (type, last4, dates; no notes, no scans) and the Wallet: cars (plate, colour, body type,
            expiries), current insurance policies (carrier, last4, term) and wallet_cards (wallet.py)
Files (scans, statements) are never synced.

Push (`POST /api/sync/push`): up to MAX_OPS small edits, each with the phone's own id. Each goes through
data/edit_actions.py as the phone's person (same checks, same edits.log) and needs the matching scope. A repeat of an
id already answered gets the stored status back and changes nothing (a phone retrying after a dropped connection).
Ops: list_add, list_tick, life_done, bill_paid, note_add, and the phone's quick-add forms event_add (name, date,
optional time and end 'HH:MM', yearly), appointment_add (who, when 'YYYY-MM-DD HH:MM', provider, purpose) and life_add (a reminder: title, due, who,
domain, notes), adults with the calendar scope only, and vehicle_details (vehicle_id, plate, plate_region, color, body_type;
adults with the ids scope). The phone's Manage calendar adds event_update (event_id, name, date, time,
end, yearly), event_drop (event_id), day_add / day_update (day_id, name, day, end, kind, who: a holiday, festival, no-school or
early-dismissal day) and day_drop (day_id): the same edit_actions functions as the Records forms. /api/ping lists the ops this phone may send, so a phone hides a
form an older PC does not know.
'retry' (the database was busy) is not stored, so the phone sends it again later. The PC wins: an edit that no longer
fits (the item was finished or removed meanwhile) is 'rejected' with a sentence, and the phone drops it.
"""
import datetime as dt
import hashlib
import pathlib
import re
import secrets
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import db as _db  # noqa: E402

VERSION = 1
# The oldest phone app this PC still serves. A phone sends X-App-Version on every /api/ call; an older one is answered
# 426 {"error": "phone_too_old", "min_phone"} so it tells its person to update instead of misreading new answers.
# Raise it in the same release as an API change an older phone cannot handle. Phones before 0.10 send no version.
MIN_PHONE = "0.9.0"


def version_tuple(v):
    """"0.10.2" -> (0, 10, 2); anything unreadable -> None."""
    parts = str(v or "").strip().split(".")
    try:
        return tuple(int(x) for x in parts[:3]) if len(parts) >= 2 else None
    except ValueError:
        return None


def phone_too_old(v):
    """True when a phone's X-App-Version is older than MIN_PHONE (no or unreadable version: not refused)."""
    have = version_tuple(v)
    return have is not None and have < version_tuple(MIN_PHONE)
KEEP_DAYS = 90
PAGE = 500            # rows per pull answer
LOG_PAGE = 2000       # change-log entries read per incremental pull answer
MAX_OPS = 50
SNAPSHOT_TXN_DAYS = 400
_CLIENT_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SAFE_DOMAINS = ("school", "activity", "chore", "gift", "travel", "pet", "medical", "other")  # = limited_view


def _adult(dev):
    return dev.get("role") == "adult"


def _mine(dev, who):
    return bool(who) and who == dev.get("member")


def _wall(dev):
    """The Mitra Home app in wall mode (webapp/routes_wall_api.py): the household's tablet, not a person. It carries what
    the wall shows of everyone (calendar, family lists, children's jobs, meals), never money, notes or adults-only rows."""
    return dev.get("role") == "wall"


WALL_DAYS = 35     # how far ahead a wall's copy reaches (offline plan D2)
WALL_BACK = 14     # how far back it keeps jobs done and meals


# name -> (table, scope or None = everyone, {role: columns}, visible(row, dev), snapshot WHERE or None)
# A role missing from the columns map never gets the table.
SOURCES = {
    "people": ("members", None,
               {"adult": ("id", "name", "role", "birth_month_day"), "limited": ("id", "name", "role", "birth_month_day"),
                "wall": ("id", "name", "role", "birth_month_day")},
               lambda r, d: True, None),
    "own": ("life_items", "own",
            {"limited": ("id", "domain", "member", "title", "due_date", "status", "provider")},
            lambda r, d: r["status"] == "open" and r["domain"] in SAFE_DOMAINS and (r["member"] is None or _mine(d, r["member"])),
            None),
    "life_items": ("life_items", "calendar",
                   {"adult": ("id", "domain", "member", "title", "due_date", "recur_months", "lead_days", "amount",
                              "status", "last_done", "provider", "notes")},
                   lambda r, d: r["status"] == "open", None),
    "appointments": ("appointments", "calendar",
                     {"adult": ("id", "person", "provider", "purpose", "appt_datetime", "followup_due"),
                      "limited": ("id", "person", "provider", "purpose", "appt_datetime"),
                      "wall": ("id", "person", "purpose", "appt_datetime")},
                     lambda r, d: _adult(d) or _wall(d) or _mine(d, r["person"]), None),
    "events": ("events", "calendar", {"adult": ("id", "name", "event_date", "recurs_yearly", "start_time", "end_time"),
                                      "wall": ("id", "name", "event_date", "recurs_yearly", "start_time", "end_time")},
               lambda r, d: True, None),
    "activities": ("activity_schedules", "calendar",
                   {"adult": ("id", "member", "title", "provider", "weekdays", "start_time", "end_time", "term_start",
                              "term_end", "skip_dates", "school_days", "status"),
                    "limited": ("id", "member", "title", "provider", "weekdays", "start_time", "end_time", "term_start",
                                "term_end", "skip_dates", "school_days", "status"),
                    "wall": ("id", "member", "title", "weekdays", "start_time", "end_time", "term_start", "term_end",
                             "skip_dates", "school_days", "status")},
                   lambda r, d: r["status"] == "active" and (_adult(d) or _wall(d) or _mine(d, r["member"])), None),
    "days": ("calendar_days", "calendar",
             {"adult": ("id", "day", "end_day", "kind", "name", "member"),
              "limited": ("id", "day", "end_day", "kind", "name", "member"),
              "wall": ("id", "day", "end_day", "kind", "name", "member")},
             lambda r, d: r["status"] == "active" and (_adult(d) or _wall(d) or r["member"] is None or _mine(d, r["member"])),
             None),
    "lists": ("lists", "lists",
              {"adult": ("id", "name", "kind", "audience"), "limited": ("id", "name", "kind", "audience"),
               "wall": ("id", "name", "kind", "audience")},
              lambda r, d: r["status"] == "active" and (_adult(d) or r["audience"] == "family"), None),
    "list_items": ("list_items", "lists",
                   {"adult": ("id", "list_id", "text", "qty", "assigned_to", "status", "added_by", "added_at", "done_by",
                              "done_at"),
                    "limited": ("id", "list_id", "text", "qty", "assigned_to", "status", "added_by", "added_at",
                                "done_by", "done_at"),
                    "wall": ("id", "list_id", "text", "qty", "assigned_to", "status", "added_at", "done_at")},
                   None, None),  # visible: see _visible (depends on the list)
    # ---- a wall only (scope "wall"): what the Mitra Wall draws for the next WALL_DAYS while the PC is off -----------
    "needs": ("life_items", "wall", {"wall": ("id", "domain", "member", "title", "due_date")},
              lambda r, d: r["status"] == "open" and r["domain"] in SAFE_DOMAINS, "due_date <= :ahead"),
    "routines": ("routines", "wall", {"wall": ("id", "member", "part", "title", "icon", "stars", "weekdays", "sort")},
                 lambda r, d: r["status"] == "active", None),
    "routine_done": ("routine_done", "wall", {"wall": ("id", "routine_id", "day", "stars")},
                     lambda r, d: True, "day >= :back"),
    "rewards": ("rewards", "wall", {"wall": ("id", "title", "stars", "member")},
                lambda r, d: r["status"] == "active", None),
    "reward_claims": ("reward_claims", "wall", {"wall": ("id", "reward_id", "member", "stars", "asked_at")},
                      lambda r, d: r["status"] == "asked", None),
    "meals": ("meal_plan", "wall", {"wall": ("id", "day", "slot", "recipe_id", "title")},
              lambda r, d: True, "day >= :back"),
    "recipes": ("recipes", "wall", {"wall": ("id", "name")}, lambda r, d: r["status"] == "active", None),
    "bills": ("bills", "bills",
              {"adult": ("id", "name", "vendor", "frequency", "amount", "due_date", "status", "paid_date")},
              lambda r, d: True, None),
    "subscriptions": ("subscriptions", "bills", {"adult": ("id", "name", "amount", "frequency", "next_renewal", "active")},
                      lambda r, d: True, None),
    "notes": ("saved_items", "notes",
              {"adult": ("id", "kind", "title", "url", "domain", "body", "place_address", "expires_on", "tags",
                         "audience", "owner", "pinned", "added_at")},
              lambda r, d: r["status"] == "active" and (r["audience"] != "private" or _mine(d, r["owner"])), None),
    "accounts": ("accounts", "finance", {"adult": ("id", "name", "type", "last4", "currency")}, lambda r, d: True, None),
    "budget": ("budget", "finance", {"adult": ("id", "category", "monthly_limit")}, lambda r, d: True, None),
    "transactions": ("transactions", "finance",
                     {"adult": ("id", "account_id", "txn_date", "description", "amount", "category", "payee", "txn_type")},
                     lambda r, d: True, "txn_date >= :since"),
    "id_documents": ("id_documents", "ids",
                     {"adult": ("id", "person", "doc_type", "number_last4", "issued", "expires", "issuing_authority",
                                "active")},
                     lambda r, d: True, None),
    "vehicles": ("vehicles", "ids",
                 {"adult": ("id", "year", "make", "model", "color", "body_type", "plate", "plate_region", "plate_last4",
                            "vin_last4", "registration_expires", "inspection_expires", "status")},
                 lambda r, d: (r["status"] or "active") == "active", None),
    "policies": ("policies", "ids",
                 {"adult": ("id", "kind", "carrier", "policy_last4", "term_start", "term_end", "prior_policy_id", "status")},
                 lambda r, d: (r["status"] or "active") == "active", None),
    "wallet_cards": ("wallet_cards", "ids",
                     {"adult": ("id", "kind", "title", "member", "issuer", "number", "number_last4", "where_hint",
                                "details", "expires", "status")},
                     lambda r, d: r["status"] == "active", None),
}
TABLES = sorted({s[0] for s in SOURCES.values()})


# ---- change log --------------------------------------------------------------------------------------------------
def ensure_triggers(con):
    """Create the change-log triggers on every synced table that exists (idempotent). -> number of tables covered."""
    have = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    n = 0
    for t in TABLES:
        if t not in have:
            continue
        for op, ev, ref in (("I", "INSERT", "NEW"), ("U", "UPDATE", "NEW"), ("D", "DELETE", "OLD")):
            con.execute(f"CREATE TRIGGER IF NOT EXISTS sync_{t}_{op.lower()} AFTER {ev} ON {t} BEGIN "
                        f"INSERT INTO sync_log(tbl, row_id, op, ts) VALUES ('{t}', {ref}.rowid, '{op}', "
                        f"strftime('%Y-%m-%dT%H:%M:%S','now','localtime')); END")
        n += 1
    return n


def prune(con, now=None):
    """Forget change-log entries older than KEEP_DAYS (the last entry always stays, so the log never restarts at 1)."""
    cut = ((now or dt.datetime.now()) - dt.timedelta(days=KEEP_DAYS)).isoformat(timespec="seconds")
    last = con.execute("SELECT MAX(id) FROM sync_log").fetchone()[0]
    if last is None:
        return 0
    return con.execute("DELETE FROM sync_log WHERE ts < ? AND id < ?", (cut, last)).rowcount


_PRUNED = {"at": None}


def maybe_prune(con, now=None):
    """prune() at most once an hour per running app."""
    now = now or dt.datetime.now()
    if _PRUNED["at"] and (now - _PRUNED["at"]).total_seconds() < 3600:
        return 0
    _PRUNED["at"] = now
    n = prune(con, now)
    con.commit()
    return n


def _log_bounds(con):
    lo, hi = con.execute("SELECT MIN(id), MAX(id) FROM sync_log").fetchone()
    return lo or 0, hi or 0


# ---- what this phone may see -------------------------------------------------------------------------------------
def sources_for(dev):
    """Source names this phone carries, in SOURCES order."""
    role, scopes = dev.get("role"), set(dev.get("scopes") or [])
    return [k for k, (_, scope, cols, _, _) in SOURCES.items() if role in cols and (scope is None or scope in scopes)]


def signature(dev, ep=""):
    raw = f"{VERSION}|{dev.get('member')}|{dev.get('role')}|{','.join(sources_for(dev))}|{ep}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


EPOCH_KEY = "sync_epoch"


def epoch(con):
    """Random id of this copy of the database (`meta` key sync_epoch), folded into every cursor. A restored backup
    gets a new one (restore_backup.restore_db), so each phone takes a full copy again instead of trusting a cursor
    into a change log that went back in time (audit M9)."""
    try:
        r = con.execute("SELECT value FROM meta WHERE key=?", (EPOCH_KEY,)).fetchone()
    except sqlite3.OperationalError as e:
        if not _db.missing(e):
            raise
        return ""
    if r and r[0]:
        return str(r[0])
    return new_epoch(con)


def new_epoch(con):
    v = secrets.token_hex(4)
    con.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (EPOCH_KEY, v))
    con.commit()
    return v


def _columns(con, table, want):
    have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
    return [c for c in want if c == "id" or c in have]


def _select(con, table, cols):
    return ", ".join("rowid AS id" if c == "id" else c for c in cols)


def _visible(con, name, row, dev, lists_seen):
    if name == "list_items":
        lid = row["list_id"]
        if lid not in lists_seen:
            lr = con.execute("SELECT status, audience FROM lists WHERE id=?", (lid,)).fetchone()
            lists_seen[lid] = bool(lr) and SOURCES["lists"][3](lr, dev)
        return lists_seen[lid] and row["status"] in ("open", "done")
    return SOURCES[name][3](row, dev)


def _fetch(con, name, dev, ids):
    """{rowid: row dict (only the role's columns) or None (gone or not for this phone)} for these rowids."""
    table, _, cols, _, _ = SOURCES[name]
    want = _columns(con, table, cols[dev["role"]])
    extra = [c for c in ("status", "audience", "owner", "member", "person", "domain", "list_id")
             if c not in want and c in {r[1] for r in con.execute(f"PRAGMA table_info({table})")}]
    out, seen = {i: None for i in ids}, {}
    ids = list(ids)
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        sql = f"SELECT {_select(con, table, want + extra)} FROM {table} WHERE rowid IN ({','.join('?' * len(part))})"
        for r in con.execute(sql, part):
            if _visible(con, name, r, dev, seen):
                out[r["id"]] = {c: r[c] for c in want}
    return out


# ---- cursor ------------------------------------------------------------------------------------------------------
def _cursor(sig, log_id, snap=None):
    return f"{VERSION}.{sig}.{log_id}" + (f".{snap[0]}.{snap[1]}" if snap else "")


def _parse(cursor):
    """-> (sig, log_id, (source index, after rowid) or None) or None."""
    parts = str(cursor or "").split(".")
    if len(parts) not in (3, 5) or parts[0] != str(VERSION) or not all(p.isdigit() for p in parts[2:]):
        return None
    nums = [int(p) for p in parts[2:]]
    return parts[1], nums[0], (tuple(nums[1:]) if len(nums) == 3 else None)


# ---- pull --------------------------------------------------------------------------------------------------------
def pull(con, dev, cursor=None, today=None, page=PAGE, log_page=LOG_PAGE):
    """One page of changes for this phone. con needs row_factory sqlite3.Row.

    -> {'cursor', 'reset', 'more', 'changes': {source: {'upsert': [rows], 'delete': [ids]}}, 'sources'}"""
    con.row_factory = sqlite3.Row
    sig, names = signature(dev, epoch(con)), sources_for(dev)
    lo, hi = _log_bounds(con)
    p = _parse(cursor)
    reset = (p is None or p[0] != sig or p[1] > hi or (p[2] is None and p[1] < lo - 1))
    if reset:
        out = _snapshot(con, dev, names, sig, hi, (0, 0), today, page, True)
    elif p[2] is not None:
        out = _snapshot(con, dev, names, sig, p[1], p[2], today, page, False)
    else:
        out = _changes(con, dev, names, sig, p[1], hi, log_page)
    extras = _extras(con, dev, names, today)
    if extras:
        out["phone_extras"] = extras  # not "extras": a wall tablet keeps its own `extras` (wall_copy.extras)
    return out


SPECIAL_BACK, SPECIAL_AHEAD = 7, 400  # the built-in days a phone shows (= wall_copy.SPECIAL_BACK / SPECIAL_AHEAD)


def _extras(con, dev, names, today=None):
    """What a phone gets besides table rows, with every answer (the phone replaces it each time): `special_days`, the
    public holidays and the festivals of the family's traditions the PC works out by rule (calendar_days rows the family
    stored are in the `days` table). A phone that carries the calendar gets them: {'special_days': [{'start', 'end',
    'kind', 'name'}]}. No tradition label or source is sent, only the day's name and kind."""
    if "days" not in names or (dev or {}).get("role") == "wall":
        return {}
    import calendar_days
    today = today or dates.today()
    try:
        rows = calendar_days.between(today - dt.timedelta(days=SPECIAL_BACK), today + dt.timedelta(days=SPECIAL_AHEAD), con)
    except Exception:  # noqa: BLE001 (a broken rules file must not stop a sync)
        return {}
    return {"special_days": [{"start": r["start"].isoformat(), "end": r["end"].isoformat(), "kind": r["kind"], "name": r["name"]}
                             for r in rows if not r.get("id")]}


def _empty(names):
    return {n: {"upsert": [], "delete": []} for n in names}


def _snapshot(con, dev, names, sig, log_at, pos, today, page, reset):
    today = today or dates.today()
    since = (today - dt.timedelta(days=SNAPSHOT_TXN_DAYS)).isoformat()
    window = {"since": since, "back": (today - dt.timedelta(days=WALL_BACK)).isoformat(),
              "ahead": (today + dt.timedelta(days=WALL_DAYS)).isoformat()}
    changes, left, (si, after) = _empty(names), page, pos
    while si < len(names) and left > 0:
        name = names[si]
        table, _, cols, _, where = SOURCES[name]
        try:
            q = f"SELECT rowid FROM {table} WHERE rowid > :after" + (f" AND {where}" if where else "")
            ids = [r[0] for r in con.execute(q + " ORDER BY rowid LIMIT :n", {"after": after, "n": left, **window})]
        except sqlite3.OperationalError as e:
            if not _db.missing(e):
                raise
            ids = []
        if ids:
            rows = _fetch(con, name, dev, ids)
            changes[name]["upsert"] += [r for r in rows.values() if r]
            left -= len(ids)
            after = ids[-1]
        if not ids or left > 0:  # this source is done
            si, after = si + 1, 0
    done = si >= len(names)
    cur = _cursor(sig, log_at) if done else _cursor(sig, log_at, (si, after))
    return {"cursor": cur, "reset": reset, "more": not done, "changes": changes, "sources": names}


def _changes(con, dev, names, sig, since, hi, log_page):
    rows = con.execute("SELECT id, tbl, row_id FROM sync_log WHERE id > ? ORDER BY id LIMIT ?", (since, log_page)).fetchall()
    last = rows[-1]["id"] if rows else since
    touched = {}
    for r in rows:
        touched.setdefault(r["tbl"], set()).add(r["row_id"])
    if "lists" in touched and "list_items" in names:  # a list archived or made adults-only: its items go too
        lids = sorted(touched["lists"])
        for k in range(0, len(lids), 500):
            part = lids[k:k + 500]
            touched.setdefault("list_items", set()).update(
                i for (i,) in con.execute(f"SELECT rowid FROM list_items WHERE list_id IN ({','.join('?' * len(part))})", part))
    changes = _empty(names)
    for name in names:
        ids = touched.get(SOURCES[name][0])
        if not ids:
            continue
        for rid, row in sorted(_fetch(con, name, dev, ids).items()):
            if row:
                changes[name]["upsert"].append(row)
            else:
                changes[name]["delete"].append(rid)
    return {"cursor": _cursor(sig, last), "reset": False, "more": last < hi and len(rows) == log_page,
            "changes": changes, "sources": names}


# ---- push --------------------------------------------------------------------------------------------------------
def _int(x):
    if isinstance(x, bool) or not isinstance(x, (int, str)) or not (str(x).isascii() and str(x).isdigit()):
        raise ValueError  # "²" and other Unicode digits are not ids
    return int(x)


def _str(x, n):
    if x is None:
        return None
    if not isinstance(x, str):
        raise ValueError
    return x[:n]


# op -> (scope for adults, scope for limited or None = adults only)
OPS = {
    "list_add": ("lists", "lists"),
    "list_tick": ("lists", "lists"),
    "life_done": ("calendar", "own"),
    "bill_paid": ("bills", None),
    "note_add": ("notes", None),
    # the phone's Add sheet (event, appointment, reminder): adults with the calendar scope; queued offline, applied at the next sync
    "event_add": ("calendar", None),
    "appointment_add": ("calendar", None),
    "life_add": ("calendar", None),
    # the Wallet's car card: whole plate, state, colour, body type (adults with the ids scope; the plate is the user's
    # decision of 2026-10-17: kept whole on the PC and the phone, never sent anywhere else)
    "vehicle_details": ("ids", None),
    # Manage calendar on the phone (companion 0.23): change or remove a family event, add / change / remove a calendar day
    "event_update": ("calendar", None),
    "event_drop": ("calendar", None),
    "day_add": ("calendar", None),
    "day_update": ("calendar", None),
    "day_drop": ("calendar", None),
}


def _bool(x, default):
    if x is None:
        return default
    if not isinstance(x, bool):
        raise ValueError
    return x


def _apply(actor, op, o):
    import edit_actions as ea
    if op == "list_add":
        return ea.list_item_add(actor, _int(o.get("list_id")), _str(o.get("text"), 200) or "", _str(o.get("qty"), 40))
    if op == "list_tick":
        done = o.get("done", True)
        if not isinstance(done, bool):
            raise ValueError
        return ea.list_item_tick(actor, _int(o.get("item_id")), done)
    if op == "life_done":
        if actor["role"] == "adult":
            return ea.life_done(actor, _int(o.get("item_id")))
        return ea.life_done_own(actor, _int(o.get("item_id")))
    if op == "bill_paid":
        return ea.bill_paid(actor, _int(o.get("bill_id")), _str(o.get("paid_on"), 10))
    if op == "note_add":
        aud = o.get("audience", "family")
        if aud not in ("family", "adults", "private"):
            raise ValueError
        return ea.saved_add(actor, _str(o.get("title"), 300) or "", _str(o.get("url"), 2100), _str(o.get("kind"), 20),
                            _str(o.get("note"), 6000), _str(o.get("tags"), 500), None, None, aud)
    if op == "event_add":  # a family event, at a time of day when the phone sends one (events.start_time / end_time)
        return ea.event_add(actor, _str(o.get("name"), 200) or "", _str(o.get("date"), 20) or "",
                            _bool(o.get("yearly"), False), start_time=_str(o.get("time"), 10),
                            end_time=_str(o.get("end"), 10))
    if op == "appointment_add":
        return ea.appointment_add(actor, _str(o.get("who"), 80) or "", _str(o.get("when"), 30) or "",
                                  _str(o.get("provider"), 200), _str(o.get("purpose"), 200))
    if op == "life_add":  # a reminder: something to do by a date
        return ea.life_add(actor, _str(o.get("domain"), 20) or "other", _str(o.get("title"), 300) or "",
                           _str(o.get("who"), 80), _str(o.get("due"), 20) or "", None, None, None,
                           _str(o.get("notes"), 600))
    if op == "vehicle_details":  # all four fields travel together: edit_actions.vehicle_details clears what is left out
        return ea.vehicle_details(actor, _int(o.get("vehicle_id")), _str(o.get("color"), 20) or "",
                                  _str(o.get("body_type"), 20) or "", _str(o.get("plate"), 10) or "",
                                  _str(o.get("plate_region"), 20) or "")
    if op == "event_update":
        return ea.event_update(actor, _int(o.get("event_id")), _str(o.get("name"), 200) or "", _str(o.get("date"), 20) or "",
                               _bool(o.get("yearly"), False), start_time=_str(o.get("time"), 10), end_time=_str(o.get("end"), 10))
    if op == "event_drop":
        return ea.event_drop(actor, _int(o.get("event_id")))
    if op == "day_add":
        return ea.calendar_day_add(actor, _str(o.get("day"), 20) or "", _str(o.get("name"), 200) or "",
                                   _str(o.get("kind"), 20) or "holiday", _str(o.get("end"), 20), _str(o.get("who"), 80))
    if op == "day_update":
        return ea.calendar_day_update(actor, _int(o.get("day_id")), _str(o.get("day"), 20) or "", _str(o.get("name"), 200) or "",
                                      _str(o.get("kind"), 20) or "holiday", _str(o.get("end"), 20), _str(o.get("who"), 80))
    if op == "day_drop":
        return ea.calendar_day_drop(actor, _int(o.get("day_id")))
    raise ValueError


def push(con, dev, ops, now=None):
    """Apply a phone's queued edits in order. -> list of {'id', 'status': ok|rejected|retry, 'message'[, 'repeat']}.
    `con` is used for the receipts only; each edit opens its own transaction in edit_actions."""
    import edit_actions as ea
    now = (now or dt.datetime.now()).isoformat(timespec="seconds")
    actor = {"name": dev["member"], "role": dev["role"]}
    scopes = set(dev.get("scopes") or [])
    out = []
    waiting = False
    for o in (ops or [])[:MAX_OPS]:
        cid = o.get("id") if isinstance(o, dict) else None
        if not isinstance(cid, str) or not _CLIENT_ID.match(cid):
            out.append({"id": cid if isinstance(cid, str) else None, "status": "rejected", "message": "Bad edit id."})
            continue
        if waiting:  # an earlier edit has to be retried: later ones wait too, so the order on the phone is kept
            out.append({"id": cid, "status": "retry", "message": "Waiting for an earlier edit."})
            continue
        old = con.execute("SELECT id, status, op, created_at FROM sync_ops WHERE device_id=? AND client_id=?",
                          (dev["id"], cid)).fetchone()
        if old and _in_flight(old, now):  # being applied by another request right now: ask again shortly
            out.append({"id": cid, "status": "retry", "message": "Still being saved."})
            waiting = True
            continue
        if old and old[2].startswith(PENDING):  # a claim whose request died before the edit was finished (S10)
            con.execute("DELETE FROM sync_ops WHERE id=?", (old[0],))
            con.commit()
        elif old:
            out.append({"id": cid, "status": old[1], "repeat": True, "message": "Already received."})
            continue
        op = o.get("op")
        # claim the id before doing anything (audit M15): a second push of the same id, racing this one, finds the
        # claim and waits; the claim is marked in flight (op "~name") until the edit is made, so a crash in between
        # is not mistaken for a saved edit (audit S10): its claim is dropped and the edit applied on the next push
        name = str(op)[:19] if op in OPS else "unknown"
        claim = con.execute("INSERT OR IGNORE INTO sync_ops(device_id, client_id, op, status, created_at) VALUES (?,?,?,'ok',?)",
                            (dev["id"], cid, PENDING + name, now))
        con.commit()
        if claim.rowcount != 1:
            out.append({"id": cid, "status": "retry", "message": "Still being saved."})
            waiting = True
            continue
        rid = claim.lastrowid
        need = OPS.get(op, (None, None))[0 if dev["role"] == "adult" else 1]
        try:
            if op not in OPS:
                ok, msg = False, "This app version does not know that edit."
            elif not need or need not in scopes:
                ok, msg = False, "This phone may not make that change."
            else:
                try:
                    ok, msg = _apply(actor, op, o)
                except ValueError:
                    ok, msg = False, "That edit is not complete."
        except BaseException:
            con.execute("DELETE FROM sync_ops WHERE id=?", (rid,))
            con.commit()
            raise
        if not ok and msg == ea.BUSY:
            con.execute("DELETE FROM sync_ops WHERE id=?", (rid,))
            con.commit()
            out.append({"id": cid, "status": "retry", "message": msg})
            waiting = True
            continue
        con.execute("UPDATE sync_ops SET op=?, status=? WHERE id=?", (name, "ok" if ok else "rejected", rid))
        con.commit()
        out.append({"id": cid, "status": "ok" if ok else "rejected", "message": msg})
    return out


PENDING = "~"          # sync_ops.op prefix while an edit is being applied
PENDING_STALE = 120    # seconds: an older in-flight claim belonged to a request that died


def _in_flight(row, now):
    """True for a claim another request is still working on (in flight and younger than PENDING_STALE)."""
    if not str(row[2]).startswith(PENDING):
        return False
    try:
        age = (dt.datetime.fromisoformat(now) - dt.datetime.fromisoformat(str(row[3])[:19])).total_seconds()
    except ValueError:
        return False
    return age < PENDING_STALE


# ---- CLI ---------------------------------------------------------------------------------------------------------
def status(con):
    n, lo_ts = con.execute("SELECT COUNT(*), MIN(ts) FROM sync_log").fetchone()
    ops = con.execute("SELECT status, COUNT(*) FROM sync_ops GROUP BY status").fetchall()
    return {"log_entries": n, "oldest": lo_ts, "edits": {s: c for s, c in ops}}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    try:
        con = _db.connect(paths.DB)
    except sqlite3.Error as e:
        print("Could not open the database:", e)
        return 1
    try:
        if cmd == "status":
            s = status(con)
            print(f"change log: {s['log_entries']} entries since {s['oldest'] or '-'}; edits from phones: "
                  + (", ".join(f"{c} {k}" for k, c in s["edits"].items()) or "none"))
            return 0
        if cmd == "prune":  # the daily task: a household without phones never pulls, so the log is pruned here too
            n = prune(con)
            con.commit()
            print(f"change log: {n} old entries removed")
            return 0
        if cmd == "triggers":
            n = ensure_triggers(con)
            con.commit()
            print(f"change-log triggers on {n} tables")
            return 0
    finally:
        con.close()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
