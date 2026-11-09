"""Inbox intake with any configured LLM provider (the Python alternative to the Claude `intake` agent).

  python data/ai_intake.py              process every file in inbox/
  python data/ai_intake.py review       list files waiting for a person
  python data/ai_intake.py file ID --type bill --vendor "Acme Power" --date 2026-09-01 [--amount 40 --due 2026-09-25]
                                        a person files a waiting item (no AI): archived, logged, bill row if due
  python data/ai_intake.py resolve ID   close a review item without filing (the file stays where it is)

For each file: extract text (data/doc_text.py), mask identifiers and the household's names (data/pii.py), ask the provider for {type, vendor, date,
amount, due date, account last4, period, confidence}, validate it, then rename to YYYY-MM-DD_vendor_type.ext, move to
archive/<year>/<category>/, log to `documents`, and for bills with an amount and due date add a `bills` row.
Photos (.jpg/.png/.webp; iPhone .heic as a JPEG made here, data/heic.py) of receipts are read only when the family
opted in (ai.read_receipt_photos: true; a photo cannot be masked before it is sent): store, date, total and card last4
become a `receipts` row matched to the charge.
Policies, ID documents, vehicle papers, medical letters, investment and tax papers get a second call that reads
their details into the right tables (data/doc_extract.py: policy, vehicles, drivers, coverages; ID expiry; visit and
follow-up; value; form and year). Statements are read without AI first (data/pdf_statement.py); when that fails, the
AI reads every line and they are imported only if the lines add up to the printed balances.
Anything uncertain (confidence < 0.7, scanned PDF, unsupported type, invalid answer, details not sure, statement that
does not add up) is MOVED to inbox/needs_review/ and logged in `review_queue`. Nothing is deleted.
An exact copy of a paper already filed or waiting for review (same SHA-256) is moved to archive/duplicates/ before any
AI call and filed nowhere (hashes cached in logs/archive_hashes.json).
The document text is untrusted data; the model's answer is validated and only ever used as field values (filenames are
sanitised, SQL is parameterised).
"""
import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import doc_extract  # noqa: E402
import doc_text  # noqa: E402
import heic  # noqa: E402
import llm  # noqa: E402
import money as _money  # noqa: E402
import validators as v  # noqa: E402
import db  # noqa: E402
import intake_progress  # noqa: E402

DB = paths.DB
TYPES = ["bill", "statement", "receipt", "policy", "id", "vehicle", "tax", "medical", "investment", "manual", "timesheet",
         "work_calendar", "school_calendar", "other"]
CATEGORY = {"bill": "bills", "statement": "statements", "receipt": "receipts", "policy": "insurance", "id": "ids",
            "vehicle": "vehicles", "tax": "tax", "medical": "medical", "investment": "investments", "manual": "manuals",
            "timesheet": "work", "work_calendar": "work", "school_calendar": "school", "other": "other"}
MIN_CONF = 0.7
SCHEMA = {
    "doc_type": (str, True, TYPES),
    "vendor": (str, False, None),
    "doc_date": (str, False, None),
    "amount": ((int, float), False, None),
    "due_date": (str, False, None),
    "account_last4": (str, False, None),
    "period": (str, False, None),
    "confidence": ((int, float), True, None),
}
MEANING = {"bill": "an amount to pay (utility, phone, invoice, premium notice)",
           "statement": "bank, card or loan statement listing transactions", "receipt": "proof of a purchase already paid",
           "policy": "insurance declarations page, renewal or insurance ID card",
           "id": "passport, driver licence, state ID, green card or other identity document",
           "vehicle": "vehicle registration, inspection or title", "tax": "tax form (W-2, 1099, 1098), tax bill or tax letter",
           "medical": "visit summary, appointment letter, referral, lab result or vaccine record",
           "investment": "brokerage, retirement or fund statement, deposit certificate", "manual": "product manual or warranty",
           "timesheet": "hours worked", "work_calendar": "employer or client holiday calendar",
           "school_calendar": "a school or school district calendar for the year (holidays, breaks, days off)",
           "other": "anything else"}
INSTRUCTION = ("Classify this household document and extract: doc_type (one of: " + "; ".join(f"{t} = {MEANING[t]}" for t in TYPES)
               + "), vendor (the company, clinic, agency or person it is from), doc_date (YYYY-MM-DD: the date printed on it; if "
               "none, the start of the period it covers), amount (number, the amount due or total), due_date (YYYY-MM-DD), "
               "account_last4 (last 4 digits only, never more), period, confidence (0 to 1).")


def _iso(v):
    try:
        return dt.date.fromisoformat(str(v)[:10]).isoformat()
    except (ValueError, TypeError):
        return None


def slug(s, default="unknown", n=40):
    s = re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:n]
    return s or default


def unique(path):
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError("too many name collisions")


