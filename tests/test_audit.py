"""The data check (data/audit.py, migration 055, Settings > Data > Data check): fixed rules, read-only on the records,
results kept per run for the score over time; on demand from Settings (adults) and weekly with the digest task."""
import datetime as D
import pathlib
import re

import pytest

from conftest import db, q, run

TODAY = D.date.today()


def _iso(days):
    return (TODAY + D.timedelta(days=days)).isoformat()


def _plant(root):
    """One of each problem the checks look for."""
    (root / "archive" / "2026" / "misc").mkdir(parents=True, exist_ok=True)
    (root / "archive" / "2026" / "misc" / "loose_paper.pdf").write_bytes(b"%PDF-1.4 loose")
    with db(root) as con:
        acc = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Audit Checking', 'checking', '7777')").lastrowid
        for _ in range(2):  # the same charge twice, no source reference
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) "
                        "VALUES (?, ?, 'CORNER CAFE', -12.5, 'Dining')", (acc, _iso(-5)))
        for ref in ("r1", "r2"):  # two real coffees: different references, not a duplicate
            con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category, ref) "
                        "VALUES (?, ?, 'TWIN COFFEE', -4, 'Dining', ?)", (acc, _iso(-6), ref))
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) "
                    "VALUES (?, ?, 'MISREAD LINE', -9, 'Other')", (acc, _iso(40)))
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, ?, 'NO CATEGORY', -20)",
                    (acc, _iso(-3)))
        con.execute("INSERT INTO bills(name, frequency, amount, due_date, status) VALUES ('Audit Water', 'monthly', 40, ?, 'due')",
                    (_iso(-60),))
        con.execute("INSERT INTO bills(name, frequency, amount, due_date, status) VALUES ('Audit Gas', 'monthly', 30, ?, 'due')",
                    (_iso(10),))
        con.execute("INSERT INTO bills(name, frequency, amount, due_date, status) VALUES ('Audit Gas', 'monthly', 30, ?, 'due')",
                    (_iso(10),))
        con.execute("INSERT INTO bills(name, frequency, amount, due_date, status) VALUES ('Audit Power', 'monthly', 90, ?, 'paid')",
                    (_iso(-2),))
        bid = con.execute("INSERT INTO mobile_bills(carrier, invoice, bill_date, bill_total) VALUES ('Audit Mobile', 'A1', ?, 100)",
                          (_iso(-20),)).lastrowid
        con.execute("INSERT INTO mobile_bill_lines(bill_id, person, line_total, net) VALUES (?, 'Alex', 55, 55)", (bid,))
        con.execute("INSERT INTO mobile_bill_lines(bill_id, person, line_total, net) VALUES (?, 'Sam', 40, 40)", (bid,))
        con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) "
                    "VALUES ('2026/misc/2026-09-01_gone_bill.pdf', 'bill', 'Audit Gone', '2026-09-01')")


def test_checks_find_each_planted_problem_and_change_nothing(root, modules):
    au = modules("audit")
    _plant(root)
    before = {t: q(root, f"SELECT COUNT(*) FROM {t}")[0][0] for t in ("transactions", "bills", "documents", "mobile_bills")}
    rid = au.run("now", "Alex")
    after = {t: q(root, f"SELECT COUNT(*) FROM {t}")[0][0] for t in before}
    assert before == after, "a run changes no record"
    rows = q(root, "SELECT check_key, level, summary FROM audit_findings WHERE run_id=?", rid)
    text = "\n".join(f"{k}|{lv}|{s}" for k, lv, s in rows)
    assert re.search(r"duplicate_txns\|decide\|CORNER CAFE .* listed 2 times", text)
    assert "TWIN COFFEE" not in text, "different source references are two real charges"
    assert re.search(r"txn_dates\|decide\|MISREAD LINE is dated", text)
    assert re.search(r"uncategorized\|note\|\d+ payment\(s\) in the last 90 days have no category", text)
    assert re.search(r"bills\|decide\|Audit Water due .* is still open", text)
    assert re.search(r"bills\|decide\|Audit Gas due .* is listed 2 times", text)
    assert re.search(r"bills\|note\|Audit Power .* paid with no paid date", text)
    assert re.search(r"phone_bills\|money\|Audit Mobile bill of .* is off by \$5\.00", text)
    assert re.search(r"papers\|note\|Audit Gone bill .* its file is missing", text)
    assert re.search(r"papers\|note\|\d+ file\(s\) in the archive are not on record", text)
    assert "7777" not in text, "no account numbers in findings"
    r = q(root, "SELECT trigger, actor, checks_total, checks_ok, score, errors FROM audit_runs WHERE id=?", rid)[0]
    assert r[:2] == ("now", "Alex") and r[2] == len(au.CHECKS) and r[3] < r[2] and r[5] is None
    assert r[4] == round(100 * r[3] / r[2])


