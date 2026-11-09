"""The family's own traditions (religious, cultural, regional) and their dates, looked up once a year with the
family's AI and confirmed by an adult in the Inbox. Optional and off until an adult turns it on.

  python data/traditions.py show                       the traditions and whether the yearly look-up is on
  python data/traditions.py set "Hindu (Telugu)" "Christian" [--lookup on|off]     (empty list = none)
  python data/traditions.py fetch YEAR [--tradition NAME]   ask the AI now (adults; one call per tradition)
  python data/traditions.py auto                       what the daily task runs: this year's dates when none were asked
                                                        yet, and next year's from October 1; nothing when off

Privacy: the traditions live only in config/family.json on this PC (`traditions`, `traditions_lookup`); they are never
synced to phones, copied to Drive or put in a brief. Each look-up sends ONLY the tradition's name, the year and the
country code to the provider the family chose: no names, no address, no other records. The answer is untrusted data:
each date is checked (inside the year, a real date, a short plain name, at most MAX_DAYS) and stored in calendar_days
as 'proposed' with source 'tradition'. Nothing shows on a calendar until an adult accepts that tradition's dates in
the Inbox (proposals.py source 'tradition'). Lunar and regional dates can differ by a day: the Inbox card says so.
"""
import argparse
import datetime as dt
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

MAX_TRADITIONS = 6
MAX_DAYS = 40
NEXT_YEAR_FROM = (10, 1)  # month, day: from then on the next year's dates are asked for
NAME = re.compile(r"^[^\W\d_][\w .,'()&/-]{0,39}$", re.UNICODE)
SCHEMA = {"days": (list, True, {"date": (str, True, None), "name": (str, True, None), "end": (str, False, None),
                                "kind": (str, False, ("holiday", "festival"))})}
INSTRUCTION = ("List the main religious and cultural observances, festivals and holidays of the tradition named in the "
               "data, with their dates in the given year as usually observed in the given country. Use YYYY-MM-DD. "
               "end = last day when it lasts several days, else leave it out. kind = holiday for a major day off, else "
               "festival. Only real observances with a fixed date for that year; no explanations, no links, at most "
               f"{MAX_DAYS} entries. If the tradition is not a real religious or cultural tradition, return an empty list.")


class TraditionError(ValueError):
    pass


def clean_name(x):
    s = " ".join(str(x or "").split())
    if not NAME.match(s):
        raise TraditionError(f"'{s[:40]}': use a short name like Hindu (Telugu), Christian, Jewish or Lunar New Year")
    return s


def get():
    """{'traditions': [names], 'lookup': bool}"""
    fam = config.family()
    names = []
    for t in fam.get("traditions") or []:
        try:
            names.append(clean_name(t))
        except TraditionError:
            continue
    return {"traditions": names[:MAX_TRADITIONS], "lookup": bool(fam.get("traditions_lookup")) and bool(names)}


def save(names, lookup):
    """Write the list and the switch to config/family.json (atomic). -> the cleaned list."""
    clean = list(dict.fromkeys(clean_name(n) for n in names if str(n or "").strip()))
    if len(clean) > MAX_TRADITIONS:
        raise TraditionError(f"at most {MAX_TRADITIONS} traditions")
    with config.family_edit() as data:  # a family.json that does not parse is refused (it used to become {})
        data["traditions"] = clean
        data["traditions_lookup"] = bool(lookup) and bool(clean)
    return clean


def ai_ready():
    """'' when a provider can be asked, else why not."""
    try:
        import llm
        s = llm.settings()
    except Exception:  # noqa: BLE001
        return "the AI settings could not be read"
    if s["provider"] in ("none", "claude_code", ""):
        return "no AI provider is set up (Settings > Connections > AI)"
    return llm.training_risk(s) or ""


def _country():
    try:
        import country
        return country.code()
    except Exception:  # noqa: BLE001
        return "US"


def _checked(obj, year, tradition):
    """[(day, end, kind, name)] from an AI answer: only real dates inside the year, short plain names, no links."""
    out = []
    for d in (obj or {}).get("days") or []:
        try:
            a = dt.date.fromisoformat(str(d.get("date") or "")[:10])
            b = dt.date.fromisoformat(str(d["end"])[:10]) if d.get("end") else a
        except (ValueError, TypeError, AttributeError):
            continue
        name = " ".join(str(d.get("name") or "").split())[:80]
        if a.year != year or b < a or (b - a).days > 40 or not name or re.search(r"https?:|www\.|[<>{}]", name):
            continue
        kind = d.get("kind") if d.get("kind") in ("holiday", "festival") else "festival"
        out.append((a.isoformat(), b.isoformat() if b != a else None, kind, name))
        if len(out) >= MAX_DAYS:
            break
    return out


