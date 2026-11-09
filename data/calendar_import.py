"""A school's, college's or employer's year calendar read from a link or a file: the days off (and a school's early
dismissals) become proposed calendar_days rows for the people linked to it; an adult accepts them in the Inbox.

Readers, cheapest first: an .ics calendar feed (no AI), a PDF in a layout school_calendar.py knows (no AI), then the
family's AI on the masked text (doc_extract's school_calendar reading; only when an AI provider is set). Dates are only
ever read from the calendar itself: nothing is guessed. A web page that is only a list of links is searched for the
calendar file it points to (calendar_find.links_in).

  python data/calendar_import.py check FILE_OR_URL [--employer]     what would be read (nothing is stored)

Library: read(body, ctype, name, kind) -> {"school", "school_year", "days": [{day, end, kind, name}], "how"};
store(con, org, details, url=None) -> rows added.
"""
import argparse
import datetime as dt
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import dates  # noqa: E402
import school_calendar as sc  # noqa: E402

MAX_DAYS = 150
WORK_OFF = re.compile(r"(?i)holiday|closed|closure|day off|no work|observed|recess|break|vacation|" + sc.OFF.pattern.replace("(?i)", ""))
SHOWN = {"ics": "the calendar feed", "pdf": "the calendar file", "page": "the web page", "ai": "your AI reading the calendar"}


class ImportError_(ValueError):
    pass


def _year_label(days):
    first = min(dt.date.fromisoformat(d["day"]) for d in days)
    y = first.year if first.month >= 7 else first.year - 1
    return f"{y}-{str(y + 1)[2:]}"


def _keep(name, kind):
    """-> 'closure' | 'early' | 'holiday' | None for one entry's name."""
    if kind == "employer":
        return "holiday" if WORK_OFF.search(name) and not re.search(r"(?i)meeting|deadline|training|review", name) else None
    if sc.EARLY.search(name):
        return "early"
    if sc.SKIP.search(name):
        return None
    return "closure" if sc.OFF.search(name) else None


# ---------------------------------------------------------------- .ics
def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))


def _ics_date(v):
    m = re.match(r"(\d{4})(\d{2})(\d{2})", v or "")
    return dt.date(int(m[1]), int(m[2]), int(m[3])) if m else None