def test_latest_history_and_health(root, modules):
    au, dbm = modules("audit"), modules("db")
    au.run("weekly")
    with dbm.open(readonly=True) as con:
        x = au.latest(con)
        hr = au.health_row(con, TODAY)
    assert x["run"]["trigger"] == "weekly" and len(x["history"]) >= 2
    assert [f["level"] for f in x["findings"]] == sorted((f["level"] for f in x["findings"]), key=au.LEVELS.index)
    assert not any(f["new"] for f in x["findings"]), "the same problems as the run before are not new"
    states = {c["key"]: c["state"] for c in x["checks"]}
    assert states["phone_bills"] == "money" and states["duplicate_txns"] == "decide"
    assert hr[0] == "warn" and "to look at" in hr[1]
    h = modules("health")
    assert any(r["name"] == "Data check" and r["status"] == "warn" and r["here"] == "Settings > Data > Data check"
               for r in h.checks(TODAY))
    out = run(["data/audit.py", "show"], root)
    assert out.returncode == 0 and "score" in out.stdout and "Audit Mobile" in out.stdout


def test_one_broken_check_does_not_stop_the_rest(root, modules, monkeypatch):
    au = modules("audit")

    def boom(con, today):
        raise RuntimeError("broken")
    monkeypatch.setattr(au, "CHECKS", [("boom", "Broken", boom)] + [c for c in au.CHECKS if c[0] == "phone_bills"])
    rid = au.run("now")
    assert q(root, "SELECT checks_total, errors FROM audit_runs WHERE id=?", rid) == [(1, "boom")]
    assert q(root, "SELECT COUNT(*) FROM audit_findings WHERE run_id=? AND check_key='phone_bills'", rid)[0][0] == 1


def test_weekly_digest_task_runs_it(root):
    src = (root / "tasks" / "run_task.py").read_text(encoding="utf-8")
    body = src.split("def weekly_digest", 1)[1].split("\ndef ", 1)[0]
    assert '"data/audit.py", "run", "--weekly"' in body


@pytest.fixture()
def web(root, modules):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    auth, config = modules("auth"), modules("config")
    app_mod, sessions = modules("webapp.app"), modules("webapp.sessions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    yield c
    sessions.clear()


def _tok(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)


def test_settings_page_and_check_now(web, root):
    c = web
    if not q(root, "SELECT 1 FROM mobile_bills WHERE carrier='Audit Mobile'"):  # run alone (-k): plant what it reads
        _plant(root)
    assert c.get("/settings/audit").status_code == 303, "signed in only"
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    assert c.get("/settings/audit").status_code == 403
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    assert 'href="/settings/audit"' in c.get("/settings?group=data").text
    n = q(root, "SELECT COUNT(*) FROM audit_runs")[0][0]
    assert c.post("/settings/audit").status_code == 403, "CSRF token required"
    r = c.post("/settings/audit", headers={"X-CSRF-Token": _tok(c), "HX-Request": "true"})
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/settings/audit"
    assert q(root, "SELECT COUNT(*) FROM audit_runs")[0][0] == n + 1
    assert q(root, "SELECT actor FROM audit_runs ORDER BY id DESC LIMIT 1") == [("Ann",)]
    html = c.get("/settings/audit").text
    assert "Data check done." in html and "Data score" in html and "Audit Mobile bill of" in html
    assert "/records?ref=mobile_bills:" in html and "Every check" in html


ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


def test_safe_fix_fills_categories_and_undo_clears_them(root, modules):
    au, ea = modules("audit"), modules("edit_actions")
    with db(root) as con:
        con.execute("INSERT OR IGNORE INTO category_rules(pattern, category, payee_type, payee, priority) "
                    "VALUES ('AUDITRULE SHOP%', 'groceries', 'spend', 'Audit Shop', 1)")
        acc = con.execute("SELECT id FROM accounts WHERE name='Audit Checking'").fetchone()[0]
        tid = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) "
                          "VALUES (?, ?, 'AUDITRULE SHOP 12', -30)", (acc, _iso(-2))).lastrowid
        mine = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, category) "
                           "VALUES (?, ?, 'AUDITRULE SHOP 13', -31, 'gifts')", (acc, _iso(-2))).lastrowid
    rid = au.run("now")
    assert q(root, "SELECT category, payee, txn_type FROM transactions WHERE id=?", tid) == [("groceries", "Audit Shop", "spend")]
    assert q(root, "SELECT category FROM transactions WHERE id=?", mine) == [("gifts",)], "a person's category is never changed"
    fx = q(root, "SELECT id, action, done_by, run_id FROM audit_fixes WHERE action='categorize' ORDER BY id DESC LIMIT 1")[0]
    assert fx[1:] == ("categorize", "auto", rid)
    assert ea.audit_fix_undo(KID, fx[0])[0] is False
    ok, msg = ea.audit_fix_undo(ADULT, fx[0])
    assert ok, msg
    assert q(root, "SELECT category, payee, txn_type FROM transactions WHERE id=?", tid) == [(None, None, None)]
    assert ea.audit_fix_undo(ADULT, fx[0])[0] is False, "undone once only"
    au.run("now", fix=False)
    assert q(root, "SELECT category FROM transactions WHERE id=?", tid) == [(None,)], "fix=False changes nothing"
    with db(root) as con:  # the rule stays out of the other tests
        con.execute("UPDATE transactions SET category='groceries' WHERE id=?", (tid,))


