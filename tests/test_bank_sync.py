"""Bank sync through SimpleFIN Bridge (data/bank_sync.py): claiming the setup token, pulling with the statement
importer's dedupe, mapping SimpleFIN accounts onto `accounts` rows, a failed pull as one Inbox item, forget, and the
access URL never in any output. No network: urllib's urlopen is replaced."""
import base64
import datetime as dt
import io
import json
import urllib.error

from conftest import db, q, run

CLAIM_URL = "https://bridge.example.test/simplefin/claim/abc123"
TOKEN = base64.b64encode(CLAIM_URL.encode()).decode()
ACCESS = "https://sfuser-9f8e:sfsecret-7a6b5c@bridge.example.test/simplefin"
DAY = 1_760_000_000  # a fixed epoch second (2025-10) so the test does not depend on today
ACCOUNTS = [
    {"id": "ACT-chk", "name": "Everyday Checking ...4477", "currency": "USD", "balance": "1200.50", "balance-date": DAY,
     "org": {"name": "Test Bank", "domain": "bank.example.test"},
     "transactions": [
         {"id": "t1", "posted": DAY - 86400, "amount": "-45.10", "description": "GROCER 1", "pending": False},
         {"id": "t2", "posted": DAY - 2 * 86400, "amount": "2500.00", "description": "SALARY", "pending": False},
         {"id": "t3", "posted": DAY, "amount": "-9.99", "description": "PENDING COFFEE", "pending": True},
     ]},
    {"id": "ACT-card", "name": "Rewards Visa Credit Card (9911)", "currency": "USD", "balance": "-310.00", "balance-date": DAY,
     "org": {"name": "Test Bank"},
     "transactions": [{"id": "c1", "posted": DAY - 86400, "amount": "-310.00", "description": "SHOP", "pending": False}]},
]


class _Resp:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body


def fake_http(monkeypatch, bs, accounts=None, fail=None, access=ACCESS):
    """urlopen that answers the claim POST with the access URL and every GET with `accounts`. -> list of calls."""
    calls = []

    def urlopen(req, timeout=0):
        calls.append((req.get_method(), req.full_url, dict(req.header_items())))
        if fail is not None:
            raise fail
        if req.get_method() == "POST":
            return _Resp(access.encode())
        return _Resp(json.dumps({"errors": [], "accounts": accounts if accounts is not None else ACCOUNTS}).encode())
    monkeypatch.setattr(bs.urllib.request, "urlopen", urlopen)
    return calls


def _secrets(root):
    f = root / "config" / "secrets.env"
    return f.read_text(encoding="utf-8") if f.exists() else ""


def _clean(root, bs):
    con = db(root)
    con.execute("DELETE FROM transactions WHERE account_id IN (SELECT id FROM accounts WHERE name LIKE 'Everyday Checking%' OR name LIKE 'Rewards Visa%')")
    con.execute("DELETE FROM account_balances WHERE account_id IN (SELECT id FROM accounts WHERE name LIKE 'Everyday Checking%' OR name LIKE 'Rewards Visa%')")
    con.execute("DELETE FROM accounts WHERE name LIKE 'Everyday Checking%' OR name LIKE 'Rewards Visa%'")
    con.execute("DELETE FROM proposals WHERE source IN ('bank_sync', 'bank_dupe')")
    con.commit()
    con.close()
    bs.forget()


