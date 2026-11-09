"""One queue of things the agent wants a person to decide: the Inbox (files, decisions, questions).

  python data/proposals.py sync                      refresh the queue from the detectors (no AI)
  python data/proposals.py list [--all]              open items (or every item) with their options
  python data/proposals.py decide ID OPTION [--date YYYY-MM-DD] [--name TEXT]
  python data/proposals.py restore ID                show a dismissed or done item again

Producers (all existing, all without AI): review_queue rows (files the pipeline would not guess about),
recurring_bills.detect + subscriptions.detect (payments seen three or more times), statement_watch (statements due or
missing), recurring_bills.status price rises, subscription price changes and policy premiums up 10% or more, policy terms
ending within 45 days with no newer term filed (source "renewal"), Amazon charges with no order details and orders with
no card charge (source "amazon", only with the Amazon pack), recurring_rows with no date (checkups and home tasks), and
the household profile's gaps (data/profile_gaps.py: at most two new questions a day), and a newer release found by the
daily look (data/update_notice.py, source "update": Update now runs the signed update through admin_actions), and the
newest data check's fixable findings (data/audit.py, source "audit": remove extra copies, mark a late bill paid).

Safety. A proposal never stores a command or an action name. `payload` only holds the arguments for the fixed handler
of its source below, and every handler goes through data/edit_actions.py (adults only, validated, logged). Dismiss and
snooze change only this table, except where the source has its own "do not propose again" list (recurring payees).

Lifecycle. `sync` inserts new items, refreshes open ones, re-opens snoozed ones whose date has passed and marks open or
snoozed items `expired` when their source no longer reports them (handled elsewhere: on the Money tab, by the intake
agent, by a new statement). Done and dismissed items stay as they are, so a dismissed payee is not proposed again.
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import brand  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import log  # noqa: E402
from money import fmt as money  # noqa: E402

DB = paths.DB
KINDS = ("file", "decision", "question")
LIVE = ("open", "snoozed")
HOUSE = {"home", "house", "household", "family", "all"}

# source -> {option: label}. The first option is the suggested one. Order is the order shown.
OPTIONS = {
    "review": {"job": "Pick the job", "file": "File it by hand", "account": "Add the account", "statement": "Import as statement", "retry": "Reprocess",
               "dismiss": "Dismiss"},
    "recurring": {"bill": "Track as a bill", "subscription": "Track as subscription", "ignore": "Not a bill"},
    "statement": {"later": "Remind me in a week", "dismiss": "Dismiss"},
    "price_rise": {"ok": "OK, noted", "dismiss": "Dismiss"},
    "undated": {"date": "Pick date", "not_sure": "Not sure", "not_ours": "Not ours"},
    "profile": {"later": "Ask me later", "dismiss": "Not needed"},  # per question: profile_gaps.OPTIONS
    "renewal": {"reviewed": "I looked into it", "later": "Remind me in a week", "dismiss": "Dismiss"},
    "amazon": {"later": "Remind me in two weeks", "dismiss": "Not needed"},
    "bank_sync": {"later": "Remind me in a week", "dismiss": "Dismiss"},
    "bank_dupe": {"remove": "Remove the bank-sync copy", "keep": "Keep both"},
    "days": {"accept": "Add them to the calendar", "later": "Remind me in a week", "dismiss": "Leave them out"},
    "info_review": {"ok": "All still correct", "later": "Remind me in a week"},
    "update": {"update": "Update now", "later": "Later"},
    "audit": {"remove": "Remove the extra copies", "paid": "Mark it paid", "keep": "Leave it as it is",
              "later": "Remind me in a week"},  # per finding: AUDIT_OPTIONS
    "calendar_back": {"accept": "Use the new date", "hide": "Take it off", "keep": "Keep ours"},  # per change: _row
}
LATER_DAYS = {"statement": 7, "renewal": 7, "amazon": 14, "bank_sync": 7, "days": 7, "info_review": 7,
              "update": 7, "audit": 7}  # snooze length for the queue-only sources
# options that need an answer from the person (the Inbox opens a small form for these)
NEEDS = {("review", "file"): ("type", "vendor", "date"), ("review", "account"): ("name", "type", "last4"), ("review", "statement"): ("account",), ("review", "job"): ("contract",), ("undated", "date"): ("date",), ("profile", "birthday"): ("date",),
         ("audit", "paid"): ("date",)}
AUDIT_OPTIONS = {"dupe_txn": ("remove", "keep", "later"), "dupe_bill": ("remove", "keep", "later"),
                 "late_bill": ("paid", "keep", "later")}


def _con():
    return db.connect(DB, timeout=10)


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _has_table(con, name):
    return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


# ------------------------------------------------------------------ producers: each yields proposal dicts
def _p(key, source, kind, summary, detail="", payload=None, ref=(None, None)):
    return {"dedupe_key": key, "source": source, "kind": kind, "summary": summary, "detail": detail or "",
            "payload": json.dumps(payload or {}, sort_keys=True), "ref_table": ref[0], "ref_id": ref[1]}


def from_review(con, today):
    if not _has_table(con, "review_queue"):
        return
    for rid, path, reason, detail in con.execute(
            "SELECT id, path, reason, detail FROM review_queue WHERE resolved=0 ORDER BY id"):
        name = pathlib.PurePath(str(path)).name
        sheet = str(reason or "").startswith("timesheet:")
        jobs = _timesheet_jobs(con) if sheet else []
        yield _p(f"review:{rid}", "review", "file", f"{name}: whose timesheet is it?" if jobs else f"{name} needs you: say what it is",
                 "Pick the job it belongs to; it is read into that job's hours." if jobs
                 else " ".join(x for x in (_plain_reason(reason, name), _plain_guess(detail)) if x),
                 {"review_id": rid, "why": _why(reason, detail), "guess": guess_of(detail),
                  "last4s": _missing_accounts(reason), "fix_link": _fix_link(reason), "jobs": jobs,
                  "statement_ok": _statement_like(name, reason, detail)}, ("review_queue", rid))


def _timesheet_jobs(con):
    """[{id, label}] of the shared jobs that need timesheets: the choices of "Which job?" (private jobs are picked on Work)."""
    try:
        import work_match
        return [{"id": j["id"], "label": j["client"] + (f" ({j['person']})" if j.get("person") else "")}
                for j in work_match.jobs(con)]
    except Exception:  # noqa: BLE001 (an older database)
        return []


STATEMENT_FILES = (".pdf", ".txt", ".csv", ".ofx", ".qfx")


def _statement_like(name, reason, detail):
    """True when "Import as statement" can help: a PDF / CSV / OFX the reader or the AI took for a statement."""
    r = f"{reason} {detail}".lower()
    return (pathlib.PurePath(str(name)).suffix.lower() in STATEMENT_FILES
            and ("statement" in r or "transactions export" in r or "ofx" in r) and "scanned" not in r)


def _missing_accounts(reason):
    """The last fours of a statement's account(s) this PC does not have yet (the "Add the account" fix), or []."""
    m = LAST4S.search(str(reason or "").lower())
    return list(dict.fromkeys(re.findall(r"\d{4}", m.group(1)))) if m else []


