"""Today > Keep up (data/keepup.py): the bank-sync row and Sync now, accounts that went quiet (synced vs statement
thresholds, the 2-of-3-months rule), the scheduled-jobs row (flag or heartbeat evidence, failed runs), the Inbox count,
adults only, and the card on the page. bank_sync is never reached for real: its status is faked."""
import datetime as dt
import re
import sqlite3

import pytest

T = dt.date(2026, 10, 23)


@pytest.fixture()
def ku(modules):
    return modules("keepup")


def _sql(modules, sql, *params):
    con = sqlite3.connect(modules("paths").DB)
    try:
        with con:
            return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _account(modules, name, last4, days_back, sfin=None):
    """An account with one line a month on each of the given days back (newest first)."""
    aid = _sql(modules, "INSERT INTO accounts(name, last4, type, simplefin_id) VALUES (?, ?, 'checking', ?) RETURNING id",
               name, last4, sfin)[0][0]
    for i, d in enumerate(days_back):
        _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount, ref) VALUES (?, ?, 'x', -1, ?)",
             aid, (T - dt.timedelta(days=d)).isoformat(), f"t:{aid}:{i}")
    return aid


def test_quiet_accounts_apply_the_kind_thresholds_and_the_active_rule(ku, modules):
    con = sqlite3.connect(modules("paths").DB)
    try:
        con.execute("DELETE FROM transactions")
        con.execute("DELETE FROM accounts")
        con.commit()
    finally:
        con.close()
    fresh = _account(modules, "Fresh card", "1111", [2, 35, 65])
    stmt = _account(modules, "Monthly statement", "2222", [45, 75, 105])      # 45 d > 40: one statement missing
    recent_stmt = _account(modules, "Recent statement", "3333", [23, 50, 80])  # 23 d < 40: fine
    synced = _account(modules, "Salary", "5023", [23, 50, 80], sfin="ACT-1")   # synced + 23 d > 10: broken connection
    dormant = _account(modules, "Old CD", "4444", [62, 400])                   # lines in 1 of the 3 months: ignored
    con = sqlite3.connect(modules("paths").DB)
    try:
        rows = ku.quiet_accounts(con, T, synced={synced})
    finally:
        con.close()
    ids = [r["id"] for r in rows]
    assert stmt in ids and synced in ids
    assert fresh not in ids and recent_stmt not in ids and dormant not in ids
    assert rows[0]["id"] == synced, "a broken sync first, then statement accounts by the age of the gap"
    assert rows[1]["id"] == stmt
    by = {r["id"]: r for r in rows}
    assert by[synced]["synced"] is True and by[synced]["days"] == 23
    con = sqlite3.connect(modules("paths").DB)
    try:
        texts = ku.account_rows(con, T)
    finally:
        con.close()
    assert any("Monthly statement x2222: no new lines since" in r["text"] and r["action"] == "Add statement" and r["href"] == "/add"
               for r in texts)
    # Salary is not in config/bank_sync.json here, so it counts as a statement account (23 d: quiet enough? no)
    assert not any(r["key"] == f"acct:{synced}" for r in texts)


def test_quiet_accounts_list_checking_and_cards_before_savings(ku, modules):
    con = sqlite3.connect(modules("paths").DB)
    try:
        con.execute("DELETE FROM transactions")
        con.execute("DELETE FROM accounts")
        con.commit()
    finally:
        con.close()
    cds = [_account(modules, f"CD {i}", f"900{i}", [52, 82, 112]) for i in range(4)]
    _sql(modules, "UPDATE accounts SET type='savings' WHERE id IN (%s)" % ",".join(map(str, cds)))
    card = _account(modules, "Everyday card", "1008", [42, 72, 102])
    _sql(modules, "UPDATE accounts SET type='credit' WHERE id=?", card)
    salary = _account(modules, "Salary", "5023", [23, 50, 80], sfin="ACT-1")
    con = sqlite3.connect(modules("paths").DB)
    try:
        rows = ku.quiet_accounts(con, T, synced={salary})
        shown = [r["key"] for r in ku.account_rows(con, T, synced={salary})]
    finally:
        con.close()
    assert [r["id"] for r in rows][:2] == [salary, card], "synced first, then the card, then the CDs by age"
    assert f"acct:{salary}" in shown and f"acct:{card}" in shown and len(shown) == 4


