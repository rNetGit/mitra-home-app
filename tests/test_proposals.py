"""The Inbox queue (data/proposals.py, migration 037): producers, idempotent sync, expiry when handled elsewhere,
snooze and reopen, every handler going through edit_actions, the adult gate, and the CLI. No AI."""
import datetime as D
import sqlite3
import json

import pytest

from conftest import db, q, run

ADULT = {"name": "Alex", "role": "adult"}
CHILD = {"name": "Sam", "role": "child"}


@pytest.fixture(scope="module")
def pr(root, modules):
    return modules("proposals")


def _sync(pr, today=None):
    return pr.sync(today=today or D.date.today())


def _open(pr, root, source=None):
    con = db(root)
    try:
        return [r for r in pr.items(con) if source is None or r["source"] == source]
    finally:
        con.close()


def test_migration_made_the_table(root):
    cols = {r[1] for r in q(root, "PRAGMA table_info(proposals)")}
    assert {"dedupe_key", "source", "kind", "summary", "payload", "status", "until", "outcome"} <= cols
    assert q(root, "SELECT name FROM schema_migrations WHERE name='migrate_037_proposals.py'")


def test_sync_fills_the_queue_from_the_demo_family_and_is_idempotent(root, pr):
    first = _sync(pr)
    assert first["added"] > 0 and first["open"] == first["added"]
    con = db(root)
    try:
        c = pr.counts(con)
    finally:
        con.close()
    assert c["question"] > 0 and c["decision"] > 0, c
    assert c["all"] == c["file"] + c["decision"] + c["question"]
    again = _sync(pr)
    assert again["added"] == 0 and again["expired"] == 0 and again["open"] == first["open"]


def test_payload_holds_arguments_only(root, pr):
    allowed = {"review_id", "payee", "bill_ok", "sub_ok", "account", "item_id", "gap", "member"}
    for (payload,) in q(root, "SELECT payload FROM proposals"):
        keys = set(json.loads(payload or "{}"))
        assert keys <= allowed, keys
    for (summary,) in q(root, "SELECT summary FROM proposals"):
        assert "data/" not in summary and "python" not in summary and "\\" not in summary, summary


def test_review_file_needs_fields_and_dismiss_closes_the_review_row(root, pr):
    con = db(root)
    con.execute("INSERT INTO review_queue(path, reason) VALUES (?, ?)",
                ("inbox/needs_review/scan_0001.pdf", "scanned PDF (no text layer)"))
    con.commit()
    rid = con.execute("SELECT MAX(id) FROM review_queue").fetchone()[0]
    con.close()
    _sync(pr)
    item = next(r for r in _open(pr, root, "review") if r["payload"]["review_id"] == rid)
    assert item["kind"] == "file" and item["summary"].startswith("scan_0001.pdf ") and "inbox" not in item["summary"]
    assert item["detail"].startswith("It is a scan, so there is no text to read.")
    ok, msg = pr.decide(ADULT, item["id"], "file")
    assert not ok and "type" in msg and "vendor" in msg
    ok, msg = pr.decide(ADULT, item["id"], "dismiss")
    assert ok, msg
    assert q(root, "SELECT resolved FROM review_queue WHERE id=?", rid) == [(1,)]
    assert q(root, "SELECT status, outcome, decided_by FROM proposals WHERE id=?", item["id"]) == [("dismissed", "dismiss", "Alex")]
    assert "source=review option=dismiss" in (root / "logs" / "edits.log").read_text(encoding="utf-8")


def test_undated_question_date_records_it_and_stays_done(root, pr):
    _sync(pr)
    item = _open(pr, root, "undated")[0]
    iid = item["payload"]["item_id"]
    assert set(item["options"]) == {"date", "not_sure", "not_ours"}
    ok, msg = pr.decide(ADULT, item["id"], "date", date="2026-03-01")
    assert ok, msg
    assert q(root, "SELECT last_done FROM recurring_items WHERE id=?", iid) == [("2026-03-01",)]
    _sync(pr)
    assert q(root, "SELECT status FROM proposals WHERE id=?", item["id"]) == [("done",)]


def test_not_sure_snoozes_then_reopens_and_restore_works(root, pr):
    item = _open(pr, root, "undated")[0]
    ok, _ = pr.decide(ADULT, item["id"], "not_sure")
    assert ok
    (status, until), = q(root, "SELECT status, until FROM proposals WHERE id=?", item["id"])
    assert status == "snoozed" and until == (D.date.today() + D.timedelta(days=30)).isoformat()
    assert _sync(pr)["reopened"] == 0
    assert _sync(pr, D.date.today() + D.timedelta(days=31))["reopened"] >= 1
    assert q(root, "SELECT status, until FROM proposals WHERE id=?", item["id"]) == [("open", None)]
    ok, _ = pr.decide(ADULT, item["id"], "not_sure")
    ok, msg = pr.restore(ADULT, item["id"])
    assert ok, msg
    assert q(root, "SELECT status FROM proposals WHERE id=?", item["id"]) == [("open",)]
    assert not pr.restore(ADULT, item["id"])[0], "an open item cannot be restored"


def test_not_ours_stops_tracking(root, pr):
    item = _open(pr, root, "undated")[0]
    ok, msg = pr.decide(ADULT, item["id"], "not_ours")
    assert ok, msg
    assert q(root, "SELECT active FROM recurring_items WHERE id=?", item["payload"]["item_id"]) == [(0,)]


