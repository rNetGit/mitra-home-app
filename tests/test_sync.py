"""Sync with paired phones (0.103): change log triggers, pull (snapshot, paging, changes, tombstones, reset), what each
role and scope may carry, push (edits through edit_actions, repeats, scopes, busy = retry) and the /api/sync routes."""
import datetime as dt
import json

import pytest

NOW = dt.datetime(2026, 10, 14, 9, 0, 0)


@pytest.fixture()
def sy(modules, root):
    """(sync_data, devices, connection, make_device) with an empty change log and no phones."""
    s, d = modules("sync_data"), modules("devices")
    con = d._con()
    con.execute("DELETE FROM device_pairings")
    con.execute("DELETE FROM devices")
    con.commit()

    def make(who="Alex", scopes=None):
        secret, _ = d.pair_start(con, who, f"{who} phone", scopes=scopes, now=NOW)
        tok, _ = d.pair_redeem(con, secret, now=NOW)
        return d.authenticate(con, tok, now=NOW)
    yield s, d, con, make
    con.close()


def _all(s, con, dev, cursor=None, page=500):
    """Pull until `more` is false. -> (merged {source: {id: row}}, deleted {source: set}, last body, pages)."""
    rows, gone, pages = {}, {}, 0
    while True:
        body = s.pull(con, dev, cursor, page=page)
        pages += 1
        for name, ch in body["changes"].items():
            for r in ch["upsert"]:
                rows.setdefault(name, {})[r["id"]] = r
            gone.setdefault(name, set()).update(ch["delete"])
        cursor = body["cursor"]
        if not body["more"]:
            return rows, gone, body, pages


def _list(con, name, audience="family"):
    cur = con.execute("INSERT INTO lists(name, kind, audience, created_at) VALUES (?,?,?,?)",
                      (name, "todo", audience, "2026-10-01T10:00:00"))
    con.commit()
    return cur.lastrowid


def _item(con, list_id, text):
    cur = con.execute("INSERT INTO list_items(list_id, text, added_at) VALUES (?,?,?)", (list_id, text, "2026-10-01T10:00:00"))
    con.commit()
    return cur.lastrowid


# ---- change log ------------------------------------------------------------------------------------------------
def test_triggers_log_every_change_without_content(sy):
    s, _, con, _ = sy
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'sync_%'")}
    assert {"sync_bills_i", "sync_bills_u", "sync_bills_d", "sync_list_items_u", "sync_saved_items_d"} <= names
    assert s.ensure_triggers(con) == len(s.TABLES), "idempotent, every synced table covered"
    top = con.execute("SELECT COALESCE(MAX(id),0) FROM sync_log").fetchone()[0]
    bid = con.execute("INSERT INTO bills(name, due_date) VALUES ('Water', '2026-11-01')").lastrowid
    con.execute("UPDATE bills SET amount=40 WHERE id=?", (bid,))
    con.execute("DELETE FROM bills WHERE id=?", (bid,))
    con.commit()
    log = [tuple(r) for r in con.execute("SELECT tbl, row_id, op FROM sync_log WHERE id > ? ORDER BY id", (top,))]
    assert log == [("bills", bid, "I"), ("bills", bid, "U"), ("bills", bid, "D")]
    assert [r[1] for r in con.execute("PRAGMA table_info(sync_log)")] == ["id", "tbl", "row_id", "op", "ts"]


def test_prune_keeps_the_last_entry(sy):
    s, _, con, _ = sy
    con.execute("UPDATE sync_log SET ts='2020-01-01T00:00:00'")
    con.commit()
    hi = con.execute("SELECT MAX(id) FROM sync_log").fetchone()[0]
    s.prune(con)
    con.commit()
    assert [r[0] for r in con.execute("SELECT id FROM sync_log")] == [hi]


def test_daily_prune_without_any_phone(sy, root):
    """D8: a household without phones never pulls, so the daily task prunes the change log (`sync_data.py prune`)."""
    from conftest import run
    s, _, con, _ = sy
    for n in range(3):
        con.execute("INSERT INTO bills(name, due_date) VALUES (?, '2026-11-01')", (f"Old {n}",))
    con.execute("UPDATE sync_log SET ts='2020-01-01T00:00:00'")
    con.commit()
    before = con.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0]
    r = run(["data/sync_data.py", "prune"], root)
    assert r.returncode == 0 and "old entries removed" in r.stdout, r.stdout + r.stderr[-300:]
    assert before > 1 and con.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0] == 1
    assert '"data/sync_data.py", "prune"' in (root / "tasks" / "run_task.py").read_text(encoding="utf-8")


# ---- pull ------------------------------------------------------------------------------------------------------
def test_first_pull_is_a_full_copy_of_what_the_adult_defaults_allow(sy):
    s, _, con, make = sy
    dev = make("Alex")
    rows, _, body, _ = _all(s, con, dev)
    assert set(body["sources"]) == {"people", "life_items", "appointments", "events", "activities", "days", "lists",
                                    "list_items", "bills", "subscriptions", "notes"}
    assert not {"accounts", "transactions", "budget", "id_documents"} & set(rows)
    assert {r["name"] for r in rows["people"].values()} >= {"Alex", "Sam", "Biscuit"}
    assert "birth_year" not in next(iter(rows["people"].values()))
    open_n = con.execute("SELECT COUNT(*) FROM life_items WHERE status='open'").fetchone()[0]
    assert len(rows.get("life_items", {})) == open_n
    assert s.pull(con, dev)["reset"] is True


def test_paging_gives_the_same_copy(sy):
    s, _, con, make = sy
    dev = make("Alex")
    lid = _list(con, "Paging")
    for i in range(7):
        _item(con, lid, f"thing {i}")
    big, _, _, one = _all(s, con, dev)
    small, _, _, many = _all(s, con, dev, page=3)
    assert one < many
    assert big == small