DUP_DIR = paths.ARCHIVE / "duplicates"
_MOVED = []  # (archive path, inbox path) of papers moved by file_document for the file being processed
HASH_CACHE = paths.LOGS / "archive_hashes.json"


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def known_files():
    """sha256 -> path of every paper already filed (archive/, not archive/duplicates/) or waiting in inbox/needs_review/.
    Hashes are cached in logs/archive_hashes.json by size + modification time, so a run reads only new files."""
    try:
        cache = json.loads(HASH_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    fresh, out = {}, {}
    places = [paths.ARCHIVE, paths.INBOX / "needs_review"]
    for base in places:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if not p.is_file() or DUP_DIR in p.parents or p.name == ".gitkeep":
                continue
            rel, st = paths.rel(p), p.stat()
            old = cache.get(rel)
            h = old[2] if old and old[0] == st.st_size and old[1] == st.st_mtime_ns else sha256(p)
            fresh[rel] = [st.st_size, st.st_mtime_ns, h]
            out.setdefault(h, rel)
    try:
        HASH_CACHE.parent.mkdir(exist_ok=True)
        HASH_CACHE.write_text(json.dumps(fresh), encoding="utf-8")
    except OSError:
        pass
    return out


def to_duplicates(f, same_as):
    """An exact copy of a paper already filed: moved to archive/duplicates/ (never deleted), not read or filed again."""
    DUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = unique(DUP_DIR / f.name)
    shutil.move(str(f), dest)
    import log
    log.get("intake").info("duplicate %s -> %s (same file as %s)", f.name, paths.rel(dest), same_as)
    return f.name, "duplicate", f"same file as {same_as}; moved to {paths.rel(dest)}"


def _guess(obj):
    """The AI's answer as the review note the Inbox pre-fills the File it by hand form from:
    'guess type=bill vendor=City Water date=2026-09-01 amount=41.2 due=2026-09-20' (only what it gave)."""
    obj = obj if isinstance(obj, dict) else {}
    parts = {"type": obj.get("doc_type"), "vendor": obj.get("vendor"), "date": _iso(obj.get("doc_date")),
             "amount": obj.get("amount"), "due": _iso(obj.get("due_date"))}
    return "guess " + " ".join(f"{k}={' '.join(str(v).replace('=', '-').split())[:60]}" for k, v in parts.items()
                               if v not in (None, ""))


def to_review(con, f, reason, detail=""):
    dest_dir = paths.INBOX / "needs_review"
    dest_dir.mkdir(exist_ok=True)
    dest = unique(dest_dir / f.name)
    shutil.move(str(f), dest)
    con.execute("INSERT INTO review_queue(path, reason, detail) VALUES (?,?,?)", (paths.rel(dest), reason, detail[:300]))
    con.commit()
    return dest


def clean_last4(v):
    d = re.sub(r"\D", "", str(v or ""))
    return d[-4:] if len(d) >= 4 else None


PHOTO_SCHEMA = {
    "is_receipt": (bool, True, None),
    "store": (str, False, None),
    "date": (str, False, None),
    "total": ((int, float), False, None),
    "card_last4": (str, False, None),
    "confidence": ((int, float), True, None),
}
PHOTO_INSTRUCTION = ("Is this a photo of a shop or restaurant receipt? Extract: is_receipt (true/false), store (shop name "
                     "as printed), date (YYYY-MM-DD), total (number: the final amount paid, after tax and tip), card_last4 "
                     "(last 4 digits of the card if printed, never more), confidence (0 to 1).")


def photo_receipt(con, f):
    """Opt-in (ai.read_receipt_photos): a receipt photo read by the family's own AI provider, filed as a receipt and
    matched to the card charge. Anything doubtful goes to a person with the guess in the review note."""
    try:
        obj, errs = llm.extract_image_json(PHOTO_INSTRUCTION, f, PHOTO_SCHEMA, purpose="receipt_photo")
    except llm.LLMError as e:
        if _ai_down(e):
            return f.name, "skipped", f"AI unavailable: {e}"
        to_review(con, f, "photo not read by AI", str(e)[:200])
        return f.name, "review", "photo not read"
    if errs or obj is None:
        to_review(con, f, "AI answer for the photo failed validation", "; ".join(errs))
        return f.name, "review", "invalid answer"
    conf, date, total, store = float(obj["confidence"]), _iso(obj.get("date")), obj.get("total"), (obj.get("store") or "").strip()
    guess = f"guess store={store[:40]} date={obj.get('date')} total={total} confidence {conf:.2f}"
    if not obj["is_receipt"]:
        to_review(con, f, "photo is not a receipt (AI)", guess)
        return f.name, "review", "not a receipt"
    if conf < MIN_CONF or not date or not store or total is None or total <= 0:
        to_review(con, f, "receipt photo: low confidence or missing store/date/total", guess)
        return f.name, "review", "low confidence"
    try:
        _, dest = file_document(con, f, "receipt", store[:80], date, total,
                                note=f"ai_intake photo {llm.settings()['provider']}; confidence {conf:.2f}",
                                last4=clean_last4(obj.get("card_last4")))
    except ValueError as e:
        to_review(con, f, f"AI answer rejected: {e}", guess)
        return f.name, "review", "rejected"
    con.commit()
    return f.name, "filed", paths.rel(dest)


def process_file(con, f, local=False, step=None):
    """(name, status, info) for one inbox file; `step(name)` (optional) hears "reading" and "sorting" as it goes."""
    step = step or (lambda _s: None)
    step("reading")
    if llm.reads_photo(f) and not llm.photos_allowed():
        return photo_receipt(con, f)
    if f.suffix.lower() in (".ofx", ".qfx"):  # a bank's download for money software: read here, never by an AI
        return _ofx_route(con, f)
    text, status = doc_text.extract(f)
    if status == "scanned" and not local and f.suffix.lower() in llm.SCAN_TYPES and not llm.photos_allowed():
        step("sorting")
        return _scan_route(con, f)
    if status != "ok":
        reason = _unread_reason(f, status)
        to_review(con, f, reason)
        return f.name, "review", reason
    export = _csv_route(con, f) if f.suffix.lower() == ".csv" else None  # a bank or card activity export
    if export:
        return export
    paypal = _paypal_route(con, f, text)
    if paypal:
        return paypal
    mobile = _mobile_route(con, f, text)
    if mobile:
        return mobile
    school = _school_route(con, f, text)
    if school:
        return school
    statement = _local_statement(con, f, text, ai=not local)  # a statement this PC reads itself never waits for an AI
    if statement:
        return statement
    if local:  # `ai_intake.py local`: only the readers that need no AI; the rest waits for one
        return f.name, "waiting", "needs an AI to be filed"
    step("sorting")
    try:
        obj, errs = llm.extract_json(INSTRUCTION, text, SCHEMA, purpose="intake")
    except llm.LLMError as e:
        return f.name, "skipped", f"AI unavailable: {e}"  # leave the file where it is; retried next cycle
    if errs or obj is None:
        to_review(con, f, "AI answer failed validation", "; ".join(errs))
        return f.name, "review", "invalid answer"
    typ, conf = obj["doc_type"], float(obj["confidence"])
    if typ == "statement":
        return _statement_route(con, f, obj, text)
    if typ in ("timesheet", "work_calendar") and conf >= MIN_CONF:
        return _work_route(con, f, typ)
    date = _iso(obj.get("doc_date")) or _iso(obj.get("due_date"))
    details = None
    if conf < MIN_CONF or not obj.get("vendor") or not (date or typ in doc_extract.DETAILS):
        to_review(con, f, f"low confidence or missing vendor/date (confidence {conf:.2f})", _guess(obj))
        return f.name, "review", "low confidence"
    if typ in doc_extract.DETAILS:  # second call: the fields this kind of paper carries (and its date, if none was printed)
        try:
            raw, errs = doc_extract.read(typ, text)
        except llm.LLMError as e:
            return f.name, "skipped", f"AI unavailable: {e}"
        try:
            if errs or raw is None:
                raise doc_extract.Unusable("the details answer was not usable: " + "; ".join(errs[:3]))
            details = doc_extract.prepare(typ, raw)
        except (doc_extract.Unusable, ValueError, TypeError) as e:
            to_review(con, f, f"{typ}: details not read ({e})", _guess(obj))
            return f.name, "review", "details"
        date = date or doc_extract.date_of(typ, details)
        if not date:
            to_review(con, f, "no date on the document", _guess(obj))
            return f.name, "review", "low confidence"
    note =f"ai_intake {llm.settings()['provider']}; confidence {conf:.2f}; period {obj.get('period') or ''}; last4 {clean_last4(obj.get('account_last4')) or ''}"
    amount = obj.get("amount")
    try:
        doc_id, dest = file_document(con, f, typ, obj["vendor"].strip()[:80], date, amount if amount is not None and amount >= 0 else None,
                                     _iso(obj.get("due_date")), note)
    except ValueError as e:  # the vendor the model produced is unusable (e.g. a full account number): a person decides
        to_review(con, f, f"AI answer rejected: {e}", _guess(obj))
        return f.name, "review", "rejected"
    info = paths.rel(dest)
    if details is not None:
        info = doc_extract.save(con, typ, details, doc_id)
    con.commit()
    return f.name, "filed", info


def _statement_route(con, f, obj, text=""):
    """A statement: read it with data/pdf_statement.py (no AI). If that cannot, the AI reads every line
    (doc_extract.read_statement). Either way it is imported only when the lines add up to the printed balances;
    anything else waits in the review queue with the reason."""
    import pdf_statement as ps
    how = "pdf_statement"
    try:
        res = _read_pdf(con, f, text, ps) if f.suffix.lower() == ".pdf" else None
        if res is None or res["verified"] is not True:
            raise ps.StatementError("not a PDF the reader knows" if res is None else
                                    "balances not printed or do not add up" if res["verified"] is None else
                                    "balances do not add up; some lines were not read")
    except (ps.StatementError, ValueError) as first:
        try:
            res, how = doc_extract.read_statement(con, text), "read by AI"
        except llm.LLMError as e:
            return f.name, "skipped", f"AI unavailable: {e}"
        except (doc_extract.Unusable, ValueError, TypeError) as e:
            to_review(con, f, f"statement not imported automatically: {first}; AI reader: {e}", _guess(obj))
            return f.name, "review", "statement"
    return _file_statement(con, f, res, how)


NO_ACCOUNT = "no account with the last four digits"


def _read_pdf(con, f, text, ps):
    """pdf_statement.read; for the first statement of an account this PC does not know, the account is added when the
    statement then adds up (_statement_new_account). Raises ps.StatementError as read() does."""
    try:
        return ps.read(con, f)
    except ps.StatementError as e:
        if not (str(e).startswith(NO_ACCOUNT) and ps.last4s(text)):
            raise
        res = _statement_new_account(con, f, text, ps)
        if res is None:
            raise
        return res


def _local_statement(con, f, text, ai=False):
    """Before any AI: a statement PDF that data/pdf_statement.py reads and that adds up to the printed balances is filed
    like `_statement_route` does (nothing leaves this PC). None = not one, or not readable here (the AI, when one is
    set, reads it next). Without an AI (ai=False) a statement of an account this PC does not know waits with what to add."""
    import pdf_statement as ps
    if f.suffix.lower() != ".pdf" or not ps.END.search(text):
        return None
    try:
        res = _read_pdf(con, f, text, ps)
    except (ps.StatementError, ValueError) as e:
        if not ai and str(e).startswith(NO_ACCOUNT) and ps.last4s(text):
            return f.name, "waiting", f"Add the account ending {' or '.join(dict.fromkeys(ps.last4s(text)))} in Money > Accounts, then press File them now."
        return None
    if res["verified"] is not True:
        return None
    return _file_statement(con, f, res, "pdf_statement (no AI)")


def _ai_down(e):
    """True when an AI error is worth waiting out (busy, network, server, today's call cap, the AI account out of
    credit): the file stays in inbox/ and is read once the AI can be used again."""
    s = str(e)
    return any(x in s for x in ("429", "network", "HTTP 5", "HTTP 402", "timed out", "cap reached"))


def _scan_route(con, f):
    """A scanned PDF (pictures of the pages, no text layer) with photo reading on: the AI reads the file itself. A
    statement is imported only when its lines add up to the printed balances (doc_extract.read_statement_scan); a
    plain paper (a bill, a receipt) is filed like a text one; papers whose details need their text, and anything
    doubtful, wait for a person with the AI's guess."""
    try:
        obj, errs = llm.extract_image_json(INSTRUCTION, f, SCHEMA, purpose="intake_scan")
    except llm.LLMError as e:
        if _ai_down(e):
            return f.name, "skipped", f"AI unavailable: {e}"
        to_review(con, f, f"scanned PDF: the AI could not read it ({str(e)[:120]})")
        return f.name, "review", "scan not read"
    if errs or obj is None:
        to_review(con, f, "scanned PDF: the AI answer failed validation", "; ".join(errs))
        return f.name, "review", "invalid answer"
    typ, conf = obj["doc_type"], float(obj["confidence"])
    guess = _guess(obj)
    if typ == "statement":
        try:
            res = doc_extract.read_statement_scan(con, f)
        except llm.LLMError as e:
            if _ai_down(e):
                return f.name, "skipped", f"AI unavailable: {e}"
            to_review(con, f, f"scanned PDF: the AI could not read it ({str(e)[:120]})", guess)
            return f.name, "review", "scan not read"
        except (doc_extract.Unusable, ValueError, TypeError) as e:
            to_review(con, f, f"scanned statement read by AI, not imported: {e}", guess)
            return f.name, "review", "statement"
        return _file_statement(con, f, res, "scanned PDF read by AI")
    date = _iso(obj.get("doc_date")) or _iso(obj.get("due_date"))
    if (conf < MIN_CONF or not obj.get("vendor") or not date or typ in doc_extract.DETAILS
            or typ in ("timesheet", "work_calendar", "school_calendar")):
        to_review(con, f, f"scanned PDF read by AI: check it and file it by hand (confidence {conf:.2f})", guess)
        return f.name, "review", "scan"
    amount = obj.get("amount")
    note = f"scanned PDF read by AI {llm.settings()['provider']}; confidence {conf:.2f}"
    try:
        _, dest = file_document(con, f, typ, obj["vendor"].strip()[:80], date,
                                amount if amount is not None and amount >= 0 else None, _iso(obj.get("due_date")), note)
    except ValueError as e:
        to_review(con, f, f"AI answer rejected: {e}", guess)
        return f.name, "review", "rejected"
    con.commit()
    return f.name, "filed", paths.rel(dest)


def _unread_reason(f, status):
    """The review reason for a file whose text could not be pulled out, in words a person can act on."""
    ext = f.suffix.lower()
    if status == "scanned":
        why = llm.photos_allowed()
        hint = ("; turn on photo reading to have the AI read scans" if why.startswith("reading photos with AI is off")
                and llm.settings()["provider"] in llm.API else "")
        return "scanned PDF (no text layer): the pages are pictures, so there is no text to read" + hint
    if status == "error":
        return "could not open the file (damaged, or protected with a password?)"
    if ext == llm.HEIC and not heic.available():
        return f"HEIC photo not read: {heic.MISSING}; save it as JPG or PDF and drop it again"
    if ext in llm.PHOTO_TYPES or ext == llm.HEIC:
        return "photo not read: " + (llm.photos_allowed() or "photo reading is off")
    return f"{ext or 'this'} files are not read automatically yet"


def _statement_new_account(con, f, text, ps):
    """A first statement of an account this PC does not know: add the account (name as printed without digits, type from
    the wording, last four only) and keep it only if the statement then reads and adds up to the printed balances."""
    seen = list(dict.fromkeys(ps.last4s(text)))
    if len(seen) != 1:  # several accounts on one statement (savings + checking): a person says which one is new
        return None
    last4 = seen[0]
    m = ps.LAST4.search(text)
    stop = text.find("\n", m.end())
    own = text[text.rfind("\n", 0, m.start()) + 1:stop if stop >= 0 else len(text)]  # the line that prints the number
    head = text[:1500].lower()
    kind = ("credit" if re.search(r"new balance|statement balance|minimum payment|payment due|credit limit|credit card", head)
            else "savings" if re.search(r"savings", own, re.I) or ("savings" in head and not re.search(r"checking", own, re.I))
            else "checking")
    lines = [own] + text.splitlines()  # the account's own line first ("Everyday Checking 1234564455"), digits left out
    name = next((re.sub(r"[^A-Za-z&' ]+", " ", ln).strip() for ln in lines
                 if re.search(r"checking|savings|card|credit", ln, re.I) and (ln is own or not re.search(r"\d{5,}", ln))), "")
    name = re.sub(r"\s+", " ", name)[:40] or kind.title()
    con.execute("SAVEPOINT new_account")
    try:
        aid = con.execute("INSERT INTO accounts(name, type, last4) VALUES (?,?,?)", (name, kind, last4)).lastrowid
        res = ps.read(con, f)
        if res["verified"] is not True:
            raise ps.StatementError("balances do not add up")
    except (ps.StatementError, ValueError, sqlite3.Error):
        con.execute("ROLLBACK TO new_account")
        con.execute("RELEASE new_account")
        return None
    con.execute("RELEASE new_account")
    res["account"] = {**res["account"], "id": aid, "new": True}
    return res


YEARS = range(1990, 2100)


def _export_account(con, f, header, rows):
    """The account of an activity export (CSV): from an account column ("Account #", "Account Number": only the last
    four are used) or the file's name ("Card1234_Activity.csv"), and only when exactly one account has those last four.
    A four-digit number that could be a year counts from the name only when letters touch it. None = not sure."""
    seen = []
    low = [h.strip().lower() for h in header]
    col = next((i for i, h in enumerate(low) if h in ("account", "account #", "account number", "account no", "acct")), None)
    if col is not None:
        vals = {re.sub(r"\D", "", r[col])[-4:] for r in rows if col < len(r) and len(re.sub(r"\D", "", r[col])) >= 4}
        seen += sorted(vals) if len(vals) == 1 else []
    for m in re.finditer(r"(?<!\d)(\d{4})(?!\d)", f.stem):
        glued = m.start() > 0 and f.stem[m.start() - 1].isalpha()
        if int(m.group(1)) not in YEARS or glued:
            seen.append(m.group(1))
    for l4 in dict.fromkeys(seen):
        hit = con.execute("SELECT id, name, type, last4 FROM accounts WHERE last4=?", (l4,)).fetchall()
        if len(hit) == 1:
            return dict(zip(("id", "name", "type", "last4"), hit[0]))
    return None


def _csv_route(con, f):
    """A bank or card activity export (CSV with date, description and amount columns) imported without AI into the
    account it names (see _export_account). An export whose account is not clear waits with the "Import as statement"
    choice; None = not an activity export (carry on)."""
    import import_statement as ist
    try:
        header, rows = ist.read_rows(f)
        mapping = ist.guess_mapping(header)
        parsed, problems = ist.parse_rows(header, rows, mapping)
    except (ist.ImportError_, ValueError, StopIteration, OSError):
        return None
    if not parsed or len(problems) > max(2, len(rows) // 10):
        return None
    acct = _export_account(con, f, header, rows)
    if acct is None:
        to_review(con, f, "transactions export: it does not say which account it is from; choose the account to "
                          "import it into", "guess type=statement")
        return f.name, "review", "which account"
    days = sorted(p["date"] for p in parsed)
    vendor = f"{acct['name'][:60]} x{acct['last4'] or ''}".strip()
    doc_id, dest = file_document(con, f, "statement", vendor, days[-1],
                                 note=f"activity export (no AI); {len(parsed)} lines {days[0]}..{days[-1]}")
    con.commit()  # the paper is filed: keep that whatever happens to the lines
    rep = ist.run_import(dest, acct["name"], document_id=doc_id, con=con)
    if not rep["ok"]:
        return f.name, "filed", f"{paths.rel(dest)} (lines not imported: {'; '.join(rep['problems'][:2])})"
    return f.name, "filed", (f"activity export: {rep['inserted']} transactions added, {rep['skipped']} already loaded "
                             f"({acct['name']} x{acct['last4']})")


def _ofx_route(con, f):
    """An OFX / QFX download (data/ofx_statement.py): imported into the account its number names; a new account is
    added by its last four. A download that cannot be read waits for a person with the reason."""
    import ofx_statement as ox
    try:
        r = ox.read(f)
    except ox.OFXError as e:
        to_review(con, f, f"OFX download not read: {e}")
        return f.name, "review", "ofx"
    hit = con.execute("SELECT id, name, type, last4 FROM accounts WHERE last4=?", (r["last4"],)).fetchall()
    if len(hit) > 1:
        to_review(con, f, f"OFX download: more than one account ends in {r['last4']}; choose the account to import it into",
                  "guess type=statement")
        return f.name, "review", "which account"
    if hit:
        acct = dict(zip(("id", "name", "type", "last4"), hit[0]))
    else:
        name = (f"{r['org']} {r['kind']}".strip() if r["org"] else r["kind"].title())[:40]
        aid = con.execute("INSERT INTO accounts(name, type, last4) VALUES (?,?,?)", (name, r["kind"], r["last4"])).lastrowid
        acct = {"id": aid, "name": name, "type": r["kind"], "last4": r["last4"], "new": True}
    res = {"rows": r["rows"], "period": r["period"], "end": r["end"], "account": acct, "verified": None}
    return _file_statement(con, f, res, "OFX download (no AI)", "lines as the bank sent them")


def _file_statement(con, f, res, how, checked="balances check out"):
    import pdf_statement as ps
    acct = res["account"]
    end = (res["period"][1] if res["period"] else dates.today()).isoformat()
    odd = _outside_period(res)
    look = (f"; {len(odd)} line{'' if len(odd) == 1 else 's'} dated outside the statement period ({', '.join(odd[:3])}): "
            "check in Money > Ledger") if odd else ""
    doc_id, dest = file_document(con, f, "statement", f"{acct['name'][:60]} x{acct['last4'] or ''}".strip(), end,
                                 note=f"{how}; {len(res['rows'])} lines; {checked}{look}")
    rep = ps.store(con, res, document_id=doc_id)
    con.commit()
    extra = f" (new account {acct['name']} x{acct['last4']})" if acct.get("new") else ""
    return f.name, "filed", f"statement: {rep['inserted']} transactions added, {rep['skipped']} already loaded{extra}{look}"


def _outside_period(res, slack_days=3):
    """Dates of the lines that fall outside the printed period (a few days' slack for posting): the balances still
    check out, but a misread day or a line from another month is worth a look. [] when no period is known."""
    per = res.get("period")
    if not per:
        return []
    lo, hi = per[0] - dt.timedelta(days=slack_days), per[1] + dt.timedelta(days=slack_days)
    return sorted({r["date"] for r in res["rows"] if not lo <= dt.date.fromisoformat(r["date"]) <= hi})


def _paypal_route(con, f, text):
    """A PayPal account statement is read by data/paypal_statement.py without AI (nothing leaves this PC): the paper is filed
    as a statement of vendor PayPal and each payment becomes a receipt that names the card or bank charge it was paid with
    (never new spending). None = not a PayPal statement (carry on)."""
    import paypal_statement as pp
    if f.suffix.lower() != ".pdf" or not pp.looks_like(text):
        return None
    try:
        res = pp.read(f)
    except (pp.StatementError, ValueError, OSError) as e:
        to_review(con, f, f"PayPal statement not read: {e}", "file it as a plain statement, or drop a clean copy of the PDF")
        return f.name, "review", "paypal statement"
    try:
        doc_id, dest = file_document(con, f, "statement", "PayPal", res["period"][1].isoformat(),
                                     note=f"paypal_statement (no AI); {res['lines']} lines, {len(res['payments'])} payments")
    except ValueError as e:
        to_review(con, f, f"PayPal statement rejected: {e}")
        return f.name, "review", "rejected"
    con.commit()  # the paper is filed and moved: keep that whatever happens to the receipts
    try:
        rep = pp.store(con, res, doc_id)
        con.commit()
    except (sqlite3.Error, ValueError) as e:
        con.rollback()
        return f.name, "filed", f"{paths.rel(dest)} (receipts not stored: {e})"
    if not res["payments"]:
        return f.name, "filed", "PayPal statement: no payments this month"
    return f.name, "filed", (f"PayPal statement: {rep['filed']} payment{'' if rep['filed'] == 1 else 's'} filed as receipts, "
                             f"{rep['matched']} matched to a card or bank charge")


def _mobile_route(con, f, text):
    """A per-line phone bill is read by data/mobile_bill.py without AI (nothing leaves this PC), filed as a bill for the
    total due, and its lines stored only when every figure adds up to the cent. None = not such a bill (carry on)."""
    import mobile_bill as mb
    if not mb.looks_like(text):
        return None
    try:
        res = mb.read(text, strict=True)
    except mb.BillError as e:
        to_review(con, f, f"phone bill not read per line: {e}", "file it as a plain bill, or drop a clean copy of the PDF")
        return f.name, "review", "phone bill"
    try:
        doc_id, dest = file_document(con, f, "bill", res["carrier"], res["bill_date"].isoformat(), res["total_due"],
                                     res["due_date"].isoformat() if res["due_date"] else None,
                                     f"mobile_bill; {len(res['lines'])} lines; adds up to the cent")
    except ValueError as e:
        to_review(con, f, f"phone bill rejected: {e}")
        return f.name, "review", "rejected"
    con.commit()  # the paper is filed and moved: keep that whatever happens to the lines
    try:
        mb.store(con, res, doc_id)
    except (mb.BillError, sqlite3.Error) as e:  # stays filed with its total; `mobile_bill.py reparse ID` reads it again
        con.rollback()
        return f.name, "filed", f"{paths.rel(dest)} (phone lines not stored: {e})"
    return f.name, "filed", f"phone bill: {len(res['lines'])} lines, net cost per person stored"


def _school_route(con, f, text):
    """A school year calendar in a layout data/school_calendar.py knows is read without AI: its days off and early
    dismissals wait in the Inbox as proposed calendar days. None = not one (or not readable): the AI reads it."""
    import school_calendar as sc
    if not sc.looks_like(text):
        return None
    try:
        details = doc_extract.prepare("school_calendar", sc.read(text))
    except (sc.CalendarError, doc_extract.Unusable, ValueError, TypeError):
        return None
    date = doc_extract.date_of("school_calendar", details) or min(d["day"] for d in details["days"])
    try:
        doc_id, _ = file_document(con, f, "school_calendar", details["school"] or "school", date, None, None,
                                  f"school_calendar (no AI); {len(details['days'])} days")
    except ValueError as e:
        to_review(con, f, f"school calendar rejected: {e}")
        return f.name, "review", "rejected"
    info = doc_extract.save(con, "school_calendar", details, doc_id)
    con.commit()
    return f.name, "filed", info


def _work_route(con, f, typ):
    """A timesheet or work calendar: import it when exactly one active contract can take it, else a person picks."""
    import work
    import work_match
    try:
        prof = [c for c in work.contracts(con) if c.get("timesheet_cycle") or c.get("invoice_freq") or c.get("needs_timesheets")]
        picked = work_match.choose(work_match.candidates(con, work.read_text(f)[0])) if typ == "timesheet" else None
    except sqlite3.OperationalError:
        prof, picked = [], None
    names = sorted({c["work_calendar"] for c in prof if c.get("work_calendar")})
    if typ == "timesheet" and picked:
        kw = {"contract": picked["id"]}
    elif typ == "work_calendar" and len(names) == 1:
        kw = {"calendar": names[0]}
    elif typ == "timesheet":
        to_review(con, f, "timesheet: which job is it for?")
        return f.name, "review", typ
    else:
        to_review(con, f, f"{typ.replace('_', ' ')}: import it on the Work tab (which calendar?)")
        return f.name, "review", typ
    try:
        msg = work.file_and_import(con, f, typ, **kw)
    except ValueError as e:
        con.rollback()
        to_review(con, f, f"{typ.replace('_', ' ')} not imported: {e}")
        return f.name, "review", typ
    con.commit()
    return f.name, "filed", f"{typ.replace('_', ' ')}: {msg}"


def file_document(con, path, typ, vendor, date, amount=None, due=None, note="", last4=None):
    """File one document with NO AI: rename to YYYY-MM-DD_vendor_type.ext, move it under archive/<year>/<category>/, insert
    the `documents` row and, for a bill or policy with an amount and a due date, a `bills` row (skipped when the same vendor
    and due date already exist). Validates every field and raises ValueError on bad input; moves nothing in that case.
    `path` must be a file inside this project. Does not commit. Returns (document_id, archived_path)."""
    f = pathlib.Path(path)
    f = (f if f.is_absolute() else paths.HOME / f).resolve()
    if paths.HOME.resolve() not in f.parents or not f.is_file():
        raise ValueError("the file is not inside this household's folder or is no longer there")
    if typ not in CATEGORY:
        raise ValueError(f"type must be one of {', '.join(CATEGORY)}")
    try:
        vendor = v.text(80)(vendor)
    except ValueError as e:
        raise ValueError(f"vendor: {e}") from None
    date = _iso(date)
    if not date:
        raise ValueError("date must be YYYY-MM-DD")
    if due is not None and due != "" and not _iso(due):
        raise ValueError("due date must be YYYY-MM-DD")
    due = _iso(due) if due else None
    if amount is not None:
        amount = float(amount)
        if amount < 0 or amount > 1e9:
            raise ValueError("amount must be 0 or more")
    dest = unique(paths.ARCHIVE / date[:4] / CATEGORY[typ] / f"{date}_{slug(vendor)}_{typ}{f.suffix.lower()}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(f), dest)
    _MOVED.append((dest, f))  # put back by _process_or_put_back if the record never commits
    cur = con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date, notes, ingested_at) VALUES (?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))",
                      (dest.relative_to(paths.ARCHIVE).as_posix(), typ, vendor, date, (note or "")[:300]))
    doc_id = cur.lastrowid
    if typ == "receipt" and amount:
        try:
            import receipts
            receipts.add(con, vendor, date, amount, last4=last4, document_id=doc_id)
        except sqlite3.OperationalError as e:  # receipts table not migrated yet: the document is still filed
            if not db.missing(e):
                raise
    if typ in ("bill", "policy") and amount is not None and due:
        dup = con.execute("SELECT 1 FROM bills WHERE LOWER(vendor)=LOWER(?) AND due_date=?", (vendor, due)).fetchone()
        if not dup:
            con.execute("INSERT INTO bills(name, vendor, amount, due_date, status, document_id) VALUES (?,?,?,?, 'due', ?)",
                        (f"{vendor[:60]} {typ}", vendor, _money.round2(amount), due, doc_id))
    return doc_id, dest


