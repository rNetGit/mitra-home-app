"""0.100: the family-first Today page. today_data turns the Brief rows into Today / Family / This month: whose row it is,
duplicates merged, ranked (expired and overdue first), urgency pills, capped blocks, a 7-day strip and a person filter.
The pure parts are tested on plain rows; the pages are tested through the web app (adults only, kids keep their page)."""
import datetime as dt
import html
import re
import sqlite3

import pytest

T = dt.date(2026, 10, 14)
NAMES = ["Marcus", "Elena", "Sofia", "Mateo", "Pancho"]


def row(days, kind, title, detail="", amount=None, src="item", ref=None, key=None):
    return {"src": src, "date": T + dt.timedelta(days=days), "kind": kind, "title": title, "detail": detail,
            "amount": amount, "key": key or f"k-{kind}-{title}-{days}", "it": {"ref": ref}, "sid": title}


@pytest.fixture()
def td(modules):
    return modules("today_data")


def test_person_of_reads_the_name_in_the_title(td):
    assert td.person_of({"title": "Braces adjustment (Sofia)", "kind": "Medical"}, NAMES) == "Sofia"
    assert td.person_of({"title": "Mateo passport EXPIRED", "kind": "ID"}, NAMES) == "Mateo"
    assert td.person_of({"title": "Elena's birthday (turns 42)", "kind": "Birthday"}, NAMES) == "Elena"
    assert td.person_of({"title": "Mateo: third-grade recital", "kind": "Event"}, NAMES) == "Mateo"
    assert td.person_of({"title": "Gaming laptop (Sofia): needs a receipt", "kind": "Warranty"}, NAMES) == "Sofia"
    assert td.person_of({"title": "Replace HVAC filter (household)", "kind": "Home"}, NAMES) == td.HOUSE
    assert td.person_of({"title": "Washer: needs a receipt", "kind": "Warranty"}, NAMES) == td.HOUSE
    assert td.person_of({"title": "2021 Honda CR-V inspection expires", "kind": "Renewal",
                         "it": {"ref": ("vehicles", 1)}}, NAMES) == td.HOUSE
    assert td.person_of({"title": "Verizon", "kind": "Bill"}, NAMES) is None
    assert td.person_of({"title": "Marcuston Plumbing", "kind": "Bill"}, NAMES) is None, "whole words only"


def test_short_title_drops_the_name_the_avatar_shows(td):
    assert td.short_title("Braces adjustment (Sofia)", "Sofia") == "Braces adjustment"
    assert td.short_title("Replace HVAC filter (household)", td.HOUSE) == "Replace HVAC filter"
    assert td.short_title("Verizon", None) == "Verizon"
    assert td.short_title("Mateo: third-grade recital", "Mateo") == "Third-grade recital"
    assert td.short_title("Sofia soccer tournament", "Sofia") == "Soccer tournament"
    assert td.short_title("Elena's birthday (turns 42)", "Elena") == "Elena's birthday (turns 42)"


def test_dedupe_merges_same_title_person_and_date(td):
    rows = [row(6, "Appointment", "Braces adjustment (Sofia)", "Smile Ortho 15:30", ref=("appointments", 1)),
            row(6, "Medical", "Braces adjustment (Sofia)", "Smile Ortho", ref=("life_items", 17)),
            row(7, "Medical", "Braces adjustment (Sofia)"),
            row(6, "Medical", "Braces adjustment (Mateo)")]
    out = td.dedupe(td.decorate(rows, T, NAMES))
    assert len(out) == 3
    braces = [r for r in out if r["person"] == "Sofia" and r["date"] == T + dt.timedelta(days=6)]
    assert len(braces) == 1 and braces[0]["kind"] == "Appointment" and braces[0]["time"] == "3:30 PM"
    assert braces[0]["also"] == ["Medical"]