def test_changes_after_the_cursor_and_tombstones(sy):
    s, _, con, make = sy
    dev = make("Alex")
    lid = _list(con, "Hardware")
    keep, drop = _item(con, lid, "nails"), _item(con, lid, "glue")
    _, _, body, _ = _all(s, con, dev)
    cur = body["cursor"]
    nothing = s.pull(con, dev, cur)
    assert not nothing["reset"] and not any(c["upsert"] or c["delete"] for c in nothing["changes"].values())
    con.execute("UPDATE list_items SET status='done' WHERE id=?", (keep,))
    con.execute("UPDATE list_items SET status='dropped' WHERE id=?", (drop,))
    bid = con.execute("INSERT INTO bills(name, due_date, amount) VALUES ('Gas', '2026-11-03', 55)").lastrowid
    con.commit()
    b = s.pull(con, dev, cur)
    assert not b["reset"]
    assert [r["id"] for r in b["changes"]["list_items"]["upsert"]] == [keep]
    assert b["changes"]["list_items"]["upsert"][0]["status"] == "done"
    assert b["changes"]["list_items"]["delete"] == [drop], "a dropped item leaves the phone"
    assert [(r["id"], r["amount"]) for r in b["changes"]["bills"]["upsert"]] == [(bid, 55)]
    con.execute("DELETE FROM bills WHERE id=?", (bid,))
    con.execute("UPDATE lists SET status='archived' WHERE id=?", (lid,))
    con.commit()
    c = s.pull(con, dev, b["cursor"])
    assert c["changes"]["bills"]["delete"] == [bid]
    assert c["changes"]["lists"]["delete"] == [lid]
    assert keep in c["changes"]["list_items"]["delete"], "an archived list takes its items along"


def test_reset_on_scope_change_bad_cursor_restore_or_pruned_log(sy):
    s, _, con, make = sy
    dev = make("Alex")
    _, _, body, _ = _all(s, con, dev)
    cur = body["cursor"]
    assert not s.pull(con, dev, cur)["reset"]
    for bad in ("", "x", "9.abc.1", "1.abc.notanumber", cur + ".1"):
        assert s.pull(con, dev, bad)["reset"], bad
    v, sig, pos = cur.split(".")
    assert s.pull(con, dev, f"{v}.{sig}.{int(pos) + 1000}")["reset"], "past the end of the log: restored database"
    assert s.pull(con, {**dev, "scopes": dev["scopes"] + ["finance"]}, cur)["reset"], "new scopes: a full copy again"
    assert s.pull(con, {**dev, "role": "limited"}, cur)["reset"], "new role: a full copy again"
    for _ in range(2):  # two new entries; the older one is pruned, so the phone missed a change
        con.execute("UPDATE bills SET amount=amount WHERE id=(SELECT MIN(id) FROM bills)")
    con.commit()
    con.execute("UPDATE sync_log SET ts='2020-01-01T00:00:00' WHERE id <= ?", (int(pos) + 1,))
    con.commit()
    s.prune(con)
    con.commit()
    assert s.pull(con, dev, cur)["reset"], "the log was pruned past the phone's position"


def test_limited_person_gets_only_their_own_safe_items_and_family_lists(sy):
    s, _, con, make = sy
    fam = _list(con, "Chores")
    adults = _list(con, "Gifts for Sam", "adults")
    _item(con, fam, "feed Biscuit")
    secret = _item(con, adults, "bike")
    mine = con.execute("INSERT INTO life_items(domain, member, title, due_date, amount) VALUES "
                       "('school', 'Sam', 'Field trip form', '2026-10-20', 15)").lastrowid
    other = con.execute("INSERT INTO life_items(domain, member, title) VALUES ('school', 'Alex', 'Course')").lastrowid
    legal = con.execute("INSERT INTO life_items(domain, member, title) VALUES ('legal', 'Sam', 'Trust')").lastrowid
    a1 = con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES "
                     "('Sam', 'Dr A', 'Checkup', '2026-10-21T09:00')").lastrowid
    a2 = con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES "
                     "('Alex', 'Dr B', 'Checkup', '2026-10-22T09:00')").lastrowid
    con.commit()
    dev = make("Sam")
    assert dev["role"] == "limited"
    rows, _, body, _ = _all(s, con, dev)
    assert set(body["sources"]) == {"people", "own", "appointments", "activities", "days", "lists", "list_items"}
    assert mine in rows["own"] and other not in rows["own"] and legal not in rows["own"]
    assert "amount" not in rows["own"][mine] and "notes" not in rows["own"][mine]
    assert a1 in rows["appointments"] and a2 not in rows["appointments"]
    assert {r["person"] for r in rows["appointments"].values()} == {"Sam"}
    assert "followup_due" not in rows["appointments"][a1]
    assert fam in rows["lists"] and adults not in rows["lists"] and secret not in rows["list_items"]
    # a family list made adults-only later disappears from the child's phone with its items
    con.execute("UPDATE lists SET audience='adults' WHERE id=?", (fam,))
    con.commit()
    c = s.pull(con, dev, body["cursor"])
    assert c["changes"]["lists"]["delete"] == [fam] and c["changes"]["list_items"]["delete"]


def test_private_notes_stay_with_their_owner(sy):
    s, _, con, make = sy
    con.execute("INSERT INTO saved_items(kind, title, audience, owner, added_at) VALUES "
                "('note', 'Alex only', 'private', 'Alex', '2026-10-01T10:00:00'), "
                "('note', 'Pat only', 'private', 'Pat', '2026-10-01T10:00:00'), "
                "('note', 'For all', 'family', NULL, '2026-10-01T10:00:00')")
    con.commit()
    rows, _, _, _ = _all(s, con, make("Alex"))
    titles = {r["title"] for r in rows["notes"].values()}
    assert {"Alex only", "For all"} <= titles and "Pat only" not in titles


