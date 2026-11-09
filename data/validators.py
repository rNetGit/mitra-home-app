"""Argument validators shared by the assistant (AI-chosen actions) and the dashboard forms (typed input).

Each factory returns a function that gives back the cleaned value or raises ValueError. Text can never start with "-"
(so it cannot be mistaken for a command-line option), contain control characters, be empty/too long, or carry a full
account, card or ID number (last4 only is the rule everywhere; see pii.contains_hard).
"""
import datetime as dt
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import pii  # noqa: E402

ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MD = re.compile(r"^(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")


def text(max_len=120):
    def v(x):
        s = " ".join(str(x).split())
        if not s or len(s) > max_len or s.startswith("-") or any(ord(c) < 32 for c in s):
            raise ValueError("bad text")
        if pii.contains_hard(s):
            raise ValueError("contains a full account, card, ID or SSN-shaped number or an email address; store the last four digits only")
        return s
    return v


def iso_date(x):
    s = str(x)
    if not ISO.match(s):
        raise ValueError("date must be YYYY-MM-DD")
    dt.date.fromisoformat(s)
    return s


def iso_datetime(x):
    """A date and time of day: 'YYYY-MM-DD HH:MM' (24-hour; a 'T' between them is accepted) -> 'YYYY-MM-DD HH:MM'."""
    s = " ".join(str(x).replace("T", " ").split())
    m = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{1,2}):(\d{2})$", s)
    if not m:
        raise ValueError("must be YYYY-MM-DD HH:MM")
    dt.date.fromisoformat(m.group(1))
    h, mi = int(m.group(2)), int(m.group(3))
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError("must be YYYY-MM-DD HH:MM")
    return f"{m.group(1)} {h:02d}:{mi:02d}"


_CLOCK = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$", re.I)


def clock_time(x):
    """A time of day: '17:00', '5pm', '5:30 pm', '9' -> 'HH:MM' (24-hour)."""
    m = _CLOCK.match(str(x if x is not None else "").strip())
    if not m:
        raise ValueError("time must look like 17:00 or 5:30pm")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower().replace(".", "")
    if ap:
        if not 1 <= h <= 12:
            raise ValueError("time must look like 17:00 or 5:30pm")
        h = h % 12 + (12 if ap == "pm" else 0)
    if h > 23 or mi > 59:
        raise ValueError("time must look like 17:00 or 5:30pm")
    return f"{h:02d}:{mi:02d}"


def month_day(x):
    if not MD.match(str(x)):
        raise ValueError("must be MM-DD")
    return str(x)


def num(lo=0, hi=1e9):
    def v(x):
        n = float(x)
        if isinstance(x, bool) or not lo <= n <= hi:
            raise ValueError("number out of range")
        return n
    return v


def money(lo=0, hi=1e9):
    """An amount: accepts numbers or typed text ("1,234.56", "$40"), rounds to the cent, checks the range."""
    import money as _money

    def v(x):
        if isinstance(x, bool):
            raise ValueError("number out of range")
        n = _money.parse(x)
        if not lo <= n <= hi:
            raise ValueError("number out of range")
        return n
    return v


def integer(lo, hi):
    def v(x):
        n = int(x)
        if not lo <= n <= hi or isinstance(x, bool):
            raise ValueError("integer out of range")
        return n
    return v


def one_of(options):
    def v(x):
        if str(x) not in options:
            raise ValueError(f"must be one of {options}")
        return str(x)
    return v
