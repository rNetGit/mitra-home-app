"""Manage calendar (/calendar/manage): the family's events, holidays and days off in one list; Change for calendar days;
calendar chips linked to the record they come from; built-in holidays read-only."""
import datetime as D
import re
import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from test_webapp import _csrf, _login, _post, web  # noqa: F401 (the web fixture)

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}
SOON = (D.date.today() + D.timedelta(days=5)).isoformat()
LATER = (D.date.today() + D.timedelta(days=9)).isoformat()


def _sql(modules, sql, *params):
    con = sqlite3.connect(modules("paths").DB)
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.fetchall()
    finally:
        con.close()


# ---- the Change op for calendar days ------------------------------------------------------------------------------
def test_calendar_day_update_changes_and_checks(modules):
    ea = modules("edit_actions")
    assert ea.calendar_day_add(ADULT, SOON, "Teacher day", "closure")[0]
    rid = _sql(modules, "SELECT id FROM calendar_days WHERE name='Teacher day'")[0][0]
    ok, msg = ea.calendar_day_update(ADULT, rid, LATER, "Staff day", "early", LATER, None)
    assert ok, msg
    row = _sql(modules, "SELECT day, end_day, kind, name, member FROM calendar_days WHERE id=?", rid)[0]
    assert row == (LATER, None, "early", "Staff day", None), "a last day equal to the first is no span"
    assert ea.calendar_day_update(ADULT, rid, LATER, "Staff day", "party")[0] is False
    assert ea.calendar_day_update(ADULT, rid, LATER, "Staff day", "early", "2020-01-01")[0] is False
    assert ea.calendar_day_update(ADULT, 99999, LATER, "x")[0] is False
    assert ea.calendar_day_update(KID, rid, LATER, "Hacked")[0] is False, "adults only"
    assert ea.calendar_day_add(ADULT, SOON, "Other", "holiday")[0]
    other = _sql(modules, "SELECT id FROM calendar_days WHERE name='Other'")[0][0]
    ok, msg = ea.calendar_day_update(ADULT, other, LATER, "Staff day", "early")
    assert not ok and "already" in msg, "no two active rows alike"
    assert ea.calendar_day_drop(ADULT, rid)[0]
    assert ea.calendar_day_update(ADULT, rid, LATER, "Staff day")[0] is False, "a removed day cannot be changed"


# ---- the page ---------------------------------------------------------------------------------------------------
def test_manage_page_needs_an_adult(web):  # noqa: F811
    c, _, _ = web
    assert c.get("/calendar/manage").status_code == 303
    _login(c, "Kid", "0000")
    assert c.get("/calendar/manage").status_code == 403
    c.cookies.clear()
    _login(c)
    r = c.get("/calendar/manage")
    assert r.status_code == 200 and "Manage calendar" in r.text
    assert 'href="/calendar/manage"' in c.get("/calendar").text, "linked from the Calendar header"


def test_manage_lists_edits_and_removes(web, modules):  # noqa: F811
    c, _, _ = web
    ev = _sql(modules, "INSERT INTO events (name, event_date, recurs_yearly) VALUES ('Family picnic', ?, 0)", SOON)
    day = _sql(modules, "INSERT INTO calendar_days (day, kind, name, source) VALUES (?, 'closure', 'Inservice day', 'manual')", LATER)
    _sql(modules, "INSERT INTO bills (name, vendor, amount, due_date, status) VALUES ('Water', 'City', 40, ?, 'due')", SOON)
    _login(c)
    page = c.get("/calendar/manage").text
    assert "Family picnic" in page and "Inservice day" in page
    assert "City" not in page, "bills are not editable here, so hidden until 'show everything'"
    full = c.get("/calendar/manage?all=1").text
    assert "City" in full and "Open record" in full and "ref=bills%3A" in full
    only = c.get("/calendar/manage?kind=Event").text
    assert "Family picnic" in only and "Inservice day" not in only
    # the Records edit page of a calendar day now carries a Change form
    edit = c.get(f"/records?ref=calendar_days:{day}").text
    assert 'name="end"' in edit and "Save changes" in edit
    token = _csrf(c)
    r = _post(c, "/records/edit", token, table="calendar_days", id=str(day), op="save", name="Inservice day (moved)",
              kind="closure", day=SOON, end="", who="household", back="/calendar/manage?kind=No+school")
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/calendar/manage?kind=No+school"
    assert _sql(modules, "SELECT name, day FROM calendar_days WHERE id=?", day) == [("Inservice day (moved)", SOON)]
    # add through the same forms, back to this page
    r = _post(c, "/records/add", token, part="people/dates", table="events", name="Game night", date=LATER, repeats="once",
              back="/calendar/manage")
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/calendar/manage"
    assert _sql(modules, "SELECT count(*) FROM events WHERE name='Game night'")[0][0] == 1
    # remove needs the tick; only a /calendar/manage address is honoured as the way back
    r = _post(c, "/records/edit", token, table="events", id=str(ev), op="drop", back="https://evil.example/")
    assert r.status_code == 200 and "HX-Redirect" not in r.headers and _sql(modules, "SELECT count(*) FROM events WHERE id=?", ev)[0][0] == 1
    r = _post(c, "/records/edit", token, table="events", id=str(ev), op="drop", sure="1", back="https://evil.example/")
    assert r.headers["HX-Redirect"].startswith("/records"), "a foreign address falls back to the Records list"
    assert _sql(modules, "SELECT count(*) FROM events WHERE id=?", ev)[0][0] == 0
    r = _post(c, "/records/edit", token, table="calendar_days", id=str(day), op="drop", sure="1", back="/calendar/manage")
    assert r.headers["HX-Redirect"] == "/calendar/manage"
    assert "Inservice day" not in c.get("/calendar/manage").text.split('id="cm-list"')[1]