def _fix_link(reason):
    """Where the setting that would let this file be read lives, as {"href", "label"}, or {}."""
    r = str(reason or "").lower()
    if ("photo not read" in r and ("off" in r or "cannot read photos" in r)) or ("scanned" in r and "photo reading" in r):
        return {"href": "/settings?group=connections#conn-ai", "label": "Open AI settings"}
    return {}


LAST4S = re.compile(r"no account with the last four digits ((?:\d{4}(?:, )?)+)")


def _plain_reason(reason, name=""):
    """The review reason (ai_intake.to_review) as one sentence that says what to do next."""
    r = (reason or "").lower()
    if "http 402" in r:
        return ("Your AI account was out of credit when this was read. Add credit with your AI provider, then press "
                "Reprocess, or file it by hand.")
    if "scanned statement read by ai" in r:
        if "add up" in r:
            return ("The AI read the scan, but its lines did not add up to the printed balances, so nothing was imported. "
                    "File it by hand, or drop the PDF downloaded from the bank's website.")
        return ("The AI read the scan but could not check it well enough to import it. File it by hand, or drop the PDF "
                "downloaded from the bank's website.")
    if "scanned pdf read by ai" in r:
        return "The AI read the scan. Check what it found and file it by hand."
    if "scanned pdf: the ai" in r:
        return "The AI could not read the scan. File it by hand."
    if "scanned" in r and "photo reading" in r:
        return ("It is a scan, so there is no text to read. Turn on \"Let the AI read photos\" in Settings > Connections "
                "to have scans read, or file it by hand.")
    if "scanned" in r or "no text" in r:
        return "It is a scan, so there is no text to read. File it by hand, or drop a PDF downloaded from the website."
    if "photo not read" in r and ("off" in r or "cannot read photos" in r):
        return "Reading photos is off. Turn on \"Let the AI read photos\" in Settings > Connections, or file it by hand."
    if "heic" in r or (str(name).lower().endswith(".heic") and ("not read automatically" in r or "file type not read" in r)):
        import heic
        if heic.available():  # an older card, from before this PC could convert them
            return "It is an iPhone photo (HEIC). This PC reads them now: press Reprocess, or file it by hand."
        return ("It is an iPhone photo (HEIC), and this PC cannot turn that format into a picture the AI reads. Save it "
                "as JPG or PDF and drop it again, or file it by hand.")
    if "not read automatically" in r or "file type not read" in r:
        return "This kind of file is not read automatically yet. File it by hand."
    if "could not open" in r or "could not read the file" in r:
        return "The file could not be opened. It may be damaged or protected with a password."
    if "statement" in r:
        m = LAST4S.search(r)
        if m:
            ends = m.group(1).rstrip(", ").replace(", ", " or ")
            return (f"It is a statement of an account ending {ends} that is not set up yet. Press Add the account: "
                    "it is added and the statement is read again.")
        if "(none printed)" in r:
            return "It looks like a statement, but no account number was found on it. File it by hand."
        if "add up" in r:
            return ("It looks like a statement, but its lines did not add up to the printed balances, so nothing was "
                    "imported. File it by hand, or drop a fresh download of it.")
        if "too long" in r:
            return "The statement is too long for the AI to read. Download a shorter period, or file it by hand."
        return "It looks like a statement that could not be checked automatically."
    if "transactions export" in r:
        return "It is a list of transactions that does not say which account it is from. Choose Import as statement."
    if "ofx download" in r:
        return ("It is a download for money software (OFX) that could not be read on its own. Choose Import as "
                "statement, or download it again.")
    if "phone bill" in r:
        return "It looks like a phone bill, but its lines did not add up, so it was not split per person. File it by hand."
    if "photo is not a receipt" in r:  # the photo WAS read: only receipt photos are filed on their own
        return "The AI read the photo, but it does not look like a receipt. Say what it is with File it, or dismiss it."
    if r.startswith("receipt photo:"):
        return ("It looks like a receipt, but the AI could not read the store, date or total for sure. Check them with "
                "File it.")
    if "answer for the photo" in r:
        return "The AI read the photo, but its answer could not be used. Press Reprocess, or say what it is with File it by hand."
    if "photo not read by ai" in r:
        return "The AI could not read the photo. Press Reprocess later, or say what it is with File it by hand."
    if "confidence" in r or "missing" in r:
        return "The assistant was not sure what it is."
    if "photo" in r:
        return "The photo could not be read."
    return "The assistant would not guess what it is."


_GUESS_KEYS = "type|vendor|store|date|amount|total|due"
GUESS_KV = re.compile(rf"\b({_GUESS_KEYS})=(.*?)(?=\s+(?:{_GUESS_KEYS})=|\s+confidence\b|$)")