def test_setup_claims_the_token_once_and_keeps_the_access_url_write_only(root, modules, monkeypatch, capsys):
    bs = modules("bank_sync")
    _clean(root, bs)
    calls = fake_http(monkeypatch, bs)
    n = bs.setup(TOKEN)
    assert n == 2
    assert calls[0][0] == "POST" and calls[0][1] == CLAIM_URL and "Authorization" not in calls[0][2]
    get = calls[1]
    assert get[0] == "GET" and get[1].startswith("https://bridge.example.test/simplefin/accounts?") and "balances-only=1" in get[1]
    assert "sfsecret" not in get[1] and get[2]["Authorization"].startswith("Basic "), "the user info travels as a header, never in the URL"
    assert f"SIMPLEFIN_ACCESS_URL={ACCESS}" in _secrets(root)
    s = bs.status()
    assert s["configured"] and [a["id"] for a in s["accounts"]] == ["ACT-chk", "ACT-card"]
    assert s["accounts"][0] == {"id": "ACT-chk", "name": "Everyday Checking", "last4": "4477", "org": "Test Bank", "chosen": False}
    assert "sfsecret" not in json.dumps(s) and "sfsecret" not in (root / "config" / "bank_sync.json").read_text(encoding="utf-8")
    # a token that is not base64 of an https URL, or one SimpleFIN refuses
    for bad in ("", "not-a-token!", base64.b64encode(b"http://plain.example.test/claim").decode()):
        try:
            bs.claim(bad)
            raise AssertionError(bad)
        except bs.BankError as e:
            assert "sfsecret" not in str(e)
    fake_http(monkeypatch, bs, access="https://bridge.example.test/simplefin")  # no user info = unusable
    try:
        bs.claim(TOKEN)
        raise AssertionError("an access URL without a password was accepted")
    except bs.BankError:
        pass
    assert bs.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "set up: yes" in out and "Everyday Checking x4477" in out and "sfsecret" not in out and "sfuser" not in out


def test_pull_maps_accounts_dedupes_and_runs_the_after_import_steps(root, modules, monkeypatch):
    bs = modules("bank_sync")
    _clean(root, bs)
    fake_http(monkeypatch, bs)
    bs.setup(TOKEN)
    con = db(root)
    con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Everyday Checking', 'checking', '4477')")
    con.commit()
    before = con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    con.close()
    rep = bs.pull()
    assert rep["accounts"] == [] and rep["inserted"] == 0, "nothing is pulled until an account is ticked"
    assert q(root, "SELECT COUNT(*) FROM accounts")[0][0] == before, "untracked accounts are not created"
    assert bs.choose(["ACT-chk", "nope"]) == 1
    rep = bs.pull()
    assert rep["inserted"] == 2 and rep["skipped"] == 0 and rep["accounts"][0]["last4"] == "4477"
    assert q(root, "SELECT COUNT(*) FROM accounts")[0][0] == before, "matched by last4 + name, no new row"
    acct = q(root, "SELECT id, simplefin_id FROM accounts WHERE last4='4477'")[0]
    assert acct[1] == "ACT-chk"
    rows = q(root, "SELECT description, amount, ref FROM transactions WHERE account_id=? ORDER BY txn_date", acct[0])
    assert rows == [("SALARY", 2500.0, "sfin:t2"), ("GROCER 1", -45.1, "sfin:t1")], "the pending one is left out"
    assert q(root, "SELECT balance, kind FROM account_balances WHERE account_id=?", acct[0]) == [(1200.5, "snapshot")]
    rep = bs.pull()
    assert rep["inserted"] == 0 and rep["skipped"] == 2, "a second pull of the same days adds nothing"
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE account_id=?", acct[0])[0][0] == 2
    st = bs.status()
    assert st["last_ok"] and not st["error"] and st["last"] == {"inserted": 0, "skipped": 2, "warnings": []}
    # the card is new to the family: created with the right type, the owed amount stored positive
    bs.choose(["ACT-chk", "ACT-card"])
    rep = bs.pull()
    card = q(root, "SELECT id, type, last4, simplefin_id FROM accounts WHERE name='Rewards Visa Credit Card'")
    assert len(card) == 1 and card[0][1:] == ("credit", "9911", "ACT-card")
    assert q(root, "SELECT balance FROM account_balances WHERE account_id=?", card[0][0]) == [(310.0,)]
    assert rep["inserted"] == 1 and {r["name"] for r in rep["accounts"]} == {"Everyday Checking", "Rewards Visa Credit Card"}
    assert q(root, "SELECT COUNT(*) FROM proposals WHERE source='bank_sync' AND status='open'")[0][0] == 0


