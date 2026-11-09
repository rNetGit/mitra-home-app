"""Validated edits for the web app: house contacts, the Card Wallet, inventory, ID documents, shared lists, saved items and meals (split from edit_actions.py, audit A9).

See edit_core.py for the rules every edit follows; edit_actions.py re-exports everything, callers keep using it.
"""
import sqlite3
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import dates  # noqa: E402
import home_contacts as hc  # noqa: E402
import validators as v  # noqa: E402
import wallet as wl  # noqa: E402
from edit_core import (  # noqa: E402
    EditError,
    _adult,
    _clean,
    _con,
    _log,
    _lv,
    _member_name,
    _opt,
    _signed_in,
    edits,
)


# ---------------------------------------------------------------- house maintenance contacts (home_contacts.py)
CONTACT_TRADES = tuple(k for k, _ in hc.TRADES)
CONTACT_FIELDS = ("name", "trade", "phone", "email", "website", "notes", "last_used", "rating", "again")


def _contact(con, rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise EditError("that contact is not on file") from None
    r = con.execute(f"SELECT id, {', '.join(CONTACT_FIELDS)} FROM home_contacts WHERE id=? AND status='active'",
                    (rid,)).fetchone()
    if not r:
        raise EditError("that contact is not on file")
    return dict(zip(("id",) + CONTACT_FIELDS, r))


def _again(x):
    s = str(x).strip().lower()
    if s in ("1", "yes", "true", "on"):
        return 1
    if s in ("0", "no", "false"):
        return 0
    raise ValueError("yes or no")


def _contact_values(f):
    """Validated contact fields from a dict; a blank optional field becomes None (cleared)."""
    return {"name": _clean(v.text(80), f.get("name"), "name"),
            "trade": _clean(v.one_of(CONTACT_TRADES), f.get("trade") or "other", "kind of work"),
            "phone": _opt(hc.phone, f.get("phone"), "phone"),
            "email": _opt(hc.email, f.get("email"), "email"),
            "website": _opt(hc.website, f.get("website"), "website"),
            "notes": _opt(v.text(300), f.get("notes"), "notes"),
            "last_used": _opt(v.iso_date, f.get("last_used"), "last job"),
            "rating": _opt(v.integer(1, 5), f.get("rating"), "rating"),
            "again": _opt(_again, f.get("again"), "use again")}


@edits
def home_contact_add(actor, **f):
    """A plumber, furnace company, garage, handyman ... the household has had work done by."""
    _adult(actor)
    new = _contact_values(f)
    with _con() as con:
        if con.execute("SELECT 1 FROM home_contacts WHERE name=? AND trade=? AND status='active'",
                       (new["name"], new["trade"])).fetchone():
            raise EditError(f"{new['name']} is already on the list: change that one")
        rid = con.execute(f"INSERT INTO home_contacts({', '.join(CONTACT_FIELDS)}) VALUES ({','.join('?' * len(CONTACT_FIELDS))})",
                          [new[k] for k in CONTACT_FIELDS]).lastrowid
        _log(actor, "home_contact_add", f"id={rid} trade={new['trade']}")
    return f"Saved {new['name']}."


@edits
def home_contact_update(actor, rid, **f):
    """Change a contact: every field of the form (blank optional field = cleared)."""
    _adult(actor)
    with _con() as con:
        old = _contact(con, rid)
        new = _contact_values({**old, **f})
        if (new["name"], new["trade"]) != (old["name"], old["trade"]) and con.execute(
                "SELECT 1 FROM home_contacts WHERE name=? AND trade=? AND status='active' AND id!=?",
                (new["name"], new["trade"], old["id"])).fetchone():
            raise EditError(f"{new['name']} is already on the list")
        changed = [k for k in CONTACT_FIELDS if new[k] != old[k]]
        con.execute(f"UPDATE home_contacts SET {', '.join(k + '=?' for k in CONTACT_FIELDS)}, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') "
                    "WHERE id=?", [*(new[k] for k in CONTACT_FIELDS), old["id"]])
        _log(actor, "home_contact_update", f"id={old['id']} fields={','.join(changed) or 'none'}")
    return f"Saved {new['name']}."


@edits
def home_contact_used(actor, rid, day=None):
    """'Used them today' (or on DAY): sets the last job date."""
    _adult(actor)
    day = _opt(v.iso_date, day, "date") or dates.today().isoformat()
    with _con() as con:
        old = _contact(con, rid)
        con.execute("UPDATE home_contacts SET last_used=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id=?", (day, old["id"]))
        _log(actor, "home_contact_used", f"id={old['id']}")
    return f"Noted a job by {old['name']} on {day}."


@edits
def home_contact_drop(actor, rid):
    _adult(actor)
    with _con() as con:
        old = _contact(con, rid)
        con.execute("UPDATE home_contacts SET status='dropped', updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id=?", (old["id"],))
        _log(actor, "home_contact_drop", f"id={old['id']}")
    return f"Removed {old['name']}."


# ---------------------------------------------------------------- Card Wallet (wallet.py, migration 053)
def _wallet_card(con, rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise EditError("that card is not in the wallet") from None
    r = con.execute(f"SELECT id, {', '.join(wl.FIELDS)} FROM wallet_cards WHERE id=? AND status='active'", (rid,)).fetchone()
    if not r:
        raise EditError("that card is not in the wallet")
    return dict(zip(("id",) + wl.FIELDS, r))


def _wallet_values(con, f):
    """Validated card fields; a blank optional field becomes None. Only membership, loyalty and library cards keep the
    full number (a barcode needs it); any other kind keeps the last four only."""
    kind = _clean(v.one_of([k for k, _ in wl.KINDS]), f.get("kind") or "other", "kind of card")
    out = {"kind": kind, "title": _clean(v.text(60), f.get("title"), "name on the card"),
           "member": None, "issuer": _opt(v.text(60), f.get("issuer"), "issued by"),
           "number": _opt(wl.number, f.get("number"), "number"),
           "number_last4": _opt(wl.last4, f.get("number_last4"), "last 4"),
           "where_hint": _opt(v.text(120), f.get("where_hint"), "where the number is"),
           "details": _opt(v.text(300), f.get("details"), "details"),
           "expires": _opt(v.iso_date, f.get("expires"), "expires")}
    if out["number"] and kind not in wl.FULL_NUMBER:
        raise EditError("only membership, store and library cards keep the whole number; type the last 4 instead")
    if out["number"]:
        out["number_last4"] = out["number"].replace(" ", "").replace("-", "")[-4:]
    who = str(f.get("member") or "").strip()
    if who:
        out["member"] = _member_name(con, who)
        if not out["member"]:
            raise EditError("whose card: pick a family member")
    return out


@edits
def wallet_card_add(actor, scan=None, **f):
    """A card for the Wallet that no other record holds: membership, store, library, travel, health or home facts.
    `scan` = a waiting photo (wallet.draft_path): filed under archive/<year>/ids/ and shown on the card's back."""
    _adult(actor)
    with _con() as con:
        new = _wallet_values(con, f)
        rid = con.execute(f"INSERT INTO wallet_cards({', '.join(wl.FIELDS)}) VALUES ({','.join('?' * len(wl.FIELDS))})",
                          [new[k] for k in wl.FIELDS]).lastrowid
        if scan:
            import ai_intake
            try:
                doc_id, _dest = ai_intake.file_document(con, scan, "id", new["title"], dates.today().isoformat(),
                                                        note="Wallet card photo")
            except ValueError as e:
                raise EditError(f"the photo could not be filed: {e}") from None
            con.execute("UPDATE wallet_cards SET document_id=? WHERE id=?", (doc_id, rid))
        _log(actor, "wallet_card_add", f"id={rid} kind={new['kind']}" + (" scan" if scan else ""))
    return f"Added {new['title']} to the wallet."


@edits
def wallet_card_update(actor, rid, **f):
    """Change a wallet card: every field of the form (blank optional field = cleared)."""
    _adult(actor)
    with _con() as con:
        old = _wallet_card(con, rid)
        new = _wallet_values(con, {**old, **f})
        changed = [k for k in wl.FIELDS if new[k] != old[k]]
        con.execute(f"UPDATE wallet_cards SET {', '.join(k + '=?' for k in wl.FIELDS)}, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') "
                    "WHERE id=?", [*(new[k] for k in wl.FIELDS), old["id"]])
        _log(actor, "wallet_card_update", f"id={old['id']} fields={','.join(changed) or 'none'}")
    return f"Saved {new['title']}."


@edits
def wallet_card_drop(actor, rid):
    _adult(actor)
    with _con() as con:
        old = _wallet_card(con, rid)
        con.execute("UPDATE wallet_cards SET status='dropped', updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id=?", (old["id"],))
        _log(actor, "wallet_card_drop", f"id={old['id']}")
    return f"Removed {old['title']} from the wallet."


@edits
def vehicle_details(actor, vehicle_id, color=None, body_type=None, plate=None, plate_region=None):
    """The car card's colour, body type and plate. The plate is kept whole (it is on the street for anyone to read);
    the VIN stays last4."""
    _adult(actor)
    new = {"color": _opt(wl.color, color, "colour"),
           "body_type": _opt(v.one_of(wl.BODY_TYPES), body_type, "body type"),
           "plate": _opt(wl.plate, plate, "plate"), "plate_region": _opt(wl.region, plate_region, "state or region")}
    try:
        vehicle_id = int(vehicle_id)
    except (TypeError, ValueError):
        raise EditError("that vehicle is not there any more") from None
    with _con() as con:
        if not con.execute("SELECT 1 FROM vehicles WHERE id=? AND COALESCE(status, 'active')='active'",
                           (vehicle_id,)).fetchone():
            raise EditError("that vehicle is not there any more")
        last4 = new["plate"].replace(" ", "").replace("-", "")[-4:] if new["plate"] else None
        con.execute("UPDATE vehicles SET color=?, body_type=?, plate=?, plate_region=?, "
                    "plate_last4=COALESCE(?, plate_last4) WHERE id=?",
                    (new["color"], new["body_type"], new["plate"], new["plate_region"], last4, vehicle_id))
        _log(actor, "vehicle_details", f"id={vehicle_id}")
    return "Saved the car's plate and colour."


VEHICLE_STATUSES = ("active", "sold", "totaled")


@edits
def vehicle_update(actor, vehicle_id, year=None, make=None, model=None, vin_last4=None, plate=None, plate_region=None,
                   owner=None, primary_driver=None, registration_expires=None, inspection_expires=None, status=None,
                   notes=None):
    """Change a car's details from its record page. None = leave as is; "" = clear (make, model and status cannot be
    blank). The plate is kept whole (the user's decision of 2026-10-17) and plate_last4 follows it; the VIN stays last4."""
    _adult(actor)
    try:
        vehicle_id = int(vehicle_id)
    except (TypeError, ValueError):
        raise EditError("that vehicle is not there any more") from None

    def opt(fn, x, label):
        return None if x is None else ("" if str(x).strip() == "" else _clean(fn, x, label))
    new = {"year": opt(v.integer(1950, dates.today().year + 1), year, "year"),
           "make": None if make is None else _clean(v.text(40), make, "make"),
           "model": None if model is None else _clean(v.text(60), model, "model"),
           "vin_last4": opt(wl.last4, vin_last4, "VIN last four"),
           "plate": opt(wl.plate, plate, "plate"), "plate_region": opt(wl.region, plate_region, "state or region"),
           "owner": opt(v.text(80), owner, "owner"), "primary_driver": opt(v.text(80), primary_driver, "primary driver"),
           "registration_expires": opt(v.iso_date, registration_expires, "registration date"),
           "inspection_expires": opt(v.iso_date, inspection_expires, "inspection date"),
           "status": None if status is None else _clean(v.one_of(VEHICLE_STATUSES), status, "status"),
           "notes": opt(v.text(500), notes, "notes")}
    with _con() as con:
        if not con.execute("SELECT 1 FROM vehicles WHERE id=?", (vehicle_id,)).fetchone():
            raise EditError("that vehicle is not there any more")
        sets, args = [], []
        for k, val in new.items():
            if val is None:
                continue
            sets.append(f"{k}=?")
            args.append(val or None)
        if new["plate"]:  # last4 follows the whole plate; a cleared plate leaves the old last4 alone
            sets.append("plate_last4=?")
            args.append(new["plate"].replace(" ", "").replace("-", "")[-4:])
        if not sets:
            return "Nothing to change."
        con.execute(f"UPDATE vehicles SET {', '.join(sets)} WHERE id=?", (*args, vehicle_id))
        _log(actor, "vehicle_update", f"id={vehicle_id} fields={','.join(k for k, x in new.items() if x is not None)}")
    return "Saved the car's details."


# ---------------------------------------------------------------- expiries (data/expiries.py) and ID documents
@edits
def expiry_lead_set(actor, typ, days=None):
    """Reminder lead time for one expiry type; days None or "" = back to the default (config/expiries.json)."""
    _adult(actor)
    import expiries
    typ = _clean(v.one_of(expiries.types()), typ, "type")
    days = _opt(v.integer(0, expiries.MAX_LEAD), days, "days")
    try:
        now = expiries.set_lead(typ, days)
    except ValueError as e:
        raise EditError(str(e)) from None
    _log(actor, "expiry_lead_set", f"type={typ} days={now}")
    return f"{typ.replace('_', ' ')}: reminders now start {now} days before the date."


@edits
def id_doc_set(actor, person, doc_type, expires, last4=None):
    """Expiry date (and optional last4) of one person's ID document; the row is created if it does not exist yet."""
    _adult(actor)
    import expiries
    doc_type = _clean(v.one_of(expiries.id_types()), doc_type, "document")
    expires = _clean(v.iso_date, expires, "expiry date")
    last4 = _opt(v.text(4), last4, "last4")
    if last4 and not last4.isalnum():
        raise EditError("last4: letters and digits only")
    with _con() as con:
        person = _member_name(con, person)
        if not person:
            raise EditError("person: pick a family member")
        row = con.execute("SELECT id FROM id_documents WHERE person=? AND doc_type=?", (person, doc_type)).fetchone()
        if row:
            con.execute("UPDATE id_documents SET expires=?, number_last4=COALESCE(?, number_last4), active=1, "
                        "notes=CASE WHEN notes LIKE 'Placeholder:%' THEN NULL ELSE notes END WHERE id=?", (expires, last4, row[0]))
            rid = row[0]
        else:
            rid = con.execute("INSERT INTO id_documents(person, doc_type, number_last4, expires) VALUES (?,?,?,?)",
                              (person, doc_type, last4, expires)).lastrowid
        _log(actor, "id_doc_set", f"id={rid} type={doc_type}")
    return f"{person}'s {doc_type.replace('_', ' ')} expires {expires}."


# ---------------------------------------------------------------- household inventory (home_assets, data/assets.py)
def _asset_fields(fields):
    import assets
    out = {}
    for k, val in fields.items():
        if k == "name":
            out[k] = _clean(v.text(80), val, "name")
        elif k == "category":
            out[k] = _opt(v.one_of(assets.CATEGORIES), val, "category")
        elif k in ("purchase_date", "warranty_end"):
            out[k] = _opt(v.iso_date, val, k.replace("_", " "))
        elif k == "price":
            out[k] = _opt(v.money(0, 1e8), val, "price")
        elif k == "warranty_years":
            out[k] = _opt(v.num(0, 50), val, "warranty years")
        elif k == "serial_last4":
            s = _opt(v.text(4), val, "serial last4")
            if s and not s.isalnum():
                raise EditError("serial last4: letters and digits only")
            out[k] = s
        elif k in ("brand_model", "store", "location"):
            out[k] = _opt(v.text(80), val, k.replace("_", " "))
        elif k == "notes":
            out[k] = _opt(v.text(300), val, "notes")
        elif k in ("receipt_document_id", "manual_document_id"):
            out[k] = _opt(v.integer(1, 10**9), val, "document")
        else:
            raise EditError(f"cannot change {k}")
    return out


def _asset(con, asset_id):
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM home_assets WHERE id=? AND COALESCE(status,'in_use')='in_use'", (asset_id,)).fetchone()
    if not r:
        raise EditError("that item is no longer in the inventory")
    return r


def _doc_exists(con, did):
    if did is not None and not con.execute("SELECT 1 FROM documents WHERE id=?", (did,)).fetchone():
        raise EditError(f"document {did} is not in the archive list")


@edits
def asset_add(actor, name, **fields):
    """A new inventory item; fields as asset_update."""
    _adult(actor)
    f = _asset_fields({"name": name, **fields})
    with _con() as con:
        _doc_exists(con, f.get("receipt_document_id"))
        _doc_exists(con, f.get("manual_document_id"))
        if con.execute("SELECT 1 FROM home_assets WHERE LOWER(name)=LOWER(?)", (f["name"],)).fetchone():
            raise EditError("an item with that name already exists")
        cols = [k for k, val in f.items() if val is not None]
        cur = con.execute(f"INSERT INTO home_assets({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [f[k] for k in cols])
        _log(actor, "asset_add", f"id={cur.lastrowid} category={f.get('category') or '-'}")
    return f"Added '{f['name']}' to the inventory."


@edits
def asset_update(actor, asset_id, **fields):
    """Change named fields of one in-use item: name, category, brand_model, purchase_date, warranty_end, warranty_years,
    price, store, serial_last4, location, notes, receipt_document_id, manual_document_id. "" clears an optional field."""
    _adult(actor)
    f = _asset_fields(fields)
    if not f:
        raise EditError("nothing to change")
    with _con() as con:
        r = _asset(con, asset_id)
        _doc_exists(con, f.get("receipt_document_id"))
        _doc_exists(con, f.get("manual_document_id"))
        if "name" in f and con.execute("SELECT 1 FROM home_assets WHERE LOWER(name)=LOWER(?) AND id<>?", (f["name"], r["id"])).fetchone():
            raise EditError("an item with that name already exists")
        con.execute(f"UPDATE home_assets SET {', '.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), r["id"]))
        _log(actor, "asset_update", f"id={r['id']} fields={','.join(sorted(f))}")
    return f"Saved '{f.get('name') or r['name']}'."


@edits
def asset_dispose(actor, asset_id, how="disposed", when=None):
    """Mark one item sold / disposed / lost; it leaves the lists and reminders but keeps its history."""
    _adult(actor)
    import assets
    how = _clean(v.one_of(assets.STATUSES[1:]), how, "how")
    when = _opt(v.iso_date, when, "date") or dates.today().isoformat()
    with _con() as con:
        r = _asset(con, asset_id)
        con.execute("UPDATE home_assets SET status=?, disposed_date=? WHERE id=?", (how, when, r["id"]))
        _log(actor, "asset_dispose", f"id={r['id']} how={how}")
    return f"'{r['name']}' marked {how} ({when})."


# ---------------------------------------------------------------- shared lists
# Adults do everything. A signed-in limited user (child, guest) may add, tick and untick items and hide ticked ones on
# FAMILY lists only (never on adults-only lists), and may not drop items, name someone, or make or archive lists.
def _lists_mod():
    import lists
    return lists




def _active_list(con, actor, list_id):
    r = _lists_mod().get_list(con, list_id)
    if not r or r["status"] != "active":
        raise EditError("that list no longer exists")
    if r["audience"] != "family" and (actor or {}).get("role") != "adult":
        raise EditError("that list is for adults")
    return r


def _list_item(con, actor, item_id):
    it = _lists_mod().get_item(con, item_id)
    if not it:
        raise EditError("that item no longer exists")
    return it, _active_list(con, actor, it["list_id"])




@edits
def list_new(actor, name, kind="todo", adults_only=False):
    _adult(actor)
    with _con() as con:
        lid = _lv(_lists_mod().new_list, con, name, kind, "adults" if adults_only else "family", _signed_in(actor))
        _log(actor, "list_new", f"id={lid}")
    return f"List '{' '.join(str(name).split())}' is ready."


@edits
def list_archive(actor, list_id):
    _adult(actor)
    with _con() as con:
        r = _active_list(con, actor, list_id)
        _lists_mod().archive_list(con, r["id"])
        _log(actor, "list_archive", f"id={r['id']}")
    return f"Archived '{r['name']}' (its items are kept)."


@edits
def list_item_add(actor, list_id, text, qty=None, who=None):
    by = _signed_in(actor)
    L = _lists_mod()
    with _con() as con:
        r = _active_list(con, actor, list_id)
        if (actor or {}).get("role") != "adult":
            if who:
                raise EditError("only an adult can put a name on an item")
            if L.open_added_by(con, r["id"], by) >= L.MAX_OPEN_PER_PERSON:
                raise EditError(f"you already have {L.MAX_OPEN_PER_PERSON} open items on this list")
        iid, added = _lv(L.add_item, con, r["id"], text, qty, who, by)
        if added:
            _log(actor, "list_item_add", f"list={r['id']} id={iid}")
    t = " ".join(str(text).split())
    return f"Added '{t}' to {r['name']}." if added else f"'{t}' is already on {r['name']}."


@edits
def list_item_tick(actor, item_id, done=True):
    """Tick (done=True) or untick an item. A second tick of the same item is not an error."""
    by = _signed_in(actor)
    with _con() as con:
        it, r = _list_item(con, actor, item_id)
        if it["status"] == "dropped":
            raise EditError("that item was removed from the list")
        changed = _lists_mod().set_status(con, it["id"], "done" if done else "open", by)
        if changed:
            _log(actor, "list_item_tick" if done else "list_item_untick", f"list={r['id']} id={it['id']}")
    if not changed:
        return f"'{it['text']}' was already {'ticked' if done else 'on the list'}."
    return f"Ticked '{it['text']}'." if done else f"'{it['text']}' is back on {r['name']}."


@edits
def list_item_drop(actor, item_id):
    _adult(actor)
    with _con() as con:
        it, r = _list_item(con, actor, item_id)
        _lists_mod().set_status(con, it["id"], "dropped")
        _log(actor, "list_item_drop", f"list={r['id']} id={it['id']}")
    return f"Removed '{it['text']}' from {r['name']}."


@edits
def list_clear(actor, list_id):
    """Hide the ticked items of a list now (they stay in the database)."""
    _signed_in(actor)
    with _con() as con:
        r = _active_list(con, actor, list_id)
        n = _lists_mod().clear_done(con, r["id"])
        if n:
            _log(actor, "list_clear", f"list={r['id']} n={n}")
    return f"Cleared {n} ticked item{'' if n == 1 else 's'} from {r['name']}."


# ---------------------------------------------------------------- saved items (links, notes, places, deals)
# Anyone signed in adds. Adults: family / adults / private items, pin, archive anything they can see. A limited user
# (child, guest): family items only, at most saved.MAX_KID_PER_DAY a day, archives only their own, no pins.
# Private items are seen and changed by their owner only. edits.log: ids and kind, never title, URL or note.
def _saved_mod():
    import saved
    return saved


def _saved_item(con, actor, item_id):
    S = _saved_mod()
    r = S.get(con, item_id)
    if not r or r["status"] != "active" or not S.visible(r, actor or {}):
        raise EditError("that item no longer exists")
    return r


@edits
def saved_add(actor, title, url=None, kind=None, note=None, tags=None, where=None, until=None, audience="family"):
    by = _signed_in(actor)
    S = _saved_mod()
    adult = (actor or {}).get("role") == "adult"
    if not adult and audience != "family":
        raise EditError("only an adult can save items for adults or private items")
    if audience == "private" and not by:
        raise EditError("sign in first: a private item belongs to the person who saved it")
    with _con() as con:
        if not adult and S.added_today_by(con, by) >= S.MAX_KID_PER_DAY:
            raise EditError(f"you already saved {S.MAX_KID_PER_DAY} items today")
        iid, added = _lv(S.add, con, title, url or None, kind or None, note, tags, where, until, audience, by)
        if added:
            r = S.get(con, iid)
            _log(actor, "saved_add", f"id={iid} kind={r['kind']} audience={audience}")
    t = " ".join(str(title).split())
    return f"Saved '{t}'." if added else "That link is already saved."


@edits
def saved_archive(actor, item_id):
    by = _signed_in(actor)
    with _con() as con:
        r = _saved_item(con, actor, item_id)
        if (actor or {}).get("role") != "adult" and r["owner"] != by:
            raise EditError("you can only archive what you saved yourself")
        _saved_mod().archive(con, r["id"])
        _log(actor, "saved_archive", f"id={r['id']} kind={r['kind']}")
    return f"Archived '{r['title']}' (find it again with Show archived)."


@edits
def saved_pin(actor, item_id, on=True):
    _adult(actor)
    with _con() as con:
        r = _saved_item(con, actor, item_id)
        _saved_mod().pin(con, r["id"], on)
        _log(actor, "saved_pin" if on else "saved_unpin", f"id={r['id']}")
    return f"{'Pinned' if on else 'Unpinned'} '{r['title']}'."


@edits
def saved_tags(actor, item_id, tags):
    """Replace the tags of one item (adults, or the owner)."""
    by = _signed_in(actor)
    S = _saved_mod()
    with _con() as con:
        r = _saved_item(con, actor, item_id)
        if (actor or {}).get("role") != "adult" and r["owner"] != by:
            raise EditError("you can only tag what you saved yourself")
        new = _lv(S.parse_tags, tags)
        _lv(S.set_tags, con, r["id"], new, r["tag_list"])
        _log(actor, "saved_tags", f"id={r['id']} n={len(new)}")
    return "Tags: " + (", ".join(new) or "(none)")


# ---------------------------------------------------------------- meals (Family > Meals; adults)
def _meals():
    import meals
    return meals


@edits
def recipe_save(actor, name, ingredients_text="", servings=None, tags=None, url=None, notes=None):
    _adult(actor)
    lines = [x for x in str(ingredients_text or "").splitlines() if x.strip()]
    with _con() as con:
        rid = _lv(_meals().add_recipe, con, name, lines, servings or None, tags, url, notes, _signed_in(actor))
        _log(actor, "recipe_save", f"id={rid} ingredients={len(lines)}")
    return f"Recipe '{' '.join(str(name).split())}' saved."


@edits
def recipe_archive(actor, name):
    _adult(actor)
    with _con() as con:
        r = _lv(_meals().archive_recipe, con, name)
        _log(actor, "recipe_archive", f"id={r['id']}")
    return f"Archived '{r['name']}'."


@edits
def meal_plan_set(actor, day, slot, what, note=None):
    _adult(actor)
    with _con() as con:
        mid = _lv(_meals().plan_meal, con, day, slot, what, note, _signed_in(actor))
        _log(actor, "meal_plan_set", f"id={mid}")
    return f"Planned {slot} on {day}."


@edits
def meal_plan_clear(actor, day, slot):
    _adult(actor)
    with _con() as con:
        n = _lv(_meals().unplan, con, day, slot)
        _log(actor, "meal_plan_clear", f"day={day} slot={slot}")
    return "Removed." if n else "Nothing was planned there."


@edits
def meal_shop(actor, start, end, list_name="Groceries"):
    _adult(actor)
    with _con() as con:
        added, there, name = _lv(_meals().shop, con, start, end, list_name, False, _signed_in(actor))
        _log(actor, "meal_shop", f"added={added}")
    return f"{added} item{'' if added == 1 else 's'} added to {name}" + (f", {there} already there." if there else ".")