def test_finance_scope_carries_last4_accounts_and_recent_transactions(sy):
    s, _, con, make = sy
    acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Check', 'checking', '1234')").lastrowid
    old = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2020-01-05', 'old', -1)",
                      (acc,)).lastrowid
    new = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, ?, 'new', -2)",
                      (acc, dt.date.today().isoformat())).lastrowid
    con.commit()
    dev = make("Alex", scopes=["finance", "ids"])
    rows, _, body, _ = _all(s, con, dev)
    assert set(body["sources"]) == {"people", "accounts", "budget", "transactions", "id_documents", "vehicles", "policies",
                                    "wallet_cards"}
    assert rows["accounts"][acc]["last4"] == "1234"
    assert new in rows["transactions"] and old not in rows["transactions"], "the first copy carries recent months only"
    assert "notes" not in next(iter(rows["id_documents"].values()))


# ---- push ------------------------------------------------------------------------------------------------------
def test_push_applies_edits_once_and_in_order(sy, modules):
    s, _, con, make = sy
    dev = make("Alex")
    lid = _list(con, "Push")
    res = s.push(con, dev, [{"id": "op-0000001", "op": "list_add", "list_id": lid, "text": "milk"},
                            {"id": "op-0000002", "op": "list_add", "list_id": str(lid), "text": "eggs", "qty": "12"}])
    assert [r["status"] for r in res] == ["ok", "ok"], res
    items = {r[0]: r[1] for r in con.execute("SELECT text, id FROM list_items WHERE list_id=?", (lid,))}
    assert set(items) == {"milk", "eggs"}
    again = s.push(con, dev, [{"id": "op-0000001", "op": "list_add", "list_id": lid, "text": "milk"}])
    assert again[0]["repeat"] and again[0]["status"] == "ok"
    assert con.execute("SELECT COUNT(*) FROM list_items WHERE list_id=?", (lid,)).fetchone()[0] == 2
    t = s.push(con, dev, [{"id": "op-0000003", "op": "list_tick", "item_id": items["milk"], "done": True}])
    assert t[0]["status"] == "ok"
    assert tuple(con.execute("SELECT status, done_by FROM list_items WHERE id=?", (items["milk"],)).fetchone()) == ("done", "Alex")
    stored = con.execute("SELECT op, status FROM sync_ops WHERE device_id=? ORDER BY id", (dev["id"],)).fetchall()
    assert [tuple(r) for r in stored] == [("list_add", "ok"), ("list_add", "ok"), ("list_tick", "ok")]
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert "\tAlex\tlist_item_add\t" in log and "milk" not in log


def test_push_rejections_scopes_and_bad_input(sy, monkeypatch, modules):
    s, _, con, make = sy
    adult = make("Alex", scopes=["lists"])
    kid = make("Sam")
    bid = con.execute("INSERT INTO bills(name, due_date) VALUES ('Phone', '2026-10-30')").lastrowid
    adults_list = _list(con, "Adults only", "adults")
    con.commit()
    res = s.push(con, adult, [
        {"id": "a-0000001", "op": "bill_paid", "bill_id": bid},          # no bills scope
        {"id": "a-0000002", "op": "launch", "x": 1},                       # unknown op
        {"id": "short", "op": "list_add"},                                 # bad id
        {"op": "list_add"},                                                # no id
        {"id": "a-0000003", "op": "list_add", "list_id": "x", "text": "y"},  # bad field
        {"id": "a-0000004", "op": "list_add", "list_id": 999999, "text": "y"},  # gone: the PC wins
    ])
    assert [r["status"] for r in res] == ["rejected"] * 6
    assert res[0]["message"] == "This phone may not make that change."
    assert res[5]["message"] == "that list no longer exists"
    assert con.execute("SELECT status FROM bills WHERE id=?", (bid,)).fetchone()[0] in (None, "due")
    k = s.push(con, kid, [{"id": "k-0000001", "op": "bill_paid", "bill_id": bid},
                          {"id": "k-0000002", "op": "list_add", "list_id": adults_list, "text": "peek"},
                          {"id": "k-0000003", "op": "note_add", "title": "hi"}])
    assert [r["status"] for r in k] == ["rejected"] * 3
    assert k[1]["message"] == "that list is for adults"
    ea = modules("edit_actions")
    monkeypatch.setattr(ea, "list_item_add", lambda *a, **kw: (False, ea.BUSY))
    lid = _list(con, "Busy")
    b = s.push(con, adult, [{"id": "a-0000009", "op": "list_add", "list_id": lid, "text": "z"}])
    assert b[0]["status"] == "retry"
    assert not con.execute("SELECT 1 FROM sync_ops WHERE client_id='a-0000009'").fetchone(), "a retry is not remembered"


