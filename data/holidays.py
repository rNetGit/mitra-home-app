"""Public holidays computed from the country's rules, on this PC, with no network call and no AI.

  python data/holidays.py [YEAR]            this year's (or YEAR's) public holidays for the household's country
  python data/holidays.py --country UK 2027

Rules: packs/holidays/<code>.json (a family copy in config/holidays/<code>.json wins and survives updates). Each
holiday is one of
  {"name", "date": "MM-DD"}                                  a fixed day
  {"name", "month", "weekday": "MO", "nth": 3}               the 3rd Monday (nth -1 = the last)
  {"name", "month", "weekday": "MO", "before": 25}           the last Monday before the 25th
  {"name", "easter": -2}                                     days from Western Easter Sunday
"observances" (same rule forms) are dates that are not days off, such as the clock changes of daylight saving time;
a region with "no_observances": true (Arizona, Hawaii, Saskatchewan) skips them. Plus optional "since": YEAR and "shift": N days (the day after Thanksgiving). "regions": {CODE: {name, holidays,
drop}} adds a state's, province's or nation's own days (and drops national ones it does not keep, e.g. Scotland), for
the region in config/family.json region.state (code or name). "observed": "us" moves a Saturday holiday to Friday and a Sunday one to Monday;
"uk" moves a weekend holiday to the next free weekday. The moved day is added as "<name> (observed)".
Shipped: US (federal), UK (England and Wales), CA (federal), IN (national; festival dates come from the family's
traditions, data/traditions.py), with all 50 states and DC (state-government paid holidays; days a governor sets
each year, floating days and even-year election days are left out), provinces (AB, BC, MB, NS, ON, QC, SK) and UK
nations (Scotland, Northern Ireland). Others add their own days by hand (calendar_days.py add).
Off when config/family.json packs.holidays is false. Library: public(year, cc=None, region=None) -> [(date, name)],
observances(year, cc=None, region=None) -> [(date, name)].
"""
import argparse
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402

SHIPPED = HERE.parent / "packs" / "holidays"
LOCAL = paths.CONFIG / "holidays"
WEEKDAYS = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")
_CACHE = {}


def enabled():
    return bool(config.family().get("packs", {}).get("holidays", True))


def code():
    try:
        import country
        return country.code()
    except Exception:  # noqa: BLE001
        return "US"


def rules(cc):
    """The rules file for a country code, family copy first; None when there is none."""
    cc = str(cc or "").strip().lower()
    if not cc.isalpha() or len(cc) > 3:
        return None
    for folder in (LOCAL, SHIPPED):
        p = folder / f"{cc}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
    return None


def region_of(r, region):
    """The rules file's region entry for a code or name ("TX", "Texas", "Scotland"), or None."""
    want = " ".join(str(region or "").split()).upper()
    if not want:
        return None
    for code_, reg in (r.get("regions") or {}).items():
        if want in (code_.upper(), str(reg.get("name") or "").upper()):
            return reg
    return None


def _region():
    try:
        return config.region().get("state") or ""
    except Exception:  # noqa: BLE001
        return ""