def guess_of(detail):
    """The AI's guess in a review note ('guess type=bill vendor=City Water date=2026-09-01 amount=41.2', or a photo's
    'guess store=... date=... total=...') as {"type", "vendor", "date", "amount", "due"}: only clean values, for the
    File it form to start from. {} when the note holds no guess."""
    s = str(detail or "")
    if "guess " not in s:
        return {}
    raw = {k: v.strip() for k, v in GUESS_KV.findall(s[s.index("guess "):])}
    out = {}
    typ = raw.get("type", "")
    if re.fullmatch(r"[a-z_]{2,20}", typ) and typ not in ("other", "unknown"):
        out["type"] = typ
    vendor = re.sub(r"[^\w &'.,-]", "", raw.get("vendor") or raw.get("store") or "").strip()[:60]
    if vendor and vendor != "None":
        out["vendor"] = vendor
    for k in ("date", "due"):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.get(k, "")):
            out[k] = raw[k]
    try:
        amount = float((raw.get("amount") or raw.get("total") or "").split()[0])
        if 0 < amount < 1e9:
            out["amount"] = round(amount, 2)
    except (ValueError, IndexError):
        pass
    return out


def _why(reason, detail):
    """What was tried, one step a line, for the card's "Why?" fold: the review reason split at its steps, then any
    validation note (not the guess, which the card already says in words)."""
    steps = [x.strip() for x in str(reason or "").split("; ") if x.strip()]
    extra = str(detail or "")
    if extra and "guess " not in extra:
        steps += [x.strip() for x in extra.split("; ") if x.strip()][:3]
    return [(x[0].upper() + x[1:])[:240] for x in steps][:6]


def _plain_guess(detail):
    """'guess type=bill vendor=City Water' -> 'It looked like a bill from City Water.' (nothing for anything else)."""
    g = guess_of(detail)
    if not g.get("type"):
        return ""
    return f"It looked like a {g['type'].replace('_', ' ')}" + (f" from {g['vendor'][:40]}." if g.get("vendor") else ".")


def from_recurring(con, today):
    seen = {}
    try:
        import recurring_bills as rb
        for c in rb.detect(con, today):
            if not c["active"]:
                continue
            seen[c["payee"].lower()] = {"payee": c["payee"], "frequency": c["frequency"], "amount": c["amount"],
                                        "charges": c["charges"], "variable": c["variable"], "bill_ok": True}
    except Exception as e:  # noqa: BLE001 (one detector failing must not stop the others)
        _warn("recurring_bills.detect", e)
    try:
        import subscriptions as subs
        for c in subs.detect(con, today):
            if not c["active"]:
                continue
            k = c["merchant"].lower()
            if k not in seen:
                seen[k] = {"payee": c["merchant"], "frequency": c["frequency"], "amount": c["amount"],
                           "charges": c["charges"], "variable": False, "bill_ok": False}
            seen[k]["sub_ok"] = True
    except Exception as e:  # noqa: BLE001
        _warn("subscriptions.detect", e)
    for k, c in sorted(seen.items()):
        about = "about " if c["variable"] else ""
        yield _p(f"recurring:{k}", "recurring", "decision",
                 f"{c['payee']} charged {about}{money(c['amount'])} {c['frequency']} ({c['charges']} times)",
                 "Track it so its next charge shows up on Today?",
                 {"payee": c["payee"], "bill_ok": c["bill_ok"], "sub_ok": bool(c.get("sub_ok"))})


def from_statements(con, today):
    try:
        import statement_watch as sw
        rows = sw.watch(con, today)
    except Exception as e:  # noqa: BLE001
        _warn("statement_watch", e)
        return
    for r in rows:
        acct = f"{r['account']} ending {r['last4']}" if r.get("last4") else r["account"]
        if r["status"] in ("due now", "overdue") and r.get("expected"):
            word = "is late" if r["status"] == "overdue" else "should be out now"
            yield _p(f"statement:{r['last4'] or r['account']}:{r['expected']}", "statement", "decision",
                     f"The {acct} statement {word}", "Download it from the bank and drop it in the Inbox.",
                     {"account": r["account"]})
        for m in r.get("missing") or []:
            yield _p(f"statement_gap:{r['last4'] or r['account']}:{m}", "statement", "decision",
                     f"The {acct} statement for {dt.date.fromisoformat(m + '-01'):%B %Y} is missing",
                     "Drop it in the Inbox so the spending for that month is complete.", {"account": r["account"]})


def from_price_rises(con, today):
    try:
        import recurring_bills as rb
        rows = rb.status(con, today)
    except Exception as e:  # noqa: BLE001
        _warn("recurring_bills.status", e)
        return
    for r in rows:
        for f in r["flags"]:
            if not f.startswith("price rise"):
                continue
            nums = f.replace("price rise", "").strip()
            yield _p(f"price_rise:{r['payee'].lower()}:{nums}", "price_rise", "decision",
                     f"{r['name']} went up ({nums.replace('->', 'to')})", "Worth a call to ask why?", {"payee": r["payee"]})


RENEW_AHEAD = 45     # days before a policy's term ends that its renewal question appears
RENEW_LATE = 14      # and how long after the end date it stays when no new term was filed
SPIKE_PCT = 10.0     # a renewed premium this much above the prior term is a price spike
SPIKE_DAYS = 120     # ... for this long after the new term started
AMAZON_CHARGE_AGE = 14   # an Amazon charge counts as unexplained after this many days with no order matched
AMAZON_ORDER_GAP = 10    # an order is unmatched only once the statements run this many days past it (the match window)
AMAZON_MIN = 3


def _plain_row(con, fn, *a):
    """Run a helper that switches the connection to sqlite3.Row without restoring it."""
    old = con.row_factory
    try:
        return fn(con, *a)
    finally:
        con.row_factory = old


