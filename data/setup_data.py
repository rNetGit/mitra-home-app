"""The first run in the web app: six screens (SCREENS) holding the same steps, answers and checks as the setup interview
(setup_interview.py for the checks, the draft and `finish`; first_run.py reads the typed people and cars). No web code
here; webapp/app.py draws it.

The draft (config/setup_draft.json) is saved after every step, so a person can stop and come back. PINs are never in the
draft: they wait in this process's memory until "Set everything up" and are then stored hashed by setup_interview.finish.
Shown while setup_interview.needed() (a new install) and from Settings > Household profile (prefilled, adults).
"""
import datetime as dt

import brand
import dates
import country
import first_run as fr
import setup_interview as si

SECTIONS = si.SECTIONS
# The six screens of the first run (October 2026). Each groups steps of SECTIONS and checks every one exactly as
# before (_take). "Where" comes before "People" on purpose: the country decides how a birthday like 5/2/2012 is read.
# The AI has a screen of its own ("Read your papers", optional, after Your home) that says what it does and how the
# privacy is kept before asking; a draft saved by the ten-step version resumes on the right screen.
SCREENS = [("Welcome", ("Welcome",)), ("Your family", ("Family", "Where", "People")),
           ("Your home", ("Home", "Cars", "Traditions")), ("Read your papers", ("AI",)), ("Sign-in", ("Logins",)),
           ("All set", ("Finish",))]
SCREEN_ASK = {"Welcome": "Let's set up your home",
              "Your family": "Who lives with you, and where?",
              "Your home": "Your home, your cars and the holidays you keep",
              "Read your papers": "Should an AI read your papers for you?",
              "Sign-in": "Who signs in?",
              "All set": "That is everything. Ready?"}
PART_TITLE = {"Family": "Your family's name", "Where": "Where you live", "People": "Who lives with you",
              "Home": "Your home", "Cars": "Cars", "Traditions": "Holidays you celebrate", "Logins": "PINs",
              "Finish": "Check your answers"}
CLIMATE_TEXT = {"cold": "Cold: snowy winters", "mild": "Mild: little frost, little snow", "hot": "Hot: long hot summers"}
TENURE_TEXT = {"own": "We own it", "rent": "We rent", "": "Skip"}
# Traditions offered as tiles on the Traditions step; anything else is typed (data/traditions.py checks every name).
TRADITIONS = ["Hindu", "Muslim", "Christian", "Jewish", "Sikh", "Buddhist", "Jain", "Lunar New Year"]
# The money the household works in: shown as a list on the Where step (code, name, sign), the country's own first.
CURRENCIES = [("USD", "US dollar", "$"), ("EUR", "Euro", "€"), ("GBP", "British pound", "£"), ("INR", "Indian rupee", "₹"),
              ("CAD", "Canadian dollar", "$"), ("AUD", "Australian dollar", "$"), ("NZD", "New Zealand dollar", "$"),
              ("SGD", "Singapore dollar", "$"), ("AED", "UAE dirham", "Dh"), ("JPY", "Japanese yen", "¥"),
              ("CHF", "Swiss franc", "Fr"), ("ZAR", "South African rand", "R"), ("MXN", "Mexican peso", "$")]
CURRENCY_CODES = {c for c, _, _ in CURRENCIES}
# Yearly home tax bills asked on the Home step (owners): key -> bill name. School tax only where it is billed apart.
HOME_TAXES = {"US": [("school_tax", "School tax"), ("property_tax", "Property tax (town / county)")]}
HOME_TAXES_OTHER = [("property_tax", "Property tax")]
COUNTRY_NAMES = {"US": "United States", "UK": "United Kingdom", "CA": "Canada", "AU": "Australia", "NZ": "New Zealand",
                 "IN": "India", "IE": "Ireland", "GENERIC": "Somewhere else"}