def test_failed_pull_is_one_inbox_item_and_the_secret_stays_out_of_everything(root, modules, monkeypatch):
    bs = modules("bank_sync")
    pr = modules("proposals")
    _clean(root, bs)
    fake_http(monkeypatch, bs)
    bs.setup(TOKEN)
    bs.choose(["ACT-chk"])
    err = urllib.error.HTTPError(ACCESS + "/accounts", 403, "Forbidden sfsecret-7a6b5c", {}, io.BytesIO(b""))
    fake_http(monkeypatch, bs, fail=err)
    for _ in range(2):
        try:
            bs.pull()
            raise AssertionError("a 403 was not reported")
        except bs.BankError as e:
            assert "403" in str(e) and "sfsecret" not in str(e) and ACCESS not in str(e)
        con = db(root)
        pr.sync(con)
        con.close()
    rows = q(root, "SELECT summary, detail, status FROM proposals WHERE source='bank_sync'")
    assert len(rows) == 1 and rows[0][0] == "Bank sync did not work" and rows[0][2] == "open" and "403" in rows[0][1]
    assert "sfsecret" not in rows[0][1]
    state = (root / "config" / "bank_sync.json").read_text(encoding="utf-8")
    assert "403" in state and "sfsecret" not in state and "sfuser" not in state
    health = modules("health")
    row = next(r for r in health.checks() if r["name"] == "Bank sync")
    assert row["status"] == "warn" and "403" in row["note"] and "sfsecret" not in row["note"]
    # a reachable bridge again: the item expires, the health row is green
    fake_http(monkeypatch, bs)
    bs.pull()
    con = db(root)
    pr.sync(con)
    con.close()
    assert q(root, "SELECT status FROM proposals WHERE source='bank_sync'") == [("expired",)]
    row = next(r for r in health.checks() if r["name"] == "Bank sync")
    assert row["status"] == "ok"
    # the command line never prints the URL either
    r = run(["data/bank_sync.py", "status"], root)
    assert r.returncode == 0 and "sfsecret" not in r.stdout + r.stderr and "set up: yes" in r.stdout
    r = run(["data/bank_sync.py", "setup"], root)
    assert r.returncode == 1 and "usage" in r.stderr


def test_forget_removes_the_secret_and_the_ids_but_keeps_the_rows(root, modules, monkeypatch):
    bs = modules("bank_sync")
    _clean(root, bs)
    fake_http(monkeypatch, bs)
    bs.setup(TOKEN)
    bs.choose(["ACT-chk"])
    bs.pull()
    assert q(root, "SELECT COUNT(*) FROM accounts WHERE simplefin_id IS NOT NULL")[0][0] == 1
    bs.forget()
    assert "SIMPLEFIN_ACCESS_URL=\n" in _secrets(root) or "SIMPLEFIN_ACCESS_URL=" not in _secrets(root)
    assert ACCESS not in _secrets(root)
    assert q(root, "SELECT COUNT(*) FROM accounts WHERE simplefin_id IS NOT NULL")[0][0] == 0
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE ref IN ('sfin:t1', 'sfin:t2')")[0][0] == 2
    assert not (root / "config" / "bank_sync.json").exists()
    s = bs.status()
    assert not s["configured"] and s["accounts"] == []
    assert not [r for r in modules("health").checks() if r["name"] == "Bank sync"]
    try:
        bs.pull()
        raise AssertionError("pull without a URL")
    except bs.BankError as e:
        assert "not set up" in str(e)


def test_names_and_kinds(modules):
    bs = modules("bank_sync")
    assert bs.split_name("Everyday Checking ...4477") == ("Everyday Checking", "4477")
    assert bs.split_name("Rewards Visa (9911)") == ("Rewards Visa", "9911")
    assert bs.split_name("Card x1234") == ("Card", "1234")
    assert bs.split_name("Plain Savings") == ("Plain Savings", "")
    assert bs.split_name("1234") == ("1234", "")
    assert [bs.kind_of(n) for n in ("Rewards Visa", "Home Mortgage", "Roth IRA", "Rainy day savings", "Everyday")] == \
        ["credit", "loan", "investment", "savings", "checking"]