def from_renewals(con, today):
    """Auto and home policies whose term ends soon and has no newer term filed (record of the renewal, not advice)."""
    if not _has_table(con, "policies"):
        return
    lo, hi = today - dt.timedelta(days=RENEW_LATE), today + dt.timedelta(days=RENEW_AHEAD)
    rows = con.execute(
        "SELECT p.id, p.kind, p.carrier, p.policy_last4, p.term_end, p.premium_total, h.change_pct FROM policies p "
        "LEFT JOIN v_policy_premium_history h ON h.id = p.id "
        "WHERE (p.status IS NULL OR p.status NOT IN ('expired','replaced','cancelled','superseded')) "
        "AND p.term_end BETWEEN ? AND ? "
        "AND NOT EXISTS (SELECT 1 FROM policies n WHERE n.prior_policy_id = p.id) ORDER BY p.term_end, p.id",
        (lo.isoformat(), hi.isoformat())).fetchall()
    for pid, kind, carrier, last4, end, premium, chg in rows:
        try:
            when = dt.date.fromisoformat(str(end)[:10])
        except ValueError:
            continue
        days = (when - today).days
        name = " ".join(x for x in (carrier, kind, "policy") if x) + (f" ending {last4}" if last4 else "")
        if days >= 0:
            summary = f"Your {name} runs out on {when:%b %d}" + (" (today)" if days == 0 else f" ({days} days)")
        else:
            summary = f"Your {name} ran out on {when:%b %d} and no newer one is filed"
        bits = []
        if premium:
            bits.append(f"The premium is {money(premium)}" + (f", {chg:+.1f}% on the term before" if chg is not None else "") + ".")
        bits.append("Drop the new declarations page in the Inbox when it arrives; the review checklist compares it to this term.")
        yield _p(f"renewal:{pid}", "renewal", "decision", summary, " ".join(bits), {}, ("policies", pid))


_NUMS = re.compile(r"(\d[\d,]*\.\d\d)\D+(\d[\d,]*\.\d\d)")


def from_price_spikes(con, today):
    """Subscriptions that went up and policies that renewed for 10% or more above the term before. Same source as
    recurring_bills' price rises (`price_rise`), so one Inbox card kind covers every kind of increase."""
    try:
        import subscriptions as subs
        for s in _plain_row(con, subs.tracked, today):
            m = _NUMS.search(s.get("price_note") or "")
            if not m or s["status"] != "active":
                continue
            before, after = (float(x.replace(",", "")) for x in m.groups())
            if after <= before:
                continue
            nums = f"{before:.2f} -> {after:.2f}"
            yield _p(f"price_rise:{s['name'].lower()}:{nums}", "price_rise", "decision",
                     f"{s['name']} went up ({nums.replace('->', 'to')})", "Still worth it? Subscriptions are in Money > Pay.",
                     {"payee": s["name"]}, ("subscriptions", s["id"]))
    except Exception as e:  # noqa: BLE001
        _warn("subscriptions.tracked", e)
    if not _has_table(con, "policies"):
        return
    since = (today - dt.timedelta(days=SPIKE_DAYS)).isoformat()
    for pid, kind, carrier, last4, prior, now, pct in con.execute(
            "SELECT id, kind, carrier, policy_last4, prior_premium, premium_total, change_pct FROM v_policy_premium_history "
            "WHERE change_pct >= ? AND term_start >= ? ORDER BY term_start, id", (SPIKE_PCT, since)).fetchall():
        name = " ".join(x for x in (carrier, kind, "premium") if x)
        yield _p(f"price_rise:policy:{pid}", "price_rise", "decision",
                 f"The {name} went up {pct:.0f}% ({money(prior)} to {money(now)})",
                 "Worth a call to ask why?" + (f" It is the policy ending {last4}." if last4 else ""),
                 {}, ("policies", pid))


def from_amazon(con, today):
    """Amazon charges with no order details, and orders with no card charge (optional Amazon pack only)."""
    try:
        import amazon_match as am
        import config
        if not config.pack("amazon") or not _has_table(con, "amazon_orders"):
            return
        stale = (today - dt.timedelta(days=AMAZON_CHARGE_AGE)).isoformat()
        charges = [t for t in _plain_row(con, am.unmatched_charges) if t["amount"] < 0 and str(t["txn_date"]) <= stale]
        if len(charges) >= AMAZON_MIN:
            total = round(-sum(t["amount"] for t in charges), 2)
            yield _p("amazon:charges", "amazon", "decision",
                     f"{len(charges)} Amazon charges ({money(total)}) have no order details",
                     "Download your Amazon order history and drop it in the Inbox so each charge shows what was bought. "
                     "Prime fees and digital purchases never have one.", {})
        latest = con.execute("SELECT MAX(txn_date) FROM transactions").fetchone()[0]
        if latest:
            cutoff = (dt.date.fromisoformat(str(latest)[:10]) - dt.timedelta(days=AMAZON_ORDER_GAP)).isoformat()
            orders = con.execute(
                "SELECT total FROM amazon_orders WHERE transaction_id IS NULL AND total > 0 AND order_date <= ? "
                "AND COALESCE(status,'') NOT IN ('refunded','returned','cancelled')", (cutoff,)).fetchall()
            if len(orders) >= AMAZON_MIN:
                total = round(sum(r[0] for r in orders), 2)
                yield _p("amazon:orders", "amazon", "decision",
                         f"{len(orders)} Amazon orders ({money(total)}) have no card charge",
                         "The statement of the card you paid with may not be loaded yet, or they were paid another way "
                         "(gift card, another account).", {})
    except Exception as e:  # noqa: BLE001
        _warn("amazon_match", e)


def from_undated(con, today):
    try:
        import action_items as ai
        rows = ai.recurring_rows(con, today)
    except Exception as e:  # noqa: BLE001
        _warn("recurring_rows", e)
        return
    for r in rows:
        if r["status"] != "needs a date":
            continue
        who = f" ({r['who']})" if r.get("who") and str(r["who"]).lower() not in HOUSE else ""
        yield _p(f"undated:{r['id']}", "undated", "question", f"When was {r['name']}{who} last done?",
                 "Then the next one is scheduled from that date.", {"item_id": r["id"]}, ("recurring_items", r["id"]))


def from_profile(con, today):
    try:
        import profile_gaps
        yield from profile_gaps.produce(con, today)
    except Exception as e:  # noqa: BLE001
        _warn("profile_gaps", e)


def from_bank_sync(con, today):
    """One item while the last SimpleFIN pull failed (data/bank_sync.py); it expires by itself after a good pull."""
    try:
        import bank_sync
        if not bank_sync.configured():
            return
        s = bank_sync.status(today)
    except Exception as e:  # noqa: BLE001
        _warn("bank_sync", e)
        return
    if not s["error"]:
        return
    when = (s["last_pull"] or "")[:16].replace("T", " ")
    yield _p("bank_sync:failed", "bank_sync", "decision", "Bank sync did not work",
             f"Last try {when}: {s['error']} It is tried again tomorrow morning; Settings > Connections > Bank sync has "
             "\"Pull now\" and the account list.", {})


