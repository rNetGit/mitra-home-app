"""School calendars read without AI: the text layer of a district's year calendar (a PDF with lines such as
"Sep 7 Labor Day", "Nov 25-27 Thanksgiving Holiday", "Dec 24-Jan 1 Winter Recess") -> the days students have no school
and the early dismissals, for doc_extract's school_calendar type (proposed calendar_days rows an adult accepts in the
Inbox). Nothing leaves this PC. When the layout is not one this reader knows, intake falls back to the family's AI.

  python data/school_calendar.py check FILE      what would be read (nothing is stored)
"""
import argparse
import datetime as dt
import re
import sys

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?"
# "Sep 7", "Nov 25-27", "Dec 24-Jan 1", "Mar 26 - Apr 2"
ENTRY = re.compile(rf"\b{_MON}\s+(\d{{1,2}})(?:\s*[-–]\s*(?:{_MON}\s+)?(\d{{1,2}}))?\s+(?=[A-Za-z])")
FULL_MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
# where a name ends when no other entry follows: the next month's grid, a day tally, a weekday header
STOP = re.compile(rf"\s+(?:{FULL_MONTH}\s+\d{{4}}|School\s+Day|Days\s*=|Su\s+M\s+Tu)\b")
YEAR = re.compile(r"\b(20\d\d)\s*[-–/]\s*(20\d\d|\d\d)\b")
TITLE = re.compile(r"^\s*(.{3,80}?)\s+20\d\d\s*[-–/]\s*(?:20)?\d\d\s+(?:School\s+)?Calendar", re.I)
EARLY = re.compile(r"(?i)early|half[- ]day|dismiss")
SKIP = re.compile(r"(?i)first day|last day|classes resume|school resumes|regents|exam|graduation|picture|open house|"
                  r"board meeting|sports|game")
OFF = re.compile(r"(?i)recess|holiday|vacation|break|no school|closed|do not attend|conference|superintendent|staff|"
                 r"professional|day off|snow|labor|columbus|indigenous|veteran|thanksgiving|christmas|new year|"
                 r"martin luther|presidents|memorial|juneteenth|independence|yom|rosh|eid|diwali|lunar|good friday|"
                 r"easter|passover|election|teacher")
MIN_DAYS = 3


class CalendarError(ValueError):
    pass


def _clean(text):
    t = (text or "").replace("�", "'").replace("’", "'")
    return re.sub(r"\s+", " ", t)


def looks_like(text):
    """True when the first part of the text reads like a school year calendar."""
    head = _clean(text)[:600]
    return bool(re.search(r"(?i)\bschool\b", head) and re.search(r"(?i)calendar", head) and YEAR.search(head))


def _mon(s):
    return MONTHS.index(s[:3].title())


def read(text):
    """-> {"school", "school_year", "days": [{"date", "end", "name", "kind"}], "skipped": [names]} for
    doc_extract.prepare("school_calendar", ...). Raises CalendarError when too little is found."""
    t = _clean(text)
    y = YEAR.search(t[:600])
    if not y:
        raise CalendarError("no school year (such as 2026-2027) near the top")
    first = int(y.group(1))
    second = int(y.group(2)) if len(y.group(2)) == 4 else first + 1
    if second != first + 1:
        raise CalendarError("the school year is not two years in a row")
    m = TITLE.search(t)
    school = (m.group(1).strip(" -:,") if m else "")[:80]
    hits = list(ENTRY.finditer(t))
    days, skipped = [], []
    for i, h in enumerate(hits):
        stop = hits[i + 1].start() if i + 1 < len(hits) else len(t)
        name = t[h.end():stop]
        s = STOP.search(name)
        name = (name[:s.start()] if s else name).strip(" ,;.-")[:80]
        if not name or len(name) < 3:
            continue
        m1, d1 = _mon(h.group(1)), int(h.group(2))
        m2 = _mon(h.group(3)) if h.group(3) else m1
        d2 = int(h.group(4)) if h.group(4) else None
        try:
            a = dt.date(first if m1 >= 6 else second, m1 + 1, d1)  # July..December = the first year
            b = dt.date(first if m2 >= 6 else second, m2 + 1, d2) if d2 else None
        except ValueError:
            continue
        if b and (b < a or (b - a).days > 30):
            b = None
        early = bool(EARLY.search(name))  # "Half Day, Last Day of school" is still an early dismissal
        if not early and SKIP.search(name):
            skipped.append(name)
            continue
        kind = "early" if early else "closure" if OFF.search(name) else None
        if not kind:
            skipped.append(name)
            continue
        days.append({"date": a.isoformat(), "end": b.isoformat() if b else None, "name": name, "kind": kind})
    if len(days) < MIN_DAYS:
        raise CalendarError(f"only {len(days)} day(s) off were found: not a layout this reader knows")
    return {"school": school, "school_year": f"{first}-{str(second)[2:]}", "days": days, "skipped": skipped,
            "confidence": 0.9}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("file")
    a = ap.parse_args(argv)
    import pathlib
    import doc_text
    text, status = doc_text.extract(pathlib.Path(a.file))
    if status != "ok":
        print(f"Could not read the text ({status}).")
        return 1
    try:
        res = read(text)
    except CalendarError as e:
        print(f"Not read: {e}")
        return 1
    print(f"{res['school'] or 'School calendar'} {res['school_year']}: {len(res['days'])} days")
    for d in res["days"]:
        print(f"  {d['date']}{' to ' + d['end'] if d['end'] else ''}  {d['kind']:<7} {d['name']}")
    if res["skipped"]:
        print("Left out (school is on): " + "; ".join(res["skipped"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
