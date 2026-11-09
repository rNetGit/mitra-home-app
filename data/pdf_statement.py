"""Bank and card statement PDFs into `transactions` without AI (statements with a text layer).

  python data/pdf_statement.py FILE.pdf [--account NAME|LAST4] [--dry-run]     read, check, import
  python data/pdf_statement.py check FILE.pdf                                  only show what it reads

How it reads a statement (any bank that prints one transaction per line):
  * the account: "Account number ending: 1234", "XXXX XXXX XXXX 1234", "ending in 1234" -> the account with that last4
    (or --account). Credit accounts are read as cards, everything else as bank accounts.
  * the period: "July 31, 2026 to August 31, 2026", "Jul 26, 2026 to Aug 25, 2026", "07/01/2026 - 07/31/2026". Dates
    printed as MM/DD get the year that puts them inside the period (a December-January statement works).
  * transaction lines: a date (MM/DD or MM/DD/YYYY), an optional second date (posted / transaction), an optional
    reference number, the description, the amount at the end (an extra running-balance column is ignored).
  * the sign. Cards: a plus amount is a charge (stored as money out), a minus or "CR" amount is a payment or credit.
    Bank accounts: the section heading above the line decides (Deposits / Credits / Additions -> money in;
    Withdrawals / Debits / Checks / Fees / Purchases -> money out); a minus amount is always money out.
  * the check: beginning (previous) balance + money in - money out must equal the ending (new) balance to the cent
    (cards: the other way round). Only a statement that checks out is imported automatically by intake; the command
    line imports an unchecked one only with --force.
Rows already loaded (same reference, or same date + description + amount) are skipped, so a statement can be imported
twice, or after a CSV export of the same month. Category rules run afterwards (data/apply_rules.py), then receipts are
matched (data/receipts.py). Only the last four digits of an account are ever read; the full number stays in the PDF.
"""
import argparse
import datetime as dt
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import db  # noqa: E402
import dates  # noqa: E402
import import_statement as ist  # noqa: E402
import money as _money  # noqa: E402

ROOT = HERE.parent
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MD = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
PERIOD = re.compile(rf"({_MD})\s*(?:to|-|–|through|thru)\s*({_MD})|(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})\s*(?:to|-|–|through|thru)\s*(\d{{1,2}}/\d{{1,2}}/\d{{2,4}})", re.I)
# The last four of the account number, in the ways statements print it. Only the last four are ever kept.
_LAST4_BEFORE = (
    r"ending(?:\s+in)?\s*:?\s*(?:\d{1,2}-\d{0,2})?",  # "ending in 1234", "Account Ending 7-81002" (charge cards)
    r"(?:X{4}[\s-]*){2,3}", r"\*{4}\s*",  # "XXXX XXXX XXXX 1234", "****1234"
    r"account\s*(?:number|no\.?|#)?\s*:?\s*(?:x+|\*+)-?",  # "Account # xxxx1234"
    r"account\s*(?:number|no\.?|#)\s*:?\s*(?:\d+[ -])*\d{0,13}",  # printed in full: "Account Number 1234 5678 9012"
    r"(?:account|checking|savings)\s*-?\s*\d{4,13}",  # "Checking - Account" / "Everyday Checking" + 8 or more digits
)
LAST4 = re.compile(r"(?:" + "|".join(_LAST4_BEFORE) + r")(\d{4})\b(?![.,]\d)", re.I)
AMT = r"\(?-?\$?-?\d{1,3}(?:,\d{3})*\.\d{2}\)?(?:\s?CR\b|-)?"
LINE = re.compile(rf"^\s*(\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?)\s+(?:(\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?)\s+)?(.+?)\s+({AMT})(?:\s+({AMT}))?\s*$", re.I)
CHECK = re.compile(rf"(?<![\d/])(\d{{3,6}})\*?\s+(\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?)\s+({AMT})")
CHECK_START = re.compile(r"^\s*\d{3,6}\*?\s+\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+\(?-?\$?\d")
REF = re.compile(r"^([A-Z0-9]*\d[A-Z0-9]{7,})\s+(.+)$")
IN_WORDS = re.compile(r"deposit|credit|addition|interest paid|money in|incoming", re.I)
OUT_WORDS = re.compile(r"withdrawal|debit|subtraction|checks? paid|\bchecks\b|fee|purchase|money out|outgoing|payments? (?:and|&) transfers", re.I)
TRAILING_TOTAL = re.compile(r"\s+[\(\-]?\$?\d{1,3}(?:,\d{3})*\.\d{2}\)?-?\s*$")
SKIP_DESC = re.compile(r"^(?:sub)?totals?\b|^(?:beginning|ending|opening|closing|previous|prior|new|daily|statement)\s+"
                       r"(?:statement\s+)?balance|^balance\b", re.I)
