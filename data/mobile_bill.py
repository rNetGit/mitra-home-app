"""Phone (mobile carrier) bills per line, without AI: what each person's phone costs each month.

  python data/mobile_bill.py check FILE.pdf          show what it reads and whether the lines add up (changes nothing)
  python data/mobile_bill.py FILE.pdf [--dry-run]    read and store a bill that is already a PDF/text file on disk
  python data/mobile_bill.py reparse DOCUMENT_ID     read a filed bill again (after an update of this reader)
  python data/mobile_bill.py months [N]              net cost per person for the last N months (default 12)

A Verizon bill prints "Bill summary by line" (one name + amount + phone per line, plus account-wide charges and credits)
and "Charges by line details" (per line: Plan, Devices, Services & perks, Surcharges, Taxes & gov fees). This reader
takes only that bill portion; the pages of "Talk activity" (every call) are never read or stored.
Checks, all to the cent: every section of a line adds up to the section's printed total; the sections add up to the
line's printed total; lines match the summary; lines + account-wide charges = the printed bill total. Only a bill that
passes is stored; anything else stays a plain bill (total due only) and intake sends it to the review queue.
Account-wide credits and charges (a loyalty credit, a plan credit) are split equally across the lines, in whole cents
(leftover cents go to the first lines), so each person's net cost adds up to the bill. Only the last four digits of the
account and of each phone number are kept; the name is the one printed on the bill.
"""
import argparse
import datetime as dt
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import db  # noqa: E402
import money as _money  # noqa: E402
import paths  # noqa: E402

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
AMT = r"-?\$-?[\d,]+\.\d{2}"
ITEM = re.compile(rf"^(?P<label>.*?)\s*(?P<amt>{AMT})\s*$")
PHONE_ONLY = re.compile(r"^\(?\d{3}\)?[ -.]?\d{3}[-.]\d{4}$")
SUMMARY_DEVICE = re.compile(r"^(?P<dev>.*?)\s*\(\(?(?P<ph>\d{3}\)?[ -.]?\d{3}[-.]\d{4})\)\s*$")
FURNITURE = re.compile(r"^(?:\d{1,3}|Account:.*|Invoice:.*|Billing period:.*|Charges by line details(?: \(continued\))?|Empty Row)$",
                       re.I)
ACCOUNT_WIDE = re.compile(rf"^Account-wide charges\s*&\s*credits\s+(?P<amt>{AMT})$", re.I)
ACTIVITY = re.compile(r"^(?:Talk|Text|Message|Messaging|Data|Usage)(?:\s+(?:and|&)\s+\w+)? activity\b", re.I)
MIN_TEXT = 200


class BillError(ValueError):
    pass


def _amount(tok):
    s = tok.strip()
    n = round(float(re.sub(r"[^\d.]", "", s)), 2)
    return -n if "-" in s else n


def _date(s):
    m = re.match(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", s.strip())
    if not m or m.group(1).lower() not in MONTHS:
        raise BillError(f"cannot read the date '{s}'")
    return dt.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2)))


def _clean_lines(text):
    out = []
    for raw in text.splitlines():
        s = " ".join(raw.replace(" ", " ").split())
        if s:
            out.append(s)
    return out


def looks_like(text):
    """True for a phone bill this reader knows (has the per-line summary), so intake tries it before any AI."""
    if not text or len(text) < MIN_TEXT:
        return False
    low = text.lower()
    return "bill summary by line" in low and "charges by line details" in low and "verizon" in low


def _carrier(text):
    low = text.lower()
    if "verizon" in low:
        return "Verizon"
    raise BillError("a per-line phone bill from a carrier this reader does not know yet")


