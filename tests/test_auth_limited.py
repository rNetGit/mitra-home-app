"""Per-person logins and the kids view: PIN hashing, and the invariant that a limited user never sees money."""
import re


from conftest import db, read_family, run, write_family

MONEY_WORDS = ("amount", "balance", "account", "last4", "premium", "cost", "price", "salary", "income")


def test_pin_hash_verifies_and_hides_the_pin(modules):
    auth = modules("auth")
    h = auth.hash_pin("1234")
    assert auth.verify_pin(h, "1234") and not auth.verify_pin(h, "9999")
    assert "1234" not in h
    assert auth.hash_pin("1234") != h, "salted"


def test_set_user_persists_to_family_json(root, modules):
    auth = modules("auth")
    auth.set_user("Alex", "adult", "2468")
    auth.set_user("Sam", "limited", "1357")
    users = {u["name"]: u for u in read_family(root)["dashboard_users"]}
    assert users["Sam"]["role"] == "limited" and "1357" not in users["Sam"]["pin_hash"]
    assert auth.login("Sam", "1357") and not auth.login("Sam", "0000")
    fam = read_family(root)
    fam.pop("dashboard_users", None)
    write_family(root, fam)


def test_limited_view_shows_only_safe_domains_and_no_money(root, modules):
    lv = modules("limited_view")
    run(["data/life.py", "add", "chore", "Feed Biscuit", "--who", "Sam", "--due", "2099-01-01"], root)
    run(["data/life.py", "add", "legal", "Will review", "--who", "Sam", "--due", "2099-01-02"], root)
    con = db(root)
    con.execute("INSERT INTO life_items(domain, title, member, due_date, amount, status) VALUES ('school', 'Trip money', 'Sam', '2099-01-03', 45, 'open')")
    con.commit()
    con.close()
    d = lv.data("Sam", db=root / "data" / "family.db")
    assert any("Feed Biscuit" in r["title"] for r in d["mine"])
    assert not any("Will review" in r["title"] for r in d["mine"] + d["week"])
    for row in d["mine"] + d["week"]:
        assert row["domain"] in lv.SAFE_DOMAINS
        assert not any(w in k.lower() for k in row for w in MONEY_WORDS), row
    assert not (set(lv.SAFE_DOMAINS) & {"bill", "loan", "insurance", "tax", "legal", "finance"})


def test_limited_view_source_never_touches_money_tables(root):
    src = (root / "data" / "limited_view.py").read_text(encoding="utf-8")
    for table in ("bills", "transactions", "accounts", "loans", "policies", "budget", "subscriptions", "investments"):
        assert not re.search(rf"\bFROM\s+{table}\b", src, re.I), table
    assert "readonly=True" in src, "kids view opens the database read-only"
    assert "llm" not in src, "no AI in the kids view"


def test_login_throttle_is_file_backed_and_escalates(root, modules):
    auth = modules("auth")
    auth.clear_failures("Alex")
    auth.clear_failures("*")
    now = 1_000_000.0
    assert auth.locked_for("Alex", now) == 0
    for _ in range(4):
        assert auth.record_failure("Alex", now) == 0
    assert auth.record_failure("Alex", now) == 30, "fifth wrong PIN locks for 30 s"
    assert auth.locked_for("Alex", now + 1) == 29
    assert auth.locked_for("Alex", now + 31) == 0
    assert (root / "logs" / "login_throttle.json").exists(), "the count lives in a file, not in the browser session"
    for _ in range(5):
        auth.record_failure("Alex", now + 40)
    assert auth.locked_for("Alex", now + 41) == 59, "second lock is longer (60 s)"
    assert auth.locked_for("Sam", now + 41) == 0, "another name is not locked yet"
    auth.clear_failures("Alex")
    assert auth.locked_for("Alex", now + 41) == 0
    for _ in range(15):
        auth.record_failure("Guess", now + 50)
    assert auth.locked_for("Sam", now + 51) > 0, "many failures across names lock everyone"
    auth.clear_failures("Guess")
    auth.clear_failures("*")
    (root / "logs" / "login_throttle.json").write_text("not json", encoding="utf-8")
    assert auth.locked_for("Alex") == 0, "a damaged throttle file never locks people out"
    (root / "logs" / "login_throttle.json").unlink()


