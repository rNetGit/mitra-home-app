"""Privacy mode (data/privacy.py): stars instead of money totals, balances and dates of birth, set per sign-in, from the
household default; the figure must be absent from the rendered HTML while private and present after Easy access."""
import re

import pytest
from fastapi.testclient import TestClient

from conftest import db

BALANCE = "48,271.59"          # a distinctive bank balance
LINE = "43.21"                 # one transaction line: stays visible
STARS = "*****"


@pytest.fixture(scope="module")
def world(root, modules):
    con = db(root)
    aid = con.execute("INSERT INTO accounts(name, type, subtype, last4) VALUES ('Privacy Savings','savings','savings','7777')").lastrowid
    con.execute("INSERT INTO account_balances(account_id, as_of, balance, kind) VALUES (?,?,?,?)",
                (aid, "2026-11-13", 48271.59, "snapshot"))
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, txn_type, category) VALUES (?,?,?,?,?,?)",
                (aid, "2026-11-12", "Hardware store", -43.21, "spend", "Home"))
    con.commit()
    sid = con.execute("SELECT id FROM members WHERE birth_month_day='03-14' LIMIT 1").fetchone()
    con.close()
    auth, config, sessions = modules("auth"), modules("config"), modules("webapp.sessions")
    app_mod = modules("webapp.app")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["privacy"] = {"on_signin": True}
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    yield {"member": sid[0] if sid else None, "mk": lambda: TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False),
           "root": root, "config": config, "sessions": sessions}
    sessions.clear()


def _login(world, name="Ann", pin="1234"):
    c = world["mk"]()
    assert c.post("/login", data={"name": name, "pin": pin}).status_code == 303
    return c


def _token(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)


def _toggle(c, on):
    return c.post("/privacy", data={"on": "1" if on else "0"}, headers={"X-CSRF-Token": _token(c)})


# ---- the helper ---------------------------------------------------------------------------------------------------
def test_mask_helpers(modules):
    p = modules("privacy")
    assert p.fmt(1234.5) == "$1,234.50", "off outside a request"
    tok = p.set_current(True)
    try:
        assert p.fmt(1234.5) == STARS and p.hide("Mar 14") == STARS and p.mask_filter("Mar 14") == STARS
        assert p.mask_filter("") == "" and p.mask_filter(None) is None, "nothing to hide stays empty"
        assert p.money_filter(0)(99) == STARS and p.raw_filter(2)(99) == "$99.00", "a transaction line is not masked"
        assert p.mask_text("paid $1,200.50 and -$30 on Friday") == f"paid {STARS} and {STARS} on Friday"
        assert p.field("birth month day", "03-14") == STARS and p.field("balance", 5) == STARS and p.field("name", "Ann") == "Ann"
        assert p.hidden_col("birth_year") and not p.hidden_col("amount")
    finally:
        p.reset(tok)
    assert p.fmt(5, 0) == "$5" and p.hide("x") == "x"


def test_who_is_private(modules):
    p = modules("privacy")
    adult, kid = {"name": "Ann", "role": "adult"}, {"name": "Kid", "role": "limited"}
    assert p.effective({"private": True}, adult) and not p.effective({"private": False}, adult)
    assert p.effective({"private": False}, kid), "a limited person is always private"
    assert not p.effective({"private": True, "open": True}, adult), "nobody has a PIN: open on this PC, nothing to hide from"
    assert not p.effective(None, adult) and not p.effective({"private": True}, None)


# ---- pages --------------------------------------------------------------------------------------------------------
def test_new_sign_in_starts_private_and_toggles(world):
    c = _login(world)
    html = c.get("/money?part=books").text
    assert BALANCE not in html and "48,271" not in html and "Privacy Savings" in html and STARS in html
    assert "Privacy mode." in html and "Easy access" in html, "a visible indicator while private"
    assert BALANCE not in c.get("/money/account/%d" % _account(world)).text
    r = _toggle(c, False)
    assert r.status_code == 204 and r.headers["hx-redirect"]
    html = c.get("/money?part=books").text
    assert BALANCE in html and "Privacy mode." not in html
    assert BALANCE in c.get("/money/account/%d" % _account(world)).text
    _toggle(c, True)
    assert BALANCE not in c.get("/money?part=books").text, "the switch works both ways"