def resolve_review(con, review_id, typ, vendor, date, amount=None, due=None, note=""):
    """A person files a review_queue item (see file_document) and the row is marked resolved. Commits. ValueError on bad input,
    an unknown or already resolved id, or when the file is no longer where the queue says."""
    row = con.execute("SELECT path, resolved FROM review_queue WHERE id=?", (int(review_id),)).fetchone()
    if not row:
        raise ValueError("no review item with that id")
    if row[1]:
        raise ValueError("that review item is already resolved")
    f = paths.HOME / row[0]
    if not f.is_file():
        raise ValueError(f"the file is no longer at {row[0]} (moved by hand?); dismiss the row if it is already dealt with")
    doc_id, dest = file_document(con, f, typ, vendor, date, amount, due, note or "filed by a person from the review queue")
    con.execute("UPDATE review_queue SET resolved=1 WHERE id=?", (int(review_id),))
    con.commit()
    return doc_id, dest


def retry_review(con, review_id):
    """Put a review_queue file back in inbox/ to be read again (after its account was added, photo reading turned on or
    the AI account topped up). The row is marked resolved; a run that still cannot read it makes a new one. Commits.
    Returns the file's new path in inbox/. ValueError for an unknown or resolved id, or a file no longer there."""
    row = con.execute("SELECT path, resolved FROM review_queue WHERE id=?", (int(review_id),)).fetchone()
    if not row:
        raise ValueError("no review item with that id")
    if row[1]:
        raise ValueError("that review item is already resolved")
    f = paths.HOME / row[0]
    if not f.is_file():
        raise ValueError(f"the file is no longer at {row[0]} (moved by hand?); dismiss the row if it is already dealt with")
    paths.INBOX.mkdir(parents=True, exist_ok=True)
    dest = unique(paths.INBOX / f.name)
    shutil.move(str(f), dest)
    con.execute("UPDATE review_queue SET resolved=1 WHERE id=?", (int(review_id),))
    con.commit()
    return dest


