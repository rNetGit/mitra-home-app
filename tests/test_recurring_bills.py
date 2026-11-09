"""Recurring bills from transactions: detect, confirm (bills row + config), sync (settle + roll forward), status flags,
dismiss, the CLI exit codes, the edit_actions gate and the digest section. No AI, no migration."""
import datetime as D
import json

import pytest

from conftest import db, q, run

TODAY = D.date(2026, 9, 1)


def _txn(root, date, desc, amount, typ=None, payee=None):
    con = db(root)
    acct = con.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, txn_type, payee) VALUES (?,?,?,?,?,?)",
                (acct, date, desc, amount, typ, payee))
    con.commit()
    con.close()


@pytest.fixture(scope="module")
def rb(root, modules):
    for d, a in (("2026-06-15", 38.10), ("2026-07-15", 47.30), ("2026-08-14", 40.90)):
        _txn(root, d, "CITY WATER WORKS 0423", -a, "utility")
    for d in ("2025-12-01", "2026-03-01", "2026-06-01"):
        _txn(root, d, "CAR INSURE CO PREMIUM", -210.0, "insurance")
    for d, a in (("2026-05-03", 20.0), ("2026-06-03", 20.0), ("2026-07-03", 20.0), ("2026-08-03", 25.0)):
        _txn(root, d, "GYM PLUS MEMBERSHIP", -a, None, "Gym Plus")
    for d in ("2026-06-20", "2026-07-20"):
        _txn(root, d, "ONE OFF SHOP", -30.0)
    for d in ("2026-06-30", "2026-07-31", "2026-08-31"):
        _txn(root, d, "ACME PAYROLL", 3000.0, "income")
    return modules("recurring_bills")


def _by(cands, name):
    return next((c for c in cands if c["payee"] == name), None)


def test_detect_finds_steady_payees_only(root, rb):
    con = db(root)
    try:
        cands = rb.detect(con, TODAY)
    finally:
        con.close()
    names = {c["payee"] for c in cands}
    assert "City Water" in names and "Car Insure" in names and "Gym Plus" in names, names
    assert "One Off" not in names and "Acme Payroll" not in names, names
    assert not any("streamco" in n.lower() for n in names), "a tracked subscription is not proposed again"
    w = _by(cands, "City Water")
    assert w["frequency"] == "monthly" and w["amount"] == 40.90 and w["variable"] and w["charges"] == 3
    assert w["last"] == D.date(2026, 8, 14) and w["next"] == D.date(2026, 9, 14) and w["active"] and not w["rise"]
    c = _by(cands, "Car Insure")
    assert c["frequency"] == "quarterly" and c["amount"] == 210.0 and not c["variable"] and c["next"] == D.date(2026, 9, 1)
    g = _by(cands, "Gym Plus")
    assert g["match_payee"] == "Gym Plus" and g["rise"] == "price rise 20.00 -> 25.00"


def test_confirm_tracks_and_adds_the_next_bill(root, rb):
    con = db(root)
    try:
        bid = rb.confirm(con, "city water", TODAY, name="Water")
        assert q(root, "select name, vendor, frequency, amount, due_date, status from bills where id=?", bid) == \
            [("Water", "City Water", "monthly", 40.9, "2026-09-14", "due")]
        assert "City Water" not in {c["payee"] for c in rb.detect(con, TODAY)}
        with pytest.raises(ValueError):
            rb.confirm(con, "City Water", TODAY)
        with pytest.raises(ValueError):
            rb.confirm(con, "Nope", TODAY)
        st = {r["payee"]: r for r in rb.status(con, TODAY)}
        assert st["City Water"]["open_bill"]["due"] == "2026-09-14" and st["City Water"]["flags"] == []
    finally:
        con.close()
    conf = json.loads((root / "config" / "recurring_bills.json").read_text(encoding="utf-8"))
    assert [t["payee"] for t in conf["tracked"]] == ["City Water"] and conf["tracked"][0]["pattern"] == "%CITY%WATER%"


def test_sync_settles_the_bill_and_rolls_forward(root, rb):
    _txn(root, "2026-09-16", "CITY WATER WORKS 0423", -43.0, "utility")
    con = db(root)
    try:
        acts = rb.sync(con, D.date(2026, 9, 20))
        assert len(acts) == 2 and "paid 2026-09-16" in acts[0] and "next bill 2026-10-16" in acts[1], acts
        assert q(root, "select status, paid_date, amount from bills where vendor='City Water' and due_date='2026-09-14'") == \
            [("paid", "2026-09-16", 43.0)]
        assert q(root, "select amount, status from bills where vendor='City Water' and due_date='2026-10-16'") == [(43.0, "due")]
        assert rb.sync(con, D.date(2026, 9, 20)) == [] and q(root, "select count(*) from bills where vendor='City Water'") == [(2,)]
    finally:
        con.close()


def test_status_flags_missing_and_price_rise(root, rb):
    _txn(root, "2026-11-30", "SOMETHING ELSE", -5.0)  # newer statement loaded, still no water charge after 10-16
    con = db(root)
    try:
        st = {r["payee"]: r for r in rb.status(con, D.date(2026, 12, 1))}
        assert any(f.startswith("missing: expected about 2026-10-16") for f in st["City Water"]["flags"]), st["City Water"]
        assert not [f for f in rb.status(con, D.date(2026, 10, 20))[0]["flags"] if f.startswith("missing")], "inside the grace period"
        rb.confirm(con, "Gym Plus", TODAY)
        st = {r["payee"]: r for r in rb.status(con, TODAY)}
        assert st["Gym Plus"]["flags"] == ["price rise 20.00 -> 25.00"] and st["Gym Plus"]["amount"] == 20.0
        assert q(root, "select due_date, amount from bills where vendor='Gym Plus'") == [("2026-09-03", 20.0)]
    finally:
        con.close()


