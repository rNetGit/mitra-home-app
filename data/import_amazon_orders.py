"""Import Amazon order history PDFs (archive/*/other/*amazon_order_history_*.pdf) into amazon_orders.
Idempotent (upsert by order_no; match columns are preserved). Prints parse doubts rather than guessing.
Usage: python data/import_amazon_orders.py [pdf ...]
"""
import glob
import pathlib
import re
import shutil
import subprocess
import sys
from datetime import datetime
import db  # noqa: E402
from money import fmt as _fmt  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
DB = paths.DB
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
DATE_TOTAL = re.compile(rf"(({MONTHS}) \d+, \d{{4}})\s+\$([\d,]+\.\d\d)")
# lines that are page chrome / buttons, never item titles
NOISE = re.compile(
    r"^(Ask Alexa|Buy it again|Write a product|Track package|Get product|View order|Leave seller|Ask Product|"
    r"Return or replace|More options|Print gift|Ready to print|Gift Card is ready|Go to Your Games|Arriving|"
    r"Your package|Problem with order|When will I get|View return|Previous\s|Your return|Your Orders|Orders Buy|"
    r"Your Account|Search all|Hello,|EN Account|All Search|All +Buy|Shopping|Save with|Cre$|discounts|"
    r"\d+ orders placed|An item you have|Review the details|\d+/\d+/\d+,|https?:|ORDER PLACED|\d$)")
MARKER = re.compile(r"^(Return window|Eligible through|Delivered|Return complete|Refunded)")
STOP = re.compile(r"Previous\s+1\s+2\s+3\s+Next|Back to top|Customers who viewed|^\s*Sponsored")


def text_of(pdf):
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout
    try:
        import fitz
        return "\n".join(p.get_text() for p in fitz.open(str(pdf)))
    except ImportError:
        from pypdf import PdfReader
        return "\n".join((p.extract_text(extraction_mode="layout") or "") for p in PdfReader(str(pdf)).pages)


def parse(text, doubts, src):
    blocks, cur, skip = [], None, False
    for ln in text.splitlines():
        if "ORDER PLACED" in ln:
            cur = {"hdr": ln, "body": []}
            blocks.append(cur)
            skip = False
            continue
        if cur is None:
            continue
        if STOP.search(ln):
            skip = True
        if re.match(r"^\d+/\d+/\d+, .*Your Orders", ln):
            skip = False  # next page of the listing
            continue
        if not skip:
            cur["body"].append(ln)
    out = []
    for b in blocks:
        on = re.search(r"ORDER #\s*(\d{3}-\d{7}-\d{7})", b["hdr"])
        meta = next((l for l in b["body"] if DATE_TOTAL.search(l)), None)
        if not on or not meta:
            doubts.append(f"{src}: unparsable order header {b['hdr'].strip()[:90]}")
            continue
        order_no = on.group(1)
        dm = DATE_TOTAL.search(meta)
        date = datetime.strptime(dm.group(1), "%B %d, %Y").date().isoformat()
        total = float(dm.group(3).replace(",", ""))
        sm = re.match(r"\s+([A-Z][a-z]+) [A-Z][a-z]+", meta[dm.end():])
        ship = sm.group(1) if sm else None
        full = "\n".join(b["body"])
        items, buf = [], []
        for ln in b["body"]:
            if ln is meta:
                continue
            s = ln.strip()
            if not s:
                continue
            if MARKER.match(s):
                if buf:
                    items.append(" ".join(buf)); buf = []
                continue
            if NOISE.match(s) or "View order details" in s or re.match(rf"^({MONTHS}) \d+, \d{{4}}$", s):
                continue
            buf.append(re.split(r"\s{3,}", s)[0])
        if buf:
            items.append(" ".join(buf))
        items = [re.sub(r"\s+", " ", i)[:80] for i in items if len(i) > 3]
        if any(re.search(r"\S {6,}\S", l) and not NOISE.match(l.strip()) and "View" not in l and "Leave" not in l
               and "Ask" not in l and "Return" not in l for l in b["body"]):
            doubts.append(f"{order_no}: multi-column item layout; titles may be truncated or merged")
        if re.search(r"Refunded|refund has been issued|Return complete", full):
            status = "refunded"
        elif any(re.search(r"Gift Card|Online Game Code", i, re.I) for i in items):
            status = "gift_card"
        elif items:
            status = "delivered"
        else:
            status = "other"
            doubts.append(f"{order_no} {date} {_fmt(total)}: no item titles in the PDF text (status 'other')")
        out.append(dict(order_no=order_no, order_date=date, total=total, ship_to=ship,
                        status=status, items=" | ".join(items)))
    return out


def main():
    pdfs = sys.argv[1:] or sorted(glob.glob(str(paths.ARCHIVE / "*" / "other" / "*amazon_order_history_*.pdf")))
    con = db.connect(DB)
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name='amazon_orders'").fetchone():
        sys.exit("run data/migrate_015_amazon_orders.py first")
    doubts, orders = [], {}
    for p in pdfs:
        p = pathlib.Path(p).resolve()
        rel = "archive/" + p.relative_to(paths.ARCHIVE).as_posix()
        d = con.execute("SELECT id FROM documents WHERE REPLACE(filed_path,'\\','/')=?", (rel,)).fetchone()
        for o in parse(text_of(p), doubts, p.name):
            o["document_id"] = d[0] if d else None
            if o["order_no"] in orders:
                doubts.append(f"duplicate order {o['order_no']}; kept first")
                continue
            orders[o["order_no"]] = o
    for o in orders.values():
        con.execute("""INSERT INTO amazon_orders(order_no,order_date,total,ship_to,status,items,document_id)
            VALUES(:order_no,:order_date,:total,:ship_to,:status,:items,:document_id)
            ON CONFLICT(order_no) DO UPDATE SET order_date=excluded.order_date,total=excluded.total,
              ship_to=excluded.ship_to,status=excluded.status,items=excluded.items,document_id=excluded.document_id""", o)
    con.commit()
    tot = sum(o["total"] for o in orders.values())
    print(f"{len(orders)} orders parsed, total {_fmt(tot)}; compare with the order count and total shown on the orders page")
    for o in sorted(orders.values(), key=lambda x: x["order_date"], reverse=True):
        print(f"  {o['order_date']} {o['order_no']} ${o['total']:>7.2f} {o['status']:<9} {o['ship_to'] or '-':<7} {o['items'][:75]}")
    for d in doubts:
        print("DOUBT:", d)


if __name__ == "__main__":
    main()