def _header(text, lines):
    bd = re.search(r"Bill date\s+([A-Za-z]+ \d{1,2}, \d{4})", text)
    if not bd:
        raise BillError("no bill date printed")
    bill_date = _date(bd.group(1))
    inv = re.search(r"Invoice number\s+(\d+)", text) or re.search(r"Invoice:\s*(\d+)", text)
    if not inv:
        raise BillError("no invoice number printed")
    acct = re.search(r"Account number\s+([\d-]+)", text)
    acct4 = None
    if acct:
        first = re.sub(r"\D", "", acct.group(1).split("-")[0])
        acct4 = first[-4:] if len(first) >= 4 else None
    per = re.search(r"Billing period:\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})\s*-\s*([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})", text)
    p0 = p1 = None
    if per and per.group(1).lower() in MONTHS and per.group(3).lower() in MONTHS:
        y = int(per.group(5))
        m0, m1 = MONTHS[per.group(1).lower()], MONTHS[per.group(3).lower()]
        try:
            p1 = dt.date(y, m1, int(per.group(4)))
            p0 = dt.date(y if m0 <= m1 else y - 1, m0, int(per.group(2)))
        except ValueError:
            p0 = p1 = None
    due = total_due = None
    m = re.search(r"Total due on\s+([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})\s+(\$[\d,]+\.\d{2})", text)
    if m and m.group(1).lower() in MONTHS:
        mo = MONTHS[m.group(1).lower()]
        try:
            due = dt.date(bill_date.year + (1 if mo < bill_date.month else 0), mo, int(m.group(2)))
        except ValueError:
            due = None
        total_due = _amount(m.group(3))
    return {"bill_date": bill_date, "invoice": inv.group(1), "account_last4": acct4, "period_start": p0, "period_end": p1,
            "due_date": due, "total_due": total_due}


def _summary(lines):
    """-> (account_wide or None, [{person, device, phone, amount}], printed total)"""
    try:
        s = next(i for i, ln in enumerate(lines) if ln.lower() == "bill summary by line")
    except StopIteration:
        raise BillError("no 'Bill summary by line' block") from None
    acct, rows, total, i = None, [], None, s + 1
    while i < len(lines):
        ln = lines[i]
        m = re.match(rf"^Total:\s*({AMT})$", ln, re.I)
        if m:
            total = _amount(m.group(1))
            break
        aw = ACCOUNT_WIDE.match(ln)
        if aw:
            acct = _amount(aw.group("amt"))
            i += 1
            continue
        it, nxt = ITEM.match(ln), lines[i + 1] if i + 1 < len(lines) else ""
        dv = SUMMARY_DEVICE.match(nxt)
        if it and dv and it.group("label"):
            rows.append({"person": it.group("label").strip(), "device": dv.group("dev").strip(),
                         "phone": re.sub(r"\D", "", dv.group("ph"))[-4:], "amount": _amount(it.group("amt"))})
            i += 2
            continue
        i += 1
        if i - s > 80:
            break
    if total is None or not rows:
        raise BillError("the per-line summary has no lines or no total")
    return acct, rows, total


def _kind(name):
    n = name.lower()
    if re.search(r"tax|gov", n):
        return "taxes"
    if "surcharge" in n:
        return "surcharges"
    if re.search(r"device|equipment|installment", n):
        return "devices"
    if re.search(r"service|perk|feature|protection|add-?on", n):
        return "perks"
    if re.match(r"plan", n):
        return "plan"
    return "other"


def _sections(items, who):
    """Group (label, amount) pairs into sections: a header whose printed total equals the sum of the items after it."""
    secs, cur = [], None
    for label, amt in items:
        if cur is None:
            cur = {"name": label, "total": amt, "items": [], "sum": 0.0}
            continue
        cur["items"].append((label, amt))
        cur["sum"] = _money.round2(cur["sum"] + amt)
        if _money.eq(cur["sum"], cur["total"]):
            secs.append(cur)
            cur = None
    if cur is not None:
        raise BillError(f"{who}: '{cur['name']}' ({cur['total']:.2f}) does not add up to its items")
    return secs