def test_no_plan_needed(root, modules, monkeypatch):
    """Bank sync is free: no plan flag in family.json, the card shows and setup + pull run."""
    bs = modules("bank_sync")
    _clean(root, bs)
    assert "plan" not in modules("config").family()
    assert not hasattr(modules("config"), "plan_is_pro")
    assert [t for t in modules("settings_data").connections() if t[0].startswith("Bank sync")]
    fake_http(monkeypatch, bs)
    bs.setup(TOKEN)
    bs.choose(["ACT-chk"])
    bs.pull()
    assert bs.configured()


def _at(d):
    """Epoch seconds at noon local time on date d (how SimpleFIN's `posted` reads back as that date)."""
    return int(dt.datetime(d.year, d.month, d.day, 12).timestamp())


def test_statement_rows_and_bank_rows_are_one_transaction(root, modules, monkeypatch, tmp_path):
    """Overlap with statements: days a statement covers are skipped, a single same-amount row within 3 days is the same
    payment (both directions), two candidates = added + one Inbox item, and `dedupe` cleans up older copies."""
    bs = modules("bank_sync")
    im = modules("import_statement")
    pr = modules("proposals")
    _clean(root, bs)
    assert bs.DAYS_BACK == 45, "SimpleFIN recommends at most 45 days a request"
    d0 = dt.date(2025, 9, 20)
    day = lambda n: (d0 + dt.timedelta(days=n)).isoformat()  # noqa: E731
    con = db(root)
    aid = con.execute("INSERT INTO accounts(name, type, last4) VALUES ('Everyday Checking', 'checking', '4477')").lastrowid
    for when, desc, amt in ((0, "GROCER ONE STORE 12", -45.10), (0, "COFFEE A", -5.00), (-1, "COFFEE B", -5.00), (-3, "RENT", -20.00)):
        con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)", (aid, day(when), desc, amt))
    con.commit()
    con.close()
    sf = [{"id": "ACT-chk", "name": "Everyday Checking ...4477", "currency": "USD", "balance": "100", "balance-date": _at(d0),
           "org": {"name": "Test Bank"}, "transactions": [
               {"id": "s1", "posted": _at(d0), "amount": "-20.00", "description": "ON THE STATEMENT DAY"},
               {"id": "s2", "posted": _at(d0 + dt.timedelta(days=2)), "amount": "-45.10", "description": "GROCER 1"},
               {"id": "s3", "posted": _at(d0 + dt.timedelta(days=2)), "amount": "-5.00", "description": "COFFEE"},
               {"id": "s4", "posted": _at(d0 + dt.timedelta(days=5)), "amount": "-7.77", "description": "SHOP 7"}]}]
    fake_http(monkeypatch, bs, accounts=sf)
    bs.setup(TOKEN)
    bs.choose(["ACT-chk"])
    rep = bs.pull()
    assert (rep["inserted"], rep["skipped"]) == (2, 2), rep
    got = q(root, "SELECT ref FROM transactions WHERE account_id=? AND ref LIKE 'sfin:%' ORDER BY ref", aid)
    assert got == [("sfin:s3",), ("sfin:s4",)], "s1 is covered by the statement, s2 is the statement's GROCER row"
    assert bs.pull()["inserted"] == 0, "a repeat pull adds nothing"
    # s3 had two statement coffees within 3 days: added, and the Inbox asks once
    con = db(root)
    pr.sync(con)
    con.close()
    items = q(root, "SELECT id, summary, payload FROM proposals WHERE source='bank_dupe' AND status='open'")
    assert len(items) == 1 and "Possible duplicate" in items[0][1] and "Everyday Checking" in items[0][1]
    s3 = q(root, "SELECT id FROM transactions WHERE ref='sfin:s3'")[0][0]
    assert json.loads(items[0][2]) == {"txn_id": s3}
    assert pr.decide({"name": "Kid", "role": "limited"}, items[0][0], "remove")[0] is False
    ok, msg = pr.decide({"name": "Tester", "role": "adult"}, items[0][0], "remove")
    assert ok, msg
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE ref='sfin:s3'")[0][0] == 0
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE account_id=? AND amount=-5.0", aid)[0][0] == 2, "both statement coffees stay"
    # a statement imported after bank sync: the row bank sync already has is skipped, a new one is added
    csv_file = tmp_path / "later.csv"
    csv_file.write_text("\n".join(["Date,Description,Amount", f"{day(4)},SHOP 7 PURCHASE,-7.77", f"{day(6)},NEW THING,-3.00", ""]),
                        encoding="utf-8")
    r = im.run_import(csv_file, "4477", sign="as-is", apply_rules=False)
    assert (r["inserted"], r["skipped"]) == (1, 1), r
    # older copies (pulled before this check existed) are found and cleaned up by `dedupe`
    con = db(root)
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, ref, category) VALUES (?,?,?,?,?,?)",
                (aid, day(10), "OLD COPY", -99.99, "sfin:old", "groceries"))
    tw = con.execute("INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?,?,?,?)",
                     (aid, day(11), "OLD STATEMENT ROW", -99.99)).lastrowid
    con.commit()
    con.close()
    found = bs.dedupe()
    assert [d["description"] for d in found] == ["OLD COPY"] and found[0]["twins"] == [tw]
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE ref='sfin:old'")[0][0] == 1, "a dry run changes nothing"
    found = bs.dedupe(apply=True)
    assert found[0]["removed"] is True
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE ref='sfin:old'")[0][0] == 0
    assert q(root, "SELECT category FROM transactions WHERE id=?", tw) == [("groceries",)], "the category moves over"
    assert bs.dedupe() == []