def import_review_statement(con, review_id, account_id, read_as=None, force=False):
    """A person chose "Import as statement" on a waiting file: read it into the account they picked (PDF statement,
    activity CSV or OFX / QFX download). A PDF is imported only when its lines add up to the printed balances, unless
    the person ticked "Import anyway"; nothing is filed or imported when the check fails, so the card stays and says
    what the check found. read_as "bank" / "card" overrides the account's type for reading a PDF. Commits. Returns the
    result line. ValueError with the reason otherwise."""
    import import_statement as ist
    import pdf_statement as ps
    row = con.execute("SELECT path, resolved FROM review_queue WHERE id=?", (int(review_id),)).fetchone()
    if not row or row[1]:
        raise ValueError("that waiting file is already dealt with")
    f = paths.HOME / row[0]
    if not f.is_file():
        raise ValueError(f"the file is no longer at {row[0]} (moved by hand?); dismiss it if it is already dealt with")
    hit = con.execute("SELECT id, name, type, last4 FROM accounts WHERE id=?", (int(account_id),)).fetchone()
    if not hit:
        raise ValueError("choose one of the accounts")
    acct = dict(zip(("id", "name", "type", "last4"), hit))
    ext = f.suffix.lower()
    if ext == ".csv":
        header, rows = ist.read_rows(f)
        parsed, problems = ist.parse_rows(header, rows, ist.guess_mapping(header))
        if not parsed:
            raise ValueError("no lines with a date, a description and an amount were found in it")
        days = sorted(p["date"] for p in parsed)
        doc_id, dest = file_document(con, f, "statement", f"{acct['name'][:60]} x{acct['last4'] or ''}".strip(), days[-1],
                                     note=f"activity export, account chosen by a person; {len(parsed)} lines")
        con.execute("UPDATE review_queue SET resolved=1 WHERE id=?", (int(review_id),))
        con.commit()
        rep = ist.run_import(dest, acct["name"], document_id=doc_id, con=con)
        if not rep["ok"]:
            return f"Filed, but its lines were not imported: {'; '.join(rep['problems'][:2])}"
        return f"{rep['inserted']} transactions added to {acct['name']} ({rep['skipped']} already loaded)."
    if ext in (".ofx", ".qfx"):
        import ofx_statement as ox
        try:
            r = ox.read(f)
        except ox.OFXError as e:
            raise ValueError(str(e)) from None
        res = {"rows": r["rows"], "period": r["period"], "end": r["end"], "account": acct, "verified": None}
        info = _file_statement(con, f, res, "OFX download, account chosen by a person", "lines as the bank sent them")[2]
    elif ext in (".pdf", ".txt"):
        card = {"bank": False, "card": True}.get(read_as or "")
        try:
            res = ps.read(con, f, account=acct["last4"] or acct["name"], card=card)
        except (ps.StatementError, ist.ImportError_) as e:
            raise ValueError(str(e)) from None
        res["account"] = acct
        if res["verified"] is not True and not force:
            if res["verified"] is None:
                raise ValueError(f"it prints no balances to check {len(res['rows'])} lines against; tick Import anyway "
                                 "to import them as read")
            raise ValueError(f"the lines do not add up: begin {res['begin']}, money in {res['money_in']}, money out "
                             f"{res['money_out']}, end {res['end']} ({len(res['rows'])} lines read); check the account and "
                             "bank / card, or tick Import anyway")
        checked = "balances check out" if res["verified"] else "imported anyway by a person: the lines did not add up"
        info = _file_statement(con, f, res, "pdf_statement, account chosen by a person", checked)[2]
    else:
        raise ValueError("only PDF, CSV and OFX / QFX statements can be imported here; file it by hand instead")
    con.execute("UPDATE review_queue SET resolved=1 WHERE id=?", (int(review_id),))
    con.commit()
    return info[0].upper() + info[1:] + "."


