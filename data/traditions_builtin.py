"""Festival days worked out on this PC, no AI and no network, for the traditions a family ticks in Settings.

Christian (Easter and the days around it, Christmas), Muslim (tabular Islamic calendar: the moon-sighting date can be a
day or two different, so each name ends "(approx.)"), Jewish (the fixed Hebrew calendar; a holiday starts at sundown the
evening before) and Lunar New Year are worked out for any year. Hindu and Sikh have a short list of the biggest days for
2026-2028 only; the family's AI look-up adds the rest, and every other tradition (Buddhist, Jain, ...) is left to it.

rows(tradition, year) -> [(day 'YYYY-MM-DD', end or None, kind, name)]; covers(tradition) says the list is complete
enough that no AI look-up is needed.
"""
import datetime as dt

KEYS = {"christian": "christian", "catholic": "christian", "muslim": "muslim", "islam": "muslim", "islamic": "muslim",
        "jewish": "jewish", "judaism": "jewish", "lunar new year": "lunar", "chinese new year": "lunar",
        "hindu": "hindu", "sikh": "sikh"}
FULL = {"christian", "muslim", "jewish", "lunar"}


def key(tradition):
    """'Hindu (Telugu)' -> 'hindu'; None when this PC has nothing built in for it."""
    base = str(tradition or "").split("(")[0].strip().lower()
    return KEYS.get(base)


def covers(tradition):
    return key(tradition) in FULL


def _d(x):
    return x.isoformat() if x else None


# ---------------------------------------------------------------------------------------------------- Christian
def easter(year):
    """Western Easter Sunday (Meeus / Jones / Butcher)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return dt.date(year, month, day + 1)


def _christian(year):
    e = easter(year)
    one = dt.timedelta
    return [(e - one(days=46), None, "festival", "Ash Wednesday"), (e - one(days=7), None, "festival", "Palm Sunday"),
            (e - one(days=2), None, "festival", "Good Friday"), (e, None, "festival", "Easter Sunday"),
            (e + one(days=49), None, "festival", "Pentecost"), (dt.date(year, 12, 24), None, "festival", "Christmas Eve"),
            (dt.date(year, 12, 25), None, "holiday", "Christmas Day")]


# ------------------------------------------------------------------------------------------------------ Muslim
ISLAMIC_EPOCH = 227015  # fixed day number (1 = 0001-01-01) of 1 Muharram 1 AH, civil


def islamic_to_date(y, m, d):
    n = ISLAMIC_EPOCH - 1 + (y - 1) * 354 + (3 + 11 * y) // 30 + (59 * (m - 1) + 1) // 2 + d
    return dt.date.fromordinal(n)


def _muslim(year):
    out = []
    jan1, dec31 = dt.date(year, 1, 1), dt.date(year, 12, 31)
    hijri = int((jan1.toordinal() - ISLAMIC_EPOCH) * 30 / 10631) + 1
    for hy in (hijri - 1, hijri, hijri + 1):
        for m, d, span, name in ((1, 1, 1, "Islamic New Year"), (1, 10, 1, "Ashura"), (3, 12, 1, "Mawlid"),
                                 (9, 1, 1, "Ramadan begins"), (10, 1, 3, "Eid al-Fitr"), (12, 10, 4, "Eid al-Adha")):
            a = islamic_to_date(hy, m, d)
            if jan1 <= a <= dec31:
                b = a + dt.timedelta(days=span - 1)
                out.append((a, b if span > 1 else None, "holiday" if name.startswith("Eid") else "festival", name + " (approx.)"))
    return out


# ------------------------------------------------------------------------------------------------------ Jewish
HEBREW_EPOCH = -1373427  # fixed day number of 1 Tishri of year 1


def _elapsed(y):
    months = (235 * y - 234) // 19
    parts = 12084 + 13753 * months
    day = 29 * months + parts // 25920
    return day + 1 if (3 * (day + 1)) % 7 < 3 else day


def _new_year(y):
    ny0, ny1, ny2 = _elapsed(y - 1), _elapsed(y), _elapsed(y + 1)
    corr = 2 if ny2 - ny1 == 356 else 1 if ny1 - ny0 == 382 else 0
    return HEBREW_EPOCH + _elapsed(y) + corr


def _leap(y):
    return (7 * y + 1) % 19 < 7


def _month_len(y, m):
    if m in (2, 4, 6, 10, 13):
        return 29
    if m == 12 and not _leap(y):
        return 29
    year_days = _new_year(y + 1) - _new_year(y)
    if m == 8 and year_days % 10 != 5:
        return 29
    if m == 9 and year_days % 10 == 3:
        return 29
    return 30


def hebrew_to_date(y, m, d):
    """Month numbers: Nisan 1 ... Elul 6, Tishri 7 ... Adar 12 (Adar II 13)."""
    n = _new_year(y)
    last = 13 if _leap(y) else 12
    if m < 7:
        for k in range(7, last + 1):
            n += _month_len(y, k)
        for k in range(1, m):
            n += _month_len(y, k)
    else:
        for k in range(7, m):
            n += _month_len(y, k)
    return dt.date.fromordinal(n + d - 1)


def _jewish(year):
    out = []
    hy = year + 3761  # the Hebrew year that begins in the autumn of this Gregorian year
    one = dt.timedelta
    for y, rows in ((hy - 1, ((12, 14, 1, "Purim"), (1, 15, 8, "Passover"), (3, 6, 2, "Shavuot"))),
                    (hy, ((7, 1, 2, "Rosh Hashanah"), (7, 10, 1, "Yom Kippur"), (7, 15, 7, "Sukkot"),
                          (7, 23, 1, "Simchat Torah"), (9, 25, 8, "Hanukkah")))):
        for m, d, span, name in rows:
            mm = 13 if (name == "Purim" and _leap(y)) else m
            a = hebrew_to_date(y, mm, d)
            if a.year == year:
                out.append((a, a + one(days=span - 1) if span > 1 else None, "festival", name))
    return out


# ------------------------------------------------------------------------------------ short tables, 2026-2028
LUNAR = {2025: (1, 29), 2026: (2, 17), 2027: (2, 6), 2028: (1, 26), 2029: (2, 13), 2030: (2, 3)}
HINDU = {2026: ((2, 15, "Maha Shivaratri"), (3, 4, "Holi"), (10, 20, "Dussehra"), (11, 8, "Diwali")),
         2027: ((3, 6, "Maha Shivaratri"), (3, 22, "Holi"), (10, 9, "Dussehra"), (10, 29, "Diwali")),
         2028: ((2, 23, "Maha Shivaratri"), (3, 11, "Holi"), (9, 28, "Dussehra"), (10, 17, "Diwali"))}


def _lunar(year):
    if year not in LUNAR:
        return []
    return [(dt.date(year, *LUNAR[year]), dt.date(year, *LUNAR[year]) + dt.timedelta(days=1), "festival", "Lunar New Year")]


def _hindu(year):
    return [(dt.date(year, m, d), None, "festival", n) for m, d, n in HINDU.get(year, ())]


def _sikh(year):
    return [(dt.date(year, 4, 14), None, "festival", "Vaisakhi")] if 2026 <= year <= 2028 else []


MAKERS = {"christian": _christian, "muslim": _muslim, "jewish": _jewish, "lunar": _lunar, "hindu": _hindu, "sikh": _sikh}


def rows(tradition, year):
    k = key(tradition)
    if not k:
        return []
    return [(a.isoformat(), _d(b), kind, name) for a, b, kind, name in sorted(MAKERS[k](year), key=lambda r: r[0])]
