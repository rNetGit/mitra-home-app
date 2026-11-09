"""Bank sync through SimpleFIN Bridge (opt-in, adults, this PC only, standard library only).

  python data/bank_sync.py setup TOKEN   claim a SimpleFIN setup token once; the access URL goes to config/secrets.env
  python data/bank_sync.py pull          accounts, balances and new transactions since the last pull (first time: 45 days)
  python data/bank_sync.py status        last pull, accounts, the last error; never the secret
  python data/bank_sync.py forget        remove the access URL and the SimpleFIN ids from `accounts`
  python data/bank_sync.py dedupe [--yes]  bank-sync rows that repeat a statement row: list them (--yes: remove the
                                         bank-sync copies after a database snapshot)

The family makes a SimpleFIN Bridge account themselves (about $1.50 a month, paid by the family), connects their banks
there and gets a one-time setup token. `setup` turns that token into the access URL (a URL that carries its own
username and password, so it is a bearer secret: write-only in `config/secrets.env` as SIMPLEFIN_ACCESS_URL, never
shown, logged or returned by any function here). Every later call is one read-only HTTPS GET of `/accounts` on that
URL: nothing is written at the bank, nothing but that request leaves this PC (docs/BANK_SYNC.md).

Each SimpleFIN account maps to one `accounts` row (`accounts.simplefin_id`, migration 047), found by that id, else by
last4 + name, else created, and only for the accounts the family ticked (`config/bank_sync.json` `chosen`). New
transactions go through the same dedupe as a statement import (`import_statement.plan` with `bank=True`: the ref is
`sfin:` + SimpleFIN's transaction id; days already covered by a statement of that account are skipped, and a row with
exactly one statement row of the same amount within 3 days is that row), then the usual after-import steps: `apply_rules`, receipt matching, recurring bills, the Inbox queue.
Balances become `account_balances` rows of kind `snapshot`. A failed pull is written to the state file (one line, the
secret scrubbed) and becomes one Inbox item (proposals source `bank_sync`); nothing is retried before the next day.
"""
import base64
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import brand  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import money  # noqa: E402

NAME = "SIMPLEFIN_ACCESS_URL"
REF = "sfin:"           # `transactions.ref` prefix of bank-sync rows (import_statement.BANK_REF)
STATE = paths.CONFIG / "bank_sync.json"
DAYS_BACK = 45          # the furthest back a pull asks (SimpleFIN recommends 45 days; older days come from statements)
OVERLAP_DAYS = 3        # later pulls start a little before the last good one; the dedupe drops the repeats
STALE_DAYS = 3          # health check: last good pull older than this = warn
TIMEOUT = 60
MAX_BODY = 20_000_000
KINDS = (("credit", ("credit", "card", "visa", "mastercard", "amex", "discover")),
         ("loan", ("loan", "mortgage")),
         ("investment", ("401", "ira", "broker", "invest", "roth", "529")),
         ("savings", ("saving",)))
_TRAIL = re.compile(r"[\s(\[.*xX#-]*(\d{4})[)\]]?\s*$")   # a masked number at the end of the name: "...", "(", "x" + four digits


class BankError(Exception):
    pass


# ---------------------------------------------------------------- secret (write-only) and state
def _secret(name):
    import os
    if os.environ.get(name):
        return os.environ[name].strip()
    f = paths.CONFIG / "secrets.env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def access_url():
    return _secret(NAME)


def configured():
    return bool(access_url())


def state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    except (OSError, ValueError):
        return {}


def _save(st):
    config.write_json(STATE, st)


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def scrub(text):
    """A message with the access URL, its password or its username taken out (for logs, state and the app)."""
    text = str(text)
    url = access_url()
    if url:
        text = text.replace(url, "[access url]")
        u = urllib.parse.urlsplit(url)
        for part in (u.password, u.username):
            if part and len(part) >= 4:
                text = text.replace(part, "…")
    return text


# ---------------------------------------------------------------- HTTP (urllib; tests replace urlopen)
def _request(method, url, auth=None, body=None):
    """-> (status, text). `auth` = (user, password) for Basic auth; the URL itself never carries them."""
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("User-Agent", brand.PRODUCT + " bank sync")
    req.add_header("Accept", "application/json, text/plain")
    if auth:
        tok = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
        req.add_header("Authorization", "Basic " + tok)
    if body is not None:
        req.add_header("Content-Length", str(len(body)))
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:  # noqa: S310 (https only, checked by the callers)
            return r.status, r.read(MAX_BODY).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise BankError(scrub(f"SimpleFIN answered {e.code} {str(e.reason)[:80]}").strip()) from None
    except urllib.error.URLError as e:
        raise BankError(f"SimpleFIN could not be reached ({scrub(e.reason)})") from None
    except (OSError, TimeoutError) as e:
        raise BankError(f"SimpleFIN could not be reached ({scrub(e)})") from None