def easter(year):
    """Western (Gregorian) Easter Sunday: the anonymous Gregorian algorithm."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = (h + l_ - 7 * m + 114) % 31 + 1
    return dt.date(year, month, day)


def _nth(year, month, wd, n):
    if n > 0:
        d = dt.date(year, month, 1)
        d += dt.timedelta(days=(wd - d.weekday()) % 7)
        d += dt.timedelta(weeks=n - 1)
        return d if d.month == month else None
    nxt = dt.date(year + (month == 12), month % 12 + 1, 1)
    d = nxt - dt.timedelta(days=1)
    d -= dt.timedelta(days=(d.weekday() - wd) % 7)
    return d - dt.timedelta(weeks=-n - 1)


def one(rule, year):
    """The date of one rule in a year, or None (not yet in force, or a rule this version cannot read)."""
    try:
        if rule.get("since") and year < int(rule["since"]):
            return None
        shift = dt.timedelta(days=int(rule.get("shift") or 0))
        if "date" in rule:
            m, d = (int(x) for x in str(rule["date"]).split("-"))
            return dt.date(year, m, d) + shift
        if "easter" in rule:
            return easter(year) + dt.timedelta(days=int(rule["easter"])) + shift
        wd = WEEKDAYS.index(str(rule["weekday"]).upper())
        month = int(rule["month"])
        if "before" in rule:
            d = dt.date(year, month, int(rule["before"])) - dt.timedelta(days=1)
            return d - dt.timedelta(days=(d.weekday() - wd) % 7) + shift
        d = _nth(year, month, wd, int(rule["nth"]))
        return d + shift if d else None
    except (KeyError, ValueError, TypeError):
        return None


def _observed(days, how):
    """[(date, name)] plus the moved day of each weekend holiday, by the country's rule."""
    out, taken = list(days), {d for d, _ in days}
    for d, name in sorted(days):
        if d.weekday() < 5 or not how:
            continue
        if how == "us":
            o = d - dt.timedelta(days=1) if d.weekday() == 5 else d + dt.timedelta(days=1)
        else:  # uk: the next weekday that is not already a holiday
            o = d + dt.timedelta(days=1)
            while o.weekday() >= 5 or o in taken:
                o += dt.timedelta(days=1)
        taken.add(o)
        out.append((o, f"{name} (observed)"))
    return out


def public(year, cc=None, region=None):
    """[(date, name)] of a year's public holidays, national plus the region's (empty when off or no rules for the
    country). Without cc: the household's country and region."""
    if cc is None:
        if not enabled():
            return []
        region = _region() if region is None else region
    cc = cc or code()
    key = (str(cc).upper(), str(region or "").upper(), int(year))
    if key not in _CACHE:
        r = rules(cc) or {}
        reg = region_of(r, region) or {}
        drop = set(reg.get("drop") or [])
        rules_ = [h for h in r.get("holidays", []) if h.get("name") not in drop] + list(reg.get("holidays") or [])
        days = [(d, str(h.get("name") or "Holiday")[:80]) for h in rules_ if (d := one(h, year))]
        _CACHE[key] = sorted(_observed(days, r.get("observed") or ""))
    return list(_CACHE[key])


def observances(year, cc=None, region=None):
    """[(date, name)] of a year's dates that are not days off (daylight saving clock changes); empty when the region
    does not keep them, when public holidays are off, or when the country has none."""
    if cc is None:
        if not enabled():
            return []
        region = _region() if region is None else region
    r = rules(cc or code()) or {}
    if (region_of(r, region) or {}).get("no_observances"):
        return []
    return sorted((d, str(h.get("name") or "")[:80]) for h in r.get("observances") or [] if (d := one(h, year)))


def observances_between(start, end, cc=None, region=None):
    out = []
    for y in range(start.year, end.year + 1):
        out += [(d, n) for d, n in observances(y, cc, region) if start <= d <= end]
    return out


def between(start, end, cc=None, region=None):
    """[(date, name)] between two dates (inclusive)."""
    out = []
    for y in range(start.year, end.year + 1):
        out += [(d, n) for d, n in public(y, cc, region) if start <= d <= end]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("year", nargs="?", type=int, default=dates.today().year)
    ap.add_argument("--country")
    ap.add_argument("--region", help="state, province or nation code or name (default: the household's)")
    a = ap.parse_args(argv)
    cc = a.country or code()
    r = rules(cc)
    if not r:
        print(f"No holiday rules for {cc.upper()} yet. Add your own days with: python data/calendar_days.py add ...")
        return 0
    if not a.country and not enabled():
        print("Public holidays are switched off (Settings > Household profile > Optional features).")
        return 0
    region = a.region if a.region is not None else ("" if a.country else _region())
    reg = region_of(r, region)
    print(f"{r.get('title') or cc.upper()}" + (f" + {reg['name']}" if reg else "") + f", {a.year}:")
    for d, n in public(a.year, cc, region):
        print(f"  {d:%a %b} {d.day}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
