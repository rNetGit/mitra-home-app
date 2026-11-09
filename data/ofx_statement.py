"""OFX / QFX downloads (the "Quicken" or "Money" download most banks and card issuers offer) read without AI.

  python data/ofx_statement.py check FILE      what would be imported (nothing is written)

Both the old SGML form (OFX 1.x: tags without closing tags) and XML (OFX 2.x) are read. One file = one account: the
account number (only its last four are kept), checking / savings / credit, the institution's name, every <STMTTRN>
(posted date, amount as signed by the bank: negative = money out, a card purchase is negative too), the period
(DTSTART..DTEND) and the ledger balance. Each line keeps the bank's own id (FITID) as its ref, so a second download of
the same days adds nothing twice. Nothing is opened, run or sent anywhere.
"""
import datetime as dt
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import money as _money  # noqa: E402

TYPES = (".ofx", ".qfx")
KINDS = {"CHECKING": "checking", "SAVINGS": "savings", "MONEYMRKT": "savings", "CREDITLINE": "credit", "CD": "savings"}
MAX_LINES = 5000


class OFXError(ValueError):
    pass


def looks_like(text):
    head = text[:3000].upper()
    return "OFXHEADER" in head or "<OFX>" in head


def _field(block, tag):
    """The value of <TAG>value (SGML, no closing tag) or <TAG>value</TAG> (XML) in block, '' when absent."""
    m = re.search(rf"<{tag}>\s*([^<\r\n]*)", block, re.I)
    return m.group(1).strip() if m else ""


def _date(v):
    m = re.match(r"(\d{4})(\d{2})(\d{2})", v or "")
    if not m:
        return None
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _blocks(text, tag):
    """Every <TAG> ... </TAG> aggregate (OFX aggregates have closing tags in both forms)."""
    return re.findall(rf"<{tag}>(.*?)</{tag}>", text, re.I | re.S)


def read(path):
    """-> {"last4", "kind", "org", "rows": [{date, desc, amount, ref}], "period": (start, end) | None, "end": balance or
    None (card: the amount owed, positive)}. Raises OFXError when the file is not one account's statement."""
    p = pathlib.Path(path)
    try:
        text = p.read_bytes().decode("utf-8", errors="replace")
    except OSError as e:
        raise OFXError(f"the file cannot be opened: {e}") from None
    if not looks_like(text):
        raise OFXError("this is not an OFX / QFX download")
    card = bool(re.search(r"<CCACCTFROM>", text, re.I))
    acct = (_blocks(text, "CCACCTFROM") or _blocks(text, "BANKACCTFROM") or [""])[0]
    accounts = {_field(b, "ACCTID") for b in _blocks(text, "CCACCTFROM") + _blocks(text, "BANKACCTFROM")}
    if len(accounts) > 1:
        raise OFXError("the download holds more than one account; download each account on its own")
    digits = re.sub(r"\D", "", _field(acct, "ACCTID"))
    if len(digits) < 4:
        raise OFXError("no account number in the download")
    kind = "credit" if card else KINDS.get(_field(acct, "ACCTTYPE").upper(), "checking")
    rows = []
    for b in _blocks(text, "STMTTRN")[:MAX_LINES]:
        day = _date(_field(b, "DTPOSTED")) or _date(_field(b, "DTUSER"))
        try:
            amount = _money.round2(float(_field(b, "TRNAMT").replace(",", "")))
        except ValueError:
            raise OFXError("a line has no readable amount") from None
        if not day:
            raise OFXError("a line has no readable date")
        name, memo = _field(b, "NAME"), _field(b, "MEMO")
        desc = " ".join(x for x in (name, memo if memo and memo.lower() not in name.lower() else "") if x)
        desc = re.sub(r"\d{9,}", lambda m: "x" + m.group()[-4:], " ".join(desc.split()))[:200] or "(no description)"
        fitid = _field(b, "FITID")
        rows.append({"date": day.isoformat(), "desc": desc, "amount": amount, "ref": f"ofx:{fitid[:60]}" if fitid else None,
                     "cardholder": None, "category": None})
    if not rows:
        raise OFXError("no transaction lines in the download")
    start, end_day = _date(_field(text, "DTSTART")), _date(_field(text, "DTEND"))
    days = sorted(r["date"] for r in rows)
    period = (start or dt.date.fromisoformat(days[0]), end_day or dt.date.fromisoformat(days[-1]))
    bal = _field(_blocks(text, "LEDGERBAL")[0], "BALAMT") if _blocks(text, "LEDGERBAL") else ""
    try:
        end = _money.round2(float(bal)) if bal else None
    except ValueError:
        end = None
    if end is not None and card:
        end = -end  # OFX prints what is owed on a card as negative; the statements here keep it positive
    org = re.sub(r"[^A-Za-z&' ]+", " ", _field(text, "ORG")).strip()[:30]
    return {"last4": digits[-4:], "kind": kind, "org": org, "rows": rows, "period": period, "end": end}


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "check":
        print(__doc__)
        sys.exit(2)
    try:
        r = read(sys.argv[2])
    except OFXError as e:
        print(f"not read: {e}")
        sys.exit(1)
    print(f"{r['org'] or 'account'} {r['kind']} x{r['last4']}: {len(r['rows'])} lines {r['period'][0]}..{r['period'][1]}, "
          f"balance {r['end']}")
    for x in r["rows"][:10]:
        print(f"  {x['date']}  {x['amount']:>10.2f}  {x['desc'][:60]}")
