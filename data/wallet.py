"""The Card Wallet (migration 053): the household's cards as card-shaped tiles on the Wallet page and the phone.

  python data/wallet.py list        every card the Wallet shows, one line each (numbers as the page shows them)

A view over what is already on file: ID documents (id_documents), cars (vehicles: plate, colour, body type), insurance
(policies) and the cards no other table holds (wallet_cards: memberships, loyalty, library, travel, health, home).
Each card says where its number is printed on the real one ("where's my number"). Reference copies only: no state
seals, official layouts or logos, no made-up images; the look of the real card is the family's own scan.

Scans (slice 3): a card's back shows its filed scan (id_documents / policies / wallet_cards.document_id, migration 054):
a photo inline, a PDF as a link; scans never leave this PC. A card can be added from a photo: the photo waits in
<household>/wallet_drafts/ (`save_draft`; an iPhone HEIC waits as a JPEG made here, data/heic.py), the family's AI
may read it when photo reading is on (`read_photo`: only the fields of a card, last four digits only, never a full
number; the person checks every field before saving), and Save files the photo under archive/<year>/ids/ with the card.

Numbers: last4 everywhere, except the plate (on the street for anyone to read) and membership / loyalty / library
numbers a barcode needs (the user's decisions of 2026-10-17). Known traveler, passport, licence, health and policy
numbers stay last4. Adults only; synced to adult phones with the ids scope (sync_data SOURCES vehicles, policies,
wallet_cards); not readable through ask_sql.
"""
import datetime as dt
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import db  # noqa: E402
import dates  # noqa: E402
import paths  # noqa: E402
import secrets  # noqa: E402
import time  # noqa: E402

KINDS = (("membership", "Membership"), ("loyalty", "Store or loyalty"), ("library", "Library"),
         ("travel", "Travel (known traveler, airline)"), ("health", "Health or dental"), ("home", "Home facts"),
         ("other", "Other"))
FULL_NUMBER = ("membership", "loyalty", "library")  # a barcode needs the whole number; every other kind keeps last4
BODY_TYPES = ("sedan", "suv", "truck", "van", "minivan", "hatchback", "coupe", "wagon", "motorcycle", "other")
GROUPS = (("car", "Car"), ("people", "People"), ("home", "Home"), ("members", "Memberships"))
SOON_DAYS = 60
TABLE = "wallet_cards"
FIELDS = ("kind", "title", "member", "issuer", "number", "number_last4", "where_hint", "details", "expires")
DRAFTS = paths.HOME / "wallet_drafts"
DRAFT_TYPES = (".jpg", ".jpeg", ".png", ".webp")  # what the AI providers read; also shown inline on the card's back
DRAFT_MAX = 10 * 1024 * 1024
DRAFT_HOURS = 24  # a photo left waiting longer is removed at the next upload
IMAGE_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
CARD_SCHEMA = {
    "is_card": (bool, True, None),
    "kind": (str, False, None),
    "title": (str, False, None),
    "issuer": (str, False, None),
    "number_last4": (str, False, None),
    "expires": (str, False, None),
    "where_hint": (str, False, None),
    "confidence": ((int, float), True, None),
}
CARD_INSTRUCTION = (
    "Is this a photo of a wallet card (membership, store or loyalty, library, travel program, health or dental plan "
    "card)? Extract: is_card (true/false), kind (one of membership, loyalty, library, travel, health, other), title (the "
    "card's short name as a person would say it, for example 'City library' or 'Dental plan', at most 60 characters, no "
    "person's name), issuer (the company or library as printed), number_last4 (ONLY the last four characters of the main "
    "card or member number, never more), expires (YYYY-MM-DD if an expiry date is printed, else empty), where_hint (where "
    "on the card that number is printed, for example 'back, under the barcode', at most 80 characters), confidence (0 to 1).")