def test_push_bill_paid_life_done_and_note(sy):
    s, _, con, make = sy
    dev = make("Alex")
    kid = make("Sam")
    bid = con.execute("INSERT INTO bills(name, due_date) VALUES ('Internet', '2026-10-30')").lastrowid
    li = con.execute("INSERT INTO life_items(domain, member, title) VALUES ('chore', 'Sam', 'Rake leaves')").lastrowid
    con.commit()
    r = s.push(con, dev, [{"id": "b-0000001", "op": "bill_paid", "bill_id": bid},
                          {"id": "b-0000002", "op": "note_add", "title": "Pizza place", "note": "Thin crust", "audience": "adults"},
                          {"id": "b-0000003", "op": "note_add", "title": "x", "audience": "everyone"}])
    assert [x["status"] for x in r] == ["ok", "ok", "rejected"], r
    assert con.execute("SELECT status FROM bills WHERE id=?", (bid,)).fetchone()[0] == "paid"
    assert con.execute("SELECT audience FROM saved_items WHERE title='Pizza place'").fetchone()[0] == "adults"
    k = s.push(con, kid, [{"id": "c-0000001", "op": "life_done", "item_id": li}])
    assert k[0]["status"] == "ok", k
    assert con.execute("SELECT status FROM life_items WHERE id=?", (li,)).fetchone()[0] in ("done", "open")
    assert len(s.push(con, dev, [{"id": f"m-{i:07d}", "op": "x"} for i in range(80)])) == s.MAX_OPS


# ---- quick-add forms (event, appointment, reminder) ------------------------------------------------------------
def _quick(tag, hour=15):
    """One of each quick-add op; `tag` and `hour` keep them apart from other tests' rows (one database per run). Minute 47:
    the demo seed puts Sam at today + 9 days 15:30, which was this very slot on 2026-10-25."""
    return [{"id": f"{tag}-ev-0001", "op": "event_add", "name": f"Block party {tag}", "date": "2026-11-07"},
            {"id": f"{tag}-ap-0001", "op": "appointment_add", "who": "Sam", "when": f"2026-11-03 {hour:02d}:47",
             "provider": "Dr. Lee", "purpose": "Checkup"},
            {"id": f"{tag}-li-0001", "op": "life_add", "title": f"Permission slip {tag}", "due": "2026-10-28", "who": "Sam",
             "domain": "school"}]


def _quick_rows(con, tag, hour=15):
    return (con.execute("SELECT COUNT(*) FROM events WHERE name=?", (f"Block party {tag}",)).fetchone()[0],
            con.execute("SELECT COUNT(*) FROM appointments WHERE person='Sam' AND appt_datetime=?",
                        (f"2026-11-03 {hour:02d}:47",)).fetchone()[0],
            con.execute("SELECT COUNT(*) FROM life_items WHERE title=?", (f"Permission slip {tag}",)).fetchone()[0])


def test_quick_add_ops_from_an_adult_phone(sy, modules):
    s, _, con, make = sy
    dev = make("Alex")
    res = s.push(con, dev, _quick("qa", 15))
    assert [r["status"] for r in res] == ["ok", "ok", "ok"], res
    assert _quick_rows(con, "qa", 15) == (1, 1, 1)
    ev = con.execute("SELECT event_date, recurs_yearly FROM events WHERE name='Block party qa'").fetchone()
    assert tuple(ev) == ("2026-11-07", 0), "a one-off unless the phone says yearly"
    li = con.execute("SELECT domain, member, due_date, status FROM life_items WHERE title='Permission slip qa'").fetchone()
    assert tuple(li) == ("school", "Sam", "2026-10-28", "open")
    y = s.push(con, dev, [{"id": "qa-yearly1", "op": "event_add", "name": "Wedding day", "date": "2027-06-12", "yearly": True},
                          {"id": "qa-plain01", "op": "life_add", "title": "Call the plumber", "due": "2026-10-30"}])
    assert [r["status"] for r in y] == ["ok", "ok"], y
    assert con.execute("SELECT recurs_yearly FROM events WHERE name='Wedding day'").fetchone()[0] == 1
    assert con.execute("SELECT domain, member FROM life_items WHERE title='Call the plumber'").fetchone()[:] == ("other", None)
    stored = [r[0] for r in con.execute("SELECT op FROM sync_ops WHERE device_id=? ORDER BY id", (dev["id"],))]
    assert stored == ["event_add", "appointment_add", "life_add", "event_add", "life_add"]
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert "	Alex	event_add	" in log and "	Alex	appointment_add	" in log and "	Alex	life_add	" in log
    assert "Permission slip" not in log, "the log names the row, never its text"


def test_a_phone_event_can_carry_a_time(sy):
    """The Add sheet's Event form with Starts / Ends: the PC stores the time and sends it back with the event."""
    s, _, con, make = sy
    dev = make("Alex")
    res = s.push(con, dev, [{"id": "qt-time0001", "op": "event_add", "name": "Family dinner qt", "date": "2026-11-20",
                             "time": "20:00", "end": "20:30", "yearly": False},
                            {"id": "qt-time0002", "op": "event_add", "name": "Bad dinner qt", "date": "2026-11-20",
                             "time": "20:00", "end": "19:00"},
                            {"id": "qt-time0003", "op": "event_add", "name": "No start qt", "date": "2026-11-20",
                             "end": "19:00"}])
    assert [r["status"] for r in res] == ["ok", "rejected", "rejected"], res
    row = con.execute("SELECT start_time, end_time, recurs_yearly FROM events WHERE name='Family dinner qt'").fetchone()
    assert tuple(row) == ("20:00", "20:30", 0)
    rows, _, _, _ = _all(s, con, dev)
    ev = [r for r in rows["events"].values() if r["name"] == "Family dinner qt"]
    assert ev and (ev[0]["start_time"], ev[0]["end_time"]) == ("20:00", "20:30")


def test_quick_add_ops_refused_for_limited_people_and_phones_without_calendar(sy):
    s, _, con, make = sy
    kid = make("Sam")
    res = s.push(con, kid, _quick("qk", 16))
    assert [r["status"] for r in res] == ["rejected"] * 3
    assert {r["message"] for r in res} == {"This phone may not make that change."}
    lists_only = make("Alex", scopes=["lists"])
    res = s.push(con, lists_only, _quick("qk", 16))
    assert [r["status"] for r in res] == ["rejected"] * 3
    assert _quick_rows(con, "qk", 16) == (0, 0, 0), "nothing was written"


