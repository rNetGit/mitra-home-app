"""Tax-prep folder: per tax year, which expected documents are on file and the year's tax-relevant totals.

  python data/tax_prep.py [YEAR]     -> reports/YYYY_tax_prep.md  (default: current year)
Presence is judged from `documents` (filed_path/vendor/doc_type/notes). The expected-document list is a
generic checklist; add your own banks/brokers in config/tax_prep.json (see below). 1099s/W-2s normally arrive by
Jan 31 (1099-B/consolidated by mid-Feb), so for the current year most are "not yet issued".

config/tax_prep.json (optional):
  {"payers": ["Chase", "Credit Union X"],             one "1099-INT <payer>" line each
   "state_tax_keywords": ["state dtf"],               extra words that mark estimated state tax payments
   "education_payee_patterns": ["%UNIVERSITY BURSAR%"]}   SQL LIKE patterns on UPPER(description) for tuition payments
"""
import pathlib
import re
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
import dates  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402
import country  # noqa: E402
import db  # noqa: E402
from money import fmt as _fmt  # noqa: E402

_CFG = config.data_file("tax_prep.json") or {}
_PAYERS = [p for p in _CFG.get("payers", []) if p]
_STATE_KEYS = [k.lower() for k in _CFG.get("state_tax_keywords", []) if k]
_EDU_PATTERNS = [p.upper() for p in _CFG.get("education_payee_patterns", []) if p]

def expected(prof=None):
    """(label, keyword(s) searched in lower-cased filed_path+vendor+notes, note) from the country profile
    (packs/country/<code>.json `tax.checklist`), plus one line per payer named in config/tax_prep.json."""
    prof = prof or country.profile()
    tax = prof.get("tax", {})
    form = tax.get("payer_form", "interest statement")
    rows = [tuple(r) for r in tax.get("checklist", [])]
    payers = [(f"{form} {p}", [form.split("-")[0].lower(), p.lower()], "") for p in _PAYERS]
    out = []
    for label, keys, note in rows:
        keys = list(keys)
        if "estimated" in keys or "payment on account" in keys or "advance tax" in keys:
            keys += _STATE_KEYS
        out.append((label, keys, note))
    return out[:2] + payers + out[2:] if len(out) >= 2 else out + payers


EXPECTED = expected()  # kept for older callers; build() re-reads the profile


def build(con, year):
    docs = [(str(p or "").lower(), str(v or "").lower(), str(n or "").lower(), str(t or "").lower(), str(dd or ""))
            for p, v, n, t, dd in con.execute("SELECT filed_path, vendor, notes, doc_type, doc_date FROM documents")]
    ystr = str(year)
    tax_docs = [d for d in docs if ystr in d[0] or ystr in d[4]]
    prof = country.profile()
    tax = prof.get("tax", {})
    lines = [f"# Tax prep {year}", "", f"_Generated {dates.today()}. Source: documents + transactions in family.db. "
             f"Country profile: {prof.get('name', prof.get('code'))} ({tax.get('authority', '')}; tax year from {tax.get('year_start', '01-01')})._", ""]
    if tax.get("filing_note"):
        lines += [f"_{tax['filing_note']}_", ""]
    lines += ["## Expected documents", "", "| Document | On file? | Note |", "|---|---|---|"]
    for label, keys, note in expected(prof):
        def has(hay, k):  # whole-token match; '_' and '-' and ' ' count as separators
            return re.search(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", hay) is not None

        def match(d):
            hay = " ".join(d)
            if label.startswith(tuple(f"{tax.get('payer_form', 'interest statement')} {p}" for p in _PAYERS)):
                return has(hay, keys[0]) and any(has(hay, k) for k in keys[1:])  # the form plus the named payer
            return any(has(hay, k) for k in keys)
        hit = [d for d in tax_docs if match(d)]
        status = "yes" if hit else ("not yet issued" if year >= dates.today().year else "MISSING")
        lines.append(f"| {label} | {status} | {note} |")
    lines += ["", "## Filed tax documents", ""]
    tdocs = [r for r in con.execute("SELECT filed_path, vendor, doc_date FROM documents WHERE doc_type='tax' OR filed_path LIKE '%tax%' ORDER BY filed_path")
             if ystr in str(r[0]) or ystr in str(r[2] or "")]
    lines += [f"- {r[0]}" for r in tdocs] or ["_none_"]
    q = lambda s, *a: con.execute(s, a).fetchall()
    lines += ["", "## Totals from bank/card data (calendar year to date)", ""]
    def tot(label, sql, *a):
        v = q(sql, *a)[0][0]
        lines.append(f"- {label}: {_fmt(abs(v or 0))}")
    y0, y1 = f"{year}-01-01", f"{year}-12-31"
    tot("Tax payments (federal/state/property/school, txn_type 'tax', money out)",
        "SELECT SUM(amount_cents)/100.0 FROM transactions WHERE txn_type='tax' AND amount<0 AND txn_date BETWEEN ? AND ?", y0, y1)
    tot("Tax refunds received", "SELECT SUM(amount_cents)/100.0 FROM transactions WHERE txn_type='tax' AND amount>0 AND txn_date BETWEEN ? AND ?", y0, y1)
    tot("Bank interest credited (txn_type 'interest')", "SELECT SUM(amount_cents)/100.0 FROM transactions WHERE txn_type='interest' AND txn_date BETWEEN ? AND ?", y0, y1)
    if _EDU_PATTERNS:
        like = " OR ".join("UPPER(description) LIKE ?" for _ in _EDU_PATTERNS)
        v = con.execute(f"SELECT SUM(amount_cents)/100.0 FROM transactions WHERE ({like}) AND amount<0 AND txn_date BETWEEN ? AND ?",
                        (*_EDU_PATTERNS, y0, y1)).fetchone()[0]
        lines.append(f"- Education payments (config education_payee_patterns) - for 1098-T / tuition credit: {_fmt(abs(v or 0))}")
    try:
        import home_office as ho
        for p in ho._profile(con, year):
            c = ho.compute(con, year, p["who"])
            lines += ["", f"## Home office ({p['who']})", "",
                      f"- Business-use share {c['pct']:.1%}; simplified method {_fmt(c['simplified'])}; regular method {_fmt(c['regular'])}",
                      f"- Open questions: {len(c['issues'])}. Full detail: Money > Home office"]
    except (ImportError, sqlite3.OperationalError):
        pass
    lines += ["", "## Notes", "- This is a records checklist, not tax advice. Confirm treatment with your preparer.",
              "- Drop each form in the Inbox when it arrives; it is filed with that year's tax papers."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    year = int(sys.argv[1]) if len(sys.argv) > 1 else dates.today().year
    con = db.connect(paths.DB, readonly=True)
    out = paths.REPORTS / f"{year}_tax_prep.md"
    out.write_text(build(con, year), encoding="utf-8")
    print(out)
