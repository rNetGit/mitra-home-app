"""PayPal account statements read without AI (nothing leaves this PC): every payment becomes a receipt.

  python data/paypal_statement.py check FILE      what would be filed (nothing is changed)

A PayPal statement PDF has two views of the same money: "PayPal account" (every payment) and "PayPal Balance account" (the
part paid from a PayPal balance). Only the first is read. A payment is paid by a card or a bank account that already has
its own statement, so the payment is NOT added as spending (that would count it twice): it is filed as a receipt
(merchant, date, total) and the receipt matcher (receipts.py) names the card or bank charge it belongs to, e.g.
"PAYPAL *ROBLOX". The matching "General Credit Card Deposit" lines, refunds and other movements are counted and left alone.

The statement names the account by an email address, never by digits, so nothing about it is stored: the paper is filed as
vendor "PayPal" and the lines keep only merchant, date and amount. A statement with no activity is still filed.
The table is read from pypdf's layout text; a line that does not look like a row of that table stops the reading, and the
paper waits in the review queue with the reason.
"""
import datetime as dt
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

PERIOD = re.compile(r"Statement Period.*?([A-Z][a-z]{2} \d{1,2}, \d{4})\s*-\s*([A-Z][a-z]{2} \d{1,2}),\s*(?:\S+\s+){0,3}?(\d{4})")
ROW_START = re.compile(r"^\s*(\d{2}/\d{2}/\d{3,4})(?:\s|$)")
ROW = re.compile(r"^\s*(\d{2}/\d{2}/\d{3,4})\s+(\S.*?)\s{2,}([A-Z]{3})\s+(-?[\d,]*\.\d\d)\s+(-?[\d,]*\.\d\d)\s+(-?[\d,]*\.\d\d)\s*$")
STOP_LINE = re.compile(r"\bID:|\bUSD\b|\d+\.\d\d\b|\bCard\b|\bBank\b|\bBalance\b")
PAYMENT_KIND = re.compile(r"payment|purchase|checkout", re.I)


class StatementError(ValueError):
    pass


def looks_like(text):
    t = " ".join(str(text or "").split())
    return "PayPal" in t and "PayPal account statement" in t and "ACCOUNT ACTIVITY" in t


def page_texts(path):
    """The layout text of each page: pypdf's layout mode (pypdf is a requirement of the app), else `pdftotext -layout`."""
    try:
        from pypdf import PdfReader
        return [pg.extract_text(extraction_mode="layout") or "" for pg in PdfReader(str(path)).pages]
    except ImportError:
        if not shutil.which("pdftotext"):
            raise StatementError("no PDF reader is installed (pip install pypdf)") from None
        out = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True, text=True, timeout=60).stdout
        return out.split("\f")


def _date(s):
    m, d, y = s.split("/")
    return dt.date(int(y), int(m), int(d))


def _money(s):
    return round(float(s.replace(",", "")), 2)


def _period(pages):
    t = " ".join(" ".join(pages[:1]).split())
    m = PERIOD.search(t)
    if not m:
        raise StatementError("the statement period is not printed")
    f = lambda s: dt.datetime.strptime(s, "%b %d, %Y").date()  # noqa: E731
    return f(m.group(1)), f(f"{m.group(2)}, {m.group(3)}")  # the end year can wrap onto its own line, after the email


def parse(pages):
    """-> {"period": (start, end), "payments": [{"date", "merchant", "total", "kind"}], "lines": n, "other": n}.
    Raises StatementError for anything that is not a PayPal account statement table the reader fully understands."""
    if not pages or not looks_like(" ".join(pages)):
        raise StatementError("not a PayPal account statement")
    period = _period(pages)
    payments, lines, other, started = [], 0, 0, 0
    section = "account"
    for text in pages:
        flat = " ".join(text.split())
        if re.search(r"PAYPAL BALANCE ACCOUNT", flat) or section == "balance":
            section = "balance"  # the second view repeats the part paid from a balance: not read again
            continue
        rows = text.splitlines()
        i = 0
        while i < len(rows):
            line = rows[i]
            if not ROW_START.match(line):
                i += 1
                continue
            started += 1
            block = [line]
            i += 1
            while i < len(rows) and rows[i].strip() and not ROW_START.match(rows[i]):
                block.append(rows[i])
                i += 1
            m = ROW.match(block[0])
            if not m:
                raise StatementError("a line of the activity table is not in the layout the reader knows")
            raw_date, desc, cur, _amount, _fees, total = m.groups()
            if cur != "USD":
                raise StatementError(f"a line is in {cur}; only US dollar lines are read")
            tail = []
            for b in block[1:]:
                mm = re.match(r"^\s*(\d)(?:\s{2,}(.*))?$", b) if len(raw_date.split("/")[2]) == 3 and not tail else None
                if mm:  # the year wrapped: "02/03/202" then "6"
                    raw_date += mm.group(1)
                    b = mm.group(2) or ""
                b = b.strip()
                if not b:
                    continue
                if STOP_LINE.search(b):
                    break
                tail.append(b)
            if len(raw_date.split("/")[2]) != 4:
                raise StatementError("a line's year could not be read")
            lines += 1
            full = " ".join([desc.strip()] + tail)
            kind, _, merchant = full.partition(":")
            total = _money(total)
            if total < 0 and merchant.strip() and PAYMENT_KIND.search(kind):
                payments.append({"date": _date(raw_date), "merchant": merchant.strip().rstrip(".,;")[:80] or merchant.strip()[:80],
                                 "total": -total, "kind": kind.strip()})
            else:
                other += 1
    if started != lines:
        raise StatementError("some lines of the activity table were not read")
    return {"period": period, "payments": payments, "lines": lines, "other": other}


def read(path):
    return parse(page_texts(path))


def store(con, res, document_id=None):
    """File each payment as a receipt (skipping one already there) -> {"filed", "skipped", "matched"}."""
    import receipts
    filed = skipped = matched = 0
    for p in res["payments"]:
        d = p["date"].isoformat()
        if con.execute("SELECT 1 FROM receipts WHERE LOWER(merchant)=LOWER(?) AND receipt_date=? AND ABS(total-?)<0.005",
                       (p["merchant"], d, p["total"])).fetchone():
            skipped += 1
            continue
        rid = receipts.add(con, p["merchant"], d, p["total"], document_id=document_id, note="PayPal statement")
        filed += 1
        if receipts.get(con, rid)["status"] == "matched":
            matched += 1
    return {"filed": filed, "skipped": skipped, "matched": matched}


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    if len(a) != 2 or a[0] != "check":
        print(__doc__)
        return 2
    try:
        res = read(pathlib.Path(a[1]))
    except (StatementError, OSError) as e:
        print("error:", e)
        return 1
    print(f"period {res['period'][0]} to {res['period'][1]}; {res['lines']} lines, {len(res['payments'])} payments, "
          f"{res['other']} other (not filed)")
    for p in res["payments"]:
        print(f"  {p['date']}  {p['total']:>10.2f}  {p['merchant']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