RULES = ["Statements and bills stay on this PC. You download them yourself; I never log in to a bank or tax site.",
         "Original files are never deleted; they are filed away in an archive folder on this PC.",
         "Only the last four digits of account, policy and ID numbers are stored.",
         "Answers are AI-assisted records, not tax, legal, medical, insurance or financial advice.",
         "Never paste a Claude, ChatGPT or Google sign-in token anywhere; only API keys, and only on the AI screen.",
         "Backups hold your full financial database: keep them on an encrypted drive."]
PIN_MIN, PIN_MAX = 4, 64
# The "Read your papers" screen: what an AI does, what it sees, what it costs. Plain words, shown before the choice.
AI_DOES = ["Reads the bills, receipts and papers you drop in, works out what each one is and files it for you.",
           "Answers questions in Chat from your records.",
           "Without one: reminders, the calendar and lists still work, and statements with simple text lines, phone bills, "
           "PayPal and school calendars are read on this PC. Other bank statements, scanned papers and unfamiliar letters "
           "wait in the Inbox until you file them by hand, so you get only part of what Mitra can do.",
           "Prefer not to download statements each month? SimpleFIN Bridge (beta-bridge.simplefin.org) can bring in new "
           "transactions every morning; connect it later in Settings > Connections."]
AI_PRIVACY = ["Your files, database and backups stay on this PC. Original papers are filed here and never deleted.",
              "A paper is read on this PC first; only its text is sent, only to the provider you pick, under your own account. "
              "Account, policy and ID numbers are cut to the last four digits, and SSNs, emails, phones, addresses and your family's names are masked first. "
              "Only what is needed to fill in the fields (vendor, amount, date) goes.",
              "Photos cannot be masked, so reading photos is a separate tick box, off until you turn it on.",
              "Your key is typed only on this PC and kept in a private file here; it is never shown again or sent anywhere "
              "else. Children never use the AI.",
              "It costs what your provider charges: an OpenRouter key with $5 of credit lasts most families a year."]
# "About this step" beside each question (PC: right column; phone: under the form). Plain words, no AI.
STEP_HELP = {
    "Welcome": ("Why this matters", ["Everything you type stays in a file on this PC until \"Set everything up\".",
                                     "You can stop at any time with [Save, finish later] and come back to the same step."]),
    "AI": ("Do I need an AI?", ["No. Reminders, the calendar, lists, search and backups work without one.",
                                "With one, statements and letters you drop in are read and filed for you, and Chat answers questions. "
                                "This is where most of the daily help comes from.",
                                "Without one, papers this PC cannot read itself wait in the Inbox for you.",
                                "Recommended: an OpenRouter key with $5 of credit (most families: a year). The steps are in "
                                "the AI card.",
                                "To connect one: pick a provider, paste its key, tick the box, press [Save]. Then [Continue].",
                                "Not sure? Press [Continue] now and connect one later in Settings > Connections."]),
    "Family": ("What it is for", ["The name shows on the briefs and the emergency sheet, for example \"The Patel family\"."]),
    "Where": ("Why we ask", ["The country picks the public holidays, the tax papers to collect and the date format.",
                             "The climate picks the seasonal reminders (furnace filter, gutters, sprinklers ...).",
                             "Only the city and state are kept; nothing is looked up online."]),
    "Traditions": ("Why we ask", ["Festivals of the traditions you tick are added to the calendar each year.",
                                  "Only the tradition's name, the year and the country are ever sent to an AI; the dates "
                                  "wait in the Inbox until an adult accepts them.", "Skip it with [Continue] if none."]),
    "People": ("How to type it", ["Each person on a line of their own: name, adult / child / pet, birthday (optional).",
                                  "Press [Check what I typed] to see how it was read, and fix a role in the list.",
                                  "Full names as printed on papers are optional; they are hidden before anything goes to an AI."]),
    "Home": ("Why we ask", ["Owners get home upkeep reminders and, in the US, the school and property tax dates.",
                            "Renters skip the owner jobs. [Skip] if you would rather not say."]),
    "Cars": ("How to type it", ["Year, make and model, separated by commas, for example \"2019 Honda CR-V, 2015 Toyota "
                                "Camry\".", "Type \"no car\" if there is none. Registration and insurance dates come "
                                "from their papers later."]),
    "Logins": ("Do we need PINs?", ["With PINs, each adult signs in and children see only their own page, with no money.",
                                    "Phones can only be connected once at least one adult has a PIN.",
                                    "PINs are saved only as a scrambled hash, when you press \"Set everything up\"."]),
    "Finish": ("What happens next", ["[Set everything up] makes your family's folder, the database and the settings "
                                     "(about a minute).", "Then drop in a few papers, and switch on Settings > Data > "
                                     "Runs on its own for the daily brief and backups."]),
}