def _split(url):
    """access URL -> (clean https URL without the user info, user, password)."""
    u = urllib.parse.urlsplit(url)
    if u.scheme != "https" or not u.hostname or not u.username or u.password is None:
        raise BankError("The saved SimpleFIN access URL is not usable. Forget it and set it up again.")
    host = u.hostname + (f":{u.port}" if u.port else "")
    clean = urllib.parse.urlunsplit((u.scheme, host, u.path.rstrip("/"), "", ""))
    return clean, urllib.parse.unquote(u.username), urllib.parse.unquote(u.password)


def claim(token):
    """Turn a one-time setup token into the access URL (one POST to the claim URL inside the token). -> access URL."""
    token = (token or "").strip()
    if not token:
        raise BankError("Paste the setup token from SimpleFIN Bridge.")
    try:
        claim_url = base64.b64decode(token + "=" * (-len(token) % 4), validate=False).decode("utf-8").strip()
    except (ValueError, UnicodeDecodeError):
        raise BankError("That is not a SimpleFIN setup token.") from None
    if not claim_url.startswith("https://") or any(c.isspace() for c in claim_url):
        raise BankError("That is not a SimpleFIN setup token.")
    status, text = _request("POST", claim_url, body=b"")
    url = text.strip()
    if status != 200 or not url.startswith("https://"):
        raise BankError("SimpleFIN did not accept the setup token (a token works once; make a new one).")
    _split(url)  # must carry a username and a password
    return url


def fetch(start=None, balances_only=False):
    """GET /accounts. -> the decoded JSON {accounts: [...], errors: [...]}. start = date (transactions from then on)."""
    url = access_url()
    if not url:
        raise BankError("Bank sync is not set up.")
    clean, user, pw = _split(url)
    q = {}
    if start is not None:
        q["start-date"] = str(int(dt.datetime.combine(start, dt.time()).timestamp()))
    if balances_only:
        q["balances-only"] = "1"
    status, text = _request("GET", clean + "/accounts" + ("?" + urllib.parse.urlencode(q) if q else ""), auth=(user, pw))
    try:
        data = json.loads(text)
    except ValueError:
        raise BankError("SimpleFIN sent something that is not JSON.") from None
    if not isinstance(data, dict) or not isinstance(data.get("accounts"), list):
        raise BankError("SimpleFIN sent an answer without accounts.")
    data["errors"] = [scrub(e) for e in (data.get("errors") or []) if isinstance(e, str)]
    if not data["accounts"] and data["errors"]:
        raise BankError("; ".join(data["errors"])[:300])
    return data


# ---------------------------------------------------------------- accounts
def split_name(raw):
    """'Everyday Checking ...1234' -> ('Everyday Checking', '1234'); no digits at the end -> (name, '')."""
    raw = re.sub(r"\s+", " ", str(raw or "")).strip()
    m = _TRAIL.search(raw)
    if m and len(raw) - len(m.group(0)) >= 2:
        return raw[:m.start()].strip(), m.group(1)
    return raw, ""


def kind_of(name):
    low = name.lower()
    for kind, words in KINDS:
        if any(w in low for w in words):
            return kind
    return "checking"


def _summary(acc):
    org = acc.get("org") or {}
    name, last4 = split_name(acc.get("name") or "")
    return {"id": str(acc.get("id") or ""), "name": name or "Account", "last4": last4,
            "org": str(org.get("name") or org.get("domain") or ""), "currency": str(acc.get("currency") or "USD")[:8]}


def _remember_accounts(st, data):
    """The bridge's account list in the state file (name, last4, bank; chosen flag kept)."""
    had = st.get("accounts") or {}
    st["accounts"] = {}
    for acc in data["accounts"]:
        s = _summary(acc)
        if not s["id"]:
            continue
        st["accounts"][s["id"]] = {**s, "chosen": bool((had.get(s["id"]) or {}).get("chosen"))}
    return st