# where the number usually is on the real card, per kind of card (a card's own where_hint wins)
WHERE = {
    "drivers_license": "Licence number: front, near the top right, often after DL or LIC.",
    "state_id": "ID number: front, near the top right.",
    "permit": "Permit number: front, near the top.",
    "passport": "Passport number: photo page, top right.",
    "green_card": "Card number: front, upper left (13 characters, 3 letters first).",
    "insurance_card": "Policy number: front, near the top. Claims phone: on the back.",
    "vehicle_registration": "Plate and VIN: the registration card, kept in the glovebox.",
    "policy_auto": "Policy number: the insurance ID card, near the top. Claims phone: on the back.",
    "policy_home": "Policy number: first page of the declarations.",
    "policy": "Policy number: first page of the declarations.",
    "car": "Plate: front and back of the car. VIN: bottom of the windshield, driver side.",
    "membership": "Member number: back of the card, under the barcode.",
    "loyalty": "Card number: back of the card, under the barcode.",
    "library": "Card number: back of the card, under the barcode.",
    "travel": "Known traveler number: on the approval letter or the program's website.",
    "health": "Member ID: front of the card, under the plan name. Group number: below it.",
    "home": "",
    "other": "",
}
TONE = {"car": "wt-car", "policy": "wt-policy", "id": "wt-id", "health": "wt-health", "home": "wt-home",
        "members": "wt-members"}
ICON = {"car": "ic-car", "policy": "ic-shield", "id": "ic-id", "health": "ic-heart", "home": "ic-home",
        "members": "ic-card"}


# ---------------------------------------------------------------- checks (used by edit_actions)
def plate(x):
    s = " ".join(str(x).upper().split())
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{0,9}", s):
        raise ValueError("letters, digits, spaces and dashes, at most 10")
    return s


def region(x):
    s = " ".join(str(x).split())
    if not re.fullmatch(r"[A-Za-z][A-Za-z .]{0,19}", s):
        raise ValueError("letters only, at most 20 (NJ, Ontario)")
    return s.upper() if len(s) <= 3 else s


def color(x):
    s = " ".join(str(x).lower().split())
    if not re.fullmatch(r"[a-z][a-z /-]{0,19}", s):
        raise ValueError("a colour in words, at most 20 letters")
    return s


def number(x):
    s = " ".join(str(x).upper().split())
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9 -]{3,29}", s):
        raise ValueError("letters, digits, spaces and dashes, 4 to 30")
    return s


def last4(x):
    s = str(x).strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{1,4}", s):
        raise ValueError("up to four letters or digits")
    return s


# ---------------------------------------------------------------- reading
def _con():
    con = db.connect(paths.DB, readonly=True)
    con.row_factory = sqlite3.Row
    return con


def _rows(con, sql, params=()):
    try:
        return [dict(r) for r in con.execute(sql, params)]
    except sqlite3.OperationalError as e:
        if db.missing(e):  # a table or column a migration not run yet would add
            return []
        raise