SCREEN_HELP = {
    "Welcome": STEP_HELP["Welcome"],
    "Your family": ("How to fill it in", ["The family name shows on the briefs and the emergency sheet.",
                                          "The country picks public holidays, tax papers, the date format and the currency.",
                                          "Each person on a line of their own: name, adult / child / pet, birthday (optional). "
                                          "[Check what I typed] reads it back so you can fix a role.",
                                          "Full names as printed on papers are optional; they are hidden before anything "
                                          "goes to an AI."]),
    "Your home": ("Why we ask", ["Owners get home upkeep reminders and, in the US, the school and property tax dates.",
                                 "Cars: year, make and model, or \"no car\". Their papers fill in the dates later.",
                                 "Festivals of the traditions you tick are added to the calendar; only the tradition, the "
                                 "year and the country are ever sent to an AI."]),
    "Read your papers": ("Your choice, and you can change it later", [
        "Without an AI: statements, phone bills, PayPal and school calendars are still read on this PC. Other papers wait in the "
        "Inbox and you say what each one is with [File it by hand].",
        "With an AI: it reads those papers, fills in what they are, and answers questions in Chat.",
        "Not sure? Press [Continue] with \"No AI\". Add one any time in Settings > Connections."]),
    "Sign-in": STEP_HELP["Logins"],
    "All set": ("What happens next", ["[Set everything up] makes your family's folder, the database and the settings "
                                      "(about a minute).",
                                      "An AI is optional: reminders, the calendar, lists and search work without one. "
                                      "Add or change it later in Settings > Connections."]),
}

_PINS = {}   # name -> PIN, this process only, until finish
_DONE = []   # the messages of the last finish, for the "You are set up" page


def birthday_text(md, year):
    """How a typed birthday reads back: "March 14, 1980", "born 1980" or "no birthday"."""
    return dates.md_text(md, year) or (f"born {year}" if year else "no birthday")


def needed():
    return si.needed()


def screen_of_step(k):
    """The screen to resume on for a draft saved at SECTIONS step k (the ten-step version): the first screen with a
    step not done yet (the AI step aside: it is optional and sits on the last screen)."""
    for i, (_, secs) in enumerate(SCREENS):
        if any(SECTIONS.index(s) >= k for s in secs if s != "AI"):
            return i
    return len(SCREENS) - 1


def state():
    """(answers, screen index) from the saved draft and what is already configured."""
    a = si.defaults()
    try:
        screen = int(a["screen"]) if "screen" in a else screen_of_step(int(a.get("step", 0) or 0))
    except (TypeError, ValueError):
        screen = 0
    return a, max(0, min(screen, len(SCREENS) - 1))


