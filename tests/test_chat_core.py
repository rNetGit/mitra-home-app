"""Chat core for the phone bots (migration 033 + data/chat_core.py): pairing codes (hashed, single use, expiry,
platform lock, throttle), strangers get silence, roles (limited = no money ever), money only in private chats,
the log never holds message text, revoke/unlink, purge, CLI."""
import datetime as D

import pytest

from conftest import q, run

NOW = D.datetime(2026, 10, 9, 9, 0, 0)
TODAY = NOW.date()


@pytest.fixture(scope="module")
def C(root, modules):
    return modules("chat_core")


@pytest.fixture(scope="module")
def con(C, root):
    c = C._con(root / "data" / "family.db")
    yield c
    c.close()


@pytest.fixture(scope="module")
def money_bill(root):
    """A bill due in 3 days with an amount, so adult replies have something to hide or show."""
    from conftest import db
    c = db(root)
    c.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Electric','ZapPower',123.45,?, 'due')",
              ((TODAY + D.timedelta(days=3)).isoformat(),))
    c.commit()
    c.close()


def H(C, root, uid, text, private=True, platform="telegram", now=NOW):
    return C.handle(platform, uid, text, private=private, today=now.date(), db=root / "data" / "family.db", now=now)


def link(C, con, root, name, uid, platform="telegram", **kw):
    code, *_ = C.invite(con, name, platform=platform, now=NOW, **kw)
    return H(C, root, uid, f"/start {code}", platform=platform)


def test_tables_exist(root):
    names = {r[0] for r in q(root, "select name from sqlite_master where type='table'")}
    assert {"chat_links", "chat_invites", "chat_log"} <= names


def test_invite_stores_only_hash_and_defaults_role(C, con, root):
    code, member, role, exp = C.invite(con, "sam", now=NOW)
    assert member == "Sam" and role == "limited" and len(code) == 8 and code.isdigit()
    assert exp == "2026-10-09T09:15:00"
    rows = q(root, "select code_hash from chat_invites where member='Sam'")
    assert all(code not in r[0] for r in rows) and rows[-1][0] == C._hash(code)
    assert C.invite(con, "Alex", now=NOW)[2] == "adult"


def test_invite_uses_stored_role_for_members_not_in_family_json(C, con):
    """members.py add (not family.json) must still give an adult an adult link; anything else stays limited."""
    con.execute("INSERT INTO members(name, role) VALUES ('Dbadult','adult'), ('Dbkid','child')")
    con.commit()
    assert C.invite(con, "Dbadult", now=NOW)[2] == "adult"
    assert C.invite(con, "Dbkid", now=NOW)[2] == "limited"


@pytest.mark.parametrize("bad", ["Nobody", "Biscuit"])  # unknown, pet
def test_invite_refuses_non_members(C, con, bad):
    with pytest.raises(ValueError):
        C.invite(con, bad, now=NOW)


def test_invite_validates_role_platform_minutes(C, con):
    for kw in ({"role": "admin"}, {"platform": "whatsapp"}, {"minutes": 0}, {"minutes": 61}):
        with pytest.raises(ValueError):
            C.invite(con, "Alex", now=NOW, **kw)


def test_stranger_gets_silence_and_is_logged(C, root):
    assert H(C, root, "999", "/due") is None
    assert H(C, root, "999", "hello") is None
    assert H(C, root, "999", "") is None
    rows = q(root, "select member, command, outcome from chat_log where platform_user_id='999'")
    assert rows and all(r[0] is None and r[2] == "unknown_user" for r in rows)


def test_code_single_use_and_newer_code_replaces_older(C, con, root):
    old, *_ = C.invite(con, "Sam", now=NOW)
    new, *_ = C.invite(con, "Sam", now=NOW)
    assert "did not work" in H(C, root, "501", f"/start {old}")
    assert "you're linked" in H(C, root, "501", f"/start {new}")
    assert "did not work" in H(C, root, "502", f"/start {new}")  # used
    assert C.identify(con, "telegram", "501")["member"] == "Sam"
    assert C.identify(con, "telegram", "502") is None


def test_code_expires(C, con, root):
    code, *_ = C.invite(con, "Alex", minutes=1, now=NOW)
    assert "did not work" in H(C, root, "503", f"/start {code}", now=NOW + D.timedelta(minutes=2))


def test_code_platform_lock(C, con, root):
    code, *_ = C.invite(con, "Alex", platform="discord", now=NOW)
    assert "did not work" in H(C, root, "504", f"/start {code}", platform="telegram")
    assert "you're linked" in H(C, root, "504", f"/start {code}", platform="discord")