# "Previous Balance", "Previous Statement Balance", "Balance Last Statement"; "New Balance", "Statement Balance" (never
# the previous one's), "Balance This Statement"
BEGIN = re.compile(r"(?:(?:beginning|previous|prior|opening)\s+(?:statement\s+)?balance|balance\s+(?:last|previous)\s+statement)"
                   r"\b[^\n]*?(-?\$?-?\d{1,3}(?:,\d{3})*\.\d{2})", re.I)
END = re.compile(r"(?:(?:ending|new|closing)\s+balance|(?<!previous )(?<!prior )(?<!last )statement\s+balance"
                 r"|balance\s+this\s+statement)\b[^\n]*?(-?\$?-?\d{1,3}(?:,\d{3})*\.\d{2})", re.I)
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
MONTH_DAY = re.compile(rf"^(\s*(?:\d{{1,2}}/\d{{1,2}}\s+)?){_MON}\s+(\d{{1,2}})(?=\s)", re.I)  # "Sep 26 Sep 27 SHOP"
DASH_DATE = re.compile(r"^(\s*(?:\d{1,2}/\d{1,2}(?:/\d{2,4})?\s+)?)(\d{1,2})-(\d{1,2})(?:-(\d{2}|\d{4}))?(?=\s)")  # "10-3 SHOP"
STAR_DATE = re.compile(r"^(\s*\d{1,2}/\d{1,2}(?:/\d{2,4})?)\*(?=\s)")  # "10/10/26* PAYMENT" (* = posting date)
SPACED_SIGN = re.compile(r"(?<=\s)([-+])\s+\$(?=\d)")  # "- $500.00" -> "-$500.00"


def norm_line(ln):
    """A transaction line in the one shape LINE reads: month-name dates ("Sep 26"), dashed dates ("10-3", "10-03-26")
    and a posting-date star become MM/DD[/YY], and a sign set apart from its amount is joined to it. Up to two dates
    (transaction and posting); anything that is not a real month and day is left as it was."""
    for _ in range(2):
        m = MONTH_DAY.match(ln)
        if m and 1 <= int(m.group(3)) <= 31:
            ln = f"{m.group(1)}{MONTHS[m.group(2).lower()[:3]]:02d}/{int(m.group(3)):02d}" + ln[m.end():]
            continue
        m = DASH_DATE.match(ln)
        if m and 1 <= int(m.group(2)) <= 12 and 1 <= int(m.group(3)) <= 31:
            ln = f"{m.group(1)}{m.group(2)}/{m.group(3)}" + (f"/{m.group(4)}" if m.group(4) else "") + ln[m.end():]
            continue
        break
    ln = STAR_DATE.sub(r"\1", ln)
    return SPACED_SIGN.sub(lambda s: "-$" if s.group(1) == "-" else "$", ln)


class StatementError(ValueError):
    pass


def layout_texts(path):
    """The page text with columns kept, from each reader available: pypdf's layout mode first, then pdftotext. Readers
    disagree on some statements (rotated text, overlapping columns); read() keeps the one whose balances add up."""
    p, out = pathlib.Path(path), []
    if p.suffix.lower() == ".txt":  # text already pulled out of a PDF (pdftotext -layout), e.g. for a test or a bug report
        return [p.read_text(encoding="utf-8", errors="replace")]
    try:
        with open(p, "rb") as fh:
            head = fh.read(1024)
    except OSError as e:
        raise StatementError(f"the file cannot be opened: {e}") from None
    if b"%PDF-" not in head:
        raise StatementError("this file is not a PDF (a photo or another kind of file saved with a PDF name); "
                             "download the statement as a PDF from the bank's website, or export CSV")
    try:
        from pypdf import PdfReader
        parts = []
        for pg in PdfReader(str(p)).pages:
            try:
                parts.append(pg.extract_text(extraction_mode="layout") or "")
            except Exception:  # noqa: BLE001 (a page without text objects)
                parts.append("")
        out.append("\n".join(parts))
    except ImportError:
        pass
    except Exception:  # noqa: BLE001 (a PDF cut off when it was saved: pdftotext may still read it)
        pass
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(p), "-"], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0 and (r.stdout or "").strip():
            out.append(r.stdout)
    return [t for t in out if len(t.strip()) >= 40]