def _answer(a, name):
    ms = a.get("members") or []
    return {"Welcome": "I understand. Let's start.",
            "AI": _ai_answer(),
            "Family": a.get("family_name") or "-",
            "Where": ", ".join(x for x in (a.get("place"), a.get("state"), a.get("zip"), a.get("country")) if x) or "-",
            "People": ", ".join(f"{m['name']} ({m['role']})" for m in ms) or "-",
            "Traditions": ", ".join(a.get("traditions") or []) or "None for now.",
            "Home": TENURE_TEXT.get(a.get("tenure") or "", "Skip") + (". Someone works from home." if a.get("home_office") else ".")
                    + "".join(f" {lbl.split(' (')[0]} due {(a.get('home_taxes') or {})[k]}." for k, lbl in
                              HOME_TAXES.get(country.normalize(a.get("country") or "US"), HOME_TAXES_OTHER)
                              if (a.get("home_taxes") or {}).get(k)),
            "Cars": fr.vehicles_text(a.get("vehicles")) or "No car.",
            "Logins": "Own PINs." if pins_given() else "No PINs."}.get(name, "")


def _ai_answer():
    try:
        import config
        prov = ((config.family() or {}).get("ai") or {}).get("provider") or ""
    except Exception:  # noqa: BLE001 (no family.json yet on a brand-new install)
        prov = ""
    return f"Connected: {prov}." if prov and prov != "none" else "Not now (Settings > Connections later)."


def pins_given():
    return any(len(p) >= PIN_MIN for p in _PINS.values())


def currency_choices(current=""):
    """(code, label) for the currency list; a code typed before this list existed stays on it."""
    out = [(c, f"{c} {sign} {name}") for c, name, sign in CURRENCIES]
    cur = (current or "").strip().upper()
    if cur and cur not in CURRENCY_CODES:
        out.append((cur, cur))
    return out


def _part(a, name, typed, code, prof):
    """One step's fields on a screen: {"name", "title", ...what its fields need}."""
    v = {"name": name, "title": PART_TITLE.get(name, name)}
    if name == "Welcome":
        v["rules"] = RULES
    elif name == "Where":
        labels = prof.get("address", {})
        v.update(codes=sorted(country.codes(), key=lambda c: (c != "US", c == "GENERIC", COUNTRY_NAMES.get(c, c))), country=code, country_names=COUNTRY_NAMES, climates=[(c, CLIMATE_TEXT[c]) for c in si.CLIMATES],
                 state_label=labels.get("state", "State"), zip_label=labels.get("zip", "Postal code (optional)"),
                 currency=(a.get("currency") or prof.get("currency", "USD")).upper(), currencies=currency_choices(a.get("currency")),
                 currency_by_country={c: (country.load(c) or {}).get("currency", "USD") for c in country.codes()})
    elif name == "Traditions":
        import traditions
        have = a.get("traditions") or []
        v.update(choices=TRADITIONS, chosen=set(have), other=", ".join(t for t in have if t not in TRADITIONS),
                 lookup=bool(a.get("traditions_lookup", True)), ai_note=traditions.ai_ready())
    elif name == "People":
        text = typed.get("people", fr.people_text(a.get("members")))
        understood = fr.parse_people(text, prof.get("date_order", "mdy"))[0] if text.strip() else []
        for i, m in enumerate(understood):
            if typed.get(f"name_{i}") == m["name"] and typed.get(f"role_{i}") in si.ROLES:
                m["role"] = typed[f"role_{i}"]
            m["birthday_text"] = birthday_text(m.get("birth_month_day"), m.get("birth_year"))
        v.update(text=text, roles=si.ROLES, understood=understood,
                 papers=typed.get("papers", "\n".join(a.get("paper_names") or [])))
    elif name == "Home":
        import seasonal_packs
        v.update(taxes=[(k, lbl, (a.get("home_taxes") or {}).get(k, "")) for k, lbl in HOME_TAXES.get(code, HOME_TAXES_OTHER)],
                 tenures=list(TENURE_TEXT.items()),
                 pack=seasonal_packs.recommend(code, a.get("climate") or "cold"))
    elif name == "Cars":
        v["text"] = typed.get("cars", fr.vehicles_text(a.get("vehicles")))
    elif name == "Logins":
        v.update(people=[m for m in a.get("members") or [] if m.get("role") != "pet"], on=bool(_PINS) or typed.get("on") == "1",
                 have={n for n, p in _PINS.items() if p})
    elif name == "Finish":
        v.update(summary=si.summary(a) + [("Home", _answer(a, "Home")), ("Cars", _answer(a, "Cars")),
                                          ("PINs", _answer(a, "Logins")), ("AI", _answer(a, "AI"))],
                 problems=si.validate("Finish", a))
    return v