def from_bank_dupes(con, today):
    """A bank-sync row that still has a statement row of the same amount within 3 days (import_statement.plan could
    not tell which one it is). One item per bank-sync row; it expires when either row is gone."""
    try:
        import import_statement as im
        found = im.possible_duplicates(con)
    except Exception as e:  # noqa: BLE001 (older database without bank sync)
        _warn("bank_dupes", e)
        return
    for d in found:
        n = len(d["twins"])
        yield _p(f"bank_dupe:{d['id']}", "bank_dupe", "decision",
                 f"Possible duplicate: {money(d['amount'])} on {d['date']} ({d['account']})",
                 f"Bank sync brought in \"{d['description'][:60]}\", and a statement already has "
                 + ("a row" if n == 1 else f"{n} rows") + " of the same amount within 3 days. Remove the bank-sync copy "
                 "if it is the same payment.", {"txn_id": d["id"]}, ("transactions", d["id"]))


def from_calendar_days(con, today):
    """Days waiting for review (calendar_days status 'proposed'): one item per tradition and year (the yearly AI
    look-up, traditions.py) and one per school calendar paper (doc_extract). Accepting puts them on the calendar."""
    if not _has_table(con, "calendar_days"):
        return
    groups = {}
    for rid, day, end, kind, name, member, source, label, doc in con.execute(
            "SELECT id, day, end_day, kind, name, member, source, label, document_id FROM calendar_days "
            "WHERE status='proposed' ORDER BY day, name"):
        key = (source, label or "", doc or 0, day[:4] if source == "tradition" else "")
        groups.setdefault(key, []).append((rid, day, end, kind, name, member))
    for (source, label, doc, year), rows in groups.items():
        lines = []
        for _rid, day, end, kind, name, member in rows[:12]:
            d = dt.date.fromisoformat(day)
            when = f"{d:%b} {d.day}" + (f" to {dt.date.fromisoformat(end):%b} {dt.date.fromisoformat(end).day}" if end else "")
            what = {"closure": " (no school)", "early": " (early dismissal)"}.get(kind, "")
            lines.append(f"{when}: {name}{what}" + (f" ({member})" if member else ""))
        more = f"; and {len(rows) - 12} more" if len(rows) > 12 else ""
        n = len(rows)
        if source == "tradition":
            summary = f"{n} date{'s' if n != 1 else ''} for {label}, {year}: add to the calendar?"
            note = (" Found by your AI from the tradition's name only. Lunar and regional dates can differ by a day; "
                    "check with your community and fix any day in Family > People > Holidays and dates.")
        elif not doc and label:  # imported from a link or file for a linked school, college or employer
            summary = f"{n} day{'s' if n != 1 else ''} off from the {label} calendar: add them?"
            note = f" Read from the calendar of {label} you imported. Check them against it."
        else:
            summary = f"{n} day{'s' if n != 1 else ''} off or early from a school calendar: add them?"
            note = " Read from the school calendar paper you filed. Check them against the paper."
        yield _p(f"days:{source}:{label}:{doc}:{year}", "days", "decision", summary, "; ".join(lines) + more + "." + note,
                 {"ids": [r[0] for r in rows]}, ("calendar_days", rows[0][0]))


def from_calendar_back(con, today):
    """One item per Mitra Home event moved or deleted in Google Calendar (calendar_back.py). Nothing changes until an
    adult answers; the item expires when the change was answered elsewhere."""
    try:
        import calendar_back
        waiting = calendar_back.pending()
    except Exception as e:  # noqa: BLE001
        _warn("calendar_back", e)
        return
    for eid, ch in waiting.items():
        title = ch.get("title") or "An event"
        was = dt.date.fromisoformat(ch["was"]) if ch.get("was") else None
        if ch.get("change") == "moved":
            new = dt.date.fromisoformat(ch["date"])
            summary = f"Moved in Google Calendar: {title}, {was:%b} {was.day} to {new:%b} {new.day}"
            cal = brand.CALENDAR_NAME
            detail = (f"Someone moved it on the {cal} calendar in Google. Use the new date here too, or keep ours "
                      "(Google gets it back at the next sync)." if calendar_back.can_move(ch) else
                      f"Someone moved it on the {cal} calendar in Google. This kind of date is changed where it is "
                      "kept (Family or Money); Keep ours puts it back in Google.")
        else:
            summary = f"Deleted in Google Calendar: {title}" + (f", {was:%b} {was.day}" if was else "")
            detail = (f"Someone deleted it from the {brand.CALENDAR_NAME} calendar in Google. Take it off Today and the "
                      "calendar too, or put it back in Google at the next sync.")
        ref = ch.get("ref") or [None, None]
        yield _p(f"calendar_back:{eid}", "calendar_back", "decision", summary, detail,
                 {"eid": eid, "change": ch.get("change"), "movable": calendar_back.can_move(ch)}, (ref[0], ref[1]))


def from_member_info(con, today):
    """One item per person with critical facts (emergency, medical, school) not confirmed for the review age
    (member_info.py). Names the kinds of fact, never the values. 'All still correct' confirms them."""
    try:
        import member_info
        found = member_info.stale(con, today)
    except Exception as e:  # noqa: BLE001
        _warn("member_info", e)
        return
    title = dict(member_info.CATEGORIES)
    for member, rows in found.items():
        kinds = ", ".join(sorted({title[c].lower() for _i, c, _l in rows}))
        n = len(rows)
        yield _p(f"info_review:{member}", "info_review", "decision",
                 f"Check {member}'s critical info: {n} fact{'s' if n != 1 else ''} not confirmed in "
                 f"{member_info.review_months()} months",
                 f"Covers {kinds}. If something changed, edit it in Family > People > Critical info; otherwise confirm it.",
                 {"ids": [r[0] for r in rows], "member": member}, ("member_info", rows[0][0]))