def _amount(tok):
    s = tok.strip()
    neg = s.startswith("-") or s.startswith("(") or "-" in s[:3] or s.upper().endswith("CR") or s.endswith("-")
    n = float(re.sub(r"[^\d.]", "", s))
    return -n if neg else n


def _named_date(s):
    m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s.strip())
    return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))


def _num_date(s):
    m, d, y = (int(x) for x in s.split("/"))
    return dt.date(y + 2000 if y < 100 else y, m, d)


def period(text):
    m = PERIOD.search(text)
    if not m:
        return None
    try:
        if m.group(1):
            return _named_date(m.group(1)), _named_date(m.group(2))
        return _num_date(m.group(3)), _num_date(m.group(4))
    except (ValueError, KeyError):
        return None


def _date(tok, per):
    parts = tok.split("/")
    mo, da = int(parts[0]), int(parts[1])
    if len(parts) == 3:
        y = int(parts[2])
        return dt.date(y + 2000 if y < 100 else y, mo, da)
    years = [per[0].year, per[1].year] if per else [dates.today().year]
    best = None
    for y in sorted(set(years + [years[0] - 1])):
        try:
            d = dt.date(y, mo, da)
        except ValueError:
            continue
        ref = per[0] if per else dates.today()
        if best is None or (per and per[0] - dt.timedelta(days=40) <= d <= per[1] + dt.timedelta(days=7)
                            and not (per[0] - dt.timedelta(days=40) <= best <= per[1] + dt.timedelta(days=7))) \
                or (abs((d - ref).days) < abs((best - ref).days) and not per):
            best = d
    return best


def last4s(text):
    return [m.group(1) for m in LAST4.finditer(text)]


DETAIL = re.compile(r"(?im)^[ 	]*transaction detail[ 	]*$")
LONG_DIGITS = re.compile(r"\d{9,}")
LONGNUM = re.compile(r"\d{9,}")


def account_block(text, last4):
    """Statements that cover several accounts (checking and savings) print one TRANSACTION DETAIL per account. Returns
    the block of the account whose number (the nearest long number above the heading) ends in `last4`, or text."""
    heads = [m.start() for m in DETAIL.finditer(text)]
    if len(heads) < 2 or not last4:
        return text
    hit = []
    for i, h in enumerate(heads):
        nums = LONGNUM.findall(text[max(0, h - 1500):h])
        if nums and nums[-1].endswith(last4):
            end = heads[i + 1] if i + 1 < len(heads) else len(text)
            hit.append(text[h:end])
    return hit[0] if len(hit) == 1 else text


def _signs(amounts, need):
    """Every +/- assignment of the (unsigned) amounts that adds up to `need`, to the cent; None when too many lines."""
    if len(amounts) > 16:
        return None
    found = []
    for mask in range(1 << len(amounts)):
        t = sum(a if mask >> i & 1 else -a for i, a in enumerate(amounts))
        if _money.eq(t, need):
            found.append(mask)
            if len(found) > 1:
                break
    return found