def map_account(con, summary, live_ids=None):
    """The `accounts` row for a SimpleFIN account: by simplefin_id, else one row with the same last4 (and a name that
    matches when several share it), else a new row. -> account dict as import_statement.find_account returns.
    `live_ids` = every account id the bridge sent in this answer: a row linked to an id that is NOT among them has a
    stale link (the family signed in to the bank again at SimpleFIN, which gives its accounts new ids) and is taken
    over like an unlinked one, so a re-link keeps the history on one account instead of adding an empty copy."""
    sid = summary["id"]
    row = con.execute("SELECT id, name, type, last4 FROM accounts WHERE simplefin_id=?", (sid,)).fetchone()
    if row is None and summary["last4"]:
        rows = [r for r in con.execute("SELECT id, name, type, last4, simplefin_id FROM accounts WHERE last4=?",
                                       (summary["last4"],)).fetchall()
                if r[4] is None or (live_ids is not None and r[4] not in live_ids)]
        rows = [r[:4] for r in rows]
        if len(rows) > 1:
            low = summary["name"].lower()
            rows = [r for r in rows if r[1].lower() == low or low in r[1].lower() or r[1].lower() in low]
        if len(rows) == 1:
            row = rows[0]
    if row is None:
        low = summary["name"].lower()
        rows = con.execute("SELECT id, name, type, last4 FROM accounts WHERE lower(name)=? AND simplefin_id IS NULL "
                           "AND COALESCE(last4, '')=''", (low,)).fetchall()
        if len(rows) == 1:
            row = rows[0]
    if row is None:
        cur = con.execute("INSERT INTO accounts(name, type, last4, currency, simplefin_id) VALUES (?,?,?,?,?)",
                          (summary["name"], kind_of(summary["name"]), summary["last4"] or None, summary["currency"], sid))
        row = (cur.lastrowid, summary["name"], kind_of(summary["name"]), summary["last4"])
    else:
        con.execute("UPDATE accounts SET simplefin_id=? WHERE id=?", (sid, row[0]))
    return {"id": row[0], "name": row[1], "type": row[2], "last4": row[3]}


def _parsed(acc):
    """SimpleFIN transactions -> the rows import_statement.plan expects (posted ones only; the id is the ref)."""
    out = []
    for t in acc.get("transactions") or []:
        if t.get("pending"):
            continue
        try:
            when = dt.datetime.fromtimestamp(int(t.get("posted") or t.get("transacted_at") or 0))
            amt = money.round2(float(money.parse(str(t.get("amount", "")))))
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        desc = re.sub(r"\s+", " ", str(t.get("description") or t.get("payee") or "")).strip()
        if not desc or not t.get("posted") and not t.get("transacted_at"):
            continue
        tid = str(t.get("id") or "")
        out.append({"date": when.date().isoformat(), "desc": desc[:200], "amount": amt, "ref": (REF + tid) if tid else None,
                    "cardholder": None, "category": None})
    return out


def _balance(con, acct, acc):
    try:
        bal = money.round2(float(money.parse(str(acc.get("balance", "")))))
        when = dt.datetime.fromtimestamp(int(acc.get("balance-date") or 0)).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return False
    if not acc.get("balance-date"):
        return False
    if acct["type"] in ("credit", "loan"):
        bal = abs(bal)  # account_balances keeps what is owed as a positive number
    con.execute("INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?,?,?,'snapshot') "
                "ON CONFLICT(account_id, as_of, kind) DO UPDATE SET balance=excluded.balance",
                (acct["id"], when.isoformat(), bal))
    return True


# ---------------------------------------------------------------- commands
def setup(token):
    """Claim the token, save the access URL (write-only), list the accounts. -> number of accounts seen."""
    url = claim(token)
    config.write_secret(NAME, url)
    st = state()
    st.pop("error", None)
    try:
        data = fetch(balances_only=True)
    except BankError as e:
        st["error"] = scrub(e)
        st["last_pull"] = _now()
        _save(st)
        raise
    _remember_accounts(st, data)
    st["set_up"] = _now()
    _save(st)
    return len(st["accounts"])


def choose(ids):
    """Tick the accounts to import (SimpleFIN ids from `status()`). -> number chosen."""
    st = state()
    want = {str(i) for i in ids}
    n = 0
    for sid, a in (st.get("accounts") or {}).items():
        a["chosen"] = sid in want
        n += a["chosen"]
    _save(st)
    return n


def _after_import(con, inserted):
    """What a statement import does afterwards. -> list of notes (a failed step is a note, not a failed pull)."""
    notes = []
    if inserted:
        r = subprocess.run([sys.executable, str(HERE / "apply_rules.py")], cwd=ROOT, capture_output=True, text=True)
        if r.returncode:
            notes.append("apply_rules: " + scrub(r.stderr[-200:]))
        try:
            import receipts
            receipts.match_after_import(con)
            con.commit()
        except Exception as e:  # noqa: BLE001 (matching is a convenience; the transactions are already in)
            notes.append(f"receipts: {type(e).__name__}")
        try:
            import recurring_bills
            recurring_bills.sync(con)
        except Exception as e:  # noqa: BLE001
            notes.append(f"recurring bills: {type(e).__name__}")
    try:
        import proposals
        proposals.sync(con)
    except Exception as e:  # noqa: BLE001
        notes.append(f"inbox queue: {type(e).__name__}")
    return notes