def _d(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


def due(expires, today):
    """(pill text, level) for an expiry date: expired / due in N days (within SOON_DAYS) / Mon YYYY; None without one."""
    d = _d(expires)
    if not d:
        return None
    n = (d - today).days
    if n < 0:
        return ("expired", "bad")
    if n == 0:
        return ("expires today", "bad")
    if n <= SOON_DAYS:
        return (f"due in {n} day{'s' if n != 1 else ''}", "warn")
    return (d.strftime("%b %Y"), "ok")


def masked(l4):
    return f"•••• {l4}" if l4 else ""


def grouped(num):
    """A full card number as typed when it has spaces or dashes (cards group digits their own way), else in groups of
    four ("111022334455" -> "1110 2233 4455")."""
    s = str(num or "")
    if " " in s or "-" in s or len(s) <= 6:
        return s
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


def _label(doc_type):
    return {"drivers_license": "Driver licence", "state_id": "State ID", "green_card": "Green card",
            "insurance_card": "Insurance card"}.get(doc_type, str(doc_type or "ID").replace("_", " ").capitalize())


def _card(group, tone, title, **k):
    return {"group": group, "tone": TONE[tone], "icon": ICON[tone], "title": title, "sub": k.get("sub", ""),
            "num": k.get("num", ""), "plate": k.get("plate"), "foot": k.get("foot", ""), "due": k.get("due"),
            "hint": k.get("hint", ""), "ref": k.get("ref", ""), "edit": k.get("edit"), "who": k.get("who") or "",
            "scan": k.get("scan")}


def _scans(con):
    """{documents.id: {"id", "image"}} for every filed paper (photo or not) that exists inside archive/."""
    out = {}
    for r in _rows(con, "SELECT id, filed_path FROM documents WHERE filed_path IS NOT NULL"):
        out[r["id"]] = {"id": r["id"], "image": pathlib.Path(str(r["filed_path"])).suffix.lower() in IMAGE_MIME}
    return out


def id_cards(con):
    """{vin_last4 (upper): scan} for the newest filed insurance ID card of each car: a paper whose file name has
    'idcard' and 'vin<last4>' (the Inbox files them as ..._idcard_vin8413.pdf). The scan carries label 'insurance ID card'."""
    out = {}
    for r in _rows(con, "SELECT id, filed_path FROM documents WHERE filed_path IS NOT NULL AND lower(filed_path) LIKE '%idcard%' "
                        "ORDER BY doc_date, id"):
        m = re.search(r"vin([a-z0-9]{4})(?![a-z0-9])", str(r["filed_path"]).lower())
        if m:  # oldest first, so the newest paper of a car wins
            out[m.group(1).upper()] = {"id": r["id"], "image": pathlib.Path(str(r["filed_path"])).suffix.lower() in IMAGE_MIME,
                                       "label": "insurance ID card"}
    return out


def cards(today=None, con=None):
    """Every card the Wallet shows, grouped in GROUPS order, soonest expiry first inside a group."""
    today = today or dates.today()
    own = con is None
    con = con or _con()
    con.row_factory = sqlite3.Row
    out = []
    try:
        scans = _scans(con)
        idc = id_cards(con)
        for r in _rows(con, "SELECT * FROM vehicles WHERE COALESCE(status, 'active') = 'active' ORDER BY year DESC, id"):
            name = " ".join(str(x) for x in (r.get("year"), r.get("make"), r.get("model")) if x) or "Car"
            sub = " · ".join(x for x in ((r.get("color") or "").capitalize(), (r.get("body_type") or "").upper()
                                         if r.get("body_type") == "suv" else (r.get("body_type") or "").capitalize(),
                                         f"VIN •••• {r['vin_last4']}" if r.get("vin_last4") else "") if x)
            pl = r.get("plate") or (f"•••• {r['plate_last4']}" if r.get("plate_last4") else "")
            out.append(_card("car", "car", name, sub=sub, plate={"text": pl, "region": r.get("plate_region") or "",
                                                                "full": bool(r.get("plate"))},
                             foot="Registration", due=due(r.get("registration_expires"), today), hint=WHERE["car"],
                             ref=f"vehicles:{r['id']}", who=r.get("primary_driver") or r.get("owner"),
                             scan=idc.get(str(r.get("vin_last4") or "").upper()),
                             edit={"id": r["id"], "color": r.get("color") or "", "body_type": r.get("body_type") or "",
                                   "plate": r.get("plate") or "", "plate_region": r.get("plate_region") or ""}))
        for r in _rows(con, "SELECT id, kind, carrier, policy_last4, term_end, document_id FROM policies "
                            "WHERE COALESCE(status, 'active') = 'active' AND (term_end IS NULL OR term_end >= ?) "
                            "AND id NOT IN (SELECT prior_policy_id FROM policies WHERE prior_policy_id IS NOT NULL) "
                            "ORDER BY term_end", ((today - dt.timedelta(days=30)).isoformat(),)):
            kind = (r.get("kind") or "policy").lower()
            out.append(_card("car" if kind == "auto" else "home", "policy", f"{kind.capitalize()} insurance",
                             sub=r.get("carrier") or "", num=masked(r.get("policy_last4")), foot="Term ends",
                             due=due(r.get("term_end"), today), hint=WHERE.get(f"policy_{kind}", WHERE["policy"]),
                             ref=f"policies:{r['id']}", scan=scans.get(r.get("document_id"))))
        for r in _rows(con, "SELECT id, person, doc_type, number_last4, expires, issuing_authority, document_id FROM id_documents "
                            "WHERE COALESCE(active, 1) = 1 AND doc_type != 'vehicle_registration' "
                            "AND NOT (number_last4 IS NULL AND expires IS NULL) ORDER BY person, doc_type"):
            out.append(_card("people", "id", _label(r["doc_type"]), sub=" · ".join(
                x for x in (r.get("person"), r.get("issuing_authority")) if x), num=masked(r.get("number_last4")),
                foot="Expires", due=due(r.get("expires"), today), hint=WHERE.get(r["doc_type"], ""),
                ref=f"id_documents:{r['id']}", who=r.get("person"), scan=scans.get(r.get("document_id"))))
        cols = {c[1] for c in con.execute("PRAGMA table_info(wallet_cards)")}
        doc = "document_id" if "document_id" in cols else "NULL AS document_id"  # before migration 054
        for r in _rows(con, f"SELECT id, {', '.join(FIELDS)}, {doc} FROM wallet_cards WHERE status = 'active' "
                            "ORDER BY kind, title"):
            kind = r["kind"]
            group = "people" if kind == "health" else "home" if kind == "home" else "members"
            tone = "health" if kind == "health" else "home" if kind == "home" else "members"
            num = grouped(r["number"]) if r.get("number") else masked(r.get("number_last4"))
            sub = " · ".join(x for x in (r.get("member"), r.get("issuer")) if x)
            out.append(_card(group, tone, r["title"], sub=sub, num=num, foot=r.get("details") or "",
                             due=due(r.get("expires"), today), hint=r.get("where_hint") or WHERE.get(kind, ""),
                             ref=f"wallet_cards:{r['id']}", who=r.get("member"), scan=scans.get(r.get("document_id")),
                             edit={"id": r["id"], **{k: "" if r.get(k) is None else str(r[k]) for k in FIELDS}}))
    finally:
        if own:
            con.close()
    order = {g: i for i, (g, _) in enumerate(GROUPS)}

    def key(c):  # group, then expired / due soon first, then by name
        d = c["due"]
        return order[c["group"]], 0 if d and d[1] == "bad" else 1 if d and d[1] == "warn" else 2, c["title"].lower()
    return sorted(out, key=key)


def matches(c, q):
    """Every word of the search somewhere on the card: name, who, number, plate, details, where the number is."""
    hay = " ".join(str(x or "") for x in (c["title"], c["sub"], c["num"], c["plate"] and c["plate"]["text"],
                                           c["plate"] and c["plate"]["region"], c["foot"], c["hint"], c["who"])).lower()
    return all(w in hay for w in str(q or "").lower().split())


def page(group=None, today=None, q=""):
    """What the Wallet page shows: groups (key, label, cards) with the filter and search applied, chip counts, expiring
    count."""
    allc = cards(today)
    counts = {g: sum(1 for c in allc if c["group"] == g) for g, _ in GROUPS}
    shown = [c for c in allc if (not group or c["group"] == group) and (not q or matches(c, q))]
    groups = [(g, label, [c for c in shown if c["group"] == g]) for g, label in GROUPS]
    return {"groups": [g for g in groups if g[2]], "chips": [(g, label, counts[g]) for g, label in GROUPS if counts[g]],
            "soon": sum(1 for c in allc if c["due"] and c["due"][1] in ("bad", "warn")), "total": len(allc),
            "shown": len(shown), "cars": sum(1 for c in allc if c["plate"])}


def parking(car_id=None, today=None):
    """Parking mode: the cars with a plate on file and the one to show big (`car_id`, else the first with a whole plate).
    -> {"car": card or None, "cars": [(id, name)]}"""
    cars = [c for c in cards(today) if c["plate"] and c["plate"]["text"]]
    pick = next((c for c in cars if str(c["edit"]["id"]) == str(car_id)), None) if car_id else None
    pick = pick or next((c for c in cars if c["plate"]["full"]), None) or (cars[0] if cars else None)
    return {"car": pick, "cars": [(c["edit"]["id"], c["title"]) for c in cars]}


# ---------------------------------------------------------------- scans and photos
def scan_file(doc_id):
    """(path, mime) of a filed PHOTO for the back of a card, only from inside archive/; None for anything else."""
    try:
        did = int(doc_id)
    except (TypeError, ValueError):
        return None
    con = _con()
    try:
        r = con.execute("SELECT filed_path FROM documents WHERE id=?", (did,)).fetchone()
    finally:
        con.close()
    if not r or not r[0]:
        return None
    arch = paths.ARCHIVE.resolve()
    f = (arch / str(r[0])).resolve()
    if arch not in f.parents or not f.is_file() or f.suffix.lower() not in IMAGE_MIME:
        return None
    return f, IMAGE_MIME[f.suffix.lower()]


def _sweep(now=None):
    now = now or time.time()
    if DRAFTS.is_dir():
        for f in DRAFTS.iterdir():
            if f.is_file() and now - f.stat().st_mtime > DRAFT_HOURS * 3600:
                f.unlink(missing_ok=True)


def save_draft(name, data):
    """A card photo waiting to be checked: (True, token) or (False, why). Same content checks as the Inbox."""
    import inbox_upload
    ext = pathlib.Path(str(name or "")).suffix.lower()
    if ext not in DRAFT_TYPES and ext != ".heic":
        return False, "Use a photo: .jpg, .png or .webp."
    if not data or len(data) > DRAFT_MAX:
        return False, f"The photo must be under {DRAFT_MAX // (1024 * 1024)} MB."
    if not inbox_upload.content_ok(name, data):
        return False, "That file does not look like a photo."
    if ext == ".heic":  # an iPhone photo waits as the JPEG made here: the browser shows it, the AI reads it
        import heic
        try:
            data, ext = heic.to_jpeg(data), ".jpg"
        except ValueError:
            return False, "This PC could not read that iPhone photo (HEIC). Use a .jpg, .png or .webp photo."
    _sweep()
    DRAFTS.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(12)
    (DRAFTS / f"{token}{ext}").write_bytes(data)
    return True, token


def draft_path(token):
    """The waiting photo of a token, or None (unknown, expired or not a token)."""
    if not re.fullmatch(r"[0-9a-f]{24}", str(token or "")):
        return None
    return next((f for f in DRAFTS.glob(f"{token}.*") if f.suffix.lower() in DRAFT_TYPES), None) if DRAFTS.is_dir() else None


def drop_draft(token):
    f = draft_path(token)
    if f:
        f.unlink(missing_ok=True)


def read_photo(path):
    """The family's AI reads a card photo -> (fields for the form, message). Only when photo reading is on; only the
    last four of a number come back (llm refuses anything longer). Nothing is saved here."""
    import llm
    why = llm.photos_allowed()
    if why:
        return {}, f"Not read by AI: {why}. Fill in the card below."
    try:
        obj, errs = llm.extract_image_json(CARD_INSTRUCTION, path, CARD_SCHEMA, purpose="wallet_photo")
    except llm.LLMError as e:
        return {}, f"The AI could not read the photo ({str(e)[:120]}). Fill in the card below."
    if errs or not obj:
        return {}, "The AI's answer did not check out. Fill in the card below."
    if not obj.get("is_card"):
        return {}, "The AI did not see a wallet card in the photo. Fill in the card below, or try another photo."
    out = {}
    kind = str(obj.get("kind") or "").lower()
    out["kind"] = kind if kind in dict(KINDS) else "other"
    for k, n in (("title", 60), ("issuer", 60), ("where_hint", 120)):
        val = " ".join(str(obj.get(k) or "").split())[:n]
        if val and not val.startswith("-"):
            out[k] = val
    l4 = re.sub(r"[^A-Za-z0-9]", "", str(obj.get("number_last4") or ""))[-4:].upper()
    if l4:
        out["number_last4"] = l4
    exp = str(obj.get("expires") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", exp) and _d(exp):
        out["expires"] = exp
    conf = float(obj.get("confidence") or 0)
    msg = "Read by AI: check every field before saving." + (" It was not sure, so look closely." if conf < 0.7 else "")
    return out, msg


def main():
    if len(sys.argv) < 2 or sys.argv[1] != "list":
        raise SystemExit(__doc__)
    for c in cards():
        pl = c["plate"]["text"] if c["plate"] else c["num"]
        print(f"{c['group']:8} {c['title']:30} {pl:20} {c['due'][0] if c['due'] else ''}")


if __name__ == "__main__":
    main()