def read_ics(text, kind="school", today=None):
    today = today or dates.today()
    lo, hi = today - dt.timedelta(days=14), today + dt.timedelta(days=430)
    days, seen = [], set()
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _unfold(text), re.S):
        f = {}
        for line in ev.split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                f.setdefault(k.split(";")[0].upper(), (k.upper(), v.strip()))
        name = (f.get("SUMMARY") or ("", ""))[1]
        name = " ".join(name.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\", "").split())[:80]
        start = _ics_date((f.get("DTSTART") or ("", ""))[1])
        if not name or not start or not (lo <= start <= hi):
            continue
        what = _keep(name, kind)
        if not what:
            continue
        end = None
        dkey, dval = f.get("DTEND") or ("", "")
        e = _ics_date(dval)
        if e and "VALUE=DATE" in dkey and len(dval) == 8:
            e -= dt.timedelta(days=1)  # an all-day event's end is the day after
        if e and start < e <= start + dt.timedelta(days=30):
            end = e.isoformat()
        key = (start, what, name.lower())
        if key not in seen:
            seen.add(key)
            days.append({"day": start.isoformat(), "end": end, "kind": what, "name": name})
    days.sort(key=lambda d: d["day"])
    if not days:
        raise ImportError_("the calendar feed has no days off in the coming year")
    return {"school": "", "school_year": _year_label(days), "days": days[:MAX_DAYS], "how": "ics"}


# ---------------------------------------------------------------- text (PDF or page)
def _html_text(raw):
    import html
    t = re.sub(r"(?is)<(script|style|nav|header|footer)\b.*?</\1>", " ", raw)
    t = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", t)
    return html.unescape(re.sub(r"<[^>]+>", " ", t))


def _ai_ready():
    import llm
    s = llm.settings()
    return s["provider"] not in ("none", "claude_code", "") and not llm.training_risk(s)


def read_text(text, kind="school", how="pdf"):
    """Days from a calendar's text: the no-AI reader first, then the family's AI (masked text)."""
    try:
        r = sc.read(text)
        days = [{"day": d["date"], "end": d["end"], "kind": d["kind"], "name": d["name"]} for d in r["days"]]
        return _for_kind({"school": r["school"], "school_year": r["school_year"], "days": days, "how": how}, kind)
    except sc.CalendarError:
        pass
    if not _ai_ready():
        raise ImportError_("this calendar's layout is not one the app reads by itself, and no AI is set up to read it "
                           "(Settings > Connections > AI)")
    import doc_extract
    import llm
    try:
        d, errs = doc_extract.read("school_calendar", text)
        if errs:
            raise ImportError_("your AI could not read the days off from it")
        c = doc_extract.prepare("school_calendar", d)
    except llm.LLMError as e:
        raise ImportError_(f"your AI could not be reached ({str(e)[:120]})") from None
    except doc_extract.Unusable as e:
        raise ImportError_(f"your AI read it but {e}") from None
    return _for_kind({"school": c["school"], "school_year": c["school_year"], "days": c["days"], "how": "ai"}, kind)


def _for_kind(r, kind):
    if kind == "employer":
        r["days"] = [{**d, "kind": "holiday"} for d in r["days"] if d["kind"] != "early"]
    r["days"] = r["days"][:MAX_DAYS]
    if not r["days"]:
        raise ImportError_("no days off were found in it")
    return r


def read(body, ctype="", name="", kind="school"):
    """Bytes of a calendar (.ics, PDF or web page) -> details. Raises ImportError_ with a plain reason."""
    head = body[:2048].lstrip()
    low = (name or "").lower()
    if b"BEGIN:VCALENDAR" in head[:200] or "calendar" in ctype and "html" not in ctype or low.endswith(".ics"):
        return read_ics(body.decode("utf-8", "replace"), kind)
    if head.startswith(b"%PDF") or ctype == "application/pdf" or low.endswith(".pdf"):
        import doc_text
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "calendar.pdf"
            p.write_bytes(body)
            text, status = doc_text.extract(p)
        if status != "ok":
            raise ImportError_("the PDF has no text layer (a scan): drop it in Add so your AI can read the picture"
                               if status == "scanned" else "the PDF could not be read")
        return read_text(text, kind, "pdf")
    if "html" in ctype or head[:15].lower().startswith((b"<!doctype", b"<html")) or low.endswith((".htm", ".html")):
        text = _html_text(body.decode("utf-8", "replace"))
        if len(text.strip()) < 200:
            raise ImportError_("the page has almost no text (it may need a browser to show the calendar)")
        return read_text(text, kind, "page")
    if ctype.startswith("text/") or low.endswith(".txt"):
        return read_text(body.decode("utf-8", "replace"), kind, "page")
    raise ImportError_("that is not a calendar file this app reads (.ics, PDF or a web page)")


def store(con, org, members, details, url=None):
    """Proposed rows for each person linked to the org; an earlier still-proposed import of the org is replaced
    (accepted days stay). -> rows added."""
    con.execute("DELETE FROM calendar_days WHERE org_id=? AND status='proposed'", (org["id"],))
    source = "manual" if org["kind"] == "employer" else "school"
    label = org["name"][:60]
    n = 0
    for who in members or [None]:
        for d in details["days"]:
            n += con.execute("INSERT OR IGNORE INTO calendar_days(day, end_day, kind, name, member, source, label, status, "
                             "org_id) VALUES (?,?,?,?,?,?,?, 'proposed', ?)",
                             (d["day"], d["end"], d["kind"], d["name"][:80], who, source, label, org["id"])).rowcount
    con.execute("UPDATE orgs SET calendar_url=COALESCE(?, calendar_url), calendar_year=?, checked_at=? WHERE id=?",
                (url, details.get("school_year") or None, dates.now_iso(), org["id"]))
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("where")
    c.add_argument("--employer", action="store_true")
    a = ap.parse_args(argv)
    kind = "employer" if a.employer else "school"
    try:
        if re.match(r"(?i)https?://", a.where):
            import lookups
            ctype, body, _final = lookups.get(a.where)
            r = read(body, ctype, a.where, kind)
        else:
            p = pathlib.Path(a.where)
            r = read(p.read_bytes(), "", p.name, kind)
    except Exception as e:  # noqa: BLE001 (a command line check says why and stops)
        print(f"Not read: {e}")
        return 1
    print(f"{r['school'] or 'Calendar'} {r['school_year']}: {len(r['days'])} days (read from {SHOWN[r['how']]})")
    for d in r["days"]:
        print(f"  {d['day']}{' to ' + d['end'] if d['end'] else ''}  {d['kind']:<8} {d['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