def parse(text, card, last4=None):
    """-> dict: rows [{date, desc, amount (signed: negative = money out), ref}], period, last4 list, begin, end,
    verified (True / False / None when the statement prints no balances), money_in, money_out."""
    per = period(text)
    whole = text
    text = account_block(text, last4) if not card else text
    rows, section, pending = [], 0, []
    b0 = BEGIN.search(text)
    running = None if card or not b0 else _amount(b0.group(1))  # running balance, to read the sign from a balance column
    for ln in text.splitlines():
        ln = norm_line(ln)
        if CHECK_START.match(ln):  # "1367  04/15  $8,000.00" (several per line on some statements): paid checks
            for c in CHECK.finditer(ln):
                try:
                    d, a = _date(c.group(2), per), abs(_amount(c.group(3)))
                except ValueError:
                    continue
                if d:
                    rows.append({"date": d.isoformat(), "desc": f"Check {c.group(1)}", "amount": -_money.round2(a),
                                 "ref": f"CHK{c.group(1)}", "cardholder": None, "category": None})
            continue
        m = LINE.match(ln)
        if not m:
            head = TRAILING_TOTAL.sub("", ln.strip())  # "Deposits and Additions 653.89": the section total is printed after it
            if head and len(head) < 60 and not re.search(r"\d", head):
                if IN_WORDS.search(head) and not OUT_WORDS.search(head):
                    section = 1
                elif OUT_WORDS.search(head):
                    section = -1
            continue
        d1, d2, desc, amt = m.group(1), m.group(2), " ".join(m.group(3).split()), m.group(4)
        if SKIP_DESC.search(desc):
            continue
        ref = None
        r = REF.match(desc)
        if r:
            ref, desc = r.group(1), r.group(2)
        desc = LONG_DIGITS.sub(lambda mm: "x" + mm.group()[-4:], desc)  # a long company or ID number keeps its last four digits
        try:
            date = _date(d2 or d1, per) if card else _date(d1, per)
            a = _amount(amt)
        except ValueError:
            continue
        bal = None
        if card:
            signed = -a
        else:
            signed = a if a < 0 else (a * section if section else None)
            if m.group(5):  # a balance column: money in or out is whichever sign gets the running balance there
                try:
                    bal = _amount(m.group(5))
                except ValueError:
                    bal = None
            if bal is not None and running is not None and a != 0:
                fits = [s for s in (abs(a), -abs(a)) if _money.eq(running + s, bal)]
                if len(fits) == 1:
                    signed = fits[0]
                elif not fits:
                    continue  # that balance is not this account's (a savings account on the same statement)
        if not card:
            running = bal if bal is not None else (running + signed if running is not None and signed is not None else None)
        if signed is None and date and not card:  # sign unknown: decided below from the balances, if only one way fits
            pending.append({"date": date.isoformat(), "desc": desc[:200], "amount": _money.round2(a), "ref": ref,
                            "cardholder": None, "category": None})
            continue
        if signed is None or not date:
            continue
        rows.append({"date": date.isoformat(), "desc": desc[:200], "amount": _money.round2(signed), "ref": ref,
                     "cardholder": None, "category": None})
    b, e = BEGIN.search(text), END.search(text)
    begin = _amount(b.group(1)) if b else None
    end = _amount(e.group(1)) if e else None
    if pending and begin is not None and end is not None:
        need = _money.round2(end - begin - sum(r["amount"] for r in rows))
        masks = _signs([abs(p["amount"]) for p in pending], need)
        if masks and len(masks) == 1:  # exactly one way to add up: the signs follow from the balances
            for i, p in enumerate(pending):
                p["amount"] = abs(p["amount"]) if masks[0] >> i & 1 else -abs(p["amount"])
                rows.append(p)
    text = whole
    if per is None and rows:  # no period printed ("Closing Date" only): the dates of its lines
        days = sorted(r["date"] for r in rows)
        per = (dt.date.fromisoformat(days[0]), dt.date.fromisoformat(days[-1]))
    total = _money.round2(sum(r["amount"] for r in rows))
    verified = None
    if begin is not None and end is not None:
        want = (begin - total) if card else (begin + total)
        verified = _money.eq(want, end)
    return {"rows": rows, "period": per, "last4": last4s(text), "begin": begin, "end": end, "verified": verified,
            "money_in": _money.round2(sum(r["amount"] for r in rows if r["amount"] > 0)),
            "money_out": _money.round2(-sum(r["amount"] for r in rows if r["amount"] < 0))}


def resolve_account(con, text, account=None):
    if account:
        return ist.find_account(con, account)
    seen = []
    for l4 in last4s(text):
        if l4 not in seen:
            seen.append(l4)
    for l4 in seen:
        hit = con.execute("SELECT id, name, type, last4 FROM accounts WHERE last4=?", (l4,)).fetchall()
        if len(hit) == 1:
            h = hit[0]
            return {"id": h[0], "name": h[1], "type": h[2], "last4": h[3]}
    raise StatementError("no account with the last four digits " + (", ".join(seen) if seen else "(none printed)")
                         + ". Add the account first (Money > Accounts > Add an account), then file the statement again")


