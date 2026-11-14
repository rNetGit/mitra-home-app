"""The detailed account types (`accounts.subtype`, migration 070) and the groups Money shows them in.

Each subtype belongs to one group (bank, card, investment, insurance, loan) and one coarse `accounts.type`
(checking / savings / credit / loan / investment), which the older code keeps using for signs and spending rules.
`guess(name, institution)` is the no-AI guess bank sync and the migration use; a type the family picks by hand is
locked (`accounts.subtype_locked`) and never guessed again.

  python data/account_types.py            list the groups and their types
  python data/account_types.py guess NAME [INSTITUTION]
"""
import re
import sys

# group key -> label, in the order Money lists them; `owed` = balances are what the family owes
GROUPS = {
    "bank": {"label": "Bank accounts", "owed": False},
    "card": {"label": "Credit cards", "owed": True},
    "investment": {"label": "Investments", "owed": False},
    "insurance": {"label": "Life insurance", "owed": False},
    "loan": {"label": "Mortgage and loans", "owed": True},
}

# subtype -> (group, coarse accounts.type, label)
SUBTYPES = {
    "checking": ("bank", "checking", "Checking"),
    "savings": ("bank", "savings", "Savings"),
    "money_market": ("bank", "savings", "Money market"),
    "credit_card": ("card", "credit", "Credit card"),
    "store_card": ("card", "credit", "Store card"),
    "brokerage": ("investment", "investment", "Brokerage"),
    "401k": ("investment", "investment", "401(k) / 403(b)"),
    "ira": ("investment", "investment", "IRA"),
    "roth_ira": ("investment", "investment", "Roth IRA"),
    "529": ("investment", "investment", "529 college plan"),
    "treasury_direct": ("investment", "investment", "TreasuryDirect"),
    "cd": ("investment", "investment", "CD"),
    "hsa": ("investment", "investment", "HSA"),
    "other_investment": ("investment", "investment", "Other investment"),
    "life_whole": ("insurance", "investment", "Whole life"),
    "life_universal": ("insurance", "investment", "Universal life"),
    "life_term": ("insurance", "investment", "Term life"),
    "mortgage": ("loan", "loan", "Mortgage"),
    "heloc": ("loan", "loan", "Home equity (HELOC)"),
    "auto": ("loan", "loan", "Auto loan"),
    "furniture": ("loan", "loan", "Furniture / store loan"),
    "student": ("loan", "loan", "Student loan"),
    "personal": ("loan", "loan", "Personal loan"),
    "other_loan": ("loan", "loan", "Other loan"),
}

# coarse accounts.type -> the subtype an account gets when nothing better is known
DEFAULT_OF_TYPE = {"checking": "checking", "savings": "savings", "credit": "credit_card", "loan": "other_loan",
                   "investment": "other_investment"}

OWNERSHIP = ("individual", "joint")

# (subtype, words) tried in order on "name institution", lower case; the first hit wins.
# Narrow phrases come before broad ones ("money market" before "market", "auto loan" before "loan").
_RULES = (
    ("mortgage", (r"mortgage", r"home loan")),
    ("heloc", (r"heloc", r"home equity", r"equity line")),
    ("auto", (r"auto loan", r"car loan", r"vehicle loan", r"auto finance", r"motor credit", r"toyota financial",
              r"honda financial", r"ally auto")),
    ("student", (r"student", r"navient", r"nelnet", r"sallie mae", r"mohela")),
    ("furniture", (r"furniture", r"ashley", r"rooms to go", r"financing plan")),
    ("personal", (r"personal loan",)),
    ("other_loan", (r"\bloan\b",)),
    ("529", (r"\b529\b", r"college sav")),
    ("hsa", (r"\bhsa\b", r"health sav", r"healthequity")),
    ("roth_ira", (r"\broth\b",)),
    ("401k", (r"\b40[13]\s?\(?[kb]\)?", r"retirement plan", r"\btsp\b", r"thrift savings")),
    ("ira", (r"\bira\b", r"\bsep\b", r"rollover")),
    ("treasury_direct", (r"treasury", r"i bond", r"savings bond")),
    ("cd", (r"\bcd\b", r"certificate of deposit", r"certificate")),
    ("life_whole", (r"whole life",)),
    ("life_universal", (r"universal life",)),
    ("life_term", (r"term life",)),
    ("brokerage", (r"brokerage", r"invest", r"individual account", r"trading", r"securities", r"robinhood",
                   r"schwab one", r"fidelity account")),
    ("money_market", (r"money market", r"\bmmda\b", r"\bmma\b")),
    ("store_card", (r"redcard", r"store card", r"synchrony", r"comenity")),
    ("credit_card", (r"credit", r"\bcard\b", r"visa", r"mastercard", r"\bamex\b", r"american express",
                     r"sapphire", r"freedom", r"platinum", r"gold card", r"rewards")),
    ("savings", (r"saving", r"reserve", r"emergency fund")),
    ("checking", (r"checking", r"\bchk\b", r"spending", r"everyday")),
)
_COMPILED = tuple((sub, tuple(re.compile(w) for w in words)) for sub, words in _RULES)


def group_of(subtype):
    return SUBTYPES.get(subtype or "", (None,))[0]


def coarse(subtype):
    """The accounts.type that goes with a subtype (None when it is not a known one)."""
    s = SUBTYPES.get(subtype or "")
    return s[1] if s else None


def label(subtype):
    s = SUBTYPES.get(subtype or "")
    return s[2] if s else (subtype or "").replace("_", " ")


def owed(subtype):
    g = group_of(subtype)
    return bool(g and GROUPS[g]["owed"])


def guess(name, institution=None):
    """(subtype, sure) from the account's name and bank. sure = a word matched; False = fell back to checking."""
    text = f"{name or ''} {institution or ''}".lower()
    for sub, pats in _COMPILED:
        if any(p.search(text) for p in pats):
            return sub, True
    return "checking", False


def resolve(type_=None, name=None, institution=None):
    """The subtype for an account whose coarse type is known (or not): a guess that agrees with the coarse type wins,
    else the coarse type's default."""
    sub, sure = guess(name, institution)
    if type_ in DEFAULT_OF_TYPE:
        if sure and coarse(sub) == type_:
            return sub
        return DEFAULT_OF_TYPE[type_]
    return sub


def choices():
    """[(group label, [(subtype, label)])] for a select box, in the Money order."""
    return [(g["label"], [(k, v[2]) for k, v in SUBTYPES.items() if v[0] == key]) for key, g in GROUPS.items()]


def main(argv):
    if len(argv) >= 2 and argv[0] == "guess":
        sub, sure = guess(argv[1], argv[2] if len(argv) > 2 else None)
        print(f"{sub} ({label(sub)}){'' if sure else ' - not sure, fell back to checking'}")
        return 0
    if argv:
        print(__doc__)
        return 2
    for glabel, subs in choices():
        print(glabel)
        for k, lab in subs:
            print(f"  {k:<17} {lab}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