def test_rank_puts_expired_and_overdue_first_then_today_then_the_week(td):
    rows = td.decorate([row(3, "Bill", "Verizon"), row(0, "Chore", "Wash the car (Sofia)"),
                        row(-2, "School", "Band form (Sofia)"), row(-20, "ID", "Mateo passport EXPIRED"),
                        row(40, "ID", "Elena passport EXPIRED")], T, NAMES)
    order = [r["title"] for r in td.rank(rows)]
    assert order[:2] == ["Passport EXPIRED", "Passport EXPIRED"] and rows[3]["person"] == "Mateo", "an expired paper is first, dated or not"
    assert order.index("Band form") < order.index("Wash the car") < order.index("Verizon")


def test_pills_say_how_urgent_and_colour_only_overdue_and_today(td):
    assert td.pill(T - dt.timedelta(days=7), T) == ("Overdue 7d", "danger")
    assert td.pill(T, T) == ("Today", "warn")
    assert td.pill(T + dt.timedelta(days=1), T) == ("Tomorrow", "")
    assert td.pill(T + dt.timedelta(days=6), T) == ("in 6d", "")
    assert td.pill(T + dt.timedelta(days=12), T)[0] == "Oct 26"


def test_assemble_splits_today_needs_week_and_caps_blocks(td):
    needs = [row(-21, "ID", "Mateo passport EXPIRED"), row(-7, "School", "Band fundraiser form (Sofia)"),
             row(-5, "Medical", "Tdap booster (Sofia)"), row(-13, "Renewal", "2017 Toyota Tacoma inspection expires",
                                                              ref=("vehicles", 2)),
             row(0, "Warranty", "Washer: needs a receipt"), row(0, "Appointment", "Flu shot (Mateo)", "Clinic 09:15"),
             row(0, "Seasonal", "Flu shots", src="seasonal")]
    coming = [row(2, "Chore", "Wash the car (Sofia)"), row(3, "Bill", "Verizon", amount=191.5),
              row(6, "Appointment", "Braces adjustment (Sofia)", "Smile Ortho 15:30"),
              row(6, "Medical", "Braces adjustment (Sofia)"), row(20, "Bill", "Mortgage", amount=2150)]
    v = td.assemble(needs, coming, T, NAMES)
    assert [r["title"] for r in v["today"]] == ["Flu shot"]
    assert v["needs_total"] == 6 and len(v["needs"]) == 6, "Today lists every row (it took over To do)"
    assert v["late"][0]["title"] == "Passport EXPIRED" and len(v["late"]) + len(v["due"]) == 6
    assert all(r["sev"] <= 1 for r in v["late"]) and all(r["sev"] == 2 for r in v["due"])
    assert [r["title"] for r in v["later"]] == ["Mortgage"], "8 to 30 days ahead, folded under Later this month"
    assert v["needs"][0]["title"] == "Passport EXPIRED" and v["needs"][0]["person"] == "Mateo"
    assert [r["title"] for r in v["week"]] == ["Wash the car", "Verizon", "Braces adjustment"], "7 days, merged"
    assert v["money"]["due"] == pytest.approx(191.5 + 2150) and v["money"]["next"]["title"] == "Verizon"
    assert v["line"] == "1 on today, 6 need you"
    assert len(v["strip"]) == 7 and v["strip"][0]["today"] and v["strip"][2]["people"] == ["Sofia"]
    only = td.assemble(needs, coming, T, NAMES, who="Sofia")
    assert {r["person"] for r in only["needs"] + only["week"]} == {"Sofia"} and only["today"] == []
    house = td.assemble(needs, coming, T, NAMES, who=td.HOUSE)
    assert {r["title"] for r in house["needs"]} == {"2017 Toyota Tacoma inspection expires", "Washer: needs a receipt",
                                                    "Flu shots"}
    quiet = td.assemble([], [], T, NAMES)
    assert quiet["line"] == "Nothing needs you today."


