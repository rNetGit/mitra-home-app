"""Personal-data redaction for anything that leaves this PC (standard library only).

  python data/pii.py FILE            show what the AI provider would receive for FILE, and what was masked
  python data/pii.py --text "..."    same for a piece of text
  python data/pii.py read FILE       the masked text only: how Claude Code agents read documents when
                                     config/family.json has "ai": {"agents_read_redacted": true} (scripts/guard_tool.py
                                     then refuses the Read tool on inbox/ and archive/ files). Images cannot be masked.

Three tiers (THREAT_MODEL.md, "T2"):
  HARD   identifiers the extractor never needs: SSN/ITIN/EIN, card and account numbers (8+ digits, with or without
         spaces/dashes), routing numbers, emails, phone numbers, dates of birth, driver licence / passport numbers,
         street addresses. Always masked, e.g. "[ssn]", "[number ending <last4>]", "[email]".
  KNOWN  the household's own names (config/family.json members, privacy.paper_names = full names as printed on
         papers, the family name's surname, plus privacy.extra_terms): pseudonymised to
         "[person1]"... and mapped back locally when the answer comes in (restore()). Off with privacy.redact_names=false.
  SOFT   everything else (vendor names, amounts, dates, medical words): sent as-is, because extraction needs it;
         the prompt (llm.PRIVACY) tells the model to use it only for the requested fields and never repeat it.

Amounts ($1,234.56), ISO and US dates, times, short references and the last four digits of masked numbers survive,
so filing accuracy does not change. `contains_hard(text)` is the output-side guard: anything the model returns, or
anyone types into a form, that still carries a full identifier is refused (validators.text, ai_intake).
"""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# --- spans that must survive masking (dates, amounts, times): swapped for placeholders first, restored last
_KEEP = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b"      # ISO date / datetime
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"                               # US or EU slashed date
    r"|\b\d{1,2}-\d{1,2}-\d{4}\b"                                 # dashed d-m-yyyy
    r"|\b\d{8}\b"                                                # YYYYMMDD (checked in hold())
    r"|(?<![\w.])[$€£₹]\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b"       # amounts with a currency sign
    r"|\b\d{1,3}(?:,\d{3})+(?:\.\d{2})?\b"                        # 1,234,567.89
    r"|\b\d+\.\d{2}\b"                                            # 123.45
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\s?(?:am|pm|AM|PM)?\b"           # times
)
_YYYYMMDD = re.compile(r"\b(20\d{2}|19\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b")