def _account(world):
    con = db(world["root"])
    try:
        return con.execute("SELECT id FROM accounts WHERE name='Privacy Savings'").fetchone()[0]
    finally:
        con.close()


def test_overview_figures_and_transaction_lines(world):
    c = _login(world)
    for part in ("", "month", "trends", "statement", "homecosts", "spending", "paid", "regular", "budget", "loans", "year_end", "tax", "home_office"):
        html = c.get("/money" + (f"?part={part}" if part else "")).text
        body = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
        body = body.replace("$50 or more", "")  # the Statement's fixed rule text, not a figure of the house
        body = re.sub(r'<div class="mrow".*?</div>', "", body, flags=re.S)  # one charge of the month: the amount stays
        assert "$" not in body, (part, [body[max(0, m.start() - 90):m.end() + 20] for m in re.finditer(r"\$\d", body)][:6])
    today = re.sub(r"<script.*?</script>", "", c.get("/").text, flags=re.S)
    assert not re.search(r"\$\d", today), [today[m.start() - 150:m.end() + 20] for m in re.finditer(r"\$\d", today)][:3]
    # the amount of one transaction line stays visible: the Ledger and the account's own register
    assert LINE in c.get("/money?part=ledger").text
    assert LINE in c.get("/money/account/%d" % _account(world)).text
    _toggle(c, False)
    assert "$" in c.get("/money?part=month").text


def test_toggle_needs_the_token_an_adult_and_a_session(world):
    c = _login(world)
    assert c.post("/privacy", data={"on": "0"}).status_code == 403, "CSRF token required"
    assert world["mk"]().post("/privacy", data={"on": "0"}, headers={"X-CSRF-Token": "x"}).status_code == 403
    kid = _login(world, "Kid", "0000")
    assert kid.post("/privacy", data={"on": "0"}, headers={"X-CSRF-Token": _token(kid)}).status_code == 403
    assert BALANCE not in kid.get("/money/account/%d" % _account(world)).text


def test_birthdays_hidden_in_records_and_the_edit_form_keeps_them(world):
    mid = world["member"]
    assert mid, "the template household has a member born 03-14"
    c = _login(world)
    html = c.get(f"/records?ref=members%3A{mid}").text
    assert "Mar 14" not in html and "03-14" not in html and "1985" not in html
    assert 'name="birthday"' not in html and 'name="birthday_keep"' in html
    # saving the form drawn in privacy mode changes the name only; the birthday stays
    tok = _token(c)
    c.post("/records/edit", headers={"X-CSRF-Token": tok}, data={
        "table": "members", "id": str(mid), "op": "save", "role": "adult", "name": "Alex", "relation": "", "school": "",
        "grade": "", "grad_year": "", "birthday_keep": "1"})
    con = db(world["root"])
    assert con.execute("SELECT birth_month_day, birth_year FROM members WHERE id=?", (mid,)).fetchone() == ("03-14", 1985)
    con.close()
    _toggle(c, False)
    html = c.get(f"/records?ref=members%3A{mid}").text
    assert "Mar 14" in html and 'name="birthday"' in html and "birthday_keep" not in html


def test_downloads_and_chat_wait_for_easy_access(world):
    c = _login(world)
    assert c.get("/money/download?part=ledger").status_code == 403
    assert c.get("/money/download?part=year_end").status_code == 403
    assert c.get("/brief/doc/weekly_digest").status_code == 403
    assert c.get("/brief/doc/emergency").status_code != 403, "the emergency sheet has no figures"
    tok = _token(c)
    c.post("/chat/say", data={"text": "When is the secret birthday?"}, headers={"X-CSRF-Token": tok})
    assert "Privacy mode is on" in c.get("/chat").text, "a birthday question waits for Easy access"
    c.post("/chat/say", data={"text": "How big is the secret fund?"}, headers={"X-CSRF-Token": tok})
    assert "I found nothing" in c.get("/chat").text, "any other question is answered, not refused"
    _toggle(c, False)
    assert c.get("/money/download?part=ledger").status_code == 200
    # turning it back on clears the conversation
    _toggle(c, True)
    assert "secret fund" not in c.get("/chat").text


