"""Import a bank or card statement export (CSV) into `transactions` with no AI: column mapping, not guessing.

  python data/import_statement.py detect FILE.csv                      show the header, the guessed mapping, first rows
  python data/import_statement.py FILE.csv --account chase|1234 [...]  import (add --dry-run first)
  python data/import_statement.py account --new "Name" --type checking --last4 1234   add an account, nothing else
  python data/import_statement.py formats                               saved formats (config/statement_formats.json)

Options
  --account NAME|LAST4        the `accounts` row (name, case-insensitive, or last4); --new "Name" --type checking|savings|credit
                              [--last4 NNNN] [--owner WHO] creates one first
  --map date=COL,desc=COL,amount=COL | debit=COL,credit=COL [,ref=COL,cardholder=COL,category=COL]
                              column names from the header (case-insensitive); omitted = guessed from common names
  --dates mdy|dmy|ymd         how slashed dates read (default mdy; UK/EU exports need dmy)
  --sign as-is|invert|auto    "as-is": negative = money out (bank exports). "invert": positive = charge (most card
                              exports). "auto" (default): invert for credit accounts whose rows are mostly positive.
  --format KEY / --save-format KEY   reuse / remember the mapping, dates and sign for this account
  --document-id N             link rows to a filed statement (documents.id)
  --balance X --as-of DATE    also record the closing balance (account_balances, cards: amount owed, positive)
  --no-rules                  skip `python data/apply_rules.py` afterwards
  --dry-run                   parse, dedupe and report; write nothing

Dedupe: on (account, ref) when the export has a reference column; otherwise by count of identical
(date, description, cents) rows already stored (two identical same-day charges are both real). Re-running is safe.
A row that bank sync already brought in (same cents, within 3 days, exactly one candidate) is skipped too.
Rows whose date or amount cannot be read stop the import (listed first); fix the mapping or the file, then rerun.
Payment credits on a card ("AUTOMATIC PAYMENT", "PAYMENT THANK YOU") are typed card_payment, not spend.
"""
import argparse
import collections
import csv
import io
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
import money  # noqa: E402
from dates import parse as _iso  # noqa: E402

ROOT = HERE.parent
FORMATS = paths.CONFIG / "statement_formats.json"
PAY = re.compile(r"AUTOMATIC PAYMENT|PAYMENT.{0,3}THANK YOU|ONLINE PAYMENT|AUTOPAY|PAYMENT RECEIVED|DIRECT DEBIT PAYMENT - THANK YOU", re.I)
SYNONYMS = {
    "date": ["transaction date", "trans date", "posting date", "posted date", "post date", "date posted", "date", "booking date", "value date"],
    "desc": ["description", "details", "transaction description", "narrative", "memo", "payee", "merchant", "name", "transaction", "particulars"],
    "amount": ["amount", "transaction amount", "amount (usd)", "amount (gbp)", "value", "amt"],
    "debit": ["debit", "debit amount", "withdrawal", "withdrawals", "money out", "paid out", "out", "charges", "dr"],
    "credit": ["credit", "credit amount", "deposit", "deposits", "money in", "paid in", "in", "payments", "cr"],
    "ref": ["reference", "reference number", "transaction id", "transaction reference", "ref", "id", "fitid", "check number", "cheque number"],
    "cardholder": ["card member", "cardholder", "card holder", "name on card", "card member name", "user"],
    "category": ["category", "type"],
}
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


class ImportError_(Exception):
    pass


# ---- reading the file

def read_rows(path):
    """(header, rows) from a CSV export: delimiter sniffed, BOM and preamble lines before the header skipped."""
    raw = pathlib.Path(path).read_text(encoding="utf-8-sig", errors="replace")
    lines = raw.splitlines()
    start = 0
    for i, line in enumerate(lines[:30]):  # exports often start with "Account: ..." lines; the header is the first line naming a date column
        low = line.lower()
        if any(k in low for k in ("date", "description", "amount", "narrative", "details")) and len(re.split(r"[,;\t|]", line)) >= 2:
            start = i
            break
    body = "\n".join(lines[start:])
    try:
        dialect = csv.Sniffer().sniff(body[:4000], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(body), dialect)
    header = [h.strip() for h in next(reader)]
    rows = [r for r in reader if any(c.strip() for c in r)]
    return header, rows