def test_dismiss_hides_a_candidate(root, rb):
    assert rb.dismiss("Car Insure") and not rb.dismiss("car insure")
    con = db(root)
    try:
        assert "Car Insure" not in {c["payee"] for c in rb.detect(con, TODAY)}
    finally:
        con.close()
    assert json.loads((root / "config" / "recurring_bills.json").read_text(encoding="utf-8"))["ignored"] == ["Car Insure"]


def test_cli(root, rb):
    r = run(["data/recurring_bills.py", "confirm", "Nope"], root)
    assert r.returncode == 2 and "no candidate" in r.stderr
    r = run(["data/recurring_bills.py", "status"], root)
    assert r.returncode == 0 and "Water" in r.stdout and "Gym Plus" in r.stdout and "price rise" in r.stdout, r.stdout
    r = run(["data/recurring_bills.py", "detect"], root)
    assert r.returncode == 0 and "Car Insure" not in r.stdout and "City Water" not in r.stdout
    r = run(["data/recurring_bills.py", "sync"], root)
    assert r.returncode == 0 and ("nothing to do" in r.stdout or "next bill" in r.stdout), r.stdout
    assert run(["data/recurring_bills.py"], root).returncode == 0


def test_edit_actions_gate_and_log(root, rb, modules):
    ea = modules("edit_actions")
    kid, adult = {"name": "Sam", "role": "limited"}, {"name": "Alex", "role": "adult"}
    assert not ea.recurring_confirm(kid, "Demo Electric")[0] and not ea.recurring_dismiss(kid, "Demo Electric")[0]
    assert not ea.recurring_confirm(adult, "Nope")[0]
    ok, msg = ea.recurring_dismiss(adult, "Demo Electric")
    assert ok and "not be proposed" in msg
    elog = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "recurring_dismiss" in elog and "Demo Electric" not in elog


def test_digest_has_a_recurring_bills_section(root, rb):
    today = D.date.today()
    # one charge in each of the last three calendar months (the detector needs three distinct months)
    for back in (3, 2, 1):
        m = today.month - back
        y = today.year + (m - 1) // 12
        m = (m - 1) % 12 + 1
        _txn(root, D.date(y, m, min(today.day, 28)).isoformat(), "TRASH HAUL SERVICE", -28.0, "utility")
    assert run(["data/make_digest.py"], root).returncode == 0
    out = next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")
    assert "## Recurring bills" in out and "Trash Haul" in out and "Other recurring payments seen" not in out
    r = run(["tasks/run_task.py", "weekly_digest"], root, env={"AIFA_DRY_RUN": "1"}, timeout=600)
    assert r.returncode == 0, r.stderr[-800:]
    log = (root / "logs" / "weekly_digest.log").read_text(encoding="utf-8", errors="replace")
    assert "recurring_bills.py" in log


def test_shops_you_visit_often_are_not_proposed_as_bills(root, rb):
    con = db(root)
    acct = con.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
    for d, a in (("2026-06-02", 61.0), ("2026-07-03", 58.5), ("2026-08-02", 64.2)):  # monthly, but groceries
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) VALUES (?,?,?,?,?)",
                    (acct, d, "CORNER GROCER 17", -a, "groceries"))
    for d in ("2026-06-05", "2026-07-05", "2026-08-05"):  # same steady shape, a loan: stays a candidate
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) VALUES (?,?,?,?,?)",
                    (acct, d, "BIG LOAN SERVICER", -310.0, "auto loan"))
    con.commit()
    con.close()
    con = db(root)
    try:
        names = {c["payee"] for c in rb.detect(con, TODAY)}
    finally:
        con.close()
    assert "Corner Grocer" not in names and "Big Loan" in names


def test_subscription_detect_skips_shops_but_keeps_streaming(root, rb, modules):
    con = db(root)
    acct = con.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
    for d in ("2026-06-09", "2026-07-09", "2026-08-09"):
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) VALUES (?,?,?,?,?)",
                    (acct, d, "FUEL STOP 9", -45.0, "fuel"))
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) VALUES (?,?,?,?,?)",
                    (acct, d, "STREAMLY VIDEO", -12.99, "entertainment"))
    con.commit()
    S = modules("subscriptions")
    try:
        names = {c["merchant"] for c in S.detect(con, TODAY)}
    finally:
        con.close()
    assert "Fuel Stop" not in names and "Streamly Video" in names, names


def test_subscription_detect_accepts_one_price_rise_but_not_drift(root, rb, modules):
    con = db(root)
    acct = con.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()[0]
    rows = [("RISEN TV", d, a) for d, a in (("2026-04-07", 15.49), ("2026-05-07", 15.49), ("2026-06-07", 15.49),
                                           ("2026-07-07", 17.99), ("2026-08-07", 17.99), ("2026-09-07", 17.99))]
    rows += [("DRIFT TV", d, a) for d, a in (("2026-04-07", 10.0), ("2026-05-07", 12.0), ("2026-06-07", 14.5),
                                            ("2026-07-07", 17.0), ("2026-08-07", 20.0), ("2026-09-07", 24.0))]
    for desc, d, a in rows:
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) VALUES (?,?,?,?,?)",
                    (acct, d, desc, -a, "entertainment"))
    con.commit()
    S = modules("subscriptions")
    try:
        found = {c["merchant"]: c for c in S.detect(con, TODAY)}
    finally:
        con.close()
    assert "Risen Tv" in found and found["Risen Tv"]["amount"] == 17.99, found
    assert "Drift Tv" not in found, found