def read(con, path, account=None, card=None):
    """`card` True / False reads it as a card / bank statement whatever the account's type says (None = by the type)."""
    texts = layout_texts(path)
    if not texts:
        raise StatementError("this PDF is a picture (no text layer); download the statement again as a PDF from the "
                             "bank's website, or export CSV")
    acct = resolve_account(con, "\n".join(texts), account)
    as_card = acct["type"] == "credit" if card is None else bool(card)
    tries = [parse(t, as_card, acct.get("last4")) for t in texts]
    res = next((r for r in tries if r["verified"]), None) or max(tries, key=lambda r: (r["verified"] is None, len(r["rows"])))
    if not res["rows"]:
        raise StatementError("no transaction lines found (expected 'MM/DD description amount' lines)")
    res["account"] = acct
    return res


def import_pdf(con, path, account=None, document_id=None, dry_run=False, force=False, apply_rules=True):
    """Read, check and import one statement. Returns the report (read() plus inserted / skipped). Commits."""
    res = read(con, path, account)
    if res["verified"] is False and not force:
        raise StatementError(f"balances do not add up (begin {res['begin']}, in {res['money_in']}, out {res['money_out']}, "
                             f"end {res['end']}); some lines were not read. Nothing imported (--force to import anyway)")
    if dry_run:
        new, skipped = ist.plan(con, res["rows"], res["account"], 1)
        res.update(inserted=len(new), skipped=skipped, new=new)
        return res
    return store(con, res, document_id, apply_rules)


def store(con, res, document_id=None, apply_rules=True):
    """Insert the new lines of a checked statement (res as from read(), or doc_extract.read_statement), its closing
    balance, categorise and match receipts. Commits. Returns res with inserted / skipped / new."""
    new, skipped = ist.plan(con, res["rows"], res["account"], 1)
    res.update(inserted=len(new), skipped=skipped, new=new)
    for p in new:
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, document_id, txn_type, ref, cardholder) "
                    "VALUES (?,?,?,?,?,?,?,?,?)", (res["account"]["id"], p["date"], p["desc"], p["amount"], None, document_id,
                                                   p["txn_type"], p["ref"], None))
    if res["end"] is not None and res["period"]:
        bal = -res["end"] if res["account"]["type"] == "credit" else res["end"]
        con.execute("INSERT INTO account_balances(account_id, as_of, balance, kind, document_id) VALUES (?,?,?,'statement_end',?) "
                    "ON CONFLICT(account_id, as_of, kind) DO UPDATE SET balance=excluded.balance, "
                    "document_id=COALESCE(excluded.document_id, account_balances.document_id)",
                    (res["account"]["id"], res["period"][1].isoformat(), _money.round2(bal), document_id))
    con.commit()
    if new and apply_rules:
        subprocess.run([sys.executable, str(HERE / "apply_rules.py")], cwd=ROOT, capture_output=True, text=True)
    try:
        import receipts
        receipts.match_after_import(con)
        con.commit()
    except ImportError:
        pass
    return res


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    check = bool(argv) and argv[0] == "check"
    if check:
        argv = argv[1:]
    ap = argparse.ArgumentParser(description="statement PDF -> transactions, no AI")
    ap.add_argument("file"), ap.add_argument("--account"), ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--document-id", type=int, help="the documents row of the filed PDF, to link the rows to it")
    a = ap.parse_args(argv)
    con = db.connect()
    try:
        res = import_pdf(con, a.file, a.account, document_id=a.document_id, dry_run=a.dry_run or check, force=a.force or check)
    except (StatementError, ist.ImportError_) as e:
        raise SystemExit(f"error: {e}")
    finally:
        pass
    acct = res["account"]
    per = f"{res['period'][0]} to {res['period'][1]}" if res["period"] else "period not found"
    chk = {True: "balances check out", False: "BALANCES DO NOT ADD UP", None: "no balances printed to check"}[res["verified"]]
    print(f"{acct['name']} x{acct['last4'] or '----'} ({acct['type']}), {per}: {len(res['rows'])} lines, "
          f"in {_money.fmt(res['money_in'])}, out {_money.fmt(res['money_out'])}; {chk}")
    if check or a.dry_run:
        for p in res["rows"][:400]:
            print(f"  {p['date']}  {p['amount']:>10.2f}  {p['desc']}")
        print(f"would add {res['inserted']}, skip {res['skipped']} already loaded")
    else:
        print(f"added {res['inserted']}, skipped {res['skipped']} already loaded")
    con.close()


if __name__ == "__main__":
    main()