def test_inbox_accept_remove_paid_keep_and_undo(root, modules):
    au, pr = modules("audit"), modules("proposals")
    with db(root) as con:
        cafe = [r[0] for r in con.execute("SELECT id FROM transactions WHERE description='CORNER CAFE' ORDER BY id")]
        con.execute("INSERT INTO receipts(merchant, receipt_date, total, transaction_id, created_at) "
                    "VALUES ('Corner Cafe', ?, 12.5, ?, '2026-01-01 00:00:00')",
                    (_iso(-5), cafe[1]))
    au.run("now")
    pr.sync()
    with db(root) as con:
        items = {it["payload"].get("fix"): it for it in pr.items(con) if it["source"] == "audit"}
    assert set(items) >= {"dupe_txn", "dupe_bill", "late_bill"}
    assert list(items["dupe_txn"]["options"]) == ["remove", "keep", "later"]
    assert list(items["late_bill"]["options"]) == ["paid", "keep", "later"]
    assert pr.decide(KID, items["dupe_txn"]["id"], "remove")[0] is False
    ok, msg = pr.decide(ADULT, items["dupe_txn"]["id"], "remove")
    assert ok, msg
    assert q(root, "SELECT id FROM transactions WHERE description='CORNER CAFE'") == [(cafe[0],)]
    assert q(root, "SELECT transaction_id FROM receipts WHERE merchant='Corner Cafe'") == [(cafe[0],)], "the receipt moves"
    fx = q(root, "SELECT id, done_by FROM audit_fixes WHERE action='remove_txns' ORDER BY id DESC LIMIT 1")[0]
    assert fx[1] == "Alex"
    assert pr.decide(ADULT, items["late_bill"]["id"], "paid")[0] is False, "needs the day it was paid"
    ok, msg = pr.decide(ADULT, items["late_bill"]["id"], "paid", date=_iso(-1))
    assert ok, msg
    assert q(root, "SELECT status, paid_date FROM bills WHERE name='Audit Water'") == [("paid", _iso(-1))]
    ok, _ = pr.decide(ADULT, items["dupe_bill"]["id"], "keep")
    assert ok and q(root, "SELECT COUNT(*) FROM bills WHERE name='Audit Gas'")[0][0] == 2
    ok, msg = modules("edit_actions").audit_fix_undo(ADULT, fx[0])
    assert ok, msg
    assert [r[0] for r in q(root, "SELECT id FROM transactions WHERE description='CORNER CAFE' ORDER BY id")] == cafe
    assert q(root, "SELECT transaction_id FROM receipts WHERE merchant='Corner Cafe'") == [(cafe[1],)], "the receipt goes back"
    assert q(root, "SELECT status FROM proposals WHERE id=?", items["dupe_txn"]["id"]) == [("open",)], "undo asks again"
    pr.decide(ADULT, items["dupe_txn"]["id"], "keep")
    au.run("now")
    pr.sync()
    with db(root) as con:
        left = {it["payload"].get("fix") for it in pr.items(con) if it["source"] == "audit"}
        st = dict(con.execute("SELECT dedupe_key, status FROM proposals WHERE source='audit'").fetchall())
    assert "dupe_bill" not in left, "Leave it as it is is remembered"
    assert "late_bill" not in left and not any(k.startswith("audit:bills:late:") and v == "open" for k, v in st.items())
    assert any(v == "dismissed" for k, v in st.items() if k.startswith("audit:duplicate_txns:")), "kept after the undo: not asked again"


