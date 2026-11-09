"""What the Today, Family and This month pages show, with no web code. The rows come from the Brief (brief_data); this
module says whose row it is (the name in its title, or the House for home and car jobs), merges duplicates (same title,
person and date across kinds, e.g. an appointment that is also a medical item), ranks them (expired papers and overdue
first, then today, then the week), gives each an urgency pill and caps every block. The pure parts (decorate, dedupe,
rank, pill, assemble, family, person_rows) take plain rows and are tested on their own.
"""
import datetime as dt
import re
import sqlite3

HOUSE = "House"
CAP_SIDE = 4
WEEK, MONTH = 7, 30
# Kinds that happen at a time or on a day (Today's timeline); every other kind due today is a job (Needs you).
TIMED = {"Appointment", "Event", "Birthday", "Festival", "School", "Activity", "Chore", "Medical", "Pet", "Travel",
         "Gift", "Health", "Legal", "Other", "Family", "Work", "Class", "Holiday", "No school", "Early dismissal",
         "Clocks change"}
HOUSE_KINDS = {"Home", "Warranty", "Seasonal", "Car", "Vehicle"}
HOUSE_TABLES = {"vehicles", "home_assets", "vehicle_log", "seasonal_tasks"}
RENEW_KINDS = {"Renewal", "ID", "Cancel", "Insurance", "Contract", "Deal"}


def _renewal(r):
    """A paper or policy to renew (subscription renewals have their own block on This month)."""
    return r["kind"] in RENEW_KINDS and r["person"] != HOUSE and _ref(r) != "subscriptions"
KIND_RANK = {"Appointment": 0}  # the row kept when duplicates merge: an appointment carries the time
_TIME = re.compile(r"\b([01]\d|2[0-3]):([0-5]\d)\b")


# ---- pure ------------------------------------------------------------------------------------------------------
def _ref(r):
    return ((r.get("it") or {}).get("ref") or (None, None))[0]


def person_of(r, names):
    """The member a row is about (the name in its title), HOUSE for home and car jobs, else None (the household)."""
    title = r.get("title") or ""
    firsts = [(n, n.split()[0]) for n in names if n]
    for full, first in firsts:
        if re.search(rf"\((?:{re.escape(full)}|{re.escape(first)})\)", title):
            return full
    for full, first in firsts:
        if re.match(rf"{re.escape(first)}\b", title) or re.search(rf"\b{re.escape(first)}'s\b", title):
            return full
    for full, first in firsts:
        if re.search(rf"\b{re.escape(first)}\b", title):
            return full
    if "(household)" in title or r.get("kind") in HOUSE_KINDS or _ref(r) in HOUSE_TABLES:
        return HOUSE
    return None


def short_title(title, person):
    """The title without the "(Name)" the avatar already shows."""
    if not person:
        return title
    word = "household" if person == HOUSE else re.escape(person.split()[0]) + r"(?:\s\S+)?"
    out = re.sub(rf"\s*\((?:{word})\)", "", title).strip()
    if person != HOUSE:  # "Mateo passport EXPIRED", "Mateo: recital" -> "Passport EXPIRED", "Recital"
        lead = re.match(rf"{re.escape(person.split()[0])}(?::\s*|\s+)(.+)", out)
        if lead:
            out = lead.group(1)[:1].upper() + lead.group(1)[1:]
    return out or title


def pill(d, today):
    """(text, tone): tone is 'danger' for overdue, 'warn' for today, '' otherwise."""
    n = (d - today).days
    if n < 0:
        return f"Overdue {-n}d", "danger"
    if n == 0:
        return "Today", "warn"
    if n == 1:
        return "Tomorrow", ""
    return (f"in {n}d", "") if n <= WEEK else (f"{d:%b} {d.day}", "")


def _time(detail):
    m = _TIME.search(detail or "")
    if not m:
        return "", ""
    h, mi = int(m.group(1)), m.group(2)
    return f"{(h % 12) or 12}:{mi} {'AM' if h < 12 else 'PM'}", m.group(0)


def decorate(rows, today, names):
    """Copies of the rows with person, short title (full title kept in `full`), pill, tone, time and sev (0 expired paper,
    1 overdue, 2 today, 3 this week, 4 later)."""
    out = []
    for r in rows:
        r = dict(r)
        r["full"] = r["title"]
        r["person"] = person_of(r, names)
        r["title"] = short_title(r["full"], r["person"])
        r["pill"], r["tone"] = pill(r["date"], today)
        r["time"], r["t24"] = _time(r.get("detail"))
        expired = "EXPIRED" in r["full"].upper() or (r.get("kind") == "ID" and r["date"] < today)
        n = (r["date"] - today).days
        r["sev"] = 0 if expired else 1 if n < 0 else 2 if n == 0 else 3 if n <= WEEK else 4
        if expired and n >= 0:
            r["pill"], r["tone"] = "Expired", "danger"
        r["also"] = []
        r["av"] = avatar(r["person"], names)
        out.append(r)
    return out