def _screen_answer(a, i):
    """What a finished screen says under "Your answers so far"."""
    secs = [n for n in SCREENS[i][1] if n not in ("Welcome", "Finish")]
    return " · ".join(x for x in (_answer(a, n) for n in secs) if x and x != "-") or "-"


def view(a, screen, typed=None):
    """Everything the page needs for one screen. `typed` = what the person just sent (kept when it was refused)."""
    typed = typed or {}
    title, names = SCREENS[screen]
    code = country.normalize(a.get("country") or "US")
    prof = country.load(code) or {}
    parts = [_part(a, n, typed, code, prof) for n in names if n != "AI"]
    finish = next((p for p in parts if p["name"] == "Finish"), None)
    return {"step": screen, "screen": screen, "title": title, "names": names, "titles": [s for s, _ in SCREENS],
            "ask": SCREEN_ASK[title], "agent": brand.AGENT, "last": screen == len(SCREENS) - 1, "a": a, "parts": parts,
            "blocked": bool(finish and finish["problems"]),
            "answers": [(i, SCREENS[i][0], _screen_answer(a, i)) for i in range(1, screen)],
            "help": SCREEN_HELP.get(title), "ai_does": AI_DOES, "ai_privacy": AI_PRIVACY}


def _take(a, name, d):
    """Apply one step's fields to the answers -> plain-language problems (empty = fine to go on)."""
    if name == "Welcome":
        a["accept_rules"] = d.get("accept") == "1"
        return [] if a["accept_rules"] else ["Please tick the box to accept the rules."]
    if name == "Family":
        a["family_name"] = str(d.get("family_name", "")).strip()[:120]
        return [p for p in si.validate("Family", a) if "name" in p]
    if name == "Where":
        codes = country.codes()
        c = country.normalize(d.get("country") or "US")
        a["country"] = c if c in codes else "US"
        for k, n in (("place", 80), ("state", 60), ("zip", 20)):
            a[k] = str(d.get(k, "")).strip()[:n]
        a["climate"] = d.get("climate") if d.get("climate") in si.CLIMATES else ""
        a["currency"] = str(d.get("currency", "")).strip()[:8].upper()
        return [p for p in si.validate("Family", a) if "name" not in p]
    if name == "Traditions":
        import traditions
        picked = [t for i, t in enumerate(TRADITIONS) if d.get(f"trad_{i}") == "1"]
        other = [x for x in str(d.get("trad_other", ""))[:400].split(",") if x.strip()]
        out, names = [], []
        for x in picked + other:
            try:
                names.append(traditions.clean_name(x))
            except traditions.TraditionError as e:
                out.append(str(e)[:1].upper() + str(e)[1:] + ".")
        names = list(dict.fromkeys(names))
        if len(names) > traditions.MAX_TRADITIONS:
            out.append(f"Pick at most {traditions.MAX_TRADITIONS} traditions.")
        a["traditions"], a["traditions_lookup"] = names[:traditions.MAX_TRADITIONS], d.get("lookup") == "1"
        return out
    if name == "People":
        order = (country.load(a.get("country") or "US") or {}).get("date_order", "mdy")
        members, problems = fr.parse_people(str(d.get("people", ""))[:4000], order)
        for i, m in enumerate(members):  # the role a person picked under "Here is what I understood"
            if d.get(f"name_{i}") == m["name"] and d.get(f"role_{i}") in si.ROLES:
                m["role"] = d[f"role_{i}"]
        a["members"] = members
        import pii
        a["paper_names"], paper_probs = pii.clean_paper_names(str(d.get("papers", ""))[:4000])
        return problems + paper_probs + si.validate("People", a)
    if name == "Home":
        a["tenure"] = d.get("tenure") if d.get("tenure") in ("own", "rent") else ""
        a["home_office"] = d.get("home_office") == "1"
        code = country.normalize(a.get("country") or "US")
        taxes, out = {}, []
        for k, lbl in HOME_TAXES.get(code, HOME_TAXES_OTHER):
            raw = str(d.get(f"tax_{k}", "")).strip()[:10]
            if not raw:
                continue
            try:
                taxes[k] = dt.date.fromisoformat(raw).isoformat()
            except ValueError:
                out.append(f"{lbl}: pick the date from the calendar.")
        a["home_taxes"] = taxes if a["tenure"] == "own" else {}
        return out
    if name == "Cars":
        vehicles, problems = fr.parse_vehicles(str(d.get("cars", ""))[:1000])
        a["vehicles"], a["cars_done"] = vehicles, not problems
        return problems
    if name == "Logins":
        names = {m["name"] for m in a.get("members") or [] if m.get("role") != "pet"}
        if d.get("on") != "1":
            _PINS.clear()
            return []
        out = []
        for n in sorted(names):
            p = str(d.get(f"pin_{n}", ""))
            if not p:
                continue
            if len(p) < PIN_MIN or len(p) > PIN_MAX:
                out.append(f"{n}: a PIN needs {PIN_MIN} to {PIN_MAX} characters.")
            else:
                _PINS[n] = p
        for n in [n for n in _PINS if n not in names]:
            _PINS.pop(n)
        return out
    return []