def test_quick_add_ops_refuse_bad_dates_and_bad_fields(sy):
    s, _, con, make = sy
    dev = make("Alex")
    bad = [
        {"op": "event_add", "name": "Party", "date": "2026-02-30"},
        {"op": "event_add", "name": "Party", "date": "next Friday"},
        {"op": "event_add", "name": "", "date": "2026-11-07"},
        {"op": "event_add", "name": "Party", "date": "2026-11-07", "yearly": "yes"},
        {"op": "appointment_add", "who": "Sam", "when": "2026-11-03"},
        {"op": "appointment_add", "who": "Sam", "when": "2026-11-03 25:00"},
        {"op": "appointment_add", "who": "Nobody", "when": "2026-11-03 10:00"},
        {"op": "appointment_add", "who": "", "when": "2026-11-03 10:00"},
        {"op": "life_add", "title": "Slip", "due": "28/10/2026"},
        {"op": "life_add", "title": "Slip", "due": "2026-10-28", "domain": "taxes"},
        {"op": "life_add", "title": 5, "due": "2026-10-28"},
    ]
    res = s.push(con, dev, [dict(o, id=f"qb-{i:07d}") for i, o in enumerate(bad)])
    assert [r["status"] for r in res] == ["rejected"] * len(bad), res
    assert all(r["message"] for r in res)
    assert "date" in res[0]["message"] and "'Nobody' is not a family member" in res[6]["message"]
    assert res[3]["message"] == res[10]["message"] == "That edit is not complete."
    assert con.execute("SELECT COUNT(*) FROM events WHERE name='Party'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM life_items WHERE title='Slip'").fetchone()[0] == 0


def test_quick_add_repeat_ids_do_nothing_twice_and_busy_is_retried(sy, monkeypatch, modules):
    s, _, con, make = sy
    dev = make("Alex")
    ops = _quick("qr", 17)
    first = s.push(con, dev, ops)
    again = s.push(con, dev, ops)
    assert [r["status"] for r in first] == ["ok"] * 3, first
    assert [(r["status"], r.get("repeat")) for r in again] == [("ok", True)] * 3
    assert _quick_rows(con, "qr", 17) == (1, 1, 1)
    ea = modules("edit_actions")
    monkeypatch.setattr(ea, "appointment_add", lambda *a, **kw: (False, ea.BUSY))
    b = s.push(con, dev, [{"id": "qr-busy0001", "op": "appointment_add", "who": "Alex", "when": "2026-11-04 09:00"},
                          {"id": "qr-busy0002", "op": "event_add", "name": "After busy", "date": "2026-11-09"}])
    assert [r["status"] for r in b] == ["retry", "retry"], "a busy database: both wait, the order is kept"
    assert not con.execute("SELECT 1 FROM sync_ops WHERE client_id LIKE 'qr-busy%'").fetchone()
    assert not con.execute("SELECT 1 FROM events WHERE name='After busy'").fetchone()


def test_removing_a_phone_removes_its_sync_rows(sy):
    s, _, con, make = sy
    dev = make("Alex")
    s.push(con, dev, [{"id": "r-0000001", "op": "x"}])
    con.execute("DELETE FROM devices WHERE id=?", (dev["id"],))
    con.commit()
    assert not con.execute("SELECT 1 FROM sync_ops WHERE device_id=?", (dev["id"],)).fetchone()


# ---- API -------------------------------------------------------------------------------------------------------
@pytest.fixture()
def api(root, modules, sy):
    pytest.importorskip("cryptography")
    from fastapi.testclient import TestClient
    app_mod = modules("webapp.app")
    s, d, con, _ = sy
    secret, _ = d.pair_start(con, "Alex", "Alex phone")
    phone = TestClient(app_mod.app, base_url="https://192.168.1.20:8701", follow_redirects=False)
    tok = phone.post("/api/pair", json={"secret": secret}).json()["token"]
    return phone, {"Authorization": f"Bearer {tok}"}, app_mod, con, d


def test_api_pull_sends_the_money_outlook_only_with_the_finance_scope(api, modules):
    """summary.money = wall_money.for_phone (Money > Spending / Bills / Regular as the PC counts them), on the last page of
    a pull, for an adult's phone with the finance scope; without it the summary has no money at all."""
    phone, h, _, con, d = api

    def last_page():
        body = phone.get("/api/sync/pull", headers=h).json()
        while body["more"]:
            body = phone.get("/api/sync/pull", params={"cursor": body["cursor"]}, headers=h).json()
        return body

    assert "money" not in last_page()["summary"]
    dev_id = con.execute("SELECT id FROM devices WHERE name='Alex phone' AND revoked_at IS NULL").fetchone()[0]
    d.set_scopes(con, dev_id, d.defaults("adult") + ["finance"])
    con.commit()
    m = last_page()["summary"]["money"]
    assert set(m) == {"as_of", "spending", "bills", "regular"}
    assert {"names", "totals", "rows"} <= set(m["spending"]) and {"now_total", "wait_n", "rows", "listed"} <= set(m["bills"])
    assert {"month", "groups", "soon"} <= set(m["regular"])
    json.dumps(m)  # plain JSON: no dates as objects
    assert not any(k.endswith("_day") for r in m["bills"]["rows"] for k in r), "no per-payee dates beyond the labels"