def dedupe(rows):
    """One row per (title, person, date); an appointment wins (it has the time), other kinds go to `also`."""
    keep, order = {}, []
    for r in rows:
        k = (r["title"].lower(), r["person"], r["date"])
        if k not in keep:
            keep[k] = r
            order.append(k)
            continue
        a = keep[k]
        if KIND_RANK.get(r["kind"], 9) < KIND_RANK.get(a["kind"], 9):
            r = {**r, "also": a["also"] + [a["kind"]]}
            if not r["time"]:
                r["time"], r["t24"] = a["time"], a["t24"]
            keep[k] = r
        elif r["kind"] != a["kind"] and r["kind"] not in a["also"]:
            a["also"].append(r["kind"])
            if not a["time"] and r["time"]:
                a["time"], a["t24"] = r["time"], r["t24"]
    return [keep[k] for k in order]


def rank(rows):
    return sorted(rows, key=lambda r: (r["sev"], r["date"], r["t24"] or "99", r["title"]))


def _only(rows, who):
    return [r for r in rows if r["person"] == who] if who else rows


def _strip(rows, today, names):
    order = {n: i for i, n in enumerate(list(names) + [HOUSE])}
    out = []
    for i in range(WEEK):
        d = today + dt.timedelta(days=i)
        day = [r for r in rows if r["date"] == d]
        people = sorted({r["person"] for r in day if r["person"]}, key=lambda p: order.get(p, 99))
        out.append({"date": d, "dow": f"{d:%a}", "day": d.day, "today": i == 0, "n": len(day), "people": people,
                    "dots": [avatar(p, names)[1] for p in people]})
    return out


def _money(needs, coming, today):
    bills = sorted([r for r in needs + coming if r["kind"] == "Bill" and r["date"] <= today + dt.timedelta(days=MONTH)],
                   key=lambda r: r["date"])
    nxt = next((r for r in bills if r["date"] >= today), bills[0] if bills else None)
    return {"due": sum(r.get("amount") or 0 for r in bills), "count": len(bills),
            "overdue": sum(1 for r in bills if r["date"] < today),
            "overdue_amt": sum(r.get("amount") or 0 for r in bills if r["date"] < today), "next": nxt}


def assemble(needs, coming, today, names, who=None):
    """Today's page from the Brief's Needs you rows and Coming up rows (tomorrow onwards)."""
    n_all = dedupe(decorate(needs, today, names))
    c_all = dedupe(decorate(coming, today, names))
    n, c = _only(n_all, who), _only(c_all, who)
    on_today = sorted([r for r in n if r["date"] == today and r["kind"] in TIMED], key=lambda r: (r["t24"] or "99", r["title"]))
    jobs = rank([r for r in n if r not in on_today])
    week = rank([r for r in c if today < r["date"] <= today + dt.timedelta(days=WEEK)])
    parts = []
    if on_today:
        parts.append(f"{len(on_today)} on today")
    if jobs:
        parts.append(f"{len(jobs)} need{'s' if len(jobs) == 1 else ''} you")
    later = rank([r for r in c if r["date"] > today + dt.timedelta(days=WEEK)])
    overdue = sum(1 for r in jobs if r["sev"] <= 1)
    # Today's one list (it took over To do): Late, Today, This week, then later this month folded away
    return {"today": on_today, "needs": jobs, "needs_total": len(jobs), "week": week,
            "late": [r for r in jobs if r["sev"] <= 1], "due": [r for r in jobs if r["sev"] > 1], "later": later,
            "overdue": overdue, "due_today": len(jobs) - overdue,
            "week_total": len(week), "money": _money(n_all, c_all, today),
            "line": ", ".join(parts) if parts else "Nothing needs you today.",
            "strip": _strip(n + c, today, names), "who": who,
            # side blocks look ahead only: what is overdue or due today is already under Needs you
            "house": rank([r for r in c_all if r["person"] == HOUSE])[:CAP_SIDE],
            "renewals": rank([r for r in c_all if _renewal(r)])[:CAP_SIDE]}


def person_rows(needs, coming, today, names, who):
    return rank(_only(dedupe(decorate(list(needs) + list(coming), today, names)), who))