def test_manage_filters_by_person_and_range_and_bad_input(web, modules):  # noqa: F811
    c, _, _ = web
    _sql(modules, "INSERT INTO calendar_days (day, kind, name, member, source) VALUES (?, 'closure', 'No school', 'Sam', 'manual')", SOON)
    _sql(modules, "INSERT INTO events (name, event_date, recurs_yearly) VALUES ('Family picnic', ?, 0)", SOON)
    _login(c)
    both = c.get("/calendar/manage").text
    assert "No school (Sam)" in both and "Family picnic" in both
    sam = c.get("/calendar/manage?who=Sam").text
    assert "No school (Sam)" in sam and "Family picnic" not in sam
    far = c.get("/calendar/manage?from=2031-01-01&to=2031-02-01").text
    assert "Family picnic" not in far and "Nothing here" in far
    for q in ("from=nope&to=bad", "from=2026-02-29", "to=1990-01-01", "who=%3Cscript%3E&kind=%3Cb%3E", "from=2020-01-01&to=2099-01-01"):
        assert c.get("/calendar/manage?" + q).status_code == 200


def test_built_in_holidays_are_read_only_rows(web, modules):  # noqa: F811
    c, _, _ = web
    _login(c)
    r = c.get("/calendar/manage?all=1&from=2026-12-24&to=2026-12-26")
    assert "Christmas Day" in r.text and "built in, read-only" in r.text
    row = re.search(r'<div class="brow cm-row[^"]*" data-source="built in">.*?</div>\s*</div>|data-source="built in">.*?(?=<div class="brow|</div>\s*{)', r.text, re.S)
    assert row and "Edit" not in row.group(0) and "Remove" not in row.group(0)


# ---- chips on the calendar link to their record ------------------------------------------------------------------
def test_calendar_chips_link_to_their_records(web, modules):  # noqa: F811
    c, _, _ = web
    ev = _sql(modules, "INSERT INTO events (name, event_date, recurs_yearly) VALUES ('Chip picnic', ?, 0)", SOON)
    day = _sql(modules, "INSERT INTO calendar_days (day, kind, name, source) VALUES (?, 'closure', 'Chip inservice', 'manual')", SOON)
    _login(c)
    html = c.get(f"/calendar?view=week&ref={SOON}").text
    assert f'href="/records?ref=events%3A{ev}"' in html and f'href="/records?ref=calendar_days%3A{day}"' in html
    assert re.search(r'<a class="kchip [^"]*"[^>]*>', html)
    cal = modules("calendar_data")
    refs = {}
    got = cal.load_events(D.date.today().year, D.date.today().year + 1, refs)
    assert any(k == "Event" and t == "Chip picnic" for items in got.values() for k, t in items)
    assert refs[(D.date.fromisoformat(SOON), "Event", "Chip picnic")] == f"events:{ev}"
    assert cal.load_events(D.date.today().year, D.date.today().year) is not None, "refs stays optional"


def test_shopping_items_of_one_list_and_day_fold_into_one_row():
    import calendar_manage as cm
    import datetime as dt
    d = dt.date(2026, 11, 27)

    def row(i, it):
        return {"date": d, "kind": "Shopping", "title": f"Thanksgiving 2026: {it}", "ref": f"shopping_items:{i}",
                "source": "record", "editable": False, "who": "", "past": False, "repeats": False}
    got = cm.fold_shopping([row(1, "Pillows"), row(2, "Sheets"), row(3, "iPhone"), row(4, "Griddle"), row(5, "Egg maker"),
                            {**row(9, "Milk"), "title": "Other list: Milk"}])
    assert [r["title"] for r in got] == ["Thanksgiving 2026 (5 items: Pillows, Sheets, iPhone, Griddle, ...)", "Other list: Milk"]
    assert got[0]["ref"] == "shopping_items:1"
    one = cm.fold_shopping([row(1, "Pillows")])
    assert one[0]["title"] == "Thanksgiving 2026: Pillows", "a single item keeps its own title"