def test_api_pull_and_push(api):
    phone, h, _, con, _ = api
    assert phone.get("/api/sync/pull").status_code == 401
    ping = phone.get("/api/ping", headers=h).json()
    assert ping["sync"]["version"] == 1 and "list_add" in ping["sync"]["ops"] and "bill_paid" in ping["sync"]["ops"]
    assert {"event_add", "appointment_add", "life_add"} <= set(ping["sync"]["ops"]), "the phone shows its Add forms"
    r = phone.get("/api/sync/pull", headers=h)
    assert r.status_code == 200 and r.headers["Cache-Control"] == "no-store" and "set-cookie" not in r.headers
    body = r.json()
    assert body["money"] == {"currency": "USD", "symbol": "$"}, "the phone shows $60.00, not 60.00"
    s = body["summary"]
    assert set(s) == {"needs", "overdue", "due_today", "week"} and s["needs"] == s["overdue"] + s["due_today"]
    cur = body["cursor"]
    while body["more"]:
        body = phone.get("/api/sync/pull", params={"cursor": cur}, headers=h).json()
        cur = body["cursor"]
    assert body["reset"] in (True, False) and "people" in body["sources"]
    lid = _list(con, "Api")
    p = phone.post("/api/sync/push", json={"ops": [{"id": "api-000001", "op": "list_add", "list_id": lid, "text": "tea"}]},
                   headers=h)
    assert p.status_code == 200 and p.json()["results"][0]["status"] == "ok"
    nxt = phone.get("/api/sync/pull", params={"cursor": cur}, headers=h).json()
    assert not nxt["reset"] and [x["text"] for x in nxt["changes"]["list_items"]["upsert"]] == ["tea"]
    assert phone.post("/api/sync/push", content=b"not json", headers=h).status_code == 400
    assert phone.post("/api/sync/push", json={"ops": [{}] * 51}, headers=h).status_code == 400
    big = json.dumps({"ops": [{"id": "x" * 10, "op": "note_add", "title": "a" * 70000}]})
    assert phone.post("/api/sync/push", content=big, headers=h).status_code == 413


def test_api_sync_is_https_only_and_revoked_phones_wipe(api, root, modules):
    phone, h, app_mod, con, d = api
    from fastapi.testclient import TestClient
    plain = TestClient(app_mod.app, base_url="http://192.168.1.20:8601", follow_redirects=False)
    assert plain.get("/api/sync/pull", headers=h).status_code == 403
    dev_id = con.execute("SELECT MAX(id) FROM devices").fetchone()[0]
    d.revoke(con, dev_id)
    r = phone.get("/api/sync/pull", headers=h)
    assert r.status_code == 401 and r.json() == {"error": "revoked", "wipe": True}
    assert phone.post("/api/sync/push", json={"ops": []}, headers=h).status_code == 401


def test_a_restored_database_makes_every_phone_start_over(sy, modules, tmp_path):
    """Audit M9: after a restore the change log goes back in time; the new epoch in `meta` changes every cursor."""
    s, _, con, make = sy
    dev = make("Alex")
    _, _, body, _ = _all(s, con, dev)
    cur = body["cursor"]
    assert not s.pull(con, dev, cur)["reset"]
    s.new_epoch(con)  # what restore_backup.restore_db does to the restored copy
    assert s.pull(con, dev, cur)["reset"], "an old cursor on a restored copy = a full copy"
    rb = modules("restore_backup")
    src = tmp_path / "bk"
    src.mkdir()
    import shutil
    import sqlite3
    shutil.copy2(modules("paths").DB, src / "family_2026-10-15_0101.db")
    out = tmp_path / "restored.db"
    _, ok, _ = rb.restore_db(src, out, None, "family_2026-10-15_0101.db")
    c2 = sqlite3.connect(out)
    try:
        new = c2.execute("SELECT value FROM meta WHERE key='sync_epoch'").fetchone()[0]
    finally:
        c2.close()
    assert ok and new and new != s.epoch(con)


def test_push_never_applies_one_edit_twice_and_keeps_the_order(sy, monkeypatch, modules):
    """Audit M15: the edit id is claimed before the edit; after a busy edit the later ones wait (retry) too."""
    s, _, con, make = sy
    dev = make("Alex")
    lid = _list(con, "Once")
    res = s.push(con, dev, [{"id": "once-000001", "op": "list_add", "list_id": lid, "text": "bread"},
                            {"id": "once-000001", "op": "list_add", "list_id": lid, "text": "bread"}])
    assert [r["status"] for r in res] == ["ok", "ok"] and res[1]["repeat"]
    assert con.execute("SELECT COUNT(*) FROM list_items WHERE list_id=?", (lid,)).fetchone()[0] == 1
    ea = modules("edit_actions")
    real = ea.list_item_add
    calls = []

    def busy_first(*a, **kw):
        calls.append(a)
        return (False, ea.BUSY) if len(calls) == 1 else real(*a, **kw)
    monkeypatch.setattr(ea, "list_item_add", busy_first)
    res = s.push(con, dev, [{"id": "ord-0000001", "op": "list_add", "list_id": lid, "text": "first"},
                            {"id": "ord-0000002", "op": "list_add", "list_id": lid, "text": "second"}])
    assert [r["status"] for r in res] == ["retry", "retry"] and len(calls) == 1, "the second edit waits for the first"
    assert not con.execute("SELECT 1 FROM sync_ops WHERE client_id IN ('ord-0000001', 'ord-0000002')").fetchone()
    res = s.push(con, dev, [{"id": "ord-0000001", "op": "list_add", "list_id": lid, "text": "first"},
                            {"id": "ord-0000002", "op": "list_add", "list_id": lid, "text": "second"}])
    assert [r["status"] for r in res] == ["ok", "ok"]
    texts = [r[0] for r in con.execute("SELECT text FROM list_items WHERE list_id=? ORDER BY id", (lid,))]
    assert texts == ["bread", "first", "second"]


