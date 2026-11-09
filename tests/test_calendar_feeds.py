"""Other calendars (data/calendar_feeds.py): .ics addresses read-only, repeating events, time zones, the list kept in
config/ and shown on the Calendar page; added only on this PC; fetched only from public hosts."""
import datetime as D
import json

import pytest

from test_webapp import _csrf, _login, _post, web  # noqa: F401 (the web fixture)

ICS = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
SUMMARY:Team stand-up\r
DTSTART;TZID=America/New_York:20261019T090000\r
DTEND;TZID=America/New_York:20261019T091500\r
RRULE:FREQ=WEEKLY;BYDAY=MO,WE;COUNT=6\r
EXDATE;TZID=America/New_York:20261021T090000\r
DESCRIPTION:secret agenda\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Conference\\, day one\r
DTSTART;VALUE=DATE:20261025\r
DTEND;VALUE=DATE:20261027\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Call with\r
  Pat\r
DTSTART:20261020T170000Z\r
DTEND:20261020T173000Z\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Cancelled thing\r
STATUS:CANCELLED\r
DTSTART:20261020T120000\r
END:VEVENT\r
BEGIN:VEVENT\r
SUMMARY:Long ago\r
DTSTART:20200101T120000\r
END:VEVENT\r
END:VCALENDAR\r
"""


@pytest.fixture()
def cf(modules, monkeypatch):
    m = modules("calendar_feeds")
    m._list_path().unlink(missing_ok=True)
    m._cache_path().unlink(missing_ok=True)
    monkeypatch.setattr(m, "_local_tz", lambda: D.timezone(D.timedelta(hours=-4)))  # New York in October
    return m


def test_parse_repeats_time_zones_all_day_and_skips(cf):
    ev = cf.parse(ICS, D.date(2026, 10, 19), days=30)
    titles = [(e["date"], e["time"], e["title"]) for e in ev]
    standups = [t for t in titles if t[2] == "Team stand-up"]
    assert [d for d, _, _ in standups] == ["2026-10-19", "2026-10-26", "2026-10-28", "2026-11-02", "2026-11-04"], \
        "MO / WE, six times, the 21st left out"
    assert standups[0][1] == "09:00" and next(e for e in ev if e["title"] == "Team stand-up")["end"] == "09:15"
    call = next(e for e in ev if e["title"].startswith("Call"))
    assert call["title"] == "Call with Pat" and (call["date"], call["time"], call["end"]) == ("2026-10-20", "13:00", "13:30")
    conf = next(e for e in ev if e["title"] == "Conference, day one")
    assert conf["all_day"] and conf["date"] == "2026-10-25" and conf["end"] == "2026-10-26"
    assert not any(e["title"] in ("Cancelled thing", "Long ago") for e in ev)
    assert "secret" not in json.dumps(ev), "descriptions are not kept"


def test_monthly_yearly_until_and_interval(cf):
    ics = ("BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Rent\nDTSTART;VALUE=DATE:20260131\nRRULE:FREQ=MONTHLY\nEND:VEVENT\n"
           "BEGIN:VEVENT\nSUMMARY:Bins\nDTSTART:20261001T070000\nRRULE:FREQ=DAILY;INTERVAL=14;UNTIL=20261120T000000Z\n"
           "END:VEVENT\nEND:VCALENDAR\n")
    ev = cf.parse(ics, D.date(2026, 10, 1), days=60)
    assert [e["date"] for e in ev if e["title"] == "Rent"] == ["2026-10-31", "2026-11-30"], "a short month takes its last day"
    assert [e["date"] for e in ev if e["title"] == "Bins"] == ["2026-10-01", "2026-10-15", "2026-10-29", "2026-11-12"]


@pytest.mark.parametrize("rule", ["FREQ=DAILY;INTERVAL=99999999999", "FREQ=WEEKLY;INTERVAL=99999999999",
                                  "FREQ=YEARLY;INTERVAL=99999999999", "FREQ=MONTHLY;INTERVAL=99999999999"])
def test_a_huge_interval_does_not_break_the_feed(cf, rule):
    """audit 2026-10-28: a hostile feed's INTERVAL overflowed the date maths and the Calendar panel failed"""
    ics = (f"BEGIN:VCALENDAR\nBEGIN:VEVENT\nSUMMARY:Odd\nDTSTART;VALUE=DATE:20261005\nRRULE:{rule}\nEND:VEVENT\n"
           "BEGIN:VEVENT\nSUMMARY:Fine\nDTSTART;VALUE=DATE:20261006\nEND:VEVENT\nEND:VCALENDAR\n")
    ev = cf.parse(ics, D.date(2026, 10, 1), days=60)
    assert [e["title"] for e in ev] == ["Odd", "Fine"], "the first time still shows and the other events too"