def _details(lines):
    """-> (account items [(label, amt)] or None, blocks [{person, device, phone, amount, items}])"""
    start = next((i for i, ln in enumerate(lines) if ln.lower() == "charges by line details"
                  and any(x.lower() == "bill summary by line" for x in lines[:i])), None)
    if start is None:
        raise BillError("no 'Charges by line details' block")
    body = []
    for ln in lines[start + 1:]:
        if ACTIVITY.match(ln):
            break
        if not FURNITURE.match(ln):
            body.append(ln)
    acct, blocks, cur = None, [], None
    for i, ln in enumerate(body):
        aw = ACCOUNT_WIDE.match(ln)
        if aw and cur is None:
            acct = {"amount": _amount(aw.group("amt")), "items": []}
            cur = acct
            continue
        it = ITEM.match(ln)
        if it and it.group("label") and i + 2 < len(body) and PHONE_ONLY.match(body[i + 2]) and not ITEM.match(body[i + 1]):
            cur = {"person": it.group("label").strip(), "device": body[i + 1].strip(), "phone": re.sub(r"\D", "", body[i + 2])[-4:],
                   "amount": _amount(it.group("amt")), "items": []}
            blocks.append(cur)
            continue
        if cur is not None and it and it.group("label"):
            cur["items"].append((it.group("label").strip(), _amount(it.group("amt"))))
    return acct, blocks


def split_account_wide(amount, n):
    """Equal shares in whole cents that add up to `amount` exactly; leftover cents go to the first lines."""
    if n <= 0:
        return []
    cents = int(round(amount * 100))
    sign = -1 if cents < 0 else 1
    base, rest = divmod(abs(cents), n)
    return [_money.round2(sign * (base + (1 if i < rest else 0)) / 100) for i in range(n)]


def read(text, strict=True):
    """Read one bill's text -> dict (see below). strict: raise BillError unless every check passes; otherwise the
    problems are listed in res["problems"] and res["verified"] is False."""
    if not looks_like(text):
        raise BillError("not a per-line phone bill this reader knows")
    carrier = _carrier(text)
    lines = _clean_lines(text)
    head = _header(text, lines)
    acct_sum, srows, printed_total = _summary(lines)
    acct_det, blocks = _details(lines)
    problems = []
    if len(blocks) != len(srows):
        problems.append(f"the summary lists {len(srows)} lines but the details have {len(blocks)}")
    out = []
    for n, b in enumerate(blocks):
        who = f"{b['person']} x{b['phone']}"
        try:
            secs = _sections(b["items"], who)
        except BillError as e:
            problems.append(str(e))
            secs = []
        cols = {k: 0.0 for k in ("plan", "devices", "perks", "surcharges", "taxes", "other")}
        items = []
        for s in secs:
            kind = _kind(s["name"])
            cols[kind] = _money.round2(cols[kind] + s["total"])
            items.extend({"section": kind, "group": s["name"], "label": lb, "amount": a} for lb, a in s["items"])
        total = _money.round2(sum(cols.values()))
        if secs and not _money.eq(total, b["amount"]):
            problems.append(f"{who}: sections add up to {total:.2f} but the line total is {b['amount']:.2f}")
        if n < len(srows) and (srows[n]["phone"] != b["phone"] or not _money.eq(srows[n]["amount"], b["amount"])):
            problems.append(f"{who}: the summary has x{srows[n]['phone']} {srows[n]['amount']:.2f} in this place")
        out.append({"person": b["person"], "device": b["device"], "phone_last4": b["phone"], "line_total": b["amount"],
                    "plan": cols["plan"], "devices": cols["devices"], "perks": cols["perks"], "surcharges": cols["surcharges"],
                    "taxes": cols["taxes"], "other": cols["other"], "items": items})
    account_items, account_wide = [], 0.0
    if acct_det is not None or acct_sum is not None:
        account_wide = acct_det["amount"] if acct_det is not None else acct_sum
        if acct_sum is not None and acct_det is not None and not _money.eq(acct_sum, acct_det["amount"]):
            problems.append("account-wide charges differ between the summary and the details")
        if acct_det is not None:
            try:
                for s in _sections(acct_det["items"], "account-wide"):
                    account_items.extend({"section": "account", "group": s["name"], "label": lb, "amount": a} for lb, a in s["items"])
            except BillError as e:
                problems.append(str(e))
    lines_total = _money.round2(sum(r["line_total"] for r in out))
    if not _money.eq(lines_total + account_wide, printed_total):
        problems.append(f"lines {lines_total:.2f} + account-wide {account_wide:.2f} is not the printed total {printed_total:.2f}")
    if problems and strict:
        raise BillError("; ".join(problems[:3]))
    shares = split_account_wide(account_wide, len(out))
    for r, sh in zip(out, shares):
        r["account_share"] = sh
        r["net"] = _money.round2(r["line_total"] + sh)
    return {"carrier": carrier, **head, "bill_total": printed_total, "account_wide": account_wide, "lines_total": lines_total,
            "lines": out, "account_items": account_items, "problems": problems, "verified": not problems}