def test_ids_must_be_plain_digits(sy):
    s = sy[0]
    assert s._int("12") == 12 and s._int(7) == 7
    for bad in ("²", "١٢", "1.5", "", True, None, [1]):
        try:
            s._int(bad)
            raise AssertionError(repr(bad))
        except ValueError:
            pass


def test_a_claim_left_by_a_crash_is_not_taken_for_a_saved_edit(sy):
    """Audit S10: the claim stays 'in flight' until the edit is made. A request that died after claiming leaves a
    stale in-flight claim: the next push applies the edit instead of answering 'already received'."""
    import datetime as dt
    s, _, con, make = sy
    dev = make("Alex")
    lid = _list(con, "Crash")
    old = (dt.datetime.now() - dt.timedelta(minutes=10)).isoformat(timespec="seconds")
    con.execute("INSERT INTO sync_ops(device_id, client_id, op, status, created_at) VALUES (?,?,?,?,?)",
                (dev["id"], "crash-00001", s.PENDING + "list_add", "ok", old))
    con.commit()
    res = s.push(con, dev, [{"id": "crash-00001", "op": "list_add", "list_id": lid, "text": "milk"}])
    assert res[0]["status"] == "ok" and not res[0].get("repeat")
    assert con.execute("SELECT COUNT(*) FROM list_items WHERE list_id=? AND text='milk'", (lid,)).fetchone()[0] == 1
    assert con.execute("SELECT op FROM sync_ops WHERE client_id='crash-00001'").fetchone()[0] == "list_add"
    con.execute("INSERT INTO sync_ops(device_id, client_id, op, status, created_at) VALUES (?,?,?,?,?)",
                (dev["id"], "busy-000001", s.PENDING + "list_add", "ok", dt.datetime.now().isoformat(timespec="seconds")))
    con.commit()
    res = s.push(con, dev, [{"id": "busy-000001", "op": "list_add", "list_id": lid, "text": "eggs"}])
    assert res[0]["status"] == "retry", "another request is still saving it: the phone asks again later"


def test_vehicle_details_op_needs_ids_scope_and_keeps_the_plate_whole(sy):
    s, _, con, make = sy
    con.execute("INSERT INTO vehicles(year, make, model, plate_last4, status) VALUES (2019, 'Tesla', 'Model 3', '7486', 'active')")
    con.commit()
    vid = con.execute("SELECT id FROM vehicles WHERE model='Model 3' ORDER BY id DESC").fetchone()[0]
    op = {"id": "vd-0000001", "op": "vehicle_details", "vehicle_id": vid, "plate": "kxr 7486", "plate_region": "nj",
          "color": "white", "body_type": "sedan"}
    no_ids = make("Alex", scopes=["lists"])
    assert s.push(con, no_ids, [op])[0]["status"] == "rejected", "adults without the ids scope cannot"
    kid = make("Sam", scopes=["ids", "lists"])
    assert s.push(con, kid, [{**op, "id": "vd-0000002"}])[0]["status"] == "rejected", "a limited person cannot"
    adult = make("Alex", scopes=["lists", "ids"])
    res = s.push(con, adult, [{**op, "id": "vd-0000003"}])
    assert res[0]["status"] == "ok", res
    row = con.execute("SELECT plate, plate_region, plate_last4, color, body_type FROM vehicles WHERE id=?", (vid,)).fetchone()
    assert tuple(row) == ("KXR 7486", "NJ", "7486", "white", "sedan")
    bad = s.push(con, adult, [{**op, "id": "vd-0000004", "plate": "<script>"}])
    assert bad[0]["status"] == "rejected", bad
    assert s.push(con, adult, [{**op, "id": "vd-0000005", "vehicle_id": 99999}])[0]["status"] == "rejected"
    cols = s.SOURCES["vehicles"][2]["adult"]
    assert "plate" in cols and "plate_region" in cols, "the whole plate reaches an adult phone with the ids scope"
# ---- Manage calendar ops (phone 0.23): change / remove events, add / change / remove calendar days ----------------
def test_manage_calendar_ops_from_an_adult_phone(sy, modules):
    s, _, con, make = sy
    dev = make("Alex")
    ea = modules("edit_actions")
    adult = {"name": "Alex", "role": "adult"}
    assert ea.event_add(adult, "Manage picnic", "2026-11-14")[0]
    ev = con.execute("SELECT id FROM events WHERE name='Manage picnic'").fetchone()[0]
    res = s.push(con, dev, [
        {"id": "mc-evup0001", "op": "event_update", "event_id": ev, "name": "Manage picnic (moved)", "date": "2026-11-15",
         "time": "10:00", "end": "11:30", "yearly": False},
        {"id": "mc-dayad001", "op": "day_add", "name": "Manage inservice", "day": "2026-11-20", "kind": "closure", "who": "Sam"},
        {"id": "mc-dayad002", "op": "day_add", "name": "Manage break", "day": "2026-12-21", "end": "2027-01-01", "kind": "closure"},
    ])
    assert [r["status"] for r in res] == ["ok", "ok", "ok"], res
    row = con.execute("SELECT name, event_date, start_time, end_time FROM events WHERE id=?", (ev,)).fetchone()
    assert tuple(row) == ("Manage picnic (moved)", "2026-11-15", "10:00", "11:30")
    day = con.execute("SELECT id, kind, member, source FROM calendar_days WHERE name='Manage inservice'").fetchone()
    assert tuple(day)[1:] == ("closure", "Sam", "manual")
    brk = con.execute("SELECT id, end_day FROM calendar_days WHERE name='Manage break'").fetchone()
    assert brk[1] == "2027-01-01"
    res = s.push(con, dev, [
        {"id": "mc-dayup001", "op": "day_update", "day_id": brk[0], "name": "Manage recess", "day": "2026-12-22",
         "end": "2027-01-02", "kind": "early"},
        {"id": "mc-daydr001", "op": "day_drop", "day_id": day[0]},
        {"id": "mc-evdr0001", "op": "event_drop", "event_id": ev},
    ])
    assert [r["status"] for r in res] == ["ok", "ok", "ok"], res
    assert tuple(con.execute("SELECT name, day, end_day, kind FROM calendar_days WHERE id=?", (brk[0],)).fetchone()) == \
        ("Manage recess", "2026-12-22", "2027-01-02", "early")
    assert con.execute("SELECT status FROM calendar_days WHERE id=?", (day[0],)).fetchone()[0] == "dropped"
    assert con.execute("SELECT COUNT(*) FROM events WHERE id=?", (ev,)).fetchone()[0] == 0
    stored = [r[0] for r in con.execute("SELECT op FROM sync_ops WHERE device_id=? ORDER BY id", (dev["id"],))]
    assert stored == ["event_update", "day_add", "day_add", "day_update", "day_drop", "event_drop"]
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert "	Alex	calendar_day_update	" in log and "	Alex	event_drop	" in log
    assert "Manage recess" not in log, "the log names the row, never its text"
    again = s.push(con, dev, [{"id": "mc-daydr001", "op": "day_drop", "day_id": day[0]}])
    assert again[0].get("repeat") and again[0]["status"] == "ok", "a repeat of an id changes nothing twice"


