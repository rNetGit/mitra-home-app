"""Plain-text answers for the chat-style first run (the app's /setup page, data/setup_data.py), parsed with no AI:
people with a role and a birthday, cars, own / rent. No web code here, so the rules are tested directly
(tests/test_first_run.py).

    parse_people(text, date_order)   "Alex, adult, March 14 1980; Sam (child, 5/2/2012); Rex the dog" -> (members, problems)
    people_text(members)             the same members written back as lines the parser reads again (for a prefilled re-run)
    parse_vehicles(text)             "2019 Honda CR-V, 2015 Toyota Camry" -> (vehicles, problems); "no car" -> ([], [])
    vehicles_text(vehicles)          written back the same way
    parse_tenure(text)               "we own it" / "renting" -> "own" | "rent" | ""
"""
import re

import setup_interview as si
import dates  # noqa: E402

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
          "december"]
_MON = {m: i + 1 for i, m in enumerate(MONTHS)}
_MON.update({m[:3]: i + 1 for i, m in enumerate(MONTHS)})
_MON["sept"] = 9
ROLE_WORDS = {"adult": "adult", "grownup": "adult", "parent": "adult", "mom": "adult", "mum": "adult", "dad": "adult",
              "mother": "adult", "father": "adult", "husband": "adult", "wife": "adult", "spouse": "adult", "partner": "adult",
              "grandma": "adult", "grandpa": "adult", "grandmother": "adult", "grandfather": "adult",
              "child": "child", "kid": "child", "son": "child", "daughter": "child", "teen": "child", "teenager": "child",
              "baby": "child", "toddler": "child",
              "pet": "pet", "dog": "pet", "cat": "pet", "puppy": "pet", "kitten": "pet", "rabbit": "pet", "bird": "pet",
              "fish": "pet", "hamster": "pet", "horse": "pet"}
_FILLER = {"born", "is", "the", "a", "an", "age", "aged", "on", "in", "of", "my", "our", "birthday", "bday", "dob", "b", "and",
           "was", "turns", "will", "be"}
_NONE = {"", "no", "none", "nope", "no car", "no cars", "no vehicle", "no vehicles", "none yet", "we have none", "n/a", "-"}


def _has_name(entry):
    """True when the entry already holds a word that can be a name (not a role word, month, number or filler)."""
    for w in re.findall(r"[^\s,()]+", entry):
        k = re.sub(r"[^\w']", "", w.lower())
        if k and k not in ROLE_WORDS and k not in _FILLER and k not in _MON and not k[0].isdigit():
            return True
    return False


def _split(text):
    """Entries are separated by new lines and semicolons. Inside one line, a comma starts a new person only when the piece
    begins with a name (not a role word, a month or a digit); the rest are details of the person before it."""
    entries = []
    for line in re.split(r"[\n;]+", text or ""):
        line = line.strip(" \t.")
        if not line:
            continue
        pieces, depth, cur = [], 0, ""
        for ch in line:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth = max(0, depth - 1)
            if ch == "," and depth == 0:
                pieces.append(cur)
                cur = ""
            else:
                cur += ch
        pieces.append(cur)
        group = []
        for p in pieces:
            for q in re.split(r"\s+and\s+|\s*&\s*", p.strip()):
                q = q.strip()
                if not q:
                    continue
                first = re.sub(r"[^\w']", "", q.split()[0].lower())
                detail = first in ROLE_WORDS or first in _MON or q[0].isdigit() or first in ("born", "b", "aged", "age", "dob")
                if group and detail and _has_name(group[-1]):
                    group[-1] += " " + q
                else:
                    group.append(q)
        entries += group
    return entries


def _birthday(text, date_order):
    """-> (month, day, year, remaining text). Any of month and day may be None; year alone is fine."""
    mon, day, year, rest = _birthday_md(text, date_order)
    if mon is not None and year is None:  # "Priya 1985, 12/05": the year sits apart from the day
        m = re.search(r"\b(19\d\d|20\d\d)\b", rest)
        if m:
            year, rest = int(m.group(1)), rest.replace(m.group(0), " ")
    return mon, day, year, rest


