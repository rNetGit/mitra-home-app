"""Fail if the template still contains the original family's personal strings.

Run before publishing or sharing:  python scripts/verify_clean.py
Generic leftovers are listed in TERMS below. The maintainer's PRIVATE terms (names, emails, cities, paths of the
original family) live in scripts/private_terms.txt, which is git-ignored so it never ships. Copy
scripts/private_terms.example.txt to private_terms.txt and fill it in.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TERMS = ['New York', 'NYS ', 'KeyBank', 'TrustCo', 'NinjaTrader', 'Trump Account', 'UB EPAY']
private = ROOT / "scripts" / "private_terms.txt"
if private.exists():
    TERMS += [l.strip() for l in private.read_text(encoding="utf-8").splitlines() if l.strip() and not l.startswith("#")]
# Shapes that mean "a real household's facts leaked into code", regardless of the family: last4 maps, card refs,
# "the user said/asked", dated anecdotes, references to specific document or bill ids.
SHAPES = [
    r'"\d{4}":\s*"\d{4}"',                       # {"9273": "3192"} last4 alias maps
    r'\bx\d{4,5}\b',                              # card/account refs like x1000 (outside f-strings, see ALLOW)
    r'\b(card|account|ending)\s+(ending\s+)?\d{4,}\b',
    r'\b(the\s+)?user\s+(asked|requested|confirmed|reported)\b',
    r'\(user:\s',                                 # "(user: one credit per cycle)"
    r'\brequested by the user\b',
    r'\bscreenshot\b',
    r'\(20\d\d-\d\d-\d\d\)',                      # dated anecdotes "(2026-10-04)"
    r'\b(doc|document|bill|txn|row)\s+#?\d{1,4}\b(?!\s*(fields|rows|checks))',
    r'\bexpected\s+\d+\s*(orders|rows|txns)\b',
]
# Lines that legitimately contain a shape (format strings, prose about the feature itself).
ALLOW = [r'\bx\{', r'x\{r\[', r'f"[^"]*x\{', r"f'[^']*x\{", r'policy x', r'plate x', r'x<last4>', r'x\{l', r'x\{last4']
SKIP_DIRS = {"__pycache__", ".git", "archive", "inbox", "reports", "brief", "logs", ".pytest_cache", ".ruff_cache",
             "backups_pre_upgrade",  # copies of OLD code kept by the updater; not part of the shipped tree
             "tests",  # synthetic account numbers and phrases on purpose
             "node_modules", "build", ".gradle", ".venv", "venv"}  # third-party packages and build output
SKIP_FILES = {"verify_clean.py", "private_terms.txt", "private_terms.example.txt", "family.json", "onboard_state.json",
              "CHANGELOG.md", "smoke_test.py"}  # the smoke test holds synthetic account numbers on purpose
TEXT = {".py", ".md", ".bat", ".sh", ".sql", ".json", ".txt", ".example", ".yml", ".yaml", ".cfg", ".toml"}
pat = re.compile("|".join(re.escape(x) for x in TERMS), re.I)
shape = re.compile("|".join(SHAPES), re.I)
allow = re.compile("|".join(ALLOW))
# A state list naming every US state is not a leftover: only these exact lines may say New York.
TERM_ALLOW = re.compile(r'^\s*"NY": \{"name": "New York"|"NEW YORK": "NY"')
# the author's own name, as it appears in NOTICE and pyproject.toml: intended, not a leftover
AUTHOR = re.compile(r"Rajesh Katukojwala \(rNetGit\)")

hits = 0
for p in sorted(ROOT.rglob("*")):
    if (not p.is_file() or p.name in SKIP_FILES or SKIP_DIRS & set(p.relative_to(ROOT).parts)
            or p.suffix not in TEXT):
        continue
    for n, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        why = "term" if pat.search(AUTHOR.sub("", line)) and not TERM_ALLOW.search(line) else ("shape" if shape.search(line) and not allow.search(line) else "")
        if why:
            hits += 1
            if "--quiet" not in sys.argv:
                print(f"{p.relative_to(ROOT)}:{n}: [{why}] {line.strip()[:110]}")
if not private.exists():
    print("note: scripts/private_terms.txt not found; only generic terms were checked")
print(f"{hits} hit(s)")
sys.exit(1 if hits else 0)