def pull(con=None, today=None):
    """One pull at a time, never during an update or restore (see _pull)."""
    import joblock
    try:
        with joblock.job("bank_sync"):
            return _pull(con, today)
    except joblock.Busy as e:
        raise BankError("An update or restore is running; pull again in a few minutes." if str(e) == joblock.MAINTENANCE
                        else "Another bank pull is running; its accounts arrive in a minute.") from None


def _pull(con=None, today=None):
    """One pull for the ticked accounts. -> report {accounts: [{name, last4, inserted, skipped}], inserted, skipped,
    warnings}. Raises BankError after writing the error to the state file."""
    today = today or dates.today()
    st = state()
    if not configured():
        raise BankError("Bank sync is not set up.")
    last_ok = st.get("last_ok")
    start = (dt.date.fromisoformat(last_ok[:10]) - dt.timedelta(days=OVERLAP_DAYS)) if last_ok else today - dt.timedelta(days=DAYS_BACK)
    start = max(start, today - dt.timedelta(days=DAYS_BACK))  # after a long gap too: the bridge warns past 45 days
    st["last_pull"] = _now()
    try:
        data = fetch(start=start)
    except BankError as e:
        st["error"] = scrub(e)
        _save(st)
        raise
    _remember_accounts(st, data)
    chosen = {sid for sid, a in st["accounts"].items() if a.get("chosen")}
    own = con is None
    con = con or db.connect()
    rep = {"accounts": [], "inserted": 0, "skipped": 0, "warnings": list(data["errors"])}
    try:
        import import_statement as im
        live_ids = {a.get("id") for a in data["accounts"]}
        for acc in data["accounts"]:
            s = _summary(acc)
            if s["id"] not in chosen:
                continue
            acct = map_account(con, s, live_ids)
            new, skipped = im.plan(con, _parsed(acc), acct, 1, bank=True)
            for p in new:
                con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, document_id, txn_type, ref, cardholder) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            (acct["id"], p["date"], p["desc"], p["amount"], p["category"], None, p["txn_type"], p["ref"], p["cardholder"]))
            _balance(con, acct, acc)
            st["accounts"][s["id"]]["account_id"] = acct["id"]
            rep["accounts"].append({"name": acct["name"], "last4": acct["last4"] or "", "inserted": len(new), "skipped": skipped})
            rep["inserted"] += len(new)
            rep["skipped"] += skipped
        con.commit()
        rep["warnings"] += _after_import(con, rep["inserted"])
    except BankError:
        raise
    except Exception as e:  # noqa: BLE001 (a database problem is reported like a network one: state + Inbox item)
        con.rollback()
        st["error"] = scrub(f"{type(e).__name__}: {e}")[:300]
        _save(st)
        raise BankError(st["error"]) from e
    finally:
        if own:
            con.close()
    st["last_ok"] = _now()
    st["error"] = ""
    st["last"] = {"inserted": rep["inserted"], "skipped": rep["skipped"], "warnings": rep["warnings"][:5]}
    _save(st)
    return rep


def status(today=None):
    """{configured, last_pull, last_ok, error, stale_days, last: {...}, accounts: [{id, name, last4, org, chosen}]}.
    Never the access URL."""
    today = today or dates.today()
    st = state()
    out = {"configured": configured(), "set_up": st.get("set_up") or "", "last_pull": st.get("last_pull") or "",
           "last_ok": st.get("last_ok") or "", "error": scrub(st.get("error") or ""), "last": st.get("last") or {},
           "accounts": [{"id": sid, "name": a.get("name", ""), "last4": a.get("last4", ""), "org": a.get("org", ""),
                         "chosen": bool(a.get("chosen"))} for sid, a in sorted((st.get("accounts") or {}).items(),
                                                                               key=lambda kv: (kv[1].get("org", ""), kv[1].get("name", "")))]}
    out["stale_days"] = (today - dt.date.fromisoformat(out["last_ok"][:10])).days if out["last_ok"] else None
    return out