def _birthday_md(text, date_order):
    t = text
    m = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", t)
    if m:
        return int(m.group(2)), int(m.group(3)), int(m.group(1)), t.replace(m.group(0), " ")
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2,4}))?\b", t)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        mon, day = (a, b) if date_order == "mdy" else (b, a)
        if mon > 12 >= day:  # only one reading is possible
            mon, day = day, mon
        y = m.group(3)
        year = (int(y) + (2000 if int(y) < 30 else 1900) if len(y) == 2 else int(y)) if y else None
        return mon, day, year, t.replace(m.group(0), " ")
    names = "|".join(sorted(_MON, key=len, reverse=True))
    m = re.search(rf"\b({names})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?\b", t, re.I)
    if m:
        return _MON[m.group(1).lower()], int(m.group(2)), int(m.group(3)) if m.group(3) else None, t.replace(m.group(0), " ")
    m = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({names})\.?(?:,?\s+(\d{{4}}))?\b", t, re.I)
    if m:
        return _MON[m.group(2).lower()], int(m.group(1)), int(m.group(3)) if m.group(3) else None, t.replace(m.group(0), " ")
    m = re.search(r"\b(19\d\d|20\d\d)\b", t)
    if m:
        return None, None, int(m.group(1)), t.replace(m.group(0), " ")
    return None, None, None, t


def parse_people(text, date_order="mdy"):
    """-> (members, problems). A member is {name, role, birth_month_day, birth_year}. A person with no role word is an
    adult (the screen lets the person change it). Problems are plain sentences naming the entry."""
    members, problems = [], []
    for raw in _split(text):
        body = re.sub(r"[()]", " ", raw)
        mon, day, year, rest = _birthday(body, date_order)
        role, words = "", []
        for w in re.findall(r"[^\s,]+", rest):
            key = re.sub(r"[^\w']", "", w.lower())
            if key in ROLE_WORDS and not role:
                role = ROLE_WORDS[key]
            elif key in _FILLER or key in ROLE_WORDS or not key:
                continue
            else:
                words.append(w.strip(".,:-"))
        name = " ".join(x for x in words if x).strip()
        if not name and role:  # "Mom, Dad": the role word is the name
            name = next((w for w in re.findall(r"[^\s,]+", rest) if re.sub(r"[^\w']", "", w.lower()) in ROLE_WORDS), "").title()
        if not name:
            problems.append(f"I could not find a name in “{raw.strip()}”.")
            continue
        m = {"name": name.title() if name.islower() else name, "role": role or "adult", "birth_month_day": "", "birth_year": year}
        if mon is not None:
            if not si.valid_birthday(mon, day):
                problems.append(f"{m['name']}: that birthday is not a real date.")
                continue
            m["birth_month_day"] = si.md_text(mon, day)
        p = si.member_problem(m, [x["name"] for x in members])
        if p:
            problems.append(f"{m['name']}: {p}")
            continue
        members.append(m)
    return members, problems


def people_text(members):
    lines = []
    for m in members or []:
        bits = [m.get("name", ""), m.get("role", "adult")]
        bd = m.get("birth_month_day") or ""
        if bd:
            mo, d = int(bd[:2]), int(bd[3:])
            bits.append(f"{MONTHS[mo - 1].title()} {d}" + (f" {m['birth_year']}" if m.get("birth_year") else ""))
        elif m.get("birth_year"):
            bits.append(f"born {m['birth_year']}")
        lines.append(", ".join(bits))
    return "\n".join(lines)


def parse_vehicles(text):
    """-> (vehicles, problems). A vehicle is {year, make, model}; the year may be missing."""
    if (text or "").strip().lower().rstrip(".!") in _NONE:
        return [], []
    out, problems = [], []
    this_year = dates.today().year
    for raw in re.split(r"[\n;,]+|\s+and\s+|\s*&\s*", text):
        raw = raw.strip(" \t.")
        if not raw:
            continue
        year = None
        m = re.search(r"\b(19[5-9]\d|20\d\d)\b", raw)
        if m and int(m.group(1)) <= this_year + 1:
            year = int(m.group(1))
            raw = (raw[:m.start()] + " " + raw[m.end():]).strip()
        words = [w for w in re.findall(r"[^\s]+", raw) if re.search(r"\w", w)]
        if len(words) < 2:
            problems.append(f"Write a car as make and model, for example “2019 Honda CR-V”. I got “{raw or 'nothing'}”.")
            continue
        if any(c in raw for c in '<>"\\/') or len(raw) > 60:
            problems.append(f"I cannot use “{raw[:40]}” as a car.")
            continue
        out.append({"year": year, "make": words[0], "model": " ".join(words[1:])})
    return out, problems


def vehicles_text(vehicles):
    return ", ".join(" ".join(str(x) for x in (v.get("year"), v.get("make"), v.get("model")) if x) for v in vehicles or [])


def parse_tenure(text):
    t = (text or "").lower()
    if re.search(r"\b(rent|renting|rented|tenant|lease|leasing)\b", t):
        return "rent"
    if re.search(r"\b(own|owned|owner|mortgage|bought)\b", t):
        return "own"
    return ""