def test_the_list_add_remove_and_clean_addresses(cf):
    with pytest.raises(cf.FeedError):
        cf.add("Work", "ftp://example.com/cal.ics")
    with pytest.raises(cf.FeedError):
        cf.add("Work", "https://user:pw@example.com/cal.ics")
    with pytest.raises(cf.FeedError):
        cf.add("", "https://example.com/cal.ics")
    fid, name = cf.add("Work", "webcal://example.com/cal.ics")
    assert cf.feeds() == [{"id": fid, "name": "Work", "url": "https://example.com/cal.ics"}]
    with pytest.raises(cf.FeedError):
        cf.add("Again", "https://example.com/cal.ics")
    assert cf.remove(fid) == "Work" and cf.feeds() == []


def test_fetch_only_public_hosts_and_calendars(cf, modules, monkeypatch):
    lk = modules("lookups")
    monkeypatch.setattr(lk, "_public_host", lambda h: h != "router.local")
    with pytest.raises(cf.FeedError, match="public internet"):
        cf.fetch("https://router.local/cal.ics")
    monkeypatch.setattr(lk, "_open", lambda req: (200, "text/html", b"<html>login</html>", req.full_url))
    with pytest.raises(cf.FeedError, match="not a calendar"):
        cf.fetch("https://example.com/cal.ics")
    seen = []
    monkeypatch.setattr(lk, "_open", lambda req: (seen.append(req.full_url), (200, "text/calendar", ICS.encode(), req.full_url))[1])
    fid, _ = cf.add("Work", "webcal://example.com/cal.ics")
    out = cf.view(14, today=D.date(2026, 10, 19), now=D.datetime(2026, 10, 19, 8, 0))
    assert seen == ["https://example.com/cal.ics"] and out[0]["name"] == "Work" and out[0]["events"]
    assert cf.view(14, today=D.date(2026, 10, 19), now=D.datetime(2026, 10, 19, 8, 30)) and len(seen) == 1, "cached for an hour"
    monkeypatch.setattr(lk, "_open", lambda req: (_ for _ in ()).throw(OSError("down")))
    out = cf.view(14, today=D.date(2026, 10, 19), now=D.datetime(2026, 10, 19, 10, 0))
    assert "could not be reached" in out[0]["error"] and out[0]["events"], "the last copy stays on a failure"


def test_settings_add_only_on_this_pc_and_the_calendar_shows_it(web, modules, monkeypatch):  # noqa: F811
    c, _, _ = web
    cf = modules("calendar_feeds")
    cf._list_path().unlink(missing_ok=True)
    cf._cache_path().unlink(missing_ok=True)
    lk = modules("lookups")
    monkeypatch.setattr(lk, "_public_host", lambda h: True)
    monkeypatch.setattr(lk, "_open", lambda req: (200, "text/calendar", ICS.replace("2026", str(modules("dates").today().year)).encode(), req.full_url))
    _login(c)
    token = _csrf(c)
    app_mod = modules("webapp.app")
    monkeypatch.setattr(app_mod, "is_local", lambda request: False)
    r = _post(c, "/settings/feeds", token, op="add", name="Work", url="https://example.com/cal.ics")
    assert cf.feeds() == []
    monkeypatch.setattr(app_mod, "is_local", lambda request: True)
    r = _post(c, "/settings/feeds", token, op="add", name="Work", url="https://example.com/cal.ics")
    assert r.status_code == 200 and len(cf.feeds()) == 1
    page = c.get("/settings?group=connections").text
    assert "Other calendars" in page and "example.com" in page and "https://example.com/cal.ics" not in page
    assert "calendar_feed_add" in (modules("paths").LOGS / "admin_audit.log").read_text(encoding="utf-8")
    assert "<h2 class=\"sec\">Work" in c.get("/calendar/google?days=14").text
    fid = cf.feeds()[0]["id"]
    _post(c, "/settings/feeds", token, op="remove", id=fid)
    assert cf.feeds() == []