def test_family_tiles_and_one_persons_list(td):
    rows = [row(-7, "School", "Band fundraiser form (Sofia)"), row(6, "Medical", "Braces adjustment (Sofia)"),
            row(7, "Pet", "Heartworm pill (Pancho)"), row(11, "Home", "Replace HVAC filter (household)"),
            row(3, "Bill", "Verizon")]
    tiles = td.family(rows, [], T, [("Marcus", "adult"), ("Sofia", "child"), ("Pancho", "pet")])
    by = {t["name"]: t for t in tiles}
    assert list(by) == ["Marcus", "Sofia", "Pancho", td.HOUSE]
    assert by["Sofia"]["count"] == 2 and by["Sofia"]["overdue"] == 1 and by["Sofia"]["next"] == "Band fundraiser form"
    assert by["Marcus"]["count"] == 0 and by[td.HOUSE]["count"] == 1
    one = td.person_rows(rows, [], T, NAMES, "Sofia")
    assert [r["title"] for r in one] == ["Band fundraiser form", "Braces adjustment"]


# ---- pages -------------------------------------------------------------------------------------------------------
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def web(root, modules):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    return TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)


def _sql(modules, sql, *params):
    con = sqlite3.connect(modules("paths").DB)
    try:
        with con:
            return con.execute(sql, params).fetchall()
    finally:
        con.close()


def test_today_page_for_adults_with_person_filter(web, modules):
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    name = _sql(modules, "SELECT name FROM members ORDER BY id")[0][0]
    today = dt.date.today()
    _sql(modules, "INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Power','PowerCo',80,?,'due')",
         (today - dt.timedelta(days=3)).isoformat())
    _sql(modules, "INSERT INTO life_items(domain, member, title, due_date, status) VALUES ('school',?,'Zebra trip form',?,'open')",
         name, (today + dt.timedelta(days=2)).isoformat())
    page = c.get("/").text
    assert "<h1>Today</h1>" in page and 'id="h-late"' in page and "PowerCo" in page and "Zebra trip form" in page
    assert 'aria-current="page"' in page and 'href="/family"' in page and 'href="/money?part=month"' in page
    assert "Overdue 3d" in page
    page = c.get("/", params={"who": name}).text
    assert "Zebra trip form" in page and "PowerCo" not in page, "the person chip filters the page"
    assert c.get("/", params={"who": "<script>"}).status_code == 200
    fam = c.get("/family").text
    assert "<h1>Family</h1>" in fam and name in fam
    one = c.get("/family", params={"who": name}).text
    assert "Zebra trip form" in one
    month = c.get("/money?part=month").text
    assert "<h1>Money</h1>" in month and "where the money went" in month
    old = c.get("/brief", params={"who": name}, follow_redirects=False)
    assert old.status_code == 303 and old.headers["location"].startswith("/?who="), "To do lives on Today now"