def forget(con=None):
    """Remove the access URL and every SimpleFIN id; transactions and balances already imported stay."""
    config.write_secret(NAME, "")
    own = con is None
    con = con or db.connect()
    try:
        try:
            con.execute("UPDATE accounts SET simplefin_id=NULL WHERE simplefin_id IS NOT NULL")
            con.commit()
        except Exception as e:  # noqa: BLE001 (column not migrated yet: nothing to clear)
            if not db.missing(e):
                raise
    finally:
        if own:
            con.close()
    try:
        STATE.unlink()
    except OSError:
        pass


def remove_copy(con, txn_id):
    """Delete one bank-sync row that repeats a statement row; links (receipts, Amazon orders) and a category move to
    the statement row. -> the statement row's id, or None when `txn_id` is not such a row (nothing changed)."""
    import import_statement as im
    row = con.execute("SELECT account_id, ref, category FROM transactions WHERE id=?", (txn_id,)).fetchone()
    if not row or not str(row[1] or "").startswith(REF):
        return None
    hit = next((d for d in im.possible_duplicates(con, row[0]) if d["id"] == txn_id), None)
    if not hit:
        return None
    twin = hit["twins"][0]
    for table in ("receipts", "amazon_orders"):
        try:
            # the twin may have its own receipt (one per charge): those links are dropped, not moved
            con.execute(f"UPDATE OR IGNORE {table} SET transaction_id=? WHERE transaction_id=?", (twin, txn_id))
            con.execute(f"UPDATE {table} SET transaction_id=NULL WHERE transaction_id=?", (txn_id,))
        except Exception as e:  # noqa: BLE001 (pack table not there)
            if not db.missing(e):
                raise
    if row[2]:
        con.execute("UPDATE transactions SET category=? WHERE id=? AND (category IS NULL OR category='')", (row[2], twin))
    con.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    return twin


def dedupe(apply=False, con=None):
    """Bank-sync rows that repeat a statement row (one statement row used once). -> list of the possible duplicates;
    with `apply` the bank-sync copies are removed after a snapshot of the database (purge.snapshot)."""
    import import_statement as im
    own = con is None
    con = con or db.connect()
    try:
        found = im.possible_duplicates(con)
        if apply and found:
            import purge
            purge.snapshot("bank_dedupe")
            used = set()
            for d in found:
                free = [t for t in d["twins"] if t not in used]
                if not free:
                    d["removed"] = False
                    continue
                used.add(free[0])
                d["removed"] = remove_copy(con, d["id"]) is not None
            con.commit()
        return found
    finally:
        if own:
            con.close()


# ---------------------------------------------------------------- CLI
def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    cmd = a[0] if a else "status"
    try:
        if cmd == "setup":
            if len(a) < 2:
                raise BankError("usage: bank_sync.py setup TOKEN")
            n = setup(a[1])
            print(f"Bank sync set up; {n} account(s) at SimpleFIN. Tick the ones to import in Settings > Connections.")
        elif cmd == "pull":
            rep = pull()
            for r in rep["accounts"]:
                print(f"  {r['name']} x{r['last4'] or '----'}: {r['inserted']} new, {r['skipped']} already there")
            print(f"pulled: {rep['inserted']} new transaction(s), {rep['skipped']} already there"
                  + (f"; notes: {'; '.join(rep['warnings'])}" if rep["warnings"] else ""))
        elif cmd == "status":
            s = status()
            print("set up:", "yes" if s["configured"] else "no")
            print("last pull:", s["last_pull"] or "never", "| last good:", s["last_ok"] or "never")
            if s["error"]:
                print("last error:", s["error"])
            for acc in s["accounts"]:
                print(f"  [{'x' if acc['chosen'] else ' '}] {acc['org']} {acc['name']} x{acc['last4'] or '----'}")
        elif cmd == "dedupe":
            yes = "--yes" in a[1:]
            found = dedupe(apply=yes)
            for d in found:
                mark = (" removed" if d.get("removed") else " kept") if yes else ""
                print(f"  {d['date']} {d['account']}: {money.fmt(d['amount'])} {d['description'][:40]}"
                      f" (statement row {', '.join(map(str, d['twins']))}){mark}")
            n = sum(1 for d in found if d.get("removed"))
            print(f"{n} bank-sync copies removed (a snapshot of the database is in backups_pre_upgrade)." if yes else
                  f"{len(found)} possible duplicate(s). Run with --yes to remove the bank-sync copies.")
        elif cmd == "forget":
            forget()
            print("Bank sync forgotten: access URL removed, SimpleFIN ids cleared.")
        else:
            raise BankError("usage: bank_sync.py setup TOKEN | pull | status | dedupe [--yes] | forget")
    except BankError as e:
        print(scrub(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