# ------------------------------------------------------------------ database
def _member_for(con, person):
    """The member this printed name belongs to: the same name, or the first name when it is one member's only."""
    try:
        names = [r[0] for r in con.execute("SELECT name FROM members")]
    except Exception:  # noqa: BLE001 (members table not there yet)
        return None
    low = person.strip().lower()
    for n in names:
        if n.lower() == low:
            return n
    first = low.split()[0] if low.split() else ""
    hit = [n for n in names if first and n.lower().split()[0] == first]
    return hit[0] if len(hit) == 1 else None


def store(con, res, document_id=None):
    """Insert (or replace, same carrier + invoice) one verified bill. Commits. Returns the mobile_bills id."""
    if not res.get("verified"):
        raise BillError("this bill does not add up; nothing stored")
    old = con.execute("SELECT id FROM mobile_bills WHERE carrier=? AND invoice=?", (res["carrier"], res["invoice"])).fetchone()
    if old:
        con.execute("DELETE FROM mobile_bill_items WHERE bill_id=?", (old[0],))
        con.execute("DELETE FROM mobile_bill_lines WHERE bill_id=?", (old[0],))
        con.execute("DELETE FROM mobile_bills WHERE id=?", (old[0],))
    iso = lambda d: d.isoformat() if d else None  # noqa: E731
    bid = con.execute(
        "INSERT INTO mobile_bills(carrier, account_last4, invoice, bill_date, period_start, period_end, due_date, total_due, "
        "bill_total, account_wide, document_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (res["carrier"], res["account_last4"], res["invoice"], iso(res["bill_date"]), iso(res["period_start"]),
         iso(res["period_end"]), iso(res["due_date"]), res["total_due"], res["bill_total"], res["account_wide"],
         document_id)).lastrowid
    for r in res["lines"]:
        lid = con.execute(
            "INSERT INTO mobile_bill_lines(bill_id, person, member, device, phone_last4, plan, devices, perks, surcharges, taxes, "
            "other, line_total, account_share, net) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (bid, r["person"], _member_for(con, r["person"]), r["device"], r["phone_last4"], r["plan"], r["devices"], r["perks"],
             r["surcharges"], r["taxes"], r["other"], r["line_total"], r["account_share"], r["net"])).lastrowid
        for it in r["items"]:
            con.execute("INSERT INTO mobile_bill_items(bill_id, line_id, section, label, amount) VALUES (?,?,?,?,?)",
                        (bid, lid, it["section"], it["label"][:120], it["amount"]))
    for it in res["account_items"]:
        con.execute("INSERT INTO mobile_bill_items(bill_id, line_id, section, label, amount) VALUES (?,NULL,?,?,?)",
                    (bid, it["section"], it["label"][:120], it["amount"]))
    con.commit()
    return bid


def months(con, n=12):
    """Net cost per person per month (the bill's month), newest first: [{month, person, lines, net}]."""
    try:
        rows = con.execute(
            "SELECT substr(b.bill_date, 1, 7) AS month, l.person, COUNT(*) AS lines, ROUND(SUM(l.net), 2) AS net "
            "FROM mobile_bill_lines l JOIN mobile_bills b ON b.id=l.bill_id "
            "GROUP BY 1, LOWER(l.person) ORDER BY 1 DESC, 4 DESC").fetchall()
    except Exception:  # noqa: BLE001 (not migrated yet)
        return []
    keep = []
    for m, *_ in rows:
        if m not in keep:
            keep.append(m)
    keep = set(keep[:n])
    return [{"month": m, "person": p, "lines": c, "net": v} for m, p, c, v in rows if m in keep]