def test_today_first_needs_you_leads_with_counts_and_done_paid_on_the_rows(web, modules):
    """0.106: Needs you is the first block (phones stack it on top), headings carry counts, a Needs you row has
    Done / Paid in place (same ops as the Brief) with a flash and Undo after a paid bill; the Money card says what is
    overdue before the 30-day total."""
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    name = _sql(modules, "SELECT name FROM members ORDER BY id")[0][0]
    today = dt.date.today()
    _sql(modules, "INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Water','WaterCo',80,?,'due')",
         (today - dt.timedelta(days=3)).isoformat())
    _sql(modules, "INSERT INTO life_items(domain, member, title, due_date, status) VALUES ('school',?,'Zebra trip form',?,'open')",
         name, (today - dt.timedelta(days=5)).isoformat())
    page = c.get("/").text
    assert page.index('id="h-late"') < page.index('id="h-today"') < page.index('aria-label="Money, house and renewals"')
    assert "Zebra trip form" in page and 'class="story deck' not in page, "the old day card is gone"
    n = int(re.search(r'Late <span class="cnt">(\d+)</span>', page).group(1))
    assert n >= 2, "the count in the heading"
    assert 'aria-label="Paid: WaterCo' in page and 'aria-label="Done: Zebra trip form' in page
    assert '<b class="pt danger">Overdue 3d</b>' in page, "a row with a button keeps its urgency in the meta line"
    assert re.search(r"\d+ bills? overdue · \$", page) and "Bills in the next 30 days" in page
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    key = re.search(r'"key": "([^"]+)", "op": "done", "who": ""}[^>]*aria-label="Paid: WaterCo', html.unescape(page)).group(1)
    assert c.post("/today/act", data={"key": key, "who": ""}).status_code == 403, "needs the CSRF token"
    r = c.post("/today/act", data={"key": key, "who": ""}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/"
    page = c.get("/").text
    assert "Marked WaterCo as paid." in page and 'hx-post="/today/undo"' in page
    late = page.split('id="h-late"', 1)[1].split('<h2 class="sec">Today', 1)[0]
    assert 'aria-label="Paid: WaterCo' not in late and f'Late <span class="cnt">{n - 1}</span>' in page
    undo = re.search(r'"bill": "(\d+)", "due": "([^"]+)"', html.unescape(page))
    r = c.post("/today/undo", data={"bill": undo.group(1), "due": undo.group(2), "who": ""}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/"
    page = c.get("/").text
    assert "Put back on the list." in page and 'aria-label="Paid: WaterCo' in page
    assert "Put back" not in c.get("/").text, "the flash shows once"
    r = c.post("/today/act", data={"key": "nope", "who": name}, headers={"X-CSRF-Token": token})
    assert r.headers["HX-Redirect"] == f"/?who={name}" and "no longer on the list" in c.get("/", params={"who": name}).text
    assert c.post("/today/undo", data={"bill": "x", "due": "2026-13-40"}, headers={"X-CSRF-Token": token}).status_code == 400


def test_kids_keep_their_page_and_cannot_open_family_or_month(web):
    c = web
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    assert "Needs you" not in c.get("/").text
    assert c.get("/family").status_code == 403 and c.get("/money?part=month").status_code == 403
    assert re.search(r"adults", c.get("/money?part=month").text)


def test_rail_and_phone_bar_for_adults_only(web, modules):
    """Five tabs on the rail and the phone's bottom bar (audit U14), More from the avatar, the Inbox count on Add; a page
    not yet folded into its tab lights that tab; kids get none of it."""
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    _sql(modules, "INSERT INTO proposals(dedupe_key, source, kind, summary) VALUES ('profile:t1','profile','question','Q?')")
    page = c.get("/notes").text
    rail = page[page.index('<nav class="rail"'):page.index("</nav>")]
    assert re.findall(r'<span class="tl">([^<]+)</span>', rail) == ["Today", "Calendar", "Add", "Money", "Family", "Notes", "Ask Mitra"]
    assert 'aria-label="Add or scan, 1 waiting in the Inbox"' in rail and 'class="rmore"' in rail
    menu = rail.split('class="rmenu"', 1)[1]
    assert 'href="/notes" class="tab on" aria-current="page"' in rail and 'href="/notes"' not in menu
    assert "Log out" in menu and "Help on this page" in menu
    bnav = page[page.index('<nav class="bnav"'):]
    bnav = bnav[:bnav.index("</nav>")]
    assert re.findall(r'</i>([A-Za-z]+)</a>', bnav) == ["Today", "Calendar", "Money", "Family"] and 'class="scan' in bnav
    assert 'class="bmore pme"' in page and page.count("data-theme-toggle") == 2
    for url, tab in (("/", "Today"), ("/money?part=month", "Money"), ("/money", "Money"), ("/records?domain=people", "Family"), ("/wallet", "Family"),
                     ("/add", "Add"), ("/calendar", "Calendar"), ("/notes", "Notes"), ("/settings", None)):
        r = c.get(url).text
        nav = r[r.index('<nav class="rail"'):r.index('<details class="rmore"')]
        on = re.findall(r'class="tab(?: add)? on"[^>]*><i [^>]*></i><span class="tl">([^<]+)', nav)
        assert on == ([tab] if tab else []), url
    css = c.get("/tokens.css").text
    assert "--radius:12px" in css and ".av0,.av.av0{" in css
    c.post("/logout", headers={"X-CSRF-Token": re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)})
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    kid = c.get("/").text
    assert 'class="bnav"' not in kid and 'class="rmore"' not in kid and "badge" not in kid and 'class="tl"' not in kid


def test_today_folds_later_and_documents_and_family_cards(web, modules):
    """Today took over To do: rows 8 to 30 days ahead fold under Later this month, each row has the ⋯ menu, Documents
    sit at the foot; Family tiles are cards coloured like each person's avatar."""
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    name = _sql(modules, "SELECT name FROM members ORDER BY id")[0][0]
    today = dt.date.today()
    _sql(modules, "INSERT INTO life_items(domain, member, title, due_date, status) VALUES ('school',?,'Zebra <b>form',?,'open')",
         name, (today - dt.timedelta(days=2)).isoformat())
    _sql(modules, "INSERT INTO life_items(domain, member, title, due_date, status) VALUES ('school',?,'Yak permit',?,'open')",
         name, (today + dt.timedelta(days=10)).isoformat())
    body = c.get("/").text
    later = body.split("Later this month", 1)[1].split('<details class="tfold">', 1)[0]
    assert "Yak permit" in later and "Zebra" not in later
    assert 'aria-label="Details, snooze, hide: ' in body and "Snooze 30 days" in body
    assert body.index("Later this month") < body.index('hx-post="/today/doc"')
    fam = c.get("/family").text
    assert 'class="tile ptile gav0' in fam and 'class="tile ptile gavh' in fam and "items in 30 days" in fam
    assert "Zebra <b>form" not in fam and "Zebra <b>form" not in body


def _said(lines):
    return " ".join("".join(t for t, _ in line) for line in lines)


def test_brief_says_what_is_late_due_on_today_and_rain(td):
    rows = [row(-2, "Bill", "Brightwave", amount=70.0), row(-1, "Home", "Replace furnace filter (household)"),
            row(-3, "Bill", "Water", amount=42.5), row(0, "Backup", "The backup is missing"),
            row(0, "Class", "Piano 16:00-16:30 (Mateo)")]
    v = td.assemble(rows, [], T, NAMES)
    v["spend"] = {"spent": 2542.4, "income": 5690}
    said = _said(td.brief(v, "Rain likely from 3 PM"))
    assert said.startswith("3 things are late: Water $42.50, Brightwave $70 and 1 more. Also due today: The backup is missing.")
    assert "On the calendar today: Piano 16:00-16:30 for Mateo." in said
    assert "Rain likely from 3 PM." in said and "So far this month $2,542 spent and $5,690 came in." in said
    strong = [t for line in td.brief(v) for t, s in line if s]
    assert strong[:2] == ["Water $42.50", "Brightwave $70"], "the late things are what stands out"


def test_brief_on_a_quiet_day_and_no_rain(td):
    v = td.assemble([], [row(3, "Bill", "City Water", amount=142.18)], T, NAMES)
    said = _said(td.brief(v, "No rain expected"))
    assert said.startswith("Nothing needs you today.") and "rain" not in said.lower()
    assert "Next bill: City Water $142.18, in 3d." in said


def test_today_shows_the_brief_and_the_ask_bar(web):
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/").text
    assert 'class="brief"' in page and "Mitra noticed" in page and 'id="askq"' in page
    assert 'href="/chat">Chat</a>' not in page, "the Ask Mitra bar took over the Chat button"
    assert 'id="askq"' not in c.get("/chat").text, "Chat has its own box"


def test_ask_bar_puts_the_question_in_chat_and_opens_it(web):
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    token = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    assert c.post("/chat/ask", data={"text": "hello"}).status_code == 403, "no CSRF token"
    r = c.post("/chat/ask", data={"text": "what is due this week"}, headers={"X-CSRF-Token": token})
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/chat#chatlog"
    assert "what is due this week" in c.get("/chat").text