def run(local=False):
    """File what waits in inbox/. One run at a time ("File now" and the scheduled inbox check never overlap)."""
    import joblock
    try:
        with joblock.job("intake"):
            return _run(local)
    except joblock.Busy as e:
        print("an update or restore is running; the files wait for the next run" if str(e) == joblock.MAINTENANCE
              else "another filing run is reading the inbox; the files wait for the next one")
        return 0


def _process_or_put_back(con, f, local, step):
    """process_file, but a database error (busy for longer than the timeout) rolls back and moves the paper back to
    inbox/ for the next run, instead of leaving it in archive/ with no record."""
    _MOVED.clear()
    try:
        return process_file(con, f, local, step)
    except sqlite3.Error as e:
        con.rollback()
        kept = 0
        for dest, src in reversed(_MOVED):
            try:
                on_record = db.one(con, "SELECT 1 AS x FROM documents WHERE filed_path = ?",
                                   (dest.relative_to(paths.ARCHIVE).as_posix(),))
            except sqlite3.Error:  # still locked: no record is the likely case
                on_record = None
            if on_record:
                kept += 1  # its record was committed before the error (a route that commits early): stays filed
            elif dest.exists() and not src.exists():
                shutil.move(str(dest), src)
        if kept:
            return f.name, "filed", f"filed, but a later step failed ({e})"
        return f.name, "skipped", f"database error ({e}); left in the inbox for the next run"
    finally:
        _MOVED.clear()