def _save(a, screen):
    a["screen"] = screen
    a["step"] = SECTIONS.index(SCREENS[screen][1][0])  # the ten-step position, for setup_interview.py in a terminal
    si.save_draft(a)


def submit(op, screen, d):
    """One button on a screen: 'next', 'back', 'goto' (an earlier screen, from "Your answers so far"), 'check' (read the
    people back) or 'later' -> (screen to show, problems, typed, answers to show). Every step on the screen is checked
    as before; 'next' saves the draft only when all of them are fine, 'later' and 'back' save what was typed if it is
    fine and never refuse. A refused screen shows what was typed, not the saved draft."""
    a, _ = state()
    try:
        screen = max(0, min(int(screen), len(SCREENS) - 1))
    except (TypeError, ValueError):
        screen = 0
    before = dict(a)
    problems = []
    for name in SCREENS[screen][1]:
        problems += _take(a, name, d)
    typed = {k: str(v) for k, v in d.items() if k in ("people", "papers", "cars", "on") or k.startswith(("name_", "role_"))}
    if op in ("back", "goto"):
        a = a if not problems else before
        try:
            to = int(d.get("to", screen - 1)) if op == "goto" else screen - 1
        except (TypeError, ValueError):
            to = screen - 1
        _save(a, max(0, min(to, screen)))
        return a["screen"], [], {}, a
    if op == "check":  # read the people back without moving on
        return screen, problems, typed, a
    if op == "later":
        a = a if not problems else before
        _save(a, screen)
        return screen, [], {}, a
    if problems:
        return screen, problems, typed, a
    _save(a, min(screen + 1, len(SCREENS) - 1))
    return a["screen"], [], {}, a


def finish():
    """Set everything up from the draft and the PINs in memory -> (ok, messages). The PINs are forgotten either way."""
    a, _ = state()
    pins = {n: p for n, p in _PINS.items() if len(p) >= PIN_MIN}
    ok, msgs = si.finish(a, pins)
    if ok:
        _PINS.clear()
        _DONE[:] = msgs
    return ok, msgs


def done_messages():
    return list(_DONE)


def cancel():
    """Leave a re-run from Settings: forget the draft and the typed PINs (the household stays as it was)."""
    _PINS.clear()
    si.clear_draft()
