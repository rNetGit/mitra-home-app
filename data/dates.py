"""Date helpers shared by every module (standard library only).

    parse(v)            ISO date (or datetime string) -> date, None when missing or malformed; never raises
    add_months(d, n)    same day n months on, clamped to the month end (Jan 31 + 1 -> Feb 28/29)
    next_annual(md, today)  next occurrence of an MM-DD on or after today (Feb 29 -> Feb 28 in common years)
    valid_md(md)        "MM-DD" that exists in some year
    md_text(md, year)   "03-14" -> "March 14" (with a year: "March 14, 1980"; short=True: "Mar 14"); "" when not a date
    day_text(v)         ISO date -> "Fri, Oct 23" (with ", 2027" when not this year); anything else unchanged
    time_span(a, b)     "20:00", "20:30" -> "8:00–8:30 PM" (no end: "8:00 PM"; across noon: "11:30 AM–12:30 PM"); "" without a start
    today()             this PC's local date: the one clock every module reads (audit A11); MITRAHOME_TODAY=YYYY-MM-DD
                        fixes it for a test or a demo, anything else is ignored
    now_iso()           this PC's local time as "YYYY-MM-DDTHH:MM:SS", the one format the app writes (audit S12 / D10:
                        SQLite's CURRENT_TIMESTAMP is UTC, so a row written late in the evening read as tomorrow)
"""
import calendar
import datetime as dt
import os


def today():
    return parse(os.environ.get("MITRAHOME_TODAY")) or dt.date.today()


_today = today  # day_text's own argument is called today


def now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def parse(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except (ValueError, TypeError):
        return None


def parse_any(v):
    """Lenient: ISO first, then 10/15/2026, 15/10/2026, 15.10.2026, 20261015, 'Oct 15, 2026', '15 Oct 2026'.
    Slashed dates are read month-first unless that is impossible. None when nothing fits. Used only to repair old
    rows; new writes must be ISO."""
    d = parse(v)
    if d is not None:
        return d
    s = " ".join(str(v or "").split())
    import re
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", s)
    if m:
        a, b, y = (int(x) for x in m.groups())
        y = y + 2000 if y < 100 else y
        for mo, da in ((a, b), (b, a)):
            try:
                return dt.date(y, mo, da)
            except ValueError:
                continue
        return None
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        try:
            return dt.date(*(int(x) for x in m.groups()))
        except ValueError:
            return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%d %b %Y", "%d %B %Y", "%Y/%m/%d"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def add_months(d, n):
    m = d.month - 1 + n
    y = d.year + m // 12
    m = m % 12 + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def next_annual(md, today):
    try:
        m, d = (int(x) for x in str(md).split("-"))
    except (ValueError, AttributeError):
        return None
    for y in (today.year, today.year + 1):
        try:
            cand = dt.date(y, m, d)
        except ValueError:
            if (m, d) != (2, 29):
                return None
            cand = dt.date(y, 2, 28)
        if cand >= today:
            return cand
    return None


def valid_md(md):
    try:
        m, d = (int(x) for x in str(md).split("-"))
        dt.date(2024, m, d)  # a leap year, so 02-29 is accepted
        return True
    except (ValueError, AttributeError):
        return False


def md_text(md, year=None, short=False):
    if not valid_md(md):
        return ""
    m, d = (int(x) for x in str(md).split("-"))
    name = (calendar.month_abbr if short else calendar.month_name)[m]
    return f"{name} {d}" + (f", {year}" if year else "")


def day_text(v, today=None):
    d = parse(v) if isinstance(v, str) else v if isinstance(v, dt.date) else None
    if not d:
        return v
    today = today or _today()
    return f"{d:%a}, {d:%b} {d.day}" + ("" if d.year == today.year else f", {d.year}")


def _clock(hhmm):
    """'20:30' -> (8, 30, 'PM'); None when not HH:MM."""
    try:
        h, m = (int(x) for x in str(hhmm).split(":"))
    except (TypeError, ValueError):
        return None
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h % 12 or 12, m, "AM" if h < 12 else "PM"


def time_span(start, end=None):
    a, b = _clock(start), _clock(end) if end else None
    if not a:
        return ""
    if not b:
        return f"{a[0]}:{a[1]:02d} {a[2]}"
    head = f"{a[0]}:{a[1]:02d}" + ("" if a[2] == b[2] else f" {a[2]}")
    return f"{head}–{b[0]}:{b[1]:02d} {b[2]}"
