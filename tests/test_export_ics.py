"""Calendar file export (audit item 19): every due date as one .ics file a phone can import or subscribe to, with
no Google account. Stable UIDs so a re-import updates instead of duplicating; hidden items stay out; text escaped and
folded per RFC 5545; the weekly task and the Drive push carry the file."""
import datetime as D
import hashlib
import re
import sqlite3


from conftest import q, run

TODAY = D.date(2026, 10, 8)
ITEMS = [
    {"date": D.date(2026, 10, 15), "kind": "Bill", "title": "City Power, Inc; electricity", "detail": "Autopay is off",
     "amount": 123.45, "ref": ("bills", 7)},
    {"date": D.date(2026, 11, 2), "kind": "Birthday", "title": "Sam's birthday (turns 9)", "detail": "Gift / card / plan something?",
     "amount": None, "ref": ("members", 2)},
]
CRLF = "\r\n"


def _read(p):
    return p.read_bytes().decode("utf-8")  # keep CRLF


def _unfold(text):
    """Join continuation lines (CRLF + one space) back into logical lines."""
    return text.replace(CRLF + " ", "").split(CRLF)


def _events(text):
    out, cur = [], None
    for ln in _unfold(text):
        if ln == "BEGIN:VEVENT":
            cur = {}
        elif ln == "END:VEVENT":
            out.append(cur)
            cur = None
        elif cur is not None and ":" in ln:
            k, v = ln.split(":", 1)
            cur.setdefault(k, v)
    return out


def _uid(key):
    return hashlib.sha1(key.encode()).hexdigest()[:20] + "@familyagent"


def test_build_is_valid_stable_and_escaped(modules):
    ics = modules("export_ics")
    text = ics.build(ITEMS, TODAY)
    assert text.startswith("BEGIN:VCALENDAR" + CRLF + "VERSION:2.0" + CRLF) and text.endswith("END:VCALENDAR" + CRLF)
    assert "\n" not in text.replace(CRLF, ""), "CRLF line endings only"
    assert all(len(ln.encode("utf-8")) <= 75 for ln in text.split(CRLF)), "lines folded at 75 octets"
    ev = _events(text)
    assert len(ev) == 2
    bill = ev[0]
    assert bill["DTSTART;VALUE=DATE"] == "20261015" and bill["DTEND;VALUE=DATE"] == "20261016", "all-day, DTEND exclusive"
    assert bill["SUMMARY"] == r"Bill: City Power\, Inc\; electricity", "comma and semicolon escaped"
    assert "123.45" in bill["DESCRIPTION"] and "Autopay is off" in bill["DESCRIPTION"]
    assert bill["CATEGORIES"] == "Bill" and bill["TRANSP"] == "TRANSPARENT"
    assert bill["TRIGGER"] == "-P1D" and bill["ACTION"] == "DISPLAY", "one-day-ahead reminder"
    assert "DTSTAMP" in bill and bill["DTSTAMP"].endswith("Z")
    key = modules("action_state").key(ITEMS[0])
    assert key == "bills:7:2026-10-15"
    assert bill["UID"] == _uid(key), "UID from the stable row key"
    assert bill["UID"] != ev[1]["UID"]
    assert "Id: " + modules("action_state").display_id(key) in bill["DESCRIPTION"], "the 8-char id people use to snooze"
    assert ics.build(ITEMS, TODAY) == text, "deterministic"


def test_options_amounts_alarm_and_long_lines(modules):
    ics = modules("export_ics")
    text = ics.build(ITEMS, TODAY, amounts=False, alarm_days=0)
    assert "123.45" not in text and "VALARM" not in text
    text = ics.build(ITEMS, TODAY, alarm_days=3)
    assert "TRIGGER:-P3D" in text
    long_title = "Renewal with a very long title " * 6 + "end"
    text = ics.build([{**ITEMS[0], "title": long_title}], TODAY)
    assert all(len(ln.encode("utf-8")) <= 75 for ln in text.split(CRLF))
    assert _events(text)[0]["SUMMARY"] == "Bill: " + long_title, "folding round-trips"
    text = ics.build([{**ITEMS[0], "detail": "line one\nline two"}], TODAY)
    assert r"line one\nline two" in text, "newline escaped"


def test_cli_exports_visible_items_and_respects_snooze(root, modules):
    ai = modules("action_items")
    r = run(["data/export_ics.py", "--horizon", "400"], root)
    assert r.returncode == 0, r.stderr[-400:]
    out = root / "brief" / "mitrahome.ics"
    assert out.exists() and "mitrahome.ics" in r.stdout
    text = _read(out)
    assert CRLF in text, "file keeps CRLF"
    ev = _events(text)
    con = sqlite3.connect(root / "data" / "family.db")
    try:
        items = ai.collect_items(con, D.date.today(), 400)
    finally:
        con.close()
    single = [i for i in items if (i["ref"] or (None,))[0] != "activity_schedules"]  # a class is one weekly event
    assert len(ev) == len(single) + text.count("RRULE:FREQ=WEEKLY") > 0, f"{len(ev)} events for {len(items)} items; stdout {r.stdout}"
    assert str(len(ev)) in r.stdout
    uids = {e["UID"] for e in ev}
    target = next(i for i in items if i["ref"] and i["ref"][0] == "bills")
    assert _uid(target["key"]) in uids
    r = run(["data/action_state.py", "snooze", target["id"], "30"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    run(["data/export_ics.py", "--horizon", "400"], root)
    assert _uid(target["key"]) not in {e["UID"] for e in _events(_read(out))}, "snoozed item left out"
    run(["data/action_state.py", "reset", target["key"]], root)
    for ln in _unfold(text):
        if ln.startswith("UID:"):  # a hex hash; it can hold a run of digits by chance
            continue
        assert not re.search(r"\d{9,}", ln), "no long digit runs (account numbers) in a file headed for a phone: " + ln


def test_cli_filters_and_output_path(root, tmp_path):
    out = tmp_path / "bills.ics"
    r = run(["data/export_ics.py", "--kinds", "Bill,Birthday", "--out", str(out), "--horizon", "400", "--no-amounts"], root)
    assert r.returncode == 0, r.stderr[-400:]
    ev = _events(_read(out))
    assert ev and {e["CATEGORIES"] for e in ev} <= {"Bill", "Birthday"}
    assert not any("$" in e.get("DESCRIPTION", "") for e in ev)
    r = run(["data/export_ics.py", "--stdout", "--horizon", "30"], root)
    assert r.returncode == 0 and r.stdout.startswith("BEGIN:VCALENDAR")


def test_weekly_task_writes_the_calendar_file(root):
    out = root / "brief" / "mitrahome.ics"
    out.unlink(missing_ok=True)
    r = run(["tasks/run_task.py", "weekly_digest"], root, env={"AIFA_DRY_RUN": "1"}, timeout=600)
    assert r.returncode == 0, r.stdout[-300:] + r.stderr[-300:]
    assert out.exists(), "weekly task refreshes brief/mitrahome.ics"
    assert q(root, "select count(*) from bills")  # database untouched by the export
