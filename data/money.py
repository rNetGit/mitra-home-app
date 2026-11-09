"""Money: exact arithmetic in integer cents behind one module, formatted in the family's currency.

    fmt(1234.5)        -> "$1,234.50"      (symbol from config/family.json `currency`, default USD)
    fmt(-20, 0)        -> "-$20"
    cents(12.345)      -> 1235              integer minor units, rounded half-up like a bank statement
    from_cents(1235)   -> 12.35
    round2(0.1 + 0.2)  -> 0.3               the value a column should store
    eq(a, b)           -> True when a and b are the same amount to the cent (never compare floats directly)
    total([...])       -> sum in cents, returned as a 2-decimal float
    parse("$1,234.56") -> 1234.56           ("(12.00)" and "-12.00" are negative; "1.234,56" is read as 1234.56)

Storage: amounts stay REAL in the family's currency, because the SQL views, the Claude Code agents and the family's
own ad-hoc queries all read and write dollars (or pounds, or rupees). Every Python write goes through round2(), so a
stored value is always a whole number of cents, and `transactions.amount_cents` / `bills.amount_cents` are generated
integer columns (migration 027) for exact grouping and matching in SQL. Comparisons in Python use cents()/eq().
"""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import config

SYMBOLS = {"USD": "$", "CAD": "C$", "AUD": "A$", "NZD": "NZ$", "SGD": "S$", "EUR": "€", "GBP": "£",
           "INR": "₹", "JPY": "¥", "CHF": "CHF ", "SEK": "kr ", "NOK": "kr ", "DKK": "kr "}
_CENT = Decimal("0.01")


def symbol(code=None):
    code = (code or config.currency() or "USD").upper()
    return SYMBOLS.get(code, code + " ")


def fmt(value, decimals=2, code=None):
    v = float(value or 0)
    s = symbol(code)
    body = f"{abs(v):,.{decimals}f}"
    return f"-{s}{body}" if v < 0 else f"{s}{body}"


def _dec(value):
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def cents(value):
    """Integer minor units (half-up). cents(0.1 + 0.2) == 30, cents("12.345") == 1235."""
    try:
        return int((_dec(value) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"not an amount: {value!r}") from None


def from_cents(c):
    return float(Decimal(int(c)) / 100)


def round2(value):
    """The float a money column should store: exactly a whole number of cents."""
    return from_cents(cents(value))


def eq(a, b):
    return cents(a) == cents(b)


def total(values):
    return from_cents(sum(cents(v) for v in values if v is not None))


_NUM = re.compile(r"^\(?-?\(?\s*[^\d\-]*\s*(-?)([\d.,\s]+)\)?$")


def parse(text):
    """An amount typed or printed by a person -> float rounded to the cent. ValueError when it is not an amount."""
    if isinstance(text, (int, float, Decimal)):
        return round2(text)
    s = str(text or "").strip()
    neg = s.startswith("(") and s.endswith(")") or s.startswith("-") or s.endswith("-") or s.lower().endswith(" cr")
    s = re.sub(r"(?i)\s*cr$", "", s).strip("() ").lstrip("-").rstrip("-").strip()
    s = re.sub(r"^[A-Za-z$€£₹¥\s]{1,5}", "", s)  # a currency sign or code in front: "$", "CHF ", "USD "
    if not s or not re.fullmatch(r"[\d.,\s]+", s) or not re.search(r"\d", s):
        raise ValueError(f"not an amount: {text!r}")
    s = re.sub(r"\s", "", s)
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):   # 1.234,56
            s = s.replace(".", "").replace(",", ".")
        else:                              # 1,234.56
            s = s.replace(",", "")
    elif "," in s:
        head, _, tail = s.rpartition(",")
        s = head.replace(",", "") + "." + tail if len(tail) == 2 and head else s.replace(",", "")
    v = round2(s)
    return -v if neg and v > 0 else v