def test_remove_copies_refuses_rows_that_changed(root, modules):
    ea = modules("edit_actions")
    with db(root) as con:
        a = con.execute("SELECT id FROM transactions WHERE description='TWIN COFFEE' ORDER BY id").fetchall()
    ok, msg = ea.audit_remove_copies(ADULT, "dupe_txn", [r[0] for r in a])
    assert ok is False and "changed" in msg, "different source references are not one charge"
    assert ea.audit_remove_copies(ADULT, "drop_table", [1, 2])[0] is False


def test_ai_explanation_is_checked_cached_and_shown(root, modules, web):
    import json as J

    from conftest import set_ai
    au, ax, dbm = modules("audit"), modules("audit_explain"), modules("db")
    ax.CACHE.unlink(missing_ok=True)
    rid = au.run("now")
    with dbm.open(readonly=True) as con:
        assert ax.explain(con) is None, "no AI set up: nothing"
    set_ai(root, "fake")
    fake = root / "config" / "fake_llm.json"
    try:
        with dbm.open(readonly=True) as con:
            first = ax._findings(con, rid)[0]
            fake.write_text(J.dumps({"summary": "You lost 999 dollars.", "items": [{"n": 1, "why": "Visit http://x.example"}]}),
                            encoding="utf-8")
            assert ax.explain(con) is None, "an invented number or a link is thrown away"
            fake.write_text(J.dumps({"summary": "One bill does not add up; look at it first.",
                                     "items": [{"n": 1, "why": "Usually a line was read twice."}, {"n": 99, "why": "x"}]}),
                            encoding="utf-8")
            x = ax.explain(con, force=True)
        assert x["summary"].startswith("One bill") and x["items"] == {first["dedupe_key"]: "Usually a line was read twice."}
        fake.write_text(J.dumps({"summary": "Changed."}), encoding="utf-8")
        with dbm.open(readonly=True) as con:
            assert ax.explain(con)["summary"].startswith("One bill"), "one answer per run"
        c = web
        c.post("/login", data={"name": "Ann", "pin": "1234"})
        html = c.get("/settings/audit").text
        assert "What this means" in html and "One bill does not add up" in html and "Usually a line was read twice." in html
        ax.CACHE.unlink(missing_ok=True)
        assert "Explain with AI" in c.get("/settings/audit").text
        fake.write_text(J.dumps({"summary": "One bill does not add up."}), encoding="utf-8")
        r = c.post("/settings/audit/explain", headers={"X-CSRF-Token": _tok(c), "HX-Request": "true"})
        assert r.headers["HX-Redirect"] == "/settings/audit" and ax.cached(rid)["summary"] == "One bill does not add up."
    finally:
        fake.unlink(missing_ok=True)
        set_ai(root, "none")
        ax.CACHE.unlink(missing_ok=True)


def test_score_in_the_weekly_digest_and_monthly_report(root):
    r = run(["data/make_digest.py"], root)
    assert r.returncode == 0, r.stderr[-800:]
    text = pathlib.Path(r.stdout.strip().splitlines()[-1]).read_text(encoding="utf-8")
    sec = text.split("## Data check", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"Data score \d+%", sec) and "Audit Mobile bill of" in sec
    assert "transaction ids" not in sec and "7777" not in sec, "summaries only: no ids or account numbers on Drive"
    month = TODAY.strftime("%Y-%m")
    r = run(["data/make_report.py", "monthly", month], root)
    assert r.returncode == 0, r.stderr[-800:]
    rep = (root / "reports" / f"{month}_monthly.md").read_text(encoding="utf-8")
    sec = rep.split("## Data check", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"Runs: \d+; score .*average \d+%", sec) and "Last run found:" in sec
    assert re.search(r"Fixes: \d+", sec) and re.search(r"Inbox decisions: \d+ fixed, \d+ left", sec)