def family(needs, coming, today, members):
    """A tile per member (in family order) and one for the House: how many rows, how many overdue, the first one."""
    names = [m for m, _ in members]
    rows = dedupe(decorate(list(needs) + list(coming), today, names))
    out = []
    for name, role in list(members) + [(HOUSE, "house")]:
        mine = rank([r for r in rows if r["person"] == name])
        out.append({"name": name, "role": role, "count": len(mine), "overdue": sum(1 for r in mine if r["sev"] <= 1),
                    "next": mine[0]["title"] if mine else "", "next_pill": mine[0]["pill"] if mine else ""})
    return out


def avatar(name, names):
    """(initial, colour class) for a person chip or row; the House gets its own colour."""
    if name == HOUSE:
        return "H", "avh"
    if not name:
        return "", "avn"
    i = names.index(name) if name in names else len(name)
    return name[:1].upper(), f"av{i % 6}"


# ---- reading -------------------------------------------------------------------------------------------------------
def members(con):
    try:
        return [(r[0], r[1]) for r in con.execute("SELECT name, role FROM members ORDER BY id")]
    except sqlite3.OperationalError as e:
        import db
        if not db.missing(e):
            raise
        return []


def members_now():
    import db
    import paths
    con = db.connect(paths.DB, readonly=True)
    try:
        return members(con)
    finally:
        con.close()


def _load(ctx):
    import brief_data as bd
    mem = members_now()
    needs = bd.needs_you(ctx)
    coming = bd.coming_up(ctx, ctx.today + dt.timedelta(days=1), ctx.today + dt.timedelta(days=MONTH))
    return mem, needs, coming


def chips(mem, who):
    names = [m for m, _ in mem]
    out = [{"name": "", "label": "Everyone", "on": not who, "av": ("", "")}]
    for name, _role in list(mem) + [(HOUSE, "house")]:
        out.append({"name": name, "label": name, "on": who == name, "av": avatar(name, names)})
    return out


def valid_who(mem, who):
    return who if who and (who == HOUSE or who in [m for m, _ in mem]) else ""


def summary(ctx, who=""):
    """The one set of numbers Today and the phone show: needs = overdue + due_today (what needs someone now),
    week = coming up in the next 7 days, money = bills due in 30 days with the overdue ones included."""
    mem, needs, coming = _load(ctx)
    v = assemble(needs, coming, ctx.today, [m for m, _ in mem], valid_who(mem, who) or None)
    return {"needs": v["needs_total"], "overdue": v["overdue"], "due_today": v["due_today"], "week": v["week_total"],
            "on_today": len(v["today"]), "money": v["money"]}


def today_view(ctx, who=""):
    mem, needs, coming = _load(ctx)
    who = valid_who(mem, who)
    v = assemble(needs, coming, ctx.today, [m for m, _ in mem], who or None)
    h = dt.datetime.now().hour
    v.update(chips=chips(mem, who), names=[m for m, _ in mem], who=who,
             greeting="Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening",
             spend=None if who else _month_spend(ctx.today))
    return v


def _month_spend(today):
    """This month so far for the Today day card (spent, income, kept %, top categories), or None without statements."""
    import db
    import paths
    import trends
    try:
        with db.open(paths.DB, readonly=True) as con:
            ym = today.strftime("%Y-%m")
            if ym not in trends.months_available(con):
                return None
            return trends.month_summary(con, ym, top=4, today=today)
    except sqlite3.Error:
        return None


def _member_ids():
    """{name: members.id} for the edit icon on the Family tiles (the person's record opens in Records)."""
    import db
    import paths
    try:
        with db.open(paths.DB, readonly=True) as con:
            return {n: i for i, n in con.execute("SELECT id, name FROM members")}
    except sqlite3.Error:
        return {}


def family_view(ctx, who=""):
    mem, needs, coming = _load(ctx)
    who = valid_who(mem, who)
    names = [m for m, _ in mem]
    tiles = family(needs, coming, ctx.today, mem)
    ids = _member_ids()
    for t in tiles:
        t["av"] = avatar(t["name"], names)
        t["edit_id"] = ids.get(t["name"])
    rows = person_rows(needs, coming, ctx.today, names, who) if who else []
    return {"tiles": tiles, "who": who, "rows": rows, "names": names, "chips": chips(mem, who)}