def guess_mapping(header):
    low = [h.strip().lower() for h in header]
    out = {}
    for field, names in SYNONYMS.items():
        for n in names:
            if n in low:
                out[field] = header[low.index(n)]
                break
        if field not in out:
            for i, h in enumerate(low):  # substring, e.g. "Transaction Date (UTC)"
                if any(n == h or (len(n) > 3 and n in h) for n in names):
                    out[field] = header[i]
                    break
    if "amount" in out:
        out.pop("debit", None)
        out.pop("credit", None)
    if out.get("category") and out["category"].lower() == "type" and "desc" in out and out["desc"].lower() == "type":
        out.pop("category")
    return out


def parse_map(spec):
    out = {}
    for part in (spec or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def parse_date(s, order="mdy"):
    s = str(s or "").strip()
    d = _iso(s)
    if d:
        return d
    import datetime as dt
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", s)
    if m:
        a, b, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        first = (b, a) if order == "dmy" else (a, b)
        for mo, da in (first, first[::-1]):
            try:
                return dt.date(y, mo, da)
            except ValueError:
                continue
        return None
    m = re.match(r"^(\d{4})[/.](\d{1,2})[/.](\d{1,2})$", s)
    if m:
        try:
            return dt.date(*(int(x) for x in m.groups()))
        except ValueError:
            return None
    m = re.match(r"^(\d{1,2})[ -]([A-Za-z]{3})[A-Za-z]*[ -](\d{2,4})$", s) or re.match(r"^([A-Za-z]{3})[A-Za-z]*\.? (\d{1,2}),? (\d{4})$", s)
    if m:
        g = m.groups()
        try:
            if g[0].isdigit():
                y = int(g[2]); y = y + 2000 if y < 100 else y
                return dt.date(y, MONTHS[g[1].lower()[:3]], int(g[0]))
            return dt.date(int(g[2]), MONTHS[g[0].lower()[:3]], int(g[1]))
        except (KeyError, ValueError):
            return None
    return None


def parse_rows(header, rows, mapping, dates="mdy"):
    """-> (parsed, problems). parsed: dicts with date (ISO), desc, amount (float, as in the file), ref, cardholder, category."""
    idx = {k: header.index(v) for k, v in mapping.items() if v in header}
    missing = [k for k in ("date", "desc") if k not in idx]
    if "amount" not in idx and not ("debit" in idx or "credit" in idx):
        missing.append("amount (or debit/credit)")
    if missing:
        raise ImportError_(f"no column for {', '.join(missing)}; header is {header}. Use --map, e.g. --map date=Posted,desc=Details,amount=Amount")
    out, problems = [], []
    for n, r in enumerate(rows, 2):
        def cell(k):
            i = idx.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""
        d = parse_date(cell("date"), dates)
        if not d:
            problems.append(f"line {n}: cannot read date {cell('date')!r}")
            continue
        try:
            if "amount" in idx:
                amt = money.parse(cell("amount"))
            else:
                deb = money.parse(cell("debit")) if cell("debit") else 0.0
                cre = money.parse(cell("credit")) if cell("credit") else 0.0
                amt = money.round2(abs(cre) - abs(deb))
        except ValueError as e:
            problems.append(f"line {n}: {e}")
            continue
        desc = re.sub(r"\s+", " ", cell("desc")).strip()
        if not desc:
            problems.append(f"line {n}: empty description")
            continue
        out.append({"date": d.isoformat(), "desc": desc, "amount": amt, "ref": cell("ref") or None,
                    "cardholder": cell("cardholder") or None, "category": cell("category") or None})
    return out, problems


def decide_sign(parsed, account_type, sign="auto"):
    """Returns +1 (keep) or -1 (invert) so that stored amounts are negative = money out."""
    if sign == "as-is":
        return 1
    if sign == "invert":
        return -1
    if account_type == "credit" and parsed:
        pos = sum(1 for p in parsed if p["amount"] > 0)
        return -1 if pos > len(parsed) / 2 else 1
    return 1


# ---- accounts and formats

def find_account(con, key):
    rows = con.execute("SELECT id, name, type, last4 FROM accounts").fetchall()
    k = str(key).strip().lower()
    hit = [r for r in rows if r[1].lower() == k or (r[3] or "") == k]
    if not hit:
        hit = [r for r in rows if k in r[1].lower()]
    if len(hit) != 1:
        names = ", ".join(f"{r[1]} x{r[3] or '----'}" for r in rows) or "none yet (use --new)"
        raise ImportError_(f"{'no' if not hit else 'several'} accounts match {key!r}. Accounts: {names}")
    return {"id": hit[0][0], "name": hit[0][1], "type": hit[0][2], "last4": hit[0][3]}


def load_formats():
    try:
        return json.loads(FORMATS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_format(key, data):
    f = load_formats()
    f[key] = data
    config.write_json(FORMATS, f)


# ---- import

BANK_REF = "sfin:"   # `ref` prefix of rows from bank sync (data/bank_sync.py); every other row came from a statement
TWIN_DAYS = 3         # a bank-sync row and a statement row of the same amount this close are one transaction


def _day(s):
    return _iso(str(s)[:10]) if s else None


def _twins(con, acct_id, bank):
    """Rows of the OTHER source in this account, for matching: [(id, date, cents)]."""
    other = "(ref IS NULL OR ref NOT LIKE 'sfin:%')" if bank else "ref LIKE 'sfin:%'"
    return [(i, _day(d), money.cents(a)) for i, d, a in con.execute(
        f"SELECT id, txn_date, amount FROM transactions WHERE account_id=? AND {other}", (acct_id,))]


def statement_end(con, acct_id):
    """Newest date of a statement row in this account (None = no statement rows): bank sync starts after it."""
    r = con.execute("SELECT MAX(txn_date) FROM transactions WHERE account_id=? AND (ref IS NULL OR ref NOT LIKE 'sfin:%')",
                    (acct_id,)).fetchone()
    return _day(r[0]) if r and r[0] else None


def plan(con, parsed, acct, sign_factor, bank=False):
    """Which parsed rows are new. -> (to_insert, skipped)

    Same source: by ref, else by count of identical (date, description, cents). Across sources (statement rows vs bank
    sync rows, `bank=True` for the latter): a bank row dated on or before the newest statement row of the account is
    covered by that statement; otherwise a row with exactly one unused row of the other source with the same cents
    within TWIN_DAYS is the same transaction and skipped. Two or more such rows = it is added, and the Inbox asks
    (proposals source `bank_dupe`)."""
    have_ref = {x[0] for x in con.execute("SELECT ref FROM transactions WHERE account_id=? AND ref IS NOT NULL AND ref != ''", (acct["id"],))}
    have_cnt = collections.Counter((d_, s_, money.cents(a_)) for d_, s_, a_ in con.execute(
        "SELECT txn_date, description, amount FROM transactions WHERE account_id=? AND (ref IS NULL OR ref = '')", (acct["id"],)))
    others = _twins(con, acct["id"], bank)
    used = set()
    # statement rows of the other kind (one file with a reference column, another without, e.g. a PDF and a CSV of the
    # same month): the same (date, cents) is the same transaction, counted one to one (audit M14)
    cross_noref, cross_ref = collections.Counter(), collections.Counter()
    if not bank:
        for d_, a_, r_ in con.execute("SELECT txn_date, amount, ref FROM transactions WHERE account_id=? "
                                      "AND (ref IS NULL OR ref NOT LIKE 'sfin:%')", (acct["id"],)):
            (cross_ref if r_ else cross_noref)[(str(d_)[:10], money.cents(a_))] += 1
    cut = statement_end(con, acct["id"]) if bank else None
    seen = collections.Counter()
    new, skipped = [], 0
    for p in parsed:
        amt = money.round2(p["amount"] * sign_factor)
        if p["ref"]:
            if p["ref"] in have_ref:
                skipped += 1
                continue
            have_ref.add(p["ref"])
        else:
            key = (p["date"], p["desc"], money.cents(amt))
            seen[key] += 1
            if seen[key] <= have_cnt[key]:
                skipped += 1
                continue
        cross = cross_noref if p["ref"] else cross_ref
        ck = (str(p["date"])[:10], money.cents(amt))
        if cross[ck] > 0:
            cross[ck] -= 1
            skipped += 1
            continue
        day, cents = _day(p["date"]), money.cents(amt)
        if cut and day and day <= cut:
            skipped += 1
            continue
        near = [i for i, d, c in others if c == cents and i not in used and d and day and abs((d - day).days) <= TWIN_DAYS]
        if len(near) == 1:
            used.add(near[0])
            skipped += 1
            continue
        ttype = "card_payment" if (acct["type"] == "credit" and amt > 0 and PAY.search(p["desc"])) else None
        new.append({**p, "amount": amt, "txn_type": ttype})
    return new, skipped


def possible_duplicates(con, acct_id=None):
    """Bank-sync rows that still have a statement row of the same amount within TWIN_DAYS (left by `plan` when it
    could not tell which one, or pulled before this check existed).
    -> [{id, account_id, account, date, amount, description, twins: [ids]}]"""
    sql = ("SELECT s.id, s.account_id, a.name, s.txn_date, s.amount, s.description, t.id FROM transactions s "
           "JOIN accounts a ON a.id = s.account_id "
           "JOIN transactions t ON t.account_id = s.account_id AND t.id != s.id AND (t.ref IS NULL OR t.ref NOT LIKE 'sfin:%') "
           "AND CAST(ROUND(t.amount * 100) AS INTEGER) = CAST(ROUND(s.amount * 100) AS INTEGER) "
           f"AND ABS(julianday(substr(t.txn_date, 1, 10)) - julianday(substr(s.txn_date, 1, 10))) <= {TWIN_DAYS} "
           "WHERE s.ref LIKE 'sfin:%'" + (" AND s.account_id = ?" if acct_id else "") + " ORDER BY s.txn_date, s.id, t.id")
    out = {}
    for sid, aid, name, d, amt, desc, tid in con.execute(sql, (acct_id,) if acct_id else ()):
        out.setdefault(sid, {"id": sid, "account_id": aid, "account": name, "date": str(d)[:10], "amount": amt,
                             "description": desc, "twins": []})["twins"].append(tid)
    return list(out.values())


def run_import(path, account, mapping=None, dates="mdy", sign="auto", document_id=None, dry_run=False,
               balance=None, as_of=None, apply_rules=True, con=None):
    """Library entry. Returns a report dict: inserted, skipped, problems, sign, mapping, account, balance."""
    own = con is None
    con = con or db.connect()
    try:
        acct = find_account(con, account)
        header, rows = read_rows(path)
        mp = guess_mapping(header)
        mp.update({k: _match_col(header, v) for k, v in (mapping or {}).items()})
        parsed, problems = parse_rows(header, rows, mp, dates)
        if problems:
            return {"ok": False, "problems": problems, "mapping": mp, "inserted": 0, "skipped": 0, "account": acct}
        factor = decide_sign(parsed, acct["type"], sign)
        new, skipped = plan(con, parsed, acct, factor)
        if not dry_run:
            for p in new:
                con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, document_id, txn_type, ref, cardholder) "
                            "VALUES (?,?,?,?,?,?,?,?,?)",
                            (acct["id"], p["date"], p["desc"], p["amount"], p["category"], document_id, p["txn_type"], p["ref"], p["cardholder"]))
            if balance is not None:
                d = _iso(as_of) or _iso(max(p["date"] for p in parsed)) if parsed else _iso(as_of)
                if not d:
                    raise ImportError_("--balance needs --as-of YYYY-MM-DD")
                con.execute("INSERT INTO account_balances(account_id, as_of, balance, kind, document_id) VALUES (?,?,?,'statement_end',?) "
                            "ON CONFLICT(account_id, as_of, kind) DO UPDATE SET balance=excluded.balance, document_id=COALESCE(excluded.document_id, account_balances.document_id)",
                            (acct["id"], d.isoformat(), money.round2(balance), document_id))
            con.commit()
        rep = {"ok": True, "problems": [], "mapping": mp, "inserted": len(new), "skipped": skipped, "account": acct,
               "sign": "inverted" if factor < 0 else "as-is", "rows": len(parsed), "new": new[:5],
               "first": parsed[0]["date"] if parsed else None, "last": parsed[-1]["date"] if parsed else None}
        if not dry_run and new and apply_rules:
            r = subprocess.run([sys.executable, str(HERE / "apply_rules.py")], cwd=ROOT, capture_output=True, text=True)
            rep["rules"] = "ok" if r.returncode == 0 else r.stderr[-200:]
        if not dry_run and new:
            import receipts
            rep["receipts_matched"] = receipts.match_after_import(con)
            con.commit()
        return rep
    finally:
        if own:
            con.close()


