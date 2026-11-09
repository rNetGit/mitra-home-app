"""Missing-statement watch: which accounts are due (or overdue) for a new statement.

Statement dates come from archive filenames  YYYY-MM-DD_<vendor>_<last4>_statement.<ext>  (the intake
agent's naming) or YYYY-MM-DD_<account name>_x<last4>_statement.<ext> (statements filed by ai_intake / the review queue). Cadence is inferred from the median gap between an account's statements.
  python data/statement_watch.py          -> prints the table
"""
import datetime as dt
import pathlib
import re
import statistics
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402
from dates import parse as _pd  # noqa: E402

# vendor may hold underscores ("everyday_checking"); the account's last4 may carry an "x" (statements this app files)
PAT = re.compile(r"(\d{4}-\d{2}-\d{2})_(\w+?)_x?(\d{4})_statement")


def aliases():
    """One statement PDF covering several accounts is filed under the primary account's last4.
    Families map the other accounts to it in config/family.json:  "statement_aliases": {"<last4>": "<primary last4>"}"""
    raw = config.family().get("statement_aliases") or {}
    return {str(k): str(v) for k, v in raw.items()}


def statement_dates(con):
    """{(vendor, last4): sorted [date,...]} from documents.filed_path."""
    out = {}
    for (p,) in con.execute("SELECT filed_path FROM documents WHERE doc_type='statement'"):
        m = PAT.search(str(p).replace("\\", "/").split("/")[-1])
        if m:
            d, vend, l4 = m.groups()
            if _pd(d):
                out.setdefault((vend, l4), set()).add(_pd(d))
    return {k: sorted(v) for k, v in out.items()}


def watch(con, today):
    dates = statement_dates(con)
    rows = []
    alias = aliases()
    # investment accounts have holdings snapshots, not periodic statements
    for aid, name, typ, last4 in con.execute(
            "SELECT id, name, type, last4 FROM accounts WHERE type<>'investment' ORDER BY type, name"):
        key = alias.get(last4, last4)
        ds = next((v for (vend, l4), v in dates.items() if l4 == key), [])
        if not ds:
            rows.append({"account": name, "last4": last4, "cadence": "", "last_stmt": None, "expected": None,
                         "status": "no statements yet", "missing": []})
            continue
        gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
        med = statistics.median(gaps) if gaps else 31
        if med <= 45:
            cadence, step = "monthly", 31
        elif med <= 120:
            cadence, step = "quarterly", 91
        else:
            cadence, step = "monthly (exports)", 31
        expected = ds[-1] + dt.timedelta(days=step)
        if today > expected + dt.timedelta(days=7):
            status = "overdue"
        elif today >= expected - dt.timedelta(days=5):
            status = "due now"
        else:
            status = "ok"
        missing = []
        if cadence == "monthly":
            have = {(d.year, d.month) for d in ds}
            y, m = ds[0].year, ds[0].month
            while (y, m) < (ds[-1].year, ds[-1].month):
                if (y, m) not in have:
                    missing.append(f"{y}-{m:02d}")
                m += 1
                if m == 13:
                    y, m = y + 1, 1
        rows.append({"account": name, "last4": last4, "cadence": cadence, "last_stmt": ds[-1],
                     "expected": expected, "status": status, "missing": missing})
    return rows


if __name__ == "__main__":
    con = db.connect(paths.DB, readonly=True)
    for r in watch(con, dates.today()):
        print(f"{r['status']:18} {r['account'][:42]:42} x{r['last4']}  last={r['last_stmt']}  "
              f"next~{r['expected']}  missing={','.join(r['missing']) or '-'}")
