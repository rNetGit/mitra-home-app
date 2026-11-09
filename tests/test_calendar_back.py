"""Changes made in Google Calendar to Mitra Home's own events (data/calendar_back.py): noted, shown as Inbox cards, and
applied only when an adult answers; calendar_sync leaves those events alone until then."""
import datetime as D

from conftest import db

ADULT = {"name": "Alex", "role": "adult"}
TODAY = D.date(2031, 3, 2)


def _setup(root, modules):
    cs, cb = modules("calendar_sync"), modules("calendar_back")
    cb.STATE.unlink(missing_ok=True)
    with db(root) as con:
        bill = con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Back test water', 'Water Co', 40, "
                           "'2031-03-10', 'due')").lastrowid
        appt = con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES ('Sam', 'Dr Lee', "
                           "'Back test checkup', '2031-03-12 15:30')").lastrowid
        con.commit()
    events = {"e-bill": {"date": "2031-03-10", "title": "Bill: Water Co", "hash": "h1", "ref": ["bills", bill],
                         "key": f"bills:{bill}:2031-03-10"},
              "e-appt": {"date": "2031-03-12", "title": "Appointment: Back test checkup (Sam)", "hash": "h2",
                         "ref": ["appointments", appt], "key": f"appointments:{appt}:2031-03-12"},
              "e-renew": {"date": "2031-03-20", "title": "Renewal: car registration", "hash": "h3",
                          "ref": ["vehicles", 1], "key": "vehicles:1:2031-03-20"},
              "e-gone": {"date": "2031-03-15", "title": "Bill: Phone", "hash": "h4", "ref": ["bills", 999999],
                         "key": "bills:999999:2031-03-15"},
              "e-past": {"date": "2031-02-01", "title": "old", "hash": "h5"}}
    cs._save({"calendar_id": "abc@group.calendar.google.com", "events": events})
    google = [{"id": "e-bill", "status": "confirmed", "start": {"date": "2031-03-14"}},
              {"id": "e-appt", "status": "confirmed", "start": {"dateTime": "2031-03-12T15:30:00-04:00"}},
              {"id": "e-renew", "status": "confirmed", "start": {"date": "2031-03-22"}},
              {"id": "e-gone", "status": "cancelled", "start": {"date": "2031-03-15"}}]
    return cs, cb, bill, appt, google


def test_look_notes_moves_and_deletions_only(root, modules):
    cs, cb, bill, appt, google = _setup(root, modules)
    r = cb.look(TODAY, events=google)
    assert r == {"moved": 2, "deleted": 1, "waiting": 3}
    p = cb.pending()
    assert p["e-bill"]["date"] == "2031-03-14" and p["e-bill"]["was"] == "2031-03-10" and cb.can_move(p["e-bill"])
    assert "e-appt" not in p, "same day: not a change"
    assert p["e-renew"]["change"] == "moved" and not cb.can_move(p["e-renew"]), "a renewal date is changed where it lives"
    assert p["e-gone"]["change"] == "deleted" and "e-past" not in p
    assert cb.look(TODAY, events=google)["waiting"] == 3, "looking again adds nothing twice"


def test_inbox_cards_and_each_answer(root, modules):
    cs, cb, bill, appt, google = _setup(root, modules)
    pr = modules("proposals")
    cb.look(TODAY, events=google)
    pr.sync(today=TODAY)
    with db(root) as con:
        cards = {i["payload"]["eid"]: i for i in pr.items(con) if i["source"] == "calendar_back"}
    assert set(cards) == {"e-bill", "e-renew", "e-gone"}
    assert cards["e-bill"]["summary"] == "Moved in Google Calendar: Bill: Water Co, Mar 10 to Mar 14"
    assert set(cards["e-bill"]["options"]) == {"accept", "keep"}
    assert set(cards["e-renew"]["options"]) == {"keep"}
    assert set(cards["e-gone"]["options"]) == {"hide", "keep"}
    # use the new date: the bill moves, through edit_actions
    ok, msg = pr.decide(ADULT, cards["e-bill"]["id"], "accept", today=TODAY)
    assert ok, msg
    with db(root) as con:
        assert con.execute("SELECT due_date FROM bills WHERE id=?", (bill,)).fetchone()[0] == "2031-03-14"
    # keep ours: the next sync writes our date back
    ok, msg = pr.decide(ADULT, cards["e-renew"]["id"], "keep", today=TODAY)
    assert ok and cs._state()["events"]["e-renew"]["hash"] == ""
    # deleted: take it off Today and the calendar
    ok, msg = pr.decide(ADULT, cards["e-gone"]["id"], "hide", today=TODAY)
    assert ok, msg
    with db(root) as con:
        assert con.execute("SELECT state FROM action_state WHERE key='bills:999999:2031-03-15'").fetchone()[0] == "ignored"
    assert cb.pending() == {}
    assert not pr.decide({"name": "Sam", "role": "limited"}, cards["e-bill"]["id"], "accept", today=TODAY)[0]
    assert "bill_move\tid=" in (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")


def test_the_sync_leaves_a_waiting_event_alone(root, modules):
    cs, cb, bill, appt, google = _setup(root, modules)
    cb.look(TODAY, events=google)
    with db(root) as con:
        p = cs.plan(con, TODAY)
    touched = {r["id"] for k in ("create", "update", "delete") for r in p[k]}
    assert not touched & {"e-bill", "e-renew", "e-gone"} and p["waiting"] == 3


def test_appointment_and_event_moves_keep_the_time(root, modules):
    ea = modules("edit_actions")
    with db(root) as con:
        appt = con.execute("INSERT INTO appointments(person, purpose, appt_datetime) VALUES ('Sam', 'Move test', '2031-04-01 09:15')").lastrowid
        ev = con.execute("INSERT INTO events(name, event_date, recurs_yearly, start_time) VALUES ('Move test party', '2031-04-02', 0, '18:00')").lastrowid
        con.commit()
    assert ea.appointment_move(ADULT, appt, "2031-04-03")[0]
    assert ea.event_move(ADULT, ev, "2031-04-05")[0]
    assert not ea.appointment_move(ADULT, appt, "soon")[0]
    with db(root) as con:
        assert con.execute("SELECT appt_datetime FROM appointments WHERE id=?", (appt,)).fetchone()[0] == "2031-04-03 09:15"
        assert con.execute("SELECT event_date, start_time FROM events WHERE id=?", (ev,)).fetchone() == ("2031-04-05", "18:00")
    assert not ea.bill_move({"name": "Sam", "role": "limited"}, 1, "2031-04-01")[0]