def from_update(con, today):
    """One item while the daily look (update_notice.py) knows a release newer than this install. It expires by itself
    after the update; a release newer still is a new item."""
    try:
        import update_notice
        a = update_notice.available()
    except Exception as e:  # noqa: BLE001
        _warn("update_notice", e)
        return
    if not a:
        return
    import brand
    notes = f"What is new: {a['notes']} " if a["notes"] else ""
    if a.get("source") == "site":  # found on the public site: it can be downloaded, not installed from here
        yield _p(f"update:{a['version']}", "update", "decision", f"{brand.PRODUCT} {a['version']} is available",
                 notes + f"Download the new installer from the {brand.PRODUCT} site and run it over this one: your data is kept.",
                 {"version": a["version"], "source": "site", "fix_link": {"href": a["url"], "label": "Open the download page"}})
        return
    yield _p(f"update:{a['version']}", "update", "decision", f"{brand.PRODUCT} {a['version']} is available",
             notes + "Update now uses the same signed update as Settings > Data > Updates: your data is not touched and "
             "the database is backed up first. Start the app again afterwards.", {"version": a["version"]})


def from_audit(con, today):
    """Findings of the newest data check (data/audit.py) that a person can fix: charges entered twice, a bill listed
    twice, a bill still open a month after its due date. They expire when the next check no longer finds them."""
    if not _has_table(con, "audit_findings"):
        return
    run = con.execute("SELECT MAX(id) FROM audit_runs WHERE finished_at IS NOT NULL").fetchone()[0]
    if not run:
        return
    for key, summary, detail, payload, rt, rid in con.execute(
            "SELECT dedupe_key, summary, detail, payload, ref_table, ref_id FROM audit_findings "
            "WHERE run_id=? AND level IN ('money', 'decide') AND payload IS NOT NULL ORDER BY id", (run,)):
        pl = json.loads(payload or "{}")
        if pl.get("fix") not in AUDIT_OPTIONS:
            continue
        why = {"dupe_txn": " Remove the extra copies keeps the first one (its receipt and category stay with it).",
               "dupe_bill": " Remove the extra copies keeps one (the paid one if there is one).",
               "late_bill": " Mark it paid with the day you paid it, or leave it if it is still to pay."}[pl["fix"]]
        yield _p(f"audit:{key}", "audit", "decision", summary,
                 (detail + "." if detail else "") + why + " Found by the data check; Settings > Data > Data check can undo a fix.",
                 pl, (rt, rid))


PRODUCERS = (from_review, from_recurring, from_statements, from_price_rises, from_price_spikes, from_renewals, from_amazon,
             from_undated, from_profile, from_bank_sync, from_bank_dupes, from_calendar_days, from_member_info, from_update,
             from_audit, from_calendar_back)


def _warn(where, e):
    try:
        log.get("proposals").warning("%s failed: %s", where, type(e).__name__)
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ sync
def sync(con=None, today=None):
    """Refresh the queue. Returns counts: added, reopened, refreshed, expired, open."""
    today = today or dates.today()
    own = con is None
    con = con or _con()
    try:
        found = {}
        for prod in PRODUCERS:
            for p in prod(con, today):
                found.setdefault(p["dedupe_key"], p)
        have = {r[0]: r[1:] for r in con.execute(
            "SELECT dedupe_key, id, status, until, summary, detail, payload FROM proposals")}
        out = {"added": 0, "reopened": 0, "refreshed": 0, "expired": 0}
        now = _now()
        cols = ("source", "kind", "summary", "detail", "payload", "ref_table", "ref_id")
        with con:
            for k, p in found.items():
                if k not in have:
                    con.execute("INSERT INTO proposals(dedupe_key, source, kind, summary, detail, payload, ref_table, ref_id, "
                                "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)", (k, *[p[c] for c in cols], now, now))
                    out["added"] += 1
                    continue
                pid, status, until, summary, detail, payload = have[k]
                if status in ("done", "dismissed"):
                    continue
                new = status
                if status == "expired" or (status == "snoozed" and (not until or until <= today.isoformat())):
                    new = "open"
                    out["reopened"] += 1
                elif (summary, detail, payload) == (p["summary"], p["detail"], p["payload"]):
                    continue  # nothing changed: no write, so the database (and the dashboard's cache) stays as it is
                else:
                    out["refreshed"] += 1
                con.execute("UPDATE proposals SET summary=?, detail=?, payload=?, status=?, until=CASE WHEN ?='open' THEN NULL "
                            "ELSE until END, updated_at=? WHERE id=?", (p["summary"], p["detail"], p["payload"], new, new, now, pid))
            for k, (pid, status, *_) in have.items():
                if status in LIVE and k not in found:
                    con.execute("UPDATE proposals SET status='expired', updated_at=? WHERE id=?", (now, pid))
                    out["expired"] += 1
        out["open"] = con.execute("SELECT COUNT(*) FROM proposals WHERE status='open'").fetchone()[0]
        return out
    finally:
        if own:
            con.close()


# ------------------------------------------------------------------ reading
def _row(r):
    d = dict(r)
    d["payload"] = json.loads(d.get("payload") or "{}")
    opts = dict(OPTIONS.get(d["source"], {}))
    if d["source"] == "recurring":  # only offer what the detectors can actually do for this payee
        if not d["payload"].get("bill_ok"):
            opts.pop("bill", None)
            opts["ignore"] = "Ignore"
        if not d["payload"].get("sub_ok"):
            opts.pop("subscription", None)
    if d["source"] == "review":  # "Add the account" only for a statement whose account is missing
        l4 = d["payload"].get("last4s") or []
        if not l4:
            opts.pop("account", None)
        else:
            opts["account"] = f"Add the account ending {' or '.join(l4)}"
        if not d["payload"].get("statement_ok"):
            opts.pop("statement", None)
        if not d["payload"].get("jobs"):
            opts.pop("job", None)
    if d["source"] == "update" and d["payload"].get("source") == "site":
        opts = {"later": OPTIONS["update"]["later"]}
    if d["source"] == "audit":
        keep = AUDIT_OPTIONS.get(d["payload"].get("fix"), ("keep", "later"))
        opts = {k: v for k, v in opts.items() if k in keep}
    if d["source"] == "calendar_back":
        if d["payload"].get("change") == "deleted":
            opts = {"hide": "Take it off Today and the calendar", "keep": "Put it back in Google"}
        elif d["payload"].get("movable"):
            opts = {"accept": "Use the new date", "keep": "Keep ours"}
        else:
            opts = {"keep": "Keep ours"}
    if d["source"] == "profile":
        import profile_gaps
        opts = dict(profile_gaps.OPTIONS.get(d["payload"].get("gap"), opts))
    d["options"] = opts
    return d