def test_bank_row_states(ku, modules, monkeypatch):
    bs = modules("bank_sync")
    monkeypatch.setattr(bs, "configured", lambda: True)

    def st(**kw):
        base = {"configured": True, "last_pull": "2026-10-23T10:22:29", "last_ok": "2026-10-23T10:22:32", "error": "",
                "stale_days": 0, "last": {"inserted": 1, "skipped": 6, "warnings": []}, "accounts": []}
        base.update(kw)
        return base
    monkeypatch.setattr(bs, "status", lambda today=None: st())
    r = ku.bank_row(T)
    assert r["tone"] == "ok" and r["text"] == "Bank sync: pulled today, 1 new" and r["op"] == "syncall" and not r["href"]
    monkeypatch.setattr(bs, "status", lambda today=None: st(last={"inserted": 1, "skipped": 6,
                                                                  "warnings": ["Connection to Capital One may need attention. Auth required"]}))
    r = ku.bank_row(T)
    assert r["tone"] == "warn" and "Capital One" in r["text"] and "SimpleFIN" in r["text"] and r["href"] == ku.SETTINGS_BANK
    monkeypatch.setattr(bs, "status", lambda today=None: st(stale_days=5, last_ok="2026-10-18T07:00:00"))
    assert ku.bank_row(T)["text"] == "Bank sync: last good pull 5 days ago"
    monkeypatch.setattr(bs, "status", lambda today=None: st(error="HTTP 403", stale_days=1, last_ok="2026-10-22T07:00:00"))
    r = ku.bank_row(T)
    assert r["tone"] == "warn" and "failed (HTTP 403)" in r["text"] and "yesterday" in r["text"]
    monkeypatch.setattr(bs, "status", lambda today=None: st(stale_days=None, last_ok=None))
    assert ku.bank_row(T)["text"] == "Bank sync: no pull has worked yet"
    monkeypatch.setattr(bs, "configured", lambda: False)
    assert ku.bank_row(T) is None


def test_task_rows_flag_evidence_and_failures(ku, modules, root):
    hb, config = modules("heartbeat"), modules("config")
    hb.FILE.unlink(missing_ok=True)
    with config.family_edit() as cfg:
        cfg.pop("tasks_registered", None)
        cfg.pop("tasks_off", None)
    rows = ku.task_rows(T)
    assert len(rows) == 1 and rows[0]["key"] == "tasks" and rows[0]["action"] == "Turn on" and rows[0]["href"] == ku.SETTINGS_DATA
    # the jobs evidently run (a heartbeat this week) although the flag was never written: no "turn on" row,
    # but a failed run and a stale one are reported
    config.write_json(hb.FILE, {"daily_digest": {"ok": True, "at": (T - dt.timedelta(days=1)).isoformat() + "T07:00:00", "note": ""},
                                "inbox_cycle": {"ok": False, "at": T.isoformat() + "T13:56:04", "note": "a step failed; see logs/inbox_cycle.log"},
                                "weekly_backup": {"ok": True, "at": (T - dt.timedelta(days=12)).isoformat() + "T09:00:00", "note": ""}})
    with config.family_edit() as cfg:
        cfg["inbox_cycle"] = True
    rows = ku.task_rows(T)
    keys = {r["key"] for r in rows}
    assert "tasks" not in keys and "task:weekly_backup" in keys
    inbox = [r for r in rows if r["key"] == "task:inbox_cycle"]
    assert inbox and "FAILED" in inbox[0]["text"] and "a step failed" in inbox[0]["text"] and inbox[0]["tone"] == "warn"
    assert not any(r["key"] == "task:daily_digest" for r in rows)
    hb.FILE.unlink(missing_ok=True)