def test_a_pull_never_asks_further_back_than_45_days(root, modules, monkeypatch):
    bs = modules("bank_sync")
    _clean(root, bs)
    fake_http(monkeypatch, bs)
    bs.setup(TOKEN)
    asked = []
    real = bs.fetch
    monkeypatch.setattr(bs, "fetch", lambda start=None: asked.append(start) or real(start=start))
    today = dt.date(2026, 10, 17)
    bs.pull(today=today)
    st = bs.state()
    st["last_ok"] = "2026-06-01T07:00:00"  # a long gap since the last good pull
    bs._save(st)
    bs.pull(today=today)
    assert asked == [today - dt.timedelta(days=45)] * 2


def test_a_relink_takes_over_the_account_with_the_stale_link_not_a_new_row(root, modules, monkeypatch):
    """Signing in to the bank again at SimpleFIN gives its accounts new ids. The old row (history, stale id) is
    re-linked; a row whose id the bridge still sends is never taken."""
    bs = modules("bank_sync")
    _clean(root, bs)
    fake_http(monkeypatch, bs)
    bs.setup(TOKEN)
    con = db(root)
    con.execute("INSERT INTO accounts(name, type, last4, simplefin_id) VALUES ('Everyday Checking', 'checking', '4477', 'ACT-OLD')")
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, ref) "
                "SELECT id, '2025-01-05', 'OLD LINE', -1, 'keep:1' FROM accounts WHERE last4='4477'")
    con.commit()
    before = con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    con.close()
    bs.choose(["ACT-chk"])
    rep = bs.pull()
    assert rep["accounts"][0]["name"] == "Everyday Checking" and rep["inserted"] == 2
    assert q(root, "SELECT COUNT(*) FROM accounts")[0][0] == before, "no empty copy after a re-link"
    assert q(root, "SELECT simplefin_id FROM accounts WHERE last4='4477'") == [("ACT-chk",)]
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE ref='keep:1'")[0][0] == 1, "the history stays on that row"
    # an id the bridge still sends is not stale: a second SimpleFIN account with the same last4 gets its own row
    twin = dict(ACCOUNTS[0], id="ACT-twin", name="Joint Checking ...4477", transactions=[])
    fake_http(monkeypatch, bs, accounts=[ACCOUNTS[0], twin])
    bs.pull()  # the bridge's list is remembered, so the twin can be ticked
    bs.choose(["ACT-chk", "ACT-twin"])
    bs.pull()
    assert q(root, "SELECT COUNT(*) FROM accounts WHERE last4='4477'")[0][0] == 2
    assert q(root, "SELECT simplefin_id FROM accounts WHERE last4='4477' ORDER BY id") == [("ACT-chk",), ("ACT-twin",)]