def items(con, kind=None, statuses=("open",)):
    old, con.row_factory = con.row_factory, sqlite3.Row
    try:
        sql = f"SELECT * FROM proposals WHERE status IN ({','.join('?' * len(statuses))})"
        args = list(statuses)
        if kind:
            sql += " AND kind=?"
            args.append(kind)
        order = "CASE kind WHEN 'file' THEN 0 WHEN 'decision' THEN 1 ELSE 2 END, id"
        return [_row(r) for r in con.execute(f"{sql} ORDER BY {order}", args)]
    finally:
        con.row_factory = old


def counts(con):
    out = {k: 0 for k in KINDS}
    for k, n in con.execute("SELECT kind, COUNT(*) FROM proposals WHERE status='open' GROUP BY kind"):
        out[k] = n
    out["all"] = sum(out[k] for k in KINDS)
    return out


def get(con, pid):
    old, con.row_factory = con.row_factory, sqlite3.Row
    try:
        r = con.execute("SELECT * FROM proposals WHERE id=?", (int(pid),)).fetchone()
        return _row(r) if r else None
    finally:
        con.row_factory = old


# ------------------------------------------------------------------ deciding
def _set(pid, status, outcome, actor, until=None):
    con = _con()
    try:
        with con:
            con.execute("UPDATE proposals SET status=?, outcome=?, until=?, decided_by=?, decided_at=?, updated_at=? WHERE id=?",
                        (status, outcome, until, (actor or {}).get("name") or "-", _now(), _now(), pid))
    finally:
        con.close()


def _handle(p, option, answer, actor, today):
    """Run the fixed handler for (source, option). Returns (ok, message, new_status, until)."""
    import edit_actions as ea
    src, pl = p["source"], p["payload"]
    if src == "review":
        if option == "retry":
            ok, msg = ea.review_retry(actor, pl["review_id"])
            return ok, msg, "done", None
        if option == "job":
            ok, msg = ea.review_timesheet_job(actor, pl["review_id"], answer.get("contract"), answer.get("phrase") or None)
            return ok, msg, "done", None
        if option == "statement":
            ok, msg = ea.review_import_statement(actor, pl["review_id"], answer.get("account"), answer.get("read_as") or None,
                                                 str(answer.get("force") or "") in ("1", "on", "true"))
            return ok, msg, "done", None
        if option == "account":
            last4 = str(answer.get("last4") or "").strip()
            if last4 not in (pl.get("last4s") or []):
                return False, "Pick one of the account endings printed on the statement.", None, None
            ok, msg = ea.review_add_account(actor, pl["review_id"], answer.get("name"), answer.get("type"), last4)
            return ok, msg, "done", None
        if option == "file":
            ok, msg = ea.review_file(actor, pl["review_id"], answer.get("type"), answer.get("vendor"), answer.get("date"),
                                     answer.get("amount"), answer.get("due"))
            return ok, msg, "done", None
        ok, msg = ea.review_dismiss(actor, pl["review_id"])
        return ok, msg, "dismissed", None
    if src == "recurring":
        if option == "bill":
            ok, msg = ea.recurring_confirm(actor, pl["payee"], answer.get("name"))
            return ok, msg, "done", None
        if option == "subscription":
            ok, msg = ea.subscription_accept(actor, pl["payee"])
            return ok, msg, "done", None
        if pl.get("bill_ok"):
            ok, msg = ea.recurring_dismiss(actor, pl["payee"])
            return ok, ("Got it. " + pl["payee"] + " will not be suggested again.") if ok else msg, "dismissed", None
        return True, "Got it. It will not be suggested again.", "dismissed", None
    if src in ("statement", "renewal", "amazon", "bank_sync"):  # no record changes: only the queue entry is settled
        if option == "later":
            days = LATER_DAYS[src]
            word = "a week" if days == 7 else "two weeks"
            return True, f"I will remind you in {word}.", "snoozed", (today + dt.timedelta(days=days)).isoformat()
        if option == "reviewed":
            return True, "Noted.", "done", None
        return True, "Dismissed.", "dismissed", None
    if src == "price_rise":
        return True, "Noted.", "done" if option == "ok" else "dismissed", None
    if src == "audit":
        if option == "later":
            return True, "I will remind you in a week.", "snoozed", (today + dt.timedelta(days=LATER_DAYS[src])).isoformat()
        if option == "keep":
            return True, "Left as it is; the data check will not ask again.", "dismissed", None
        if option == "paid":
            ok, msg = ea.bill_paid(actor, pl["bill_id"], answer.get("date"))
            return ok, msg, "done", None
        ok, msg = ea.audit_remove_copies(actor, pl.get("fix"), pl.get("ids") or [], p["dedupe_key"])
        return ok, msg, "done", None
    if src == "bank_dupe":
        if option == "remove":
            ok, msg = ea.bank_copy_remove(actor, pl["txn_id"])
            return ok, msg, "done", None
        return True, "Both kept.", "done", None
    if src == "undated":
        if option == "date":
            ok, msg = ea.recurring_done(actor, pl["item_id"], answer.get("date"), answer.get("provider"))
            return ok, msg, "done", None
        if option == "not_sure":
            return True, "No problem. I will ask again in a month.", "snoozed", (today + dt.timedelta(days=30)).isoformat()
        ok, msg = ea.recurring_stop(actor, pl["item_id"])
        return ok, msg, "done", None
    if src == "profile":
        return _profile(pl, option, answer, actor, today)
    if src == "calendar_back":
        import calendar_back
        eid = pl.get("eid")
        if option == "accept":
            t = calendar_back.target(eid)
            if not t:
                return False, "That kind of date is changed where it is kept, not from the calendar.", None, None
            table, rid, day = t
            ok, msg = {"bills": lambda: ea.bill_move(actor, rid, day),
                       "appointments": lambda: ea.appointment_move(actor, rid, day),
                       "events": lambda: ea.event_move(actor, rid, day),
                       "life_items": lambda: ea.life_update(actor, rid, due=day)}[table]()
            if not ok:
                return False, msg, None, None
            calendar_back.settle(eid, "accept", actor)
            return True, msg, "done", None
        ok, msg = calendar_back.settle(eid, option, actor)
        return ok, msg, "done" if ok else None, None
    if src == "days":
        if option == "later":
            return True, "I will remind you in a week.", "snoozed", (today + dt.timedelta(days=LATER_DAYS[src])).isoformat()
        ok, msg = ea.calendar_days_decide(actor, pl.get("ids") or [], option == "accept")
        return ok, msg, "done" if option == "accept" else "dismissed", None
    if src == "info_review":
        if option == "later":
            return True, "I will remind you in a week.", "snoozed", (today + dt.timedelta(days=LATER_DAYS[src])).isoformat()
        ok, msg = ea.member_info_verify(actor, pl.get("ids") or [])
        return ok, msg, "done", None
    if src == "update":
        if option == "later":
            return True, "I will remind you in a week.", "snoozed", (today + dt.timedelta(days=LATER_DAYS[src])).isoformat()
        import maintenance_data
        ok, msg = maintenance_data.update(actor)  # the Settings > Data > Updates path: admin_actions.update_now, adults
        return ok, msg, "done" if ok else None, None
    return False, "I do not know how to handle that item.", None, None