def test_household_default_is_a_settings_toggle_that_is_audited_and_snapshotted(world):
    c = _login(world)
    _toggle(c, False)
    tok = _token(c)
    r = c.post("/settings/privacy", headers={"X-CSRF-Token": tok, "HX-Request": "true"}, data={})  # box unticked
    assert r.status_code == 200
    fam = world["config"].family()
    assert fam["privacy"]["on_signin"] is False
    assert list((world["root"] / "config" / "history").glob("*/meta.json")), "a copy of the settings was taken first"
    assert "privacy_default_set" in (world["root"] / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    c2 = _login(world)
    assert BALANCE in c2.get("/money?part=books").text, "a new sign-in follows the new default"
    c2.post("/settings/privacy", headers={"X-CSRF-Token": _token(c2), "HX-Request": "true"}, data={"on": "1"})
    assert world["config"].family()["privacy"]["on_signin"] is True
    assert BALANCE not in _login(world).get("/money?part=books").text
    assert "New sign-ins start in privacy mode" in c2.get("/settings?group=household&tab=papers").text


def test_kid_cannot_change_the_default(world):
    kid = _login(world, "Kid", "0000")
    r = kid.post("/settings/privacy", headers={"X-CSRF-Token": _token(kid)}, data={"on": "0"})
    assert r.status_code in (200, 403) and world["config"].family()["privacy"]["on_signin"] is True


def test_setup_member_rows_hide_saved_birthdays_and_keep_them(world, modules):
    fr = modules("first_run")
    saved = [{"name": "Ann", "role": "adult", "birth_month_day": "03-14", "birth_year": 1985}]
    # a row drawn in privacy mode has no birthday inputs, only m_keep_N: saving must not erase the birthday
    rows, _ = fr.rows_from_form({"m_name_0": "Ann", "m_role_0": "adult", "m_keep_0": "Ann"}, "", "mdy", saved)
    members, problems = fr.rows_to_members(rows)
    assert not problems and members[0]["birth_month_day"] == "03-14" and members[0]["birth_year"] == 1985
    # a form that does send birthday inputs (privacy off) wins over the saved one
    rows, _ = fr.rows_from_form({"m_name_0": "Ann", "m_role_0": "adult", "m_month_0": "", "m_day_0": "", "m_year_0": "",
                                 "m_keep_0": "Ann"}, "", "mdy", saved)
    assert fr.rows_to_members(rows)[0][0]["birth_month_day"] == ""
    # the page: private -> no birthday inputs on a saved row; Easy access -> they are back
    sd = modules("setup_data")
    p = modules("privacy")
    tok = p.set_current(True)
    try:
        v = _people(sd, saved)
    finally:
        p.reset(tok)
    assert v["rows"][0]["keep"] == "Ann" and not v["rows"][0]["month"] and not v["rows"][0]["year"]
    assert _people(sd, saved)["rows"][0]["month"] == "3"


def _people(sd, saved):
    return next(x for x in sd.view({"members": saved}, 1)["parts"] if x["name"] == "People")


def test_chat_answers_show_figures_as_stars_and_toggle_is_on_money(world, modules):
    p, cd = modules("privacy"), modules("chat_data")
    tok = p.set_current(True)
    try:
        st = cd.new_state()
        cd.say(st, "assistant", "You paid $1,200.50 for rent on Friday.")
        assert st["hist"][-1]["text"] == f"You paid {STARS} for rent on Friday."
        assert p.chat_refused("when is Sam's birthday?") and not p.chat_refused("what do we owe?")
    finally:
        p.reset(tok)
    st = cd.new_state()
    cd.say(st, "assistant", "You paid $1,200.50")
    assert "$1,200.50" in st["hist"][-1]["text"], "privacy off: unchanged"
    c = _login(world)
    html = c.get("/money").text
    assert 'hx-post="/privacy"' in html and "Easy access: show figures" in html