# --- HARD tier
_SSN_LABEL = re.compile(r"(?i)\b(?:ssn|social security(?: number| no\.?| #)?|itin|tin|tax(?:payer)? id(?:entification)?(?: number| no\.?)?)\b[\s:#.-]*(\d[\d\s-]{7,12}\d)")
_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}[- ](?!00)\d{2}[- ](?!0000)\d{4}\b")
_EIN = re.compile(r"\b\d{2}-\d{7}\b")
_CARD = re.compile(r"(?<!\w)(?<!\d\.)\d(?:[ -]?\d){12,18}(?!\w)(?!\.\d)")
_LONG = re.compile(r"(?<!\w)(?<!\d\.)\d(?:[ -]?\d){7,}(?!\w)(?!\.\d)")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<!\w)(?<!\d\.)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\w)(?!\.\d)")
_DOB = re.compile(r"(?i)\b(?:dob|date of birth|birth ?date|born(?: on)?)\b[\s:#.-]*(?:\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
                  r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{1,2},? \d{4}|\d{1,2} (?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.? \d{4})")
_ID_LABEL = re.compile(r"(?i)\b(?:driver'?s? ?lic(?:ense|ence)(?: no\.?| number| #)?|dl ?(?:no\.?|#|number)|passport(?: no\.?| number| #)?|"
                       r"license (?:no\.?|number|#)|member id|policy (?:no\.?|number|#)|account (?:no\.?|number|#)|acct\.? ?(?:no\.?|#)?|"
                       r"routing (?:no\.?|number|#)|iban|swift|medicare (?:no\.?|number|#)|aadhaar|pan(?: no\.?| number)?|vin)\b[\s:#.-]*"
                       r"((?:\d(?:[ -]?\d){5,30}|[A-Z]{0,3}-?\d[A-Z0-9-]{3,30}))")
_ADDRESS = re.compile(r"\b\d{1,6}[A-Za-z]?\s+(?:[A-Z][A-Za-z'.-]*\s){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Court|Ct|"
                      r"Way|Place|Pl|Terrace|Ter|Circle|Cir|Parkway|Pkwy|Highway|Hwy|Trail|Trl|Square|Sq)\b\.?(?:,?\s+(?:Apt|Suite|Ste|Unit|#)\s*[\w-]+)?")
_HARD_GUARD = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|(?<!\w)(?<!\d\.)\d(?:[ -]?\d){8,}(?!\w)(?!\.\d)|\b[\w.+-]+@[\w-]+\.[\w.-]+\b")


def _last4(s):
    d = re.sub(r"\D", "", s)
    return d[-4:]


class Redactor:
    """One instance per outgoing request. redact() masks; restore() maps pseudonyms in the answer back to names."""

    def __init__(self, names=(), extra_terms=(), redact_names=True):
        self.counts = {}
        self.people = {}
        terms = []
        if redact_names:
            for i, n in enumerate(dict.fromkeys(x.strip() for x in names if x and len(x.strip()) >= 3), 1):
                self.people[f"[person{i}]"] = n
                terms.append((n, f"[person{i}]"))
                for part in n.split():  # first or last name on its own ("Dear Alex", "SMITH, ALEX")
                    if len(part) >= 4 and part.lower() != n.lower():
                        terms.append((part, f"[person{i}]"))
            for i, t in enumerate(dict.fromkeys(x.strip() for x in extra_terms if x and len(x.strip()) >= 3), 1):
                self.people[f"[term{i}]"] = t
                terms.append((t, f"[term{i}]"))
        terms.sort(key=lambda x: -len(x[0]))  # longest first so "Sam Lee" wins over "Sam"
        self._names = [(re.compile(r"(?<!\w)" + re.escape(n) + r"(?:'s)?(?!\w)", re.I), tag) for n, tag in terms]

    def _hit(self, kind):
        self.counts[kind] = self.counts.get(kind, 0) + 1

    def redact(self, text):
        if not text:
            return text
        keep = []
        text = _DOB.sub(lambda m: self._hit("date of birth") or "[date of birth]", text)

        def hold(m):
            s = m.group(0)
            if len(s) == 8 and s.isdigit() and not _YYYYMMDD.fullmatch(s):
                return s
            keep.append(s)
            return f"\x00{len(keep) - 1}\x00"
        t = _KEEP.sub(hold, text)

        def tag(kind, repl):
            def f(m):
                self._hit(kind)
                return repl(m) if callable(repl) else repl
            return f
        t = _SSN_LABEL.sub(tag("ssn", "[ssn]"), t)
        t = _SSN.sub(tag("ssn", "[ssn]"), t)
        t = _EIN.sub(tag("tax id", "[tax id]"), t)
        t = _ID_LABEL.sub(tag("id number", lambda m: m.group(0)[:m.start(1) - m.start(0)] + "[id ending " + m.group(1)[-4:] + "]"), t)
        t = _EMAIL.sub(tag("email", "[email]"), t)
        t = _CARD.sub(tag("card/account number", lambda m: f"[number ending {_last4(m.group(0))}]"), t)
        t = _PHONE.sub(tag("phone", "[phone]"), t)
        t = _LONG.sub(tag("card/account number", lambda m: f"[number ending {_last4(m.group(0))}]"), t)
        t = _ADDRESS.sub(tag("address", "[address]"), t)
        for rx, label in self._names:
            t, n = rx.subn(lambda m, label=label: label + ("'s" if m.group(0).lower().endswith("'s") else ""), t)
            if n:
                self.counts["name"] = self.counts.get("name", 0) + n
        return re.sub(r"\x00(\d+)\x00", lambda m: keep[int(m.group(1))], t)

    def restore(self, value):
        """Map [personN]/[termN] in a model answer back to the real words (strings, lists and dicts; others untouched)."""
        if isinstance(value, str):
            for tag, real in self.people.items():
                value = value.replace(tag, real)
            return value
        if isinstance(value, list):
            return [self.restore(v) for v in value]
        if isinstance(value, dict):
            return {k: self.restore(v) for k, v in value.items()}
        return value

    def summary(self):
        return ", ".join(f"{v} {k}" for k, v in sorted(self.counts.items())) or "nothing to mask"


def household_terms():
    """Names to pseudonymise, from config/family.json: members, dashboard users, privacy.extra_terms."""
    import config
    fam = config.family()
    priv = fam.get("privacy") or {}
    if priv.get("redact_names") is False:
        return [], [], False
    names = [m.get("name", "") for m in fam.get("members", [])] + [u.get("name", "") for u in fam.get("dashboard_users", [])]
    names += list(priv.get("paper_names") or [])  # full names as printed on bills and policies ("ALEXANDER Q PATEL")
    return names, list(priv.get("extra_terms") or []) + surname_words(fam.get("family_name")), True


FAMILY_WORDS = {"the", "family", "household", "home", "and", "our"}
PAPER_NAMES_MAX = 20


def surname_words(family_name):
    """'The Patel family' -> ['Patel']: the family name is usually the surname printed on papers."""
    words = re.findall(r"[^\W\d_][\w'-]*", family_name or "")
    return [w for w in words if w.lower() not in FAMILY_WORDS and len(w) >= 3]


def clean_paper_names(text):
    """Names typed one per line -> (names, problems). Letters, spaces, dots, apostrophes and hyphens only."""
    names, problems = [], []
    for line in str(text or "").splitlines():
        n = " ".join(line.split())
        if not n:
            continue
        if len(n) > 80 or not re.fullmatch(r"[^\W\d_]+(?:[ .'-]+[^\W\d_]+)*\.?", n):
            problems.append(f"'{n[:40]}' does not look like a name (letters, spaces, dots, apostrophes and hyphens only)")
        elif n.lower() not in {x.lower() for x in names}:
            names.append(n)
    if len(names) > PAPER_NAMES_MAX:
        problems.append(f"at most {PAPER_NAMES_MAX} names")
    return names, problems


def names_on_papers_missing(fam=None):
    """True when masking probably misses the names printed on papers: someone is known only by one word (a first name
    or nickname) and no paper names are set. Legal first names and surnames would then reach the AI."""
    import config
    fam = fam if fam is not None else config.family()
    priv = fam.get("privacy") or {}
    if priv.get("redact_names") is False or priv.get("paper_names"):
        return False
    people = [m for m in fam.get("members", []) if m.get("role") != "pet"]
    return any(len((m.get("name") or "").split()) < 2 for m in people)


def redactor():
    names, extra, on = household_terms()
    return Redactor(names, extra, redact_names=on)


def redact(text):
    """Convenience: HARD + KNOWN tiers with the household's current settings (no restore map kept)."""
    return redactor().redact(text)


def contains_hard(text):
    """True if text still carries a full identifier (SSN shape, 9+ digit run, email). Dates and amounts never trip it."""
    if not text:
        return False
    t = _KEEP.sub(" ", str(text))
    return bool(_HARD_GUARD.search(t))


def preview(text):
    r = redactor()
    out = r.redact(text)
    return out, r.summary()


READ_MAX = 400_000  # characters an agent gets per file through `read`


def read_masked(path):
    """(masked text, status) for a document, the same extractor and masking as the Python pipeline."""
    import doc_text
    src, status = doc_text.extract(path)
    if status != "ok":
        return "", status
    return redactor().redact(src)[:READ_MAX], "ok"


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "read":
        text, status = read_masked(sys.argv[2])
        if status != "ok":
            sys.exit(f"cannot read {sys.argv[2]} as masked text ({status}): images and scans cannot be masked; "
                     "leave the file for a person (Needs your input)")
        print(text)
        sys.exit(0)
    if len(sys.argv) > 2 and sys.argv[1] == "--text":
        src = " ".join(sys.argv[2:])
    elif len(sys.argv) > 1:
        import doc_text
        src, status = doc_text.extract(sys.argv[1])
        if status != "ok":
            sys.exit(f"could not read {sys.argv[1]}: {status}")
    else:
        sys.exit(__doc__)
    masked, summary = preview(src)
    print(masked[:12000])
    print(f"\n--- masked: {summary}. Only the text above would be sent to the AI provider (first 12000 characters).")