def _profile(pl, option, answer, actor, today):
    import edit_actions as ea
    import profile_gaps
    later = (today + dt.timedelta(days=profile_gaps.LATER_DAYS)).isoformat()
    if option == "later":
        return True, "OK, I will ask again in two weeks.", "snoozed", later
    if option == "dismiss":
        return True, "OK, I will not ask about that again.", "dismissed", None
    if option == "birthday":
        try:
            d = dt.date.fromisoformat(str(answer.get("date"))[:10])
        except ValueError:
            return False, "Pick the birthday.", None, None
        ok, msg = ea.member_update(actor, pl.get("member"), birthday=f"{d:%m-%d}", year=d.year if d.year < today.year else None)
        return ok, msg, "done", None
    if option in ("own", "rent"):
        ok, msg = ea.household_set(actor, "tenure", option)
        return ok, msg, "done", None
    if option == "papers":
        return True, "Drop its registration or insurance card in the Inbox; I will ask again in two weeks if no car shows up.",             "snoozed", later
    return False, "I do not know how to handle that item.", None, None


def decide(actor, pid, option, today=None, **answer):
    """A person chose `option` on proposal `pid`. Returns (ok, message). Adults only; the record change (if any) goes
    through edit_actions, which validates and logs it."""
    today = today or dates.today()
    if (actor or {}).get("role") != "adult":
        return False, "Only an adult can decide this."
    con = _con()
    try:
        p = get(con, pid)
    finally:
        con.close()
    if not p or p["status"] not in LIVE:
        return False, "That item is already handled."
    if option not in p["options"]:
        return False, "That choice is not available for this item."
    missing = [f for f in NEEDS.get((p["source"], option), ()) if not str(answer.get(f) or "").strip()]
    if missing:
        return False, "Please fill in: " + ", ".join(missing) + "."
    ok, msg, status, until = _handle(p, option, answer, actor, today)
    if ok and status:
        _set(p["id"], status, option, actor, until)
        _audit(actor, p, option)
    return ok, msg


def restore(actor, pid):
    if (actor or {}).get("role") != "adult":
        return False, "Only an adult can do this."
    con = _con()
    try:
        with con:
            cur = con.execute("UPDATE proposals SET status='open', until=NULL, outcome=NULL, updated_at=? "
                              "WHERE id=? AND status IN ('dismissed', 'snoozed')", (_now(), int(pid)))
    finally:
        con.close()
    if cur.rowcount != 1:
        return False, "Only dismissed or snoozed items can come back."
    _audit(actor, {"id": pid, "source": "-"}, "restore")
    return True, "It is back in the Inbox."


def _audit(actor, p, option):
    import edit_actions as ea
    ea._log(actor, "proposal", f"id={p['id']} source={p['source']} option={option}")


# ------------------------------------------------------------------ CLI
def main(argv=None):
    ap = argparse.ArgumentParser(description="The Inbox queue: files, decisions and questions.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync")
    ls = sub.add_parser("list")
    ls.add_argument("--all", action="store_true")
    dc = sub.add_parser("decide")
    dc.add_argument("id", type=int)
    dc.add_argument("option")
    for f in ("date", "name", "type", "vendor", "amount", "due", "provider"):
        dc.add_argument(f"--{f}")
    rs = sub.add_parser("restore")
    rs.add_argument("id", type=int)
    a = ap.parse_args(argv)
    adult = {"name": "terminal", "role": "adult"}
    if a.cmd == "sync":
        r = sync()
        print(f"{r['open']} open ({r['added']} new, {r['reopened']} back, {r['expired']} handled elsewhere)")
        return 0
    if a.cmd == "list":
        con = _con()
        try:
            rows = items(con, statuses=("open", "snoozed", "done", "dismissed", "expired") if a.all else ("open",))
        finally:
            con.close()
        for r in rows:
            print(f"{r['id']:>4} {r['kind']:8} {r['status']:9} {r['summary']}")
            print(f"     options: {', '.join(f'{k} ({v})' for k, v in r['options'].items())}")
        if not rows:
            print("Nothing waiting.")
        return 0
    if a.cmd == "decide":
        answer = {f: getattr(a, f) for f in ("date", "name", "type", "vendor", "amount", "due", "provider") if getattr(a, f)}
        ok, msg = decide(adult, a.id, a.option, **answer)
    else:
        ok, msg = restore(adult, a.id)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