def test_manage_calendar_ops_are_refused_when_they_should_be(sy):
    s, _, con, make = sy
    kid, lists_only = make("Sam"), make("Alex", scopes=["lists"])
    ops = [{"id": "mx-kid00001", "op": "day_add", "name": "Nope", "day": "2026-11-20"},
           {"id": "mx-kid00002", "op": "event_drop", "event_id": 1}]
    for dev in (kid, lists_only):
        assert [r["status"] for r in s.push(con, dev, ops)] == ["rejected", "rejected"]
    assert con.execute("SELECT COUNT(*) FROM calendar_days WHERE name='Nope'").fetchone()[0] == 0
    adult = make("Alex")
    bad = s.push(con, adult, [
        {"id": "mx-bad00001", "op": "day_add", "name": "X", "day": "2026-02-30"},
        {"id": "mx-bad00002", "op": "day_add", "name": "X", "day": "2026-11-20", "kind": "party"},
        {"id": "mx-bad00003", "op": "day_add", "name": "X", "day": "2026-11-20", "end": "2026-01-01"},
        {"id": "mx-bad00004", "op": "day_update", "day_id": 99999, "name": "X", "day": "2026-11-20"},
        {"id": "mx-bad00005", "op": "day_drop", "day_id": "abc"},
        {"id": "mx-bad00006", "op": "event_drop", "event_id": 99999},
        {"id": "mx-bad00007", "op": "event_update", "event_id": 99999, "name": "X", "date": "2026-11-20"},
    ])
    assert [r["status"] for r in bad] == ["rejected"] * 7, bad


def test_manage_calendar_ops_are_listed_for_adults_and_pc_changes_reach_the_phone(sy, modules):
    s, _, con, make = sy
    dev = make("Alex")
    assert {"event_update", "event_drop", "day_add", "day_update", "day_drop"} <= set(s.OPS)
    assert all(s.OPS[k] == ("calendar", None) for k in ("event_update", "event_drop", "day_add", "day_update", "day_drop"))
    ea = modules("edit_actions")
    adult = {"name": "Alex", "role": "adult"}
    assert ea.calendar_day_add(adult, "2026-11-25", "PC side day", "holiday")[0]
    rid = con.execute("SELECT id FROM calendar_days WHERE name='PC side day'").fetchone()[0]
    assert ea.calendar_day_update(adult, rid, "2026-11-26", "PC side day moved", "festival")[0]
    rows, _gone, _body, _pages = _all(s, con, dev)
    assert rows["days"][rid]["name"] == "PC side day moved" and rows["days"][rid]["day"] == "2026-11-26"
    assert ea.calendar_day_drop(adult, rid)[0]
    rows, gone, _, _ = _all(s, con, dev)
    assert rid not in rows.get("days", {}) or rid in gone.get("days", set())


def test_pull_carries_the_built_in_festival_and_holiday_days_for_the_calendar_scope(sy):
    s, d, con, make = sy
    dev = make("Alex")
    today = dt.date(2026, 12, 1)
    body = s.pull(con, dev, today=today)
    days = body["phone_extras"]["special_days"]
    names = {x["name"] for x in days}
    assert any("Christmas" in n for n in names), names  # a public holiday, worked out by rule
    assert all(set(x) == {"start", "end", "kind", "name"} for x in days), "no tradition label or source leaves the PC"
    assert all(x["start"] >= (today - dt.timedelta(days=7)).isoformat() for x in days)
    assert all(x["start"] <= (today + dt.timedelta(days=400)).isoformat() for x in days)
    ok = s.pull(con, dev, body["cursor"], today=today)  # every answer carries it, a changes page too
    assert ok["phone_extras"]["special_days"] == days
    con.execute("INSERT INTO calendar_days (day, kind, name, status, source) VALUES ('2026-12-10', 'holiday', 'Family day', 'active', 'manual')")
    con.commit()
    mine = s.pull(con, dev, today=today)["phone_extras"]["special_days"]
    assert not any(x["name"] == "Family day" for x in mine), "a day the family stored travels in the days table, not here"


def test_a_phone_without_the_calendar_scope_gets_no_special_days(sy):
    s, d, con, make = sy
    dev = make("Alex", scopes=["lists"])
    assert "phone_extras" not in s.pull(con, dev, today=dt.date(2026, 12, 1))
