"""Other calendars, read-only: an iCloud, Outlook or any other calendar's .ics address ("subscribe" / "publish" link),
shown on the Calendar page next to the Google copy. No AI, no sign-in, nothing written back.

  python data/calendar_feeds.py list               the feeds and when each was last read
  python data/calendar_feeds.py events [DAYS]      what they hold in the next DAYS days (default 14)

The list of feeds is config/calendar_feeds.json ({"feeds": [{"id", "name", "url"}]}, at most MAX_FEEDS), set by adults
on this PC in Settings > Connections > Other calendars. A feed address is a private link: it is kept in config/ (not
in the database, never sent anywhere but to the calendar's own server), and it is fetched only from a public host,
over http(s), at most MAX_BYTES, redirects to private addresses refused (lookups._open). It does NOT depend on the
online look-ups switch: that switch promises only a ZIP code and public names go out, and a feed is the family's own
link to the family's own calendar, added on purpose.

Each feed is read again after REFRESH_MIN minutes; the events of the coming DAYS_MAX days are cached in
logs/calendar_feeds.json (titles, times; descriptions and locations are not kept). Repeating events: DAILY, WEEKLY
(with BYDAY), MONTHLY and YEARLY with INTERVAL, COUNT, UNTIL and EXDATE; anything rarer shows only its first time.
"""
import datetime as dt
import json
import pathlib
import re
import secrets
import sys
import threading
import urllib.parse

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dates  # noqa: E402
import paths  # noqa: E402

MAX_FEEDS = 6
MAX_BYTES = 4_000_000
REFRESH_MIN = 60
DAYS_MAX = 60
MAX_EVENTS = 400
MAX_REPEATS = 800  # occurrences tried per repeating event
MAX_INTERVAL = 1000  # a larger INTERVAL can only name days far outside the window
NAME_MAX = 40
DAYCODES = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_lock = threading.Lock()


class FeedError(ValueError):
    pass


# ---- the list -------------------------------------------------------------------------------------------------------
def _list_path():
    return paths.CONFIG / "calendar_feeds.json"


def _cache_path():
    return paths.LOGS / "calendar_feeds.json"


def feeds():
    try:
        got = json.loads(_list_path().read_text(encoding="utf-8")).get("feeds") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [f for f in got if isinstance(f, dict) and f.get("id") and f.get("url")][:MAX_FEEDS]


def _save(rows):
    config.write_json(_list_path(), {"feeds": rows})


def clean_url(url):
    """webcal:// -> https://; http(s) only, a host, no user name or password, not too long. Raises FeedError."""
    u = str(url or "").strip()
    if u.lower().startswith("webcal://"):
        u = "https://" + u[9:]
    p = urllib.parse.urlsplit(u)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or len(u) > 2000:
        raise FeedError("paste the calendar's address: it starts with https:// or webcal://")
    return urllib.parse.urlunsplit(p)


def add(name, url):
    name = " ".join(str(name or "").split())[:NAME_MAX]
    if not name:
        raise FeedError("give the calendar a name, for example Work or School")
    url = clean_url(url)
    rows = feeds()
    if len(rows) >= MAX_FEEDS:
        raise FeedError(f"{MAX_FEEDS} calendars are added already; remove one first")
    if any(r["url"] == url for r in rows):
        raise FeedError("that calendar is already added")
    fid = secrets.token_hex(4)
    _save(rows + [{"id": fid, "name": name, "url": url}])
    return fid, name


def remove(fid):
    rows = feeds()
    keep = [r for r in rows if r["id"] != fid]
    if len(keep) == len(rows):
        raise FeedError("that calendar is already gone")
    _save(keep)
    with _lock:
        cache = _load_cache()
        cache.pop(fid, None)
        _write_cache(cache)
    return next(r["name"] for r in rows if r["id"] == fid)


def host_of(url):
    return urllib.parse.urlsplit(url).hostname or ""