def month_total(con, month):
    r = con.execute("SELECT ROUND(SUM(l.net), 2) FROM mobile_bill_lines l JOIN mobile_bills b ON b.id=l.bill_id "
                    "WHERE substr(b.bill_date, 1, 7)=?", (month,)).fetchone()
    return r[0] or 0.0


def markdown(con, month=None):
    """The monthly report's Mobile section: one table of net cost per person, newest bill month first."""
    rows = months(con, 3)
    if month:
        rows = [r for r in rows if r["month"] <= month] or rows
    if not rows:
        return "No phone bills read yet.\n"
    newest = rows[0]["month"]
    cur = [r for r in rows if r["month"] == newest]
    out = [f"Phone bill of {newest}: {_money.fmt(sum(r['net'] for r in cur))} for {sum(r['lines'] for r in cur)} lines "
           "(account-wide credits shared equally).", "", "| Person | Lines | Net |", "|---|---:|---:|"]
    out += [f"| {r['person']} | {r['lines']} | {_money.fmt(r['net'])} |" for r in cur]
    return "\n".join(out) + "\n"


def import_text(con, text, document_id=None):
    res = read(text, strict=True)
    return res, store(con, res, document_id)


def reparse(con, document_id):
    row = con.execute("SELECT filed_path FROM documents WHERE id=?", (int(document_id),)).fetchone()
    if not row:
        raise BillError("no such document")
    f = paths.ARCHIVE / row[0]
    if not f.is_file():
        raise BillError("the filed copy is not on this PC any more")
    import doc_text
    text, status = doc_text.extract(f)
    if status != "ok":
        raise BillError("the paper has no text layer")
    return import_text(con, text, int(document_id))


def _show(res):
    per = f"{res['period_start']} to {res['period_end']}" if res["period_start"] else "period not found"
    print(f"{res['carrier']} x{res['account_last4'] or '----'} invoice {res['invoice']}, bill of {res['bill_date']} ({per}); "
          f"total {_money.fmt(res['bill_total'])}, due {res['due_date'] or '?'}")
    for r in res["lines"]:
        print(f"  {r['person']:<24} x{r['phone_last4']}  line {r['line_total']:>8.2f}  share {r['account_share']:>7.2f}  "
              f"net {r['net']:>8.2f}   plan {r['plan']:.2f} devices {r['devices']:.2f} perks {r['perks']:.2f} "
              f"surcharges {r['surcharges']:.2f} taxes {r['taxes']:.2f}")
    print(f"  account-wide {res['account_wide']:.2f} shared equally over {len(res['lines'])} lines; "
          + ("everything adds up" if res["verified"] else "DOES NOT ADD UP: " + "; ".join(res["problems"])))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "months":
        con = db.connect()
        for r in months(con, int(argv[1]) if len(argv) > 1 else 12):
            print(f"{r['month']}  {r['person']:<24} {r['lines']} line(s)  {_money.fmt(r['net'])}")
        return 0
    if argv and argv[0] == "reparse" and len(argv) > 1:
        con = db.connect()
        try:
            res, bid = reparse(con, argv[1])
        except BillError as e:
            raise SystemExit(f"error: {e}")
        _show(res)
        print(f"stored as phone bill {bid}")
        return 0
    check = bool(argv) and argv[0] == "check"
    if check:
        argv = argv[1:]
    ap = argparse.ArgumentParser(description="phone bill -> cost per person, no AI")
    ap.add_argument("file"), ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--document-id", type=int, help="the documents row of the filed bill, to link it")
    a = ap.parse_args(argv)
    import doc_text
    text, status = doc_text.extract(a.file)
    if status != "ok":
        raise SystemExit(f"error: cannot read the file ({status})")
    try:
        res = read(text, strict=False)
    except BillError as e:
        raise SystemExit(f"error: {e}")
    _show(res)
    if check or a.dry_run:
        return 0
    if not res["verified"]:
        raise SystemExit("error: not stored, the lines do not add up")
    con = db.connect()
    print(f"stored as phone bill {store(con, res, a.document_id)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