def test_rows_adults_only_and_inbox_count(ku, modules):
    assert ku.rows({"name": "Kid", "role": "limited"}, T) == []
    assert ku.rows(None, T) == []
    _sql(modules, "DELETE FROM proposals")
    con = sqlite3.connect(modules("paths").DB)
    try:
        assert ku.inbox_row(con) is None
        for i in range(12):
            con.execute("INSERT INTO proposals(dedupe_key, source, kind, summary, status) VALUES (?, 'audit', 'decision', 's', 'open')", (f"k{i}",))
        con.commit()
        r = ku.inbox_row(con)
        assert r["text"] == "12 Inbox cards wait for an answer" and r["tone"] == "warn" and r["href"] == "/add"
        con.execute("DELETE FROM proposals WHERE dedupe_key != 'k0'")
        con.commit()
        r = ku.inbox_row(con)
        assert r["text"] == "1 Inbox card waits for an answer" and r["tone"] == "ok"
    finally:
        con.close()
    rows = ku.rows({"name": "Ann", "role": "adult"}, T)
    assert any(r["key"] == "inbox" for r in rows)
    assert [r["tone"] for r in rows] == sorted((r["tone"] for r in rows), key=lambda t: 0 if t == "warn" else 1), "warnings first"


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


def test_today_shows_the_card_with_sync_now(web, modules, monkeypatch):
    bs = modules("bank_sync")
    monkeypatch.setattr(bs, "configured", lambda: True)
    monkeypatch.setattr(bs, "status", lambda today=None: {"configured": True, "last_pull": "x", "last_ok": dt.date.today().isoformat() + "T08:00:00",
                                                           "error": "", "stale_days": 0, "last": {"inserted": 3, "skipped": 0, "warnings": []}, "accounts": []})
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/").text
    assert 'id="h-keep"' in page and "Bank sync: pulled today, 3 new" in page and ">Sync now<" in page
    assert 'hx-post="/today/act"' in page and '"op": "syncall"' in page
    # Sync now runs the pull and comes back to Today with its message
    monkeypatch.setattr(bs, "pull", lambda con=None, today=None: {"inserted": 2, "skipped": 1, "warnings": [], "accounts": ["a"]})
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    r = c.post("/today/act", data={"op": "sync", "who": ""}, headers={"X-CSRF-Token": token, "HX-Request": "true"})
    assert r.status_code in (200, 204, 303)
    page = c.get("/").text
    assert "Pulled 2 new transaction(s); 1 were already there." in page
    # not for a child, and not with a person filter
    name = _sql(modules, "SELECT name FROM members ORDER BY id")[0][0]
    assert 'id="h-keep"' not in c.get("/", params={"who": name}).text
    c.post("/logout", headers={"X-CSRF-Token": token})
    modules("webapp.sessions").clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    assert 'id="h-keep"' not in c.get("/").text


def test_data_as_of_line_and_age_note(ku, modules):
    con = sqlite3.connect(modules("paths").DB)
    try:
        con.execute("DELETE FROM transactions")
        con.execute("DELETE FROM accounts")
        con.commit()
    finally:
        con.close()
    assert _sql(modules, "SELECT COUNT(*) FROM accounts")[0][0] == 0
    con = sqlite3.connect(modules("paths").DB)
    try:
        assert ku.data_as_of(con, T) is None, "no lines yet: no line"
    finally:
        con.close()
    _account(modules, "Everyday", "1111", [2, 35, 65])
    _account(modules, "Salary", "5023", [45, 75, 105])  # a statement account a month and a half behind
    _sql(modules, "INSERT INTO accounts(name, last4, type) VALUES ('Rainy day', '9999', 'savings')")
    con = sqlite3.connect(modules("paths").DB)
    try:
        got = ku.data_as_of(con, T, synced=set())
    finally:
        con.close()
    assert got["behind"] == 1
    assert "Cards and checking as of Oct 21" in got["text"] and "1 account behind" in got["text"]
    assert "savings" not in got["text"], "an account with no lines adds no savings clause"
    assert ku.age_note(10) == "" and ku.age_note(None) == "" and ku.age_note(41) == "no lines for 41 days"


def test_money_overview_shows_data_as_of(web, modules):
    _sql(modules, "DELETE FROM transactions")
    _sql(modules, "DELETE FROM accounts")
    today = dt.date.today()
    aid = _sql(modules, "INSERT INTO accounts(name, last4, type) VALUES ('Everyday', '1111', 'checking') RETURNING id")[0][0]
    for i, d in enumerate((2, 35, 65)):
        _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount, ref) VALUES (?, ?, 'x', -1, ?)",
             aid, (today - dt.timedelta(days=d)).isoformat(), f"p:{i}")
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/money").text
    assert "Data as of: Cards and checking as of" in page