# ---- reading a feed -------------------------------------------------------------------------------------------------
def fetch(url):
    """The feed's text. Public hosts only; redirects to private addresses refused; MAX_BYTES at most."""
    import urllib.error
    import urllib.request

    import brand
    import lookups
    url = clean_url(url)
    host = host_of(url)
    if not lookups._public_host(host):
        raise FeedError("that address is not on the public internet")
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", f"{brand.PRODUCT} calendar")
    req.add_header("Accept", "text/calendar, text/plain;q=0.5")
    try:
        status, _ctype, body, _final = lookups._open(req)
    except lookups.Refused as e:
        raise FeedError(str(e)) from None
    except urllib.error.HTTPError as e:
        raise FeedError(f"{host} answered {e.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise FeedError(f"{host} could not be reached ({str(getattr(e, 'reason', e))[:60]})") from None
    if status and status >= 400:
        raise FeedError(f"{host} answered {status}")
    if len(body) > MAX_BYTES:
        raise FeedError("that calendar is too big to read here")
    text = body.decode("utf-8", "replace")
    if "BEGIN:VCALENDAR" not in text[:2000].upper():
        raise FeedError("that address is not a calendar (.ics)")
    return text


def _unfold(text):
    return re.sub(r"\r?\n[ \t]", "", text.replace("\r\n", "\n"))


def _unescape(v):
    return " ".join(v.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").replace("\\N", " ").replace("\\", "").split())


def _local_tz():
    return dt.datetime.now().astimezone().tzinfo


def _when(key, value):
    """(date or local naive datetime, all_day) from a DTSTART / DTEND / EXDATE line, or (None, False)."""
    v = value.strip()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?", v)
    if not m:
        return None, False
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
    try:
        if m[4] is None:
            return dt.date(y, mo, d), True
        t = dt.datetime(y, mo, d, int(m[4]), int(m[5]), int(m[6] or 0))
    except ValueError:
        return None, False
    if m[7]:
        return t.replace(tzinfo=dt.timezone.utc).astimezone(_local_tz()).replace(tzinfo=None), False
    tz = re.search(r"TZID=([^;:]+)", key)
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return t.replace(tzinfo=ZoneInfo(tz[1].strip('"'))).astimezone(_local_tz()).replace(tzinfo=None), False
        except Exception:  # noqa: BLE001 (an unknown zone name: keep the time as written)
            return t, False
    return t, False


def _rule(text):
    return {k.upper(): v for k, _, v in (p.partition("=") for p in text.split(";")) if k}


def _months_add(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    for day in (d.day, 30, 29, 28):
        try:
            return d.replace(year=y, month=m, day=day)
        except ValueError:
            continue
    return d


def _candidates(freq, day0, step, byday, hi, until):
    """The days a rule names from day0 up to hi / until (at most MAX_REPEATS rounds)."""
    cands = []
    if freq == "WEEKLY":
        week = day0 - dt.timedelta(days=day0.weekday())
        days = sorted(set(byday)) or [day0.weekday()]
        for w in range(MAX_REPEATS):
            base = week + dt.timedelta(weeks=w * step)
            if base > hi or (until and base > until):
                break
            cands += [base + dt.timedelta(days=k) for k in days]
    elif freq in ("DAILY", "MONTHLY", "YEARLY"):
        for i in range(MAX_REPEATS):
            d = (day0 + dt.timedelta(days=i * step) if freq == "DAILY" else
                 _months_add(day0, i * step * (12 if freq == "YEARLY" else 1)))
            if d > hi or (until and d > until):
                break
            cands.append(d)
    else:
        cands = [day0]
    return cands


def _starts(start, rule, exdates, lo, hi):
    """The start of each occurrence of an event between lo and hi (dates), following its RRULE."""
    if not rule:
        return [start] if lo <= (start.date() if isinstance(start, dt.datetime) else start) <= hi else []
    freq = rule.get("FREQ", "")
    try:
        step = min(MAX_INTERVAL, max(1, int(rule.get("INTERVAL", "1"))))  # a feed is untrusted: no date past year 9999
        count = int(rule["COUNT"]) if "COUNT" in rule else None
    except ValueError:
        return []
    until = None
    if "UNTIL" in rule:
        u, _ = _when("UNTIL", rule["UNTIL"])
        until = u.date() if isinstance(u, dt.datetime) else u
    byday = [DAYCODES[c[-2:]] for c in rule.get("BYDAY", "").split(",") if c[-2:] in DAYCODES]
    day0 = start.date() if isinstance(start, dt.datetime) else start
    try:
        cands = _candidates(freq, day0, step, byday, hi, until)
    except (OverflowError, ValueError):  # a start date near the end of the calendar
        return []
    out, n = [], 0
    for d in cands:
        if d < day0 or (until and d > until):
            continue
        n += 1
        if count is not None and n > count:
            break
        when = dt.datetime.combine(d, start.time()) if isinstance(start, dt.datetime) else d
        if lo <= d <= hi and when not in exdates:
            out.append(when)
    return out


def parse(text, today, days=DAYS_MAX):
    """[{'date','time','end','all_day','title'}] for the next `days` days (today included), soonest first."""
    lo, hi = today, today + dt.timedelta(days=days)
    out = []
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", _unfold(text), re.S):
        f, ex = {}, set()
        for line in ev.split("\n"):
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            name = k.split(";")[0].upper()
            if name == "EXDATE":
                for part in v.split(","):
                    w, _ = _when(k, part)
                    if w:
                        ex.add(w)
                continue
            f.setdefault(name, (k, v.strip()))
        if (f.get("STATUS") or ("", ""))[1].upper() == "CANCELLED":
            continue
        title = _unescape((f.get("SUMMARY") or ("", "(no title)"))[1])[:120] or "(no title)"
        start, all_day = _when(*f.get("DTSTART", ("", "")))
        if not start:
            continue
        end, _ = _when(*f.get("DTEND", ("", "")))
        length = (end - start) if end and type(end) is type(start) else None
        for s in _starts(start, _rule((f.get("RRULE") or ("", ""))[1]), ex, lo, hi):
            e = s + length if length else None
            if all_day:
                last = (e - dt.timedelta(days=1)) if e else s
                out.append({"date": s.isoformat(), "time": "", "end": last.isoformat() if last > s else "",
                            "all_day": True, "title": title})
            else:
                out.append({"date": s.date().isoformat(), "time": f"{s:%H:%M}", "end": f"{e:%H:%M}" if e else "",
                            "all_day": False, "title": title})
            if len(out) >= MAX_EVENTS * 2:
                break
    out.sort(key=lambda e: (e["date"], not e["all_day"], e["time"], e["title"]))
    return out[:MAX_EVENTS]


# ---- the cache and what the Calendar page shows ---------------------------------------------------------------------
def _load_cache():
    try:
        c = json.loads(_cache_path().read_text(encoding="utf-8"))
        return c if isinstance(c, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(c):
    try:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        config.write_json(_cache_path(), c)
    except OSError:
        pass


def refresh(feed, now=None):
    """Read one feed now and cache it. -> (ok, message)."""
    now = now or dt.datetime.now()
    entry = {"fetched_at": now.isoformat(timespec="seconds")}
    try:
        entry["events"] = parse(fetch(feed["url"]), now.date())
        entry["error"] = ""
        ok, msg = True, f"{len(entry['events'])} events read"
    except FeedError as e:
        old = _load_cache().get(feed["id"]) or {}
        entry["events"] = old.get("events") or []
        entry["error"] = str(e)
        ok, msg = False, str(e)
    with _lock:
        c = _load_cache()
        c[feed["id"]] = entry
        _write_cache(c)
    return ok, msg


def _stale(entry, now):
    try:
        t = dt.datetime.fromisoformat(entry["fetched_at"])
    except (KeyError, TypeError, ValueError):
        return True
    return (now - t).total_seconds() > REFRESH_MIN * 60


def view(days, today=None, now=None, read=True):
    """[{'id','name','host','error','events': [...]}] for the Calendar page: each feed's events in the next `days`
    days, read again first when older than REFRESH_MIN (read=False: only the cache)."""
    now = now or dt.datetime.now()
    today = today or dates.today()
    hi = (today + dt.timedelta(days=days)).isoformat()
    out = []
    for f in feeds():
        entry = _load_cache().get(f["id"]) or {}
        if read and _stale(entry, now):
            refresh(f, now)
            entry = _load_cache().get(f["id"]) or {}
        evs = [e for e in entry.get("events") or [] if today.isoformat() <= e["date"] <= hi]
        out.append({"id": f["id"], "name": f["name"], "host": host_of(f["url"]), "error": entry.get("error", ""),
                    "fetched_at": entry.get("fetched_at", ""), "events": evs})
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        cache = _load_cache()
        for f in feeds():
            e = cache.get(f["id"]) or {}
            print(f"{f['id']}  {f['name']:<20} {host_of(f['url']):<32} read {e.get('fetched_at') or 'never'}"
                  + (f"  ({e['error']})" if e.get("error") else ""))
        return 0
    if cmd == "events":
        days = int(argv[1]) if len(argv) > 1 else 14
        for f in view(days):
            print(f"== {f['name']}" + (f" ({f['error']})" if f["error"] else ""))
            for e in f["events"]:
                print(f"  {e['date']} {'all day' if e['all_day'] else e['time']}  {e['title']}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