def test_recurring_decision_handled_elsewhere_expires(root, pr, modules):
    _sync(pr)
    bills = [r for r in _open(pr, root, "recurring") if r["payload"]["bill_ok"]]
    assert bills, "the demo family has a steady payee"
    item = bills[0]
    assert "bill" in item["options"]
    ea = modules("edit_actions")
    ok, msg = ea.recurring_confirm(ADULT, item["payload"]["payee"])  # tracked from the Money tab instead
    assert ok, msg
    assert _sync(pr)["expired"] >= 1
    assert q(root, "SELECT status FROM proposals WHERE id=?", item["id"]) == [("expired",)]


def test_track_as_subscription_goes_through_edit_actions(root, pr):
    con = sqlite3.connect(root / "data" / "family.db")
    acct = con.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
    t = D.date.today()
    for k in (1, 2, 3):  # a steady monthly streaming charge (the demo's shops no longer count as subscriptions)
        m = t.year * 12 + t.month - 1 - k  # one charge in each of the 3 months before this one (30-day steps skip a month some days)
        d = D.date(m // 12, m % 12 + 1, min(t.day, 28)).isoformat()
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, txn_type) VALUES (?,?,?,?,?,?)",
                    (acct, d, "STREAMLY VIDEO", -12.99, "entertainment", "spend"))
    con.commit()
    con.close()
    _sync(pr)
    subs = [r for r in _open(pr, root, "recurring") if r["payload"]["sub_ok"]]
    assert subs, "a steady streaming charge is offered as a subscription"
    item = next(r for r in subs if "Streamly" in r["payload"]["payee"])
    ok, msg = pr.decide(ADULT, item["id"], "subscription")
    assert ok, msg
    rows = q(root, "SELECT match_pattern, match_payee, decision FROM subscriptions WHERE name=?", item["payload"]["payee"])
    assert rows and rows[0][2] == "unreviewed" and rows[0][1] == item["payload"]["payee"]
    assert "subscription_accept" in (root / "logs" / "edits.log").read_text(encoding="utf-8")


def test_gate_and_bad_options(root, pr):
    _sync(pr)
    item = _open(pr, root)[0]
    assert pr.decide(CHILD, item["id"], next(iter(item["options"]))) == (False, "Only an adult can decide this.")
    assert pr.decide(ADULT, item["id"], "rm -rf")[0] is False
    assert pr.decide(ADULT, 999999, "dismiss") == (False, "That item is already handled.")
    assert pr.restore(CHILD, item["id"])[0] is False


def test_statement_and_price_rise_producers(root, pr, monkeypatch, modules):
    sw, rb = modules("statement_watch"), modules("recurring_bills")
    exp = D.date.today() - D.timedelta(days=10)
    monkeypatch.setattr(sw, "watch", lambda con, today: [
        {"account": "Demo Checking", "last4": "4321", "status": "overdue", "expected": exp, "missing": ["2026-02"]}])
    monkeypatch.setattr(rb, "status", lambda con, today=None: [
        {"payee": "City Water", "name": "City Water", "flags": ["price rise 20.00 -> 25.00", "missing: x"]}])
    _sync(pr)
    st = _open(pr, root, "statement")
    texts = {r["summary"] for r in st}
    assert "The Demo Checking ending 4321 statement is late" in texts
    assert "The Demo Checking ending 4321 statement for February 2026 is missing" in texts
    late = next(r for r in st if r["summary"].endswith("is late"))
    ok, msg = pr.decide(ADULT, late["id"], "later")
    assert ok and msg == "I will remind you in a week."
    pz = _open(pr, root, "price_rise")
    assert [r["summary"] for r in pz] == ["City Water went up (20.00 to 25.00)"]
    assert pr.decide(ADULT, pz[0]["id"], "ok")[0]
    monkeypatch.setattr(sw, "watch", lambda con, today: [])
    _sync(pr)
    assert q(root, "SELECT status FROM proposals WHERE id=?", late["id"]) == [("expired",)], "a snoozed item expires when the statement arrives"


def test_a_broken_detector_does_not_stop_the_others(root, pr, monkeypatch, modules):
    rb = modules("recurring_bills")

    def boom(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(rb, "detect", boom)
    monkeypatch.setattr(rb, "status", boom)
    r = _sync(pr)
    assert r["open"] >= 0


def test_cli(root):
    r = run(["data/proposals.py", "sync"], root)
    assert r.returncode == 0 and " open (" in r.stdout
    r = run(["data/proposals.py", "list"], root)
    assert r.returncode == 0 and "options:" in r.stdout
    r = run(["data/proposals.py", "decide", "999999", "dismiss"], root)
    assert r.returncode == 1 and "already handled" in r.stdout
    r = run(["data/proposals.py", "list", "--all"], root)
    assert r.returncode == 0 and ("done" in r.stdout or "dismissed" in r.stdout)


def test_purge_person_removes_their_inbox_items(root, pr):
    con = db(root)
    con.execute("INSERT INTO recurring_items(name, who, interval_months, active) VALUES ('Eye exam', 'Sam', 12, 1)")
    con.commit()
    iid = con.execute("SELECT MAX(id) FROM recurring_items").fetchone()[0]
    con.close()
    _sync(pr)
    assert q(root, "SELECT summary FROM proposals WHERE ref_table='recurring_items' AND ref_id=?", iid) == \
        [("When was Eye exam (Sam) last done?",)]
    r = run(["data/purge.py", "person", "Sam", "--yes"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert q(root, "SELECT COUNT(*) FROM proposals WHERE summary LIKE '%Sam%'") == [(0,)]