def month_view(ctx, ym=None):
    """This month: spend against the budget so far, bills, subscriptions, cancel-before-charge, house and car, renewals."""
    import budget
    import db
    import paths
    mem, needs, coming = _load(ctx)
    names = [m for m, _ in mem]
    rows = dedupe(decorate(list(needs) + list(coming), ctx.today, names))
    con = db.connect(paths.DB, readonly=True)
    try:
        try:
            p = budget.pace(con, ctx.today)
        except sqlite3.OperationalError:
            p = {"lines": [], "loaded": False, "through": ctx.today}
        try:
            import trends
            summary = trends.month_summary(con, ym, today=ctx.today)
        except sqlite3.OperationalError:
            summary = None
    finally:
        con.close()
    lines = [x for x in p["lines"] if not x["allowance"]]
    subs = [s for s in ctx.snap.get("trk") or [] if s.get("tracked_active") and s.get("status") == "active"]
    subs.sort(key=lambda s: (s.get("next") or dt.date.max, s.get("name") or ""))
    return {"summary": summary, "budget": lines[:6], "budget_more": max(0, len(lines) - 6),
            "spent": sum(x["spent"] for x in lines), "limit": sum(x["limit"] for x in lines),
            "loaded": p["loaded"], "through": p["through"],
            "bills": sorted([r for r in rows if r["kind"] == "Bill"], key=lambda r: r["date"]),
            "subs": [{"name": s["name"], "amount": s.get("last_amount"), "next": s.get("next")} for s in subs],
            "subs_month": sum(s.get("per_month") or 0 for s in subs),
            "cancel": rank([r for r in rows if r["kind"] == "Cancel"]),
            "house": rank([r for r in rows if r["person"] == HOUSE]),
            "renewals": rank([r for r in rows if _renewal(r) and r["kind"] != "Cancel"]),
            "names": names}


def _amount(a):
    s = f"{a:,.2f}"
    return "$" + (s[:-3] if s.endswith(".00") else s)


def _named(r):
    """'Brightwave $70' for a bill with an amount, else the short title."""
    return r["title"] + (f" {_amount(r['amount'])}" if r.get("kind") == "Bill" and r.get("amount") else "")


def _and(parts):
    """[[seg..], [seg..], ..] joined with ', ' and ' and ' into one list of (text, strong) segments."""
    out = []
    for i, p in enumerate(parts):
        if i:
            out.append((" and " if i == len(parts) - 1 else ", ", False))
        out.extend(p)
    return out


def narrative_rows(v):
    """The rows the brief talks about (late, due, on the calendar today) as the AI helper takes them: date, kind and
    short title only. No amounts, notes or details leave the PC (data/brief_narrative.py masks the names on top)."""
    return [{"date": r["date"], "kind": r.get("kind", "Item"), "title": r["title"]}
            for r in v["late"] + v["due"] + v["today"]]


def brief(v, rain=""):
    """Mitra's morning brief on Today: a few plain sentences built from the page's own rows (no AI call), each a list of
    (text, strong) segments. `rain` is the weather's rain line ('Rain likely from 3 PM'), said only when rain, snow or
    storms are on the way."""
    return brief_items(v) + brief_more(v, rain)


def brief_items(v):
    """The brief's sentences about the rows (late, due, on the calendar today): the part the AI may say in its own
    words (it gets the same rows, see narrative_rows)."""
    say = []
    late, due = v["late"], v["due"]
    if late:
        n = len(late)
        names = [[(_named(r), True)] for r in late[:2]]
        if n > 2:
            names.append([(f"{n - 2} more", False)])
        say.append([(f"{n} thing{'s are' if n != 1 else ' is'} late: ", False)] + _and(names) + [(".", False)])
    if due:
        n = len(due)
        lead = "Due today: " if not late else "Also due today: "
        say.append([(lead, False)] + _and([[(_named(r), True)] for r in due[:2]]
                                         + ([[(f"{n - 2} more", False)]] if n > 2 else [])) + [(".", False)])
    if not late and not due:
        say.append([("Nothing needs you today.", False)])
    if v["today"]:
        items = []
        for r in v["today"][:2]:
            who = r.get("person")
            items.append([(r["title"], True)] + ([(f" for {who}", False)] if who and who != HOUSE else []))
        more = len(v["today"]) - 2
        if more > 0:
            items.append([(f"{more} more", False)])
        say.append([("On the calendar today: ", False)] + _and(items) + [(".", False)])
    return say


def brief_more(v, rain=""):
    """The brief's other sentences (rain, spent so far, next bill): the AI never sees them, so they stay under its
    wording too."""
    say = []
    if rain and any(w in rain.lower() for w in ("rain", "snow", "storm", "shower")) and not rain.lower().startswith("no "):
        say.append([(rain.rstrip(".") + ".", False)])
    sp = v.get("spend")
    if sp and sp.get("spent") is not None:
        line = [("So far this month ", False), (_amount(round(sp["spent"])), True), (" spent", False)]
        if sp.get("income"):
            line += [(f" and {_amount(round(sp['income']))} came in", False)]
        say.append(line + [(".", False)])
    mo = v.get("money") or {}
    nxt = mo.get("next")
    if not v["late"] and nxt and nxt.get("pill"):
        when = nxt["pill"] if nxt["pill"].startswith("in ") else nxt["pill"].lower()
        say.append([("Next bill: ", False), (_named(nxt), True), (f", {when}.", False)])
    return say