def test_code_refused_in_group(C, con, root):
    code, *_ = C.invite(con, "Alex", now=NOW)
    assert "private chat" in H(C, root, "505", f"/start {code}", private=False)
    assert C.identify(con, "telegram", "505") is None


def test_bad_code_throttle(C, con, root):
    for _ in range(C.MAX_BAD_CODES):
        assert "did not work" in H(C, root, "506", "/start 00000000")
    code, *_ = C.invite(con, "Alex", now=NOW)
    assert H(C, root, "506", f"/start {code}") is None  # throttled even with a good code
    assert C.identify(con, "telegram", "506") is None
    later = NOW + D.timedelta(hours=1, minutes=1)
    code, *_ = C.invite(con, "Alex", now=later)
    assert "you're linked" in H(C, root, "506", f"/start {code}", now=later)


def test_limited_never_sees_money(C, con, root, money_bill):
    link(C, con, root, "Sam", "601")
    for txt, private in (("/due", True), ("/week", True), ("/due", False)):
        r = H(C, root, "601", txt, private=private)
        assert "ZapPower" not in r and "$" not in r and "123.45" not in r
    assert "no money" in H(C, root, "601", "/whoami")
    assert "/due" in H(C, root, "601", "/help")


def test_limited_cannot_be_upgraded_by_role_in_text(C, con, root):
    link(C, con, root, "Sam", "602")
    assert "don't know" in H(C, root, "602", "/role adult")
    assert C.identify(con, "telegram", "602")["role"] == "limited"


def test_adult_private_shows_money_group_hides_it(C, con, root, money_bill):
    link(C, con, root, "Alex", "701")
    p = H(C, root, "701", "/due")
    assert "ZapPower" in p and "$123.45" in p and "in 3d" in p
    g = H(C, root, "701", "/due", private=False)
    assert "ZapPower" not in g and "$" not in g and "money item" in g
    w = H(C, root, "701", "/week")  # family calendar view: no money even in private
    assert "ZapPower" not in w


def test_telegram_botname_suffix_and_bang_prefix(C, con, root):
    link(C, con, root, "Alex", "702")
    assert "You are Alex" in H(C, root, "702", "/whoami@Mitra HomeBot")
    assert "You are Alex" in H(C, root, "702", "!whoami", platform="telegram")


def test_log_has_no_message_text(C, con, root):
    link(C, con, root, "Alex", "703")
    H(C, root, "703", "/due secret-words-here")
    H(C, root, "999", "my ssn is 123-45-6789")
    dump = " ".join(str(c) for r in q(root, "select * from chat_log") for c in r)
    assert "secret-words" not in dump and "123-45-6789" not in dump and "ssn" not in dump


def test_unlink_and_revoke(C, con, root):
    link(C, con, root, "Alex", "801")
    assert "Unlinked" in H(C, root, "801", "/unlink")
    assert H(C, root, "801", "/due") is None
    link(C, con, root, "Sam", "802")
    link(C, con, root, "Sam", "803", platform="discord")
    assert C.revoke(con, "sam", now=NOW) >= 2
    assert H(C, root, "802", "/due") is None and H(C, root, "803", "/due", platform="discord") is None


def test_relink_same_account_replaces_link(C, con, root):
    link(C, con, root, "Alex", "804")
    link(C, con, root, "Sam", "804")
    assert C.identify(con, "telegram", "804") == {**C.identify(con, "telegram", "804"), "member": "Sam", "role": "limited"}
    assert q(root, "select count(*) from chat_links where platform_user_id='804' and revoked_at is null")[0][0] == 1


def test_unknown_platform_refused(C, root):
    with pytest.raises(ValueError):
        H(C, root, "1", "/due", platform="whatsapp")


def test_cli_invite_links_try(root):
    r = run(["data/chat_core.py", "invite", "Alex", "--platform", "telegram"], root)
    assert r.returncode == 0, r.stderr
    code = r.stdout.split("Code for Alex (adult): ")[1].split()[0]
    r = run(["data/chat_core.py", "try", "telegram", "9001", "/start", code], root)
    assert "you're linked" in r.stdout
    assert "Alex" in run(["data/chat_core.py", "links"], root).stdout
    assert "(no reply)" in run(["data/chat_core.py", "try", "telegram", "9002", "/due"], root).stdout
    assert run(["data/chat_core.py", "invite", "Nobody"], root).returncode == 2
    assert "linked" in run(["data/chat_core.py", "log"], root).stdout


def test_purge_person_plans_chat_rows(root, modules):
    P = modules("purge")
    from conftest import db
    c = db(root)
    try:
        delete, clear, *_ = P.person_plan(c, "Sam")
    finally:
        c.close()
    assert "chat_links" in delete and "chat_invites" in delete and "chat_log" in clear