def asked(con, tradition, year):
    """True when this tradition's dates for that year were already asked for (any status)."""
    try:
        return con.execute("SELECT 1 FROM calendar_days WHERE source='tradition' AND label=? AND substr(day,1,4)=? LIMIT 1",
                           (tradition, str(year))).fetchone() is not None
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return True


def fetch(year, tradition, con=None):
    """Ask the AI for one tradition's dates in a year and store them as proposed. -> (n stored, message); n is -1
    when the provider could not be asked or reached (worth trying again another day)."""
    import llm
    tradition = clean_name(tradition)
    why = ai_ready()
    if why:
        return -1, f"Not asked: {why}."
    text = f"Tradition: {tradition}\nYear: {year}\nCountry: {_country()}"
    try:
        obj, errs = llm.extract_json(INSTRUCTION, text, SCHEMA, purpose="traditions", max_tokens=1500)
    except (llm.LLMError, OSError) as e:
        return -1, f"Not asked: {str(e)[:200]}"
    if errs:
        return 0, f"The answer for {tradition} {year} could not be used ({errs[0]})."
    days = _checked(obj, year, tradition)
    own = con is None
    con = con or db.connect(paths.DB, timeout=10)
    n = 0
    try:
        for day, end, kind, name in days:
            n += con.execute("INSERT OR IGNORE INTO calendar_days(day, end_day, kind, name, source, label, status) "
                             "VALUES (?,?,?,?, 'tradition', ?, 'proposed')", (day, end, kind, name, tradition)).rowcount
        con.commit()
    finally:
        if own:
            con.close()
    return n, (f"{n} date{'s' if n != 1 else ''} for {tradition} {year} wait in the Inbox." if n else
               f"No new dates for {tradition} {year}.")


def due(today, con):
    """[(tradition, year)] the yearly task should ask for now."""
    st = get()
    if not st["lookup"]:
        return []
    years = [today.year] + ([today.year + 1] if (today.month, today.day) >= NEXT_YEAR_FROM else [])
    return [(t, y) for t in st["traditions"] for y in years if not asked(con, t, y)]


def auto(today=None):
    """The daily task's step: ask what is due (at most one call per tradition and year, ever). -> [messages]."""
    today = today or dates.today()
    con = db.connect(paths.DB, timeout=10)
    try:
        todo = due(today, con)
        if not todo:
            return []
        if ai_ready():
            return [f"Traditions: not asked ({ai_ready()})."]
        out = []
        for t, y in todo:
            n, msg = fetch(y, t, con)
            out.append(msg)
            if n == 0 and not asked(con, t, y):  # an answer with nothing usable: remember it, do not ask daily
                con.execute("INSERT OR IGNORE INTO calendar_days(day, kind, name, source, label, status) "
                            "VALUES (?, 'festival', ?, 'tradition', ?, 'dropped')", (f"{y}-01-01", "(none found)", t))
                con.commit()
        return out
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["show", "set", "fetch", "auto"])
    ap.add_argument("args", nargs="*")
    ap.add_argument("--lookup", choices=["on", "off"])
    ap.add_argument("--tradition")
    a = ap.parse_args(argv)
    if a.cmd == "show":
        st = get()
        print("Traditions: " + (", ".join(st["traditions"]) or "none"))
        print(f"Yearly look-up with the family's AI: {'on' if st['lookup'] else 'off'}")
        return 0
    if a.cmd == "set":
        try:
            names = save(a.args, (a.lookup or ("on" if get()["lookup"] else "off")) == "on")
        except TraditionError as e:
            print(e)
            return 1
        print("Saved: " + (", ".join(names) or "no traditions"))
        return 0
    if a.cmd == "fetch":
        if not a.args:
            raise SystemExit("usage: fetch YEAR [--tradition NAME]")
        year = int(a.args[0])
        if not 2000 <= year <= 2100:
            raise SystemExit("year must be 2000-2100")
        names = [a.tradition] if a.tradition else get()["traditions"]
        if not names:
            print("No traditions set. Settings > Household profile > Traditions.")
            return 0
        for t in names:
            try:
                print(fetch(year, t)[1])
            except TraditionError as e:
                print(e)
        return 0
    for m in auto():
        print(m)
    return 0


if __name__ == "__main__":
    sys.exit(main())