def _match_col(header, name):
    low = [h.lower() for h in header]
    if name in header:
        return name
    if name.lower() in low:
        return header[low.index(name.lower())]
    raise ImportError_(f"no column named {name!r}; header is {header}")


# ---- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="CSV export, or: detect FILE | formats")
    ap.add_argument("path", nargs="?")
    ap.add_argument("--account")
    ap.add_argument("--new", help="create this account first (with --type, --last4, --owner)")
    ap.add_argument("--type", choices=["checking", "savings", "credit", "loan", "investment"])
    ap.add_argument("--last4")
    ap.add_argument("--owner")
    ap.add_argument("--map")
    ap.add_argument("--dates", choices=["mdy", "dmy", "ymd"])
    ap.add_argument("--sign", choices=["as-is", "invert", "auto"])
    ap.add_argument("--format")
    ap.add_argument("--save-format")
    ap.add_argument("--document-id", type=int)
    ap.add_argument("--balance", type=float)
    ap.add_argument("--as-of")
    ap.add_argument("--no-rules", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    if a.file == "account":  # python data/import_statement.py account --new "Name" --type checking --last4 1234
        if not (a.new and a.type):
            raise SystemExit('usage: import_statement.py account --new "Name" --type checking|savings|credit|loan|investment [--last4 1234] [--owner NAME]')
        con = db.connect()
        try:
            if con.execute("SELECT 1 FROM accounts WHERE name=? COLLATE NOCASE", (a.new,)).fetchone():
                raise SystemExit(f"there is already an account called {a.new}")
            con.execute("INSERT INTO accounts(name, type, last4, owner) VALUES (?,?,?,?)", (a.new, a.type, a.last4, a.owner))
            con.commit()
        finally:
            con.close()
        print(f"created account {a.new} ({a.type}, x{a.last4 or '----'})")
        return 0
    if a.file == "formats":
        for k, v in load_formats().items():
            print(f"{k:<16} account x{v.get('account', '----')}  dates={v.get('dates', 'mdy')} sign={v.get('sign', 'auto')}  map={v.get('map')}")
        return 0
    if a.file == "detect":
        if not a.path:
            raise SystemExit("detect needs a file")
        header, rows = read_rows(a.path)
        mp = guess_mapping(header)
        print("header:", header)
        print("guessed mapping:", mp or "nothing recognised; use --map")
        try:
            parsed, problems = parse_rows(header, rows, mp, a.dates or "mdy")
        except ImportError_ as e:
            print("problem:", e)
            return 1
        for p in parsed[:5]:
            print(f"  {p['date']}  {p['amount']:>10.2f}  {p['desc'][:50]}  ref={p['ref'] or ''}")
        print(f"{len(parsed)} rows readable, {len(problems)} not" + (": " + "; ".join(problems[:3]) if problems else ""))
        return 0

    path = a.file
    fmt = load_formats().get(a.format) if a.format else None
    mapping = parse_map(a.map) if a.map else (fmt or {}).get("map") or {}
    dates = a.dates or (fmt or {}).get("dates") or "mdy"
    sign = a.sign or (fmt or {}).get("sign") or "auto"
    account = a.account or (fmt or {}).get("account")
    con = db.connect()
    try:
        if a.new:
            if not a.type:
                raise SystemExit("--new needs --type checking|savings|credit|loan|investment")
            con.execute("INSERT INTO accounts(name, type, last4, owner) VALUES (?,?,?,?)", (a.new, a.type, a.last4, a.owner))
            if not a.dry_run:  # a dry run changes nothing: the account vanishes when the connection closes
                con.commit()
            account = a.new
            print(f"{'would create' if a.dry_run else 'created'} account {a.new} ({a.type}, x{a.last4 or '----'})")
        if not account:
            raise SystemExit("--account NAME|LAST4 is required (or --new ...)")
        try:
            rep = run_import(path, account, mapping, dates, sign, a.document_id, a.dry_run, a.balance, a.as_of, not a.no_rules, con)
        except ImportError_ as e:
            raise SystemExit(str(e))
    finally:
        con.close()
    if not rep["ok"]:
        print(f"nothing imported: {len(rep['problems'])} row(s) could not be read (mapping used: {rep['mapping']}):")
        for p in rep["problems"][:10]:
            print("  " + p)
        return 1
    acct = rep["account"]
    print(f"{'would insert' if a.dry_run else 'inserted'} {rep['inserted']}, skipped {rep['skipped']} already stored, of {rep['rows']} rows "
          f"({rep['first']} to {rep['last']}) into {acct['name']} x{acct['last4'] or '----'}; amounts {rep['sign']}; mapping {rep['mapping']}")
    for p in rep["new"]:
        print(f"  {p['date']}  {p['amount']:>10.2f}  {p['desc'][:50]}{'  [card_payment]' if p['txn_type'] else ''}")
    if rep.get("rules"):
        print("categorised with apply_rules:", rep["rules"])
    if a.save_format and not a.dry_run:
        save_format(a.save_format, {"account": acct["last4"], "map": rep["mapping"], "dates": dates, "sign": rep["sign"] if sign == "auto" else sign})
        print(f"format saved as {a.save_format}: next time  python data/import_statement.py FILE --format {a.save_format}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