def test_pairing_failures_stay_off_the_all_names_lock_and_old_locks_fade(modules):
    """Audit M2: wrong pairing codes cannot lock PIN sign-in; a lock count starts over after an hour of quiet."""
    auth = modules("auth")
    auth.clear_failures("#phones")
    auth.clear_failures("*")
    now = 2_000_000.0
    for _ in range(40):
        auth.record_failure("#phones", now, everyone=False)
    assert auth.locked_for("#phones", now + 1, everyone=False) > 0, "pairing itself is throttled"
    assert auth.locked_for("Ann", now + 1) == 0, "but nobody's PIN sign-in is"
    auth.clear_failures("Zed")
    for _ in range(5):
        auth.record_failure("Zed", now)
    for _ in range(5):
        auth.record_failure("Zed", now + 40)
    assert auth.locked_for("Zed", now + 41) == 59, "second lock is 60 s"
    later = now + 40 + 60 + auth.LOCK_MEMORY + 1
    for _ in range(5):
        last = auth.record_failure("Zed", later)
    assert last == 30, "after an hour of quiet the lock starts at the shortest length again"



def test_a_device_on_the_wifi_gets_steeper_locks_and_cannot_lock_this_pc(modules):
    """Audit S2: wrong PINs from another device also count on its address (5 min, 15 min, 1 h, 6 h, 24 h), however
    it switches names; this PC never trips the all-names lock."""
    auth = modules("auth")
    for k in ("Ann", "Bob", "*", "@10.0.0.9"):
        auth.clear_failures(k)
    now = 3_000_000.0
    for i in range(5):
        auth.record_failure(["Ann", "Bob"][i % 2], now, source="10.0.0.9")
    assert auth.locked_for("Cy", now + 1, source="10.0.0.9") >= 299, "the device waits five minutes"
    assert auth.locked_for("Cy", now + 1, source="10.0.0.7") == 0, "another device does not"
    for _ in range(5):
        auth.record_failure("Ann", now + 400, source="10.0.0.9")
    assert auth.locked_for("Cy", now + 401, source="10.0.0.9") >= 899, "the second lock is fifteen minutes"
    for _ in range(20):
        auth.record_failure("Dee", now + 2000, source="10.0.0.8")
    assert auth.locked_for("Ann", now + 2001) > 0, "a device guessing many times locks the all-names counter"
    assert auth.locked_for("Ann", now + 2001, everyone=False) == 0, "but sign-in on this PC is not held by it"
    for k in ("Ann", "Bob", "Dee", "*", "@10.0.0.9", "@10.0.0.8"):
        auth.clear_failures(k)


def test_a_burst_of_parallel_guesses_is_counted_guess_by_guess(root, modules):
    """audit 2026-10-28: the lock was checked before the slow hash and the counter file had no lock, so 40 guesses sent
    at once all passed the check and most failures overwrote each other"""
    import threading
    auth = modules("auth")
    fam = read_family(root)
    auth.set_user("Alex", "adult", "2468")
    for key in ("Alex", "*", "@10.0.0.9"):
        auth.clear_failures(key)
    results = []

    def guess(i):
        results.append(auth.attempt("Alex", f"{1000 + i}", everyone=True, source="10.0.0.9"))
    threads = [threading.Thread(target=guess, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    checked = [r for r in results if not r[1]]
    assert len(checked) == auth.FAILS_BEFORE_LOCK, "only the guesses before the lock reach the PIN check"
    assert sum(1 for r in results if r[1]) == 40 - auth.FAILS_BEFORE_LOCK, "the rest are told to wait"
    assert auth.locked_for("Alex") > 0 and auth.locked_for("x", source="10.0.0.9") > 0
    u, wait, _ = auth.attempt("Alex", "2468")
    assert u is None and wait, "even the right PIN waits out the lock"
    for key in ("Alex", "*", "@10.0.0.9"):
        auth.clear_failures(key)
    assert auth.attempt("Alex", "2468")[0]["name"] == "Alex"
    write_family(root, fam)