def _run(local):
    inbox = paths.INBOX
    files = [p for p in sorted(inbox.iterdir()) if p.is_file() and p.name != ".gitkeep"] if inbox.exists() else []
    if not files:
        print("inbox is empty")
        return 0
    con = db.connect(DB)
    known, results = known_files(), []
    prog = intake_progress.Run([f.name for f in files])  # the Inbox page's progress panel
    try:
        for f in files:
            prog.step(f.name, "checking")
            h = sha256(f)
            if h in known:  # dropped twice (or the same file in this batch): no second filing, no AI call
                results.append(to_duplicates(f, known[h]))
            else:
                results.append(_process_or_put_back(con, f, local, lambda s, n=f.name: prog.step(n, s)))
                if not f.exists():  # filed or sent to review: a later identical copy in this batch is a duplicate
                    known[h] = f"inbox/{f.name} (this run)"
            prog.done(*results[-1])
    finally:
        prog.finish()
    for name, st, info in results:
        print(f"{st:<8} {name} -> {info}")
    return 0 if all(st != "skipped" for _, st, _ in results) else 1


def duplicates():
    """Only the exact-copy check, no AI and no filing: copies of papers already filed (or waiting for review) and
    repeats inside inbox/ go to archive/duplicates/; the first of identical files stays. For the Claude Code intake agent."""
    inbox = paths.INBOX
    files = [p for p in sorted(inbox.iterdir()) if p.is_file() and p.name != ".gitkeep"] if inbox.exists() else []
    known, seen, moved = known_files(), {}, 0
    for f in files:
        h = sha256(f)
        same = known.get(h) or seen.get(h)
        if same:
            print("duplicate", *to_duplicates(f, same)[::2], sep="  ")
            moved += 1
        else:
            seen[h] = f"inbox/{f.name}"
    print(f"{moved} duplicate(s) moved, {len(files) - moved} file(s) left in inbox/")
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "duplicates":
        sys.exit(duplicates())
    if cmd == "local":  # no AI: phone bills and school calendars this PC can read itself; nothing else moves
        sys.exit(run(local=True))
    if cmd == "review":
        con = db.connect(DB)
        for r in con.execute("SELECT id, path, reason FROM review_queue WHERE resolved=0 ORDER BY id"):
            print(*r, sep="  |  ")
    elif cmd == "resolve" and len(sys.argv) > 2:
        con = db.connect(DB)
        con.execute("UPDATE review_queue SET resolved=1 WHERE id=?", (int(sys.argv[2]),))
        con.commit()
        print("ok")
    elif cmd == "file":
        ap = argparse.ArgumentParser(prog="ai_intake.py file", description="File one waiting review item by hand (no AI).")
        ap.add_argument("id", type=int, help="review_queue id (see: ai_intake.py review)")
        ap.add_argument("--type", required=True, choices=list(CATEGORY))
        ap.add_argument("--vendor", required=True, help="company or person the document is from")
        ap.add_argument("--date", required=True, help="document date, YYYY-MM-DD")
        ap.add_argument("--amount", type=float, help="amount due or total")
        ap.add_argument("--due", help="due date, YYYY-MM-DD (with --amount: adds a bill for bills and policies)")
        ap.add_argument("--note", default="", help="free note stored with the document record")
        a = ap.parse_args(sys.argv[2:])
        con = db.connect(DB)
        try:
            doc_id, dest = resolve_review(con, a.id, a.type, a.vendor, a.date, a.amount, a.due, a.note)
        except ValueError as e:
            print(f"error: {e}")
            sys.exit(2)
        print(f"filed {paths.rel(dest)} (document {doc_id})")
    else:
        sys.exit(run())


if __name__ == "__main__":
    main()
