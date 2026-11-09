"""The Mitra Wall's pages (data/webapp/routes_wall.py, data/wall_data.py): HTTPS or this PC only, pairing with a one-time
code, the wall's own cookie and CSRF token, a revoked wall signed out, ticks made as the wall, adults-only lists hidden,
no amount anywhere but Money, and Money only after an adult's own PIN, for a minute."""
import datetime as dt
import re

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

ADULT = {"name": "Alex", "role": "adult"}
PAGES = ("/wall", "/wall/day", "/wall/day?d=2026-01-05", "/wall/day?d=junk", "/wall/week", "/wall/week?who=Sam", "/wall/week?start=2026-01-05", "/wall/chores",
         "/wall/chores?part=evening", "/wall/lists", "/wall/meals", "/wall/rest", "/wall/money", "/wall/money/spending", "/wall/money/bills",
         "/wall/money/regular", "/wall/month",
         "/wall/month?m=2026-01", "/wall/month?m=junk")
AMOUNT = re.compile(r"\$\s?\d")


@pytest.fixture()
def wall(root, modules):
    """(https client, wall module, wall routes module, edit_actions) with an adult (Ann, PIN 1234) and a child (Kid)."""
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    sessions = modules("webapp.sessions")
    routes = modules("webapp.routes_wall")
    W, ea = modules("wall"), modules("edit_actions")
    sessions.clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    fam["wall"] = {**(fam.get("wall") or {}), "screen": {"tabs": ["chores", "meals"]}}  # the optional pages on
    config.write_json(root / "config" / "family.json", fam)
    con = W._con()
    for t in ("routine_done", "routines", "wall_pairings", "walls"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    routes._csrf.clear()
    routes._unlock.clear()
    c = TestClient(app_mod.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    yield c, W, routes, ea
    sessions.clear()
    routes._unlock.clear()


def _code(W, name="Kitchen wall"):
    con = W._con()
    try:
        return W.pair_start(con, name, by="Ann")[0]
    finally:
        con.close()


def _pair(c, W, name="Kitchen wall"):
    r = c.post("/wall/pair", data={"code": W.pretty_code(_code(W, name))})
    assert r.status_code == 303 and r.headers["location"] == "/wall", r.text
    return r


def _token(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/wall/week").text).group(1)


def _post(c, path, data, token):
    return c.post(path, data=data, headers={"X-CSRF-Token": token})


def _wall_id(W):
    con = W._con()
    try:
        return con.execute("SELECT id FROM walls WHERE revoked_at IS NULL ORDER BY id DESC").fetchone()[0]
    finally:
        con.close()


# ---- where the wall opens ---------------------------------------------------------------------------------------
def test_plain_http_from_another_device_is_refused(wall, modules):
    c, W, _, _ = wall
    app_mod = modules("webapp.app")
    plain = TestClient(app_mod.app, base_url="http://192.168.1.20:8601", follow_redirects=False)
    for path in ("/wall", "/wall/week", "/wall/money"):
        assert plain.get(path).status_code == 403, path
    assert plain.post("/wall/pair", data={"code": W.pretty_code(_code(W))}).status_code == 403
    assert "set-cookie" not in plain.post("/wall/pair", data={"code": "x"}).headers


def test_an_unpaired_screen_gets_the_pairing_page(wall):
    c, _, _, _ = wall
    r = c.get("/wall?code=ab23cd45")
    assert r.status_code == 200 and 'action="/wall/pair"' in r.text and 'value="AB23-CD45"' in r.text
    assert c.get("/wall?code=<script>").text.count('value=""') == 1, "a bad code is not echoed"
    for path in PAGES[1:]:
        r = c.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/wall", path


def test_a_persons_session_is_not_a_wall(wall):
    c, _, _, _ = wall
    assert c.post("/login", data={"name": "Ann", "pin": "1234"}).status_code == 303
    r = c.get("/wall/week")
    assert r.status_code == 303 and r.headers["location"] == "/wall"


# ---- pairing ----------------------------------------------------------------------------------------------------
def test_a_code_pairs_the_wall_once_and_sets_a_strict_cookie(wall):
    c, W, routes, _ = wall
    code = _code(W)
    r = c.post("/wall/pair", data={"code": W.pretty_code(code).lower()})
    assert r.status_code == 303
    cookie = r.headers["set-cookie"].lower()
    for part in ("mh_wall=", "httponly", "samesite=strict", "secure", "path=/wall"):
        assert part in cookie, part
    assert c.get("/wall").status_code == 200
    other = TestClient(c.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    assert other.post("/wall/pair", data={"code": code}).status_code == 401, "a code works once"


def test_wrong_codes_are_throttled(wall):
    c, _, _, _ = wall
    seen = [c.post("/wall/pair", data={"code": "ZZZZ-ZZZZ"}).status_code for _ in range(6)]
    assert seen[:5] == [401] * 5 and seen[5] == 429
    assert "set-cookie" not in c.post("/wall/pair", data={"code": "ZZZZ-ZZZZ"}).headers


def test_pairing_is_refused_from_another_site(wall):
    c, W, _, _ = wall
    r = c.post("/wall/pair", data={"code": _code(W)}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403 and "set-cookie" not in r.headers


# ---- every screen ---------------------------------------------------------------------------------------------------
def test_chores_and_meals_only_when_ticked_and_a_clock_only_wall(wall, modules):
    """Chores and Meals are off until an adult ticks them (the rail leaves them out, the page goes to Today; the
    children's card does not link); a clock-only wall (one wall's own screen) shows the clock and nothing else."""
    c, W, _, ea = wall
    _pair(c, W)
    with modules("config").family_edit() as cfg:
        cfg["wall"]["screen"] = {}
    today = c.get("/wall").text
    assert 'href="/wall/chores"' not in today and 'href="/wall/meals"' not in today and 'href="/wall/lists"' in today
    for path in ("/wall/chores", "/wall/meals"):
        r = c.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/wall", path
    ok, _ = ea.wall_screen_set(ADULT, "digital", True, 15, 45, 4, "07:00", "21:00", "22:00", "06:00", tabs=["meals", "junk"])
    assert ok and modules("wall_screen").settings()["tabs"] == ["meals"]
    assert 'href="/wall/meals"' in c.get("/wall").text and c.get("/wall/meals").status_code == 200
    assert c.get("/wall/chores").status_code == 303
    ea.wall_screen_own_set(ADULT, _wall_id(W), True, "digital", False, 15, 45, 4, "07:00", "21:00", "22:00", "06:00",
                           clock_only=True)
    for path in ("/wall", "/wall/week", "/wall/meals", "/wall/money"):
        r = c.get(path)
        assert r.status_code == 303 and r.headers["location"] == "/wall/rest", path
    rest = c.get("/wall/rest").text
    assert 'data-clock-only="1"' in rest and 'href="/wall"' not in rest and "Tap anywhere" not in rest
    with modules("config").family_edit() as cfg:
        cfg["wall"].pop("screen", None)


def test_a_wall_theme_is_a_body_class_and_photo_brings_a_photo(wall, modules):
    """R5: the household's look (default Paper) or a wall's own is the pages' body class; an unknown one is refused; Photo
    puts one of the wall photos (a new one each day) behind the page, and with no photos the page stays Paper-like."""
    c, W, _, ea = wall
    _pair(c, W)
    WS = modules("wall_screen")
    assert "theme-paper" in c.get("/wall").text and set(WS.THEMES) == {"paper", "night", "slate", "bold", "photo"}
    ok, msg = ea.wall_screen_set(ADULT, "digital", True, 15, 45, 4, "07:00", "21:00", "22:00", "06:00", theme="neon")
    assert not ok and "look" in msg
    ok, _ = ea.wall_screen_set(ADULT, "digital", True, 15, 45, 4, "07:00", "21:00", "22:00", "06:00", theme="night")
    assert ok and "theme-night" in c.get("/wall/week").text
    ea.wall_screen_own_set(ADULT, _wall_id(W), True, "digital", False, 15, 45, 4, "07:00", "21:00", "22:00", "06:00",
                           theme="photo")
    page = c.get("/wall").text
    assert "theme-photo" in page and 'class="themebg"' not in page and "has-photo" not in page, "no photos yet"
    names = ["0123456789abcdef.jpg", "fedcba9876543210.jpg"]
    orig = WS.photos
    WS.photos = lambda: names
    try:
        page = c.get("/wall/day").text
        src = re.search(r'<img class="themebg" src="/wall/photo/([0-9a-f]{16}\.jpg)"', page)
        assert src and src.group(1) in names and "has-photo" in page and " style=" not in page
        assert 'class="themebg"' not in c.get("/wall/rest").text, "the resting clock keeps its own screen"
    finally:
        WS.photos = orig
        with modules("config").family_edit() as cfg:
            cfg["wall"].pop("screen", None)


def test_every_screen_draws_with_no_inline_code_and_no_amount(wall):
    c, W, _, _ = wall
    _pair(c, W)
    for path in PAGES:
        r = c.get(path)
        assert r.status_code == 200, (path, r.text[:300])
        assert "Content-Security-Policy" in r.headers and r.headers["Cache-Control"] == "no-store"
        assert " style=" not in r.text, path
        assert not re.search(r"<script(?![^>]*\ssrc=)", r.text), path
        assert not AMOUNT.search(r.text), (path, AMOUNT.search(r.text))
        assert 'name="csrf-token"' in r.text


def test_the_wall_templates_carry_no_inline_style_or_script(root):
    for f in sorted((root / "data" / "webapp" / "templates").glob("*wall*.html")):
        if f.name.startswith("wallet"):
            continue
        text = f.read_text(encoding="utf-8")
        assert "style=" not in text and "onclick" not in text and "<script>" not in text, f.name


def test_a_revoked_wall_is_signed_out(wall):
    c, W, _, _ = wall
    _pair(c, W)
    con = W._con()
    try:
        assert W.revoke(con, _wall_id(W))
    finally:
        con.close()
    r = c.get("/wall/week")
    assert r.status_code == 303 and r.headers["location"] == "/wall"
    assert 'action="/wall/pair"' in c.get("/wall").text


# ---- taps -----------------------------------------------------------------------------------------------------------
def test_posts_need_the_walls_own_token(wall):
    c, W, _, _ = wall
    _pair(c, W)
    assert c.post("/wall/lock").status_code == 403
    assert _post(c, "/wall/lock", {}, "wrong").status_code == 403
    assert _post(c, "/wall/lock", {}, _token(c)).status_code == 303
    login = TestClient(c.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    assert login.post("/login", data={"name": "Ann", "pin": "1234"}).status_code == 303
    token = re.search(r'name="csrf-token" content="([^"]+)"', login.get("/").text).group(1)
    assert _post(login, "/wall/lock", {}, token).status_code == 403, "a person's token is not a wall's"


def test_a_child_ticks_a_routine_on_the_wall(wall, modules):
    c, W, _, ea = wall
    _pair(c, W)
    ok, msg = ea.routine_add(ADULT, "Sam", "morning", "Make the bed", icon="bed", stars=2)
    assert ok, msg
    con = W._con()
    rid = con.execute("SELECT id FROM routines WHERE title='Make the bed'").fetchone()[0]
    con.close()
    page = c.get("/wall/chores?part=morning").text
    assert "Make the bed" in page and "Sam" in page
    token = _token(c)
    r = _post(c, "/wall/chores/tick", {"id": str(rid), "done": "1", "part": "morning"}, token)
    assert r.status_code == 303 and r.headers["location"] == "/wall/chores?part=morning"
    con = W._con()
    row = con.execute("SELECT stars, done_by FROM routine_done WHERE routine_id=?", (rid,)).fetchone()
    con.close()
    assert tuple(row) == (2, "Kitchen wall")
    assert _post(c, "/wall/chores/tick", {"id": str(rid), "done": "0"}, token).status_code == 303
    con = W._con()
    assert con.execute("SELECT COUNT(*) FROM routine_done WHERE routine_id=?", (rid,)).fetchone()[0] == 0
    con.close()
    assert _post(c, "/wall/chores/tick", {"id": "x"}, token).status_code == 400
    assert _post(c, "/wall/chores/tick", {"id": "999999"}, token).status_code == 409


def test_family_lists_only(wall, modules):
    c, W, _, _ = wall
    L = modules("lists")
    con = W._con()
    try:
        fam = L.new_list(con, "Wall groceries", "shopping", "family", by="Alex")
        adults = L.new_list(con, "Gift ideas secret", "todo", "adults", by="Alex")
        L.add_item(con, adults, "Bike for Sam", by="Alex")
        hidden = con.execute("SELECT id FROM list_items WHERE list_id=?", (adults,)).fetchone()[0]
        con.commit()
    finally:
        con.close()
    _pair(c, W)
    page = c.get("/wall/lists").text
    assert "Wall groceries" in page and "Gift ideas secret" not in page and "Bike for Sam" not in page
    token = _token(c)
    assert _post(c, "/wall/lists/add", {"list": str(fam), "text": "  Milk  "}, token).status_code == 303
    con = W._con()
    item = con.execute("SELECT id, text, added_by FROM list_items WHERE list_id=?", (fam,)).fetchone()
    con.close()
    assert (item[1], item[2]) == ("Milk", "Kitchen wall")
    assert _post(c, "/wall/lists/tick", {"item": str(item[0]), "done": "1"}, token).status_code == 303
    assert _post(c, "/wall/lists/tick", {"item": str(hidden), "done": "1"}, token).status_code == 409
    assert _post(c, "/wall/lists/add", {"list": str(adults), "text": "x"}, token).status_code == 409
    assert _post(c, "/wall/lists/add", {"list": str(fam), "text": "   "}, token).status_code == 400


# ---- money ----------------------------------------------------------------------------------------------------------
def test_money_opens_with_an_adults_pin_for_a_minute(wall):
    c, W, routes, _ = wall
    _pair(c, W)
    pad = c.get("/wall/money").text
    assert 'action="/wall/unlock"' in pad and not AMOUNT.search(pad)
    assert "<option>Ann</option>" in pad and "Kid" not in pad
    token = _token(c)
    r = _post(c, "/wall/unlock", {"name": "Ann", "pin": "9999"}, token)
    assert r.status_code == 401 and r.text == "Wrong name or PIN."
    assert _post(c, "/wall/unlock", {"name": "Kid", "pin": "0000"}, token).status_code == 401, "children never unlock"
    r = _post(c, "/wall/unlock", {"name": "Ann", "pin": "1234"}, token)
    assert r.status_code == 303 and r.headers["location"] == "/wall/money"
    page = c.get("/wall/money").text
    assert "Unlocked by Ann" in page and 'data-unlock-left="' in page
    assert 0 < routes.unlocked({"id": _wall_id(W)}) <= routes.UNLOCK_SECONDS
    for path in ("/wall", "/wall/week", "/wall/lists"):
        assert not AMOUNT.search(c.get(path).text), "amounts only on Money, even while it is open"
    routes._unlock[_wall_id(W)]["until"] -= routes.UNLOCK_SECONDS + 1
    assert 'action="/wall/unlock"' in c.get("/wall/money").text, "locks itself after the minute"
    assert _post(c, "/wall/unlock", {"name": "Ann", "pin": "1234"}, token).status_code == 303
    assert _post(c, "/wall/lock", {}, token).status_code == 303
    assert 'action="/wall/unlock"' in c.get("/wall/money").text


def test_the_money_pages_open_with_the_same_pin_and_come_back_to_the_page(wall):
    c, W, routes, _ = wall
    _pair(c, W)
    pad = c.get("/wall/money/bills").text
    assert 'action="/wall/unlock"' in pad and 'name="part" value="bills"' in pad and not AMOUNT.search(pad)
    token = _token(c)
    r = _post(c, "/wall/unlock", {"name": "Ann", "pin": "1234", "part": "bills"}, token)
    assert r.status_code == 303 and r.headers["location"] == "/wall/money/bills", "back to the page that asked"
    for path, words in (("/wall/money/spending", "Spending"), ("/wall/money/bills", "Bills"), ("/wall/money/regular", "Every month")):
        page = c.get(path)
        assert page.status_code == 200 and words in page.text and "Unlocked by Ann" in page.text, path
        assert 'aria-current="page"' in page.text and 'href="/wall/money/regular"' in page.text
    r = c.get("/wall/money/elsewhere")
    assert r.status_code == 303 and r.headers["location"] == "/wall/money"
    r = _post(c, "/wall/unlock", {"name": "Ann", "pin": "1234", "part": "../settings"}, token)
    assert r.headers["location"] == "/wall/money", "only a known page"
    routes._unlock[_wall_id(W)]["until"] -= routes.UNLOCK_SECONDS + 1
    assert 'action="/wall/unlock"' in c.get("/wall/money/regular").text, "they lock with Money"


def test_unlock_is_per_wall(wall):
    c, W, _, _ = wall
    _pair(c, W)
    assert _post(c, "/wall/unlock", {"name": "Ann", "pin": "1234"}, _token(c)).status_code == 303
    other = TestClient(c.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    _pair(other, W, "Hall tablet")
    assert 'action="/wall/unlock"' in other.get("/wall/money").text


def test_wrong_pins_on_the_wall_are_throttled(wall):
    c, W, _, _ = wall
    _pair(c, W)
    token = _token(c)
    seen = [_post(c, "/wall/unlock", {"name": "Ann", "pin": "0001"}, token).status_code for _ in range(6)]
    assert seen[:5] == [401] * 5 and seen[5] == 429
    assert _post(c, "/wall/unlock", {"name": "Ann", "pin": "1234"}, token).status_code == 429, "the right PIN waits too"


def test_forget_drops_the_cookie(wall):
    c, W, _, _ = wall
    _pair(c, W)
    r = _post(c, "/wall/forget", {}, _token(c))
    assert r.status_code == 303 and "max-age=0" in r.headers["set-cookie"].lower()
    assert 'action="/wall/pair"' in c.get("/wall").text


# ---- the PC side: Settings > Phones > Mitra Wall, Family > Routines ---------------------------------------------
@pytest.fixture()
def pc(wall, modules):
    """A signed-in adult (Ann) on this PC (plain http on 127.0.0.1) and that session's CSRF token."""
    _, W, _, ea = wall
    app_mod = modules("webapp.app")
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    return c, W, ea, app_mod


def _sign_in(c, monkeypatch, app_mod, name="Ann", pin="1234"):
    monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"})
    assert c.post("/login", data={"name": name, "pin": pin}).status_code == 303
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)


def test_settings_shows_a_wall_code_once_and_removes_a_wall(pc, monkeypatch, modules):
    c, W, _, app_mod = pc
    token = _sign_in(c, monkeypatch, app_mod)
    page = c.get("/settings?group=phones&tab=walls").text
    assert "Mitra Wall" in page and 'hx-post="/settings/wall/add"' in page
    for bad in ("", "Sam", "alex", "Ann"):
        r = _post(c, "/settings/wall/add", {"name": bad}, token)
        assert r.headers.get("hx-redirect", "").startswith("/settings"), bad
        assert "Show the wall code" in c.get("/settings?group=phones&tab=walls").text
    r = _post(c, "/settings/wall/add", {"name": "Kitchen wall"}, token)
    assert r.status_code == 200 and r.headers["hx-redirect"].startswith("/settings")
    page = c.get("/settings?group=phones&tab=walls").text
    code = re.search(r'class="wcode"[^>]*>([A-Z0-9]{4}-[A-Z0-9]{4})<', page).group(1)
    assert "Open this on Kitchen wall" in page and "data:image/svg+xml" in page
    assert "/wall?code=" not in c.get("/settings?group=phones&tab=walls").text, "the code is shown once"
    tablet = TestClient(c.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    assert tablet.post("/wall/pair", data={"code": code}).status_code == 303
    page = c.get("/settings?group=phones&tab=walls").text
    assert "Remove Kitchen wall" in page
    wid = _wall_id(W)
    assert _post(c, "/settings/wall/revoke", {"id": str(wid), "sure": "1"}, token).status_code == 200
    assert tablet.get("/wall/week").status_code == 303
    assert "Remove Kitchen wall" not in c.get("/settings?group=phones&tab=walls").text
    log = (modules("admin_actions").LOGS / "admin_audit.log").read_text(encoding="utf-8")
    assert "wall_pair_code\tKitchen wall" in log and f"wall_revoke\twall {wid}" in log and code not in log


def test_a_wall_code_needs_an_adult_on_this_pc(pc, monkeypatch):
    c, _, _, app_mod = pc
    token = _sign_in(c, monkeypatch, app_mod, "Kid", "0000")
    assert _post(c, "/settings/wall/add", {"name": "Hall"}, token).status_code == 403
    assert c.get("/family/routines").status_code == 403
    assert _post(c, "/family/routines", {"op": "rate", "rate": "100"}, token).status_code == 403
    away = TestClient(c.app, base_url="https://192.168.1.20:8701", follow_redirects=False)
    monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"127.0.0.1"})
    assert away.post("/login", data={"name": "Ann", "pin": "1234"}).status_code == 303
    t2 = re.search(r'name="csrf-token" content="([^"]+)"', away.get("/").text).group(1)
    assert _post(away, "/settings/wall/add", {"name": "Hall"}, t2).status_code == 200
    assert "Add a wall from this PC" in away.get("/settings?group=phones&tab=walls").text


def test_adults_set_routines_and_the_star_rate(pc, monkeypatch, modules):
    c, W, _, app_mod = pc
    token = _sign_in(c, monkeypatch, app_mod)
    page = c.get("/family/routines").text
    assert "Sam" in page and "Add the job" in page and 'aria-current="true">Routines' in page
    assert "Biscuit" not in page.split("Add a job")[0] and "<option>Alex</option>" not in page
    r = c.post("/family/routines", content="op=add&member=Sam&part=evening&title=Feed+Biscuit&icon=paw&stars=3&day=MO&day=WE",
               headers={"X-CSRF-Token": token, "Content-Type": "application/x-www-form-urlencoded"})
    assert r.headers["hx-redirect"] == "/family/routines"
    page = c.get("/family/routines").text
    assert "Added &#39;Feed Biscuit&#39;" in page and "Feed Biscuit" in page and "Mon, Wed" in page and "3 stars" in page
    con = W._con()
    rid, icon, days = con.execute("SELECT id, icon, weekdays FROM routines WHERE title='Feed Biscuit'").fetchone()
    con.close()
    assert (icon, days) == ("paw", "MO,WE")
    for bad in ({"op": "add", "member": "Alex", "part": "evening", "title": "x"},
                {"op": "add", "member": "Sam", "part": "night", "title": "x"},
                {"op": "add", "member": "Sam", "part": "evening", "title": "x", "stars": "9"},
                {"op": "drop", "id": "abc"}, {"op": "rate", "rate": "inf"}, {"op": "rate", "rate": "999"}, {"op": "?"}):
        assert _post(c, "/family/routines", bad, token).status_code == 200, bad
        assert 'class="alert"' in c.get("/family/routines").text, bad
    assert _post(c, "/family/routines", {"op": "rate", "rate": "$0.50"}, token).status_code == 200
    assert W.star_cents() == 50
    assert _post(c, "/family/routines", {"op": "rate", "rate": "10"}, token).status_code == 200
    assert W.star_cents() == 10
    assert _post(c, "/family/routines", {"op": "drop", "id": str(rid)}, token).status_code == 200
    con = W._con()
    assert con.execute("SELECT status FROM routines WHERE id=?", (rid,)).fetchone()[0] == "dropped"
    con.close()
    assert "Removed &#39;Feed Biscuit&#39;" in c.get("/family/routines").text


def test_goals_and_the_allowance_line_from_the_routines_page(pc, monkeypatch, wall):
    c, W, ea, app_mod = pc
    token = _sign_in(c, monkeypatch, app_mod)
    assert ea.routine_add(ADULT, "Sam", "morning", "Make the bed", stars=2)[0]
    assert _post(c, "/family/routines", {"op": "goal", "member": "Sam", "title": "New bike", "stars": "40"}, token).status_code == 200
    page = c.get("/family/routines").text
    assert "Sam&#39;s goal: New bike, 40 stars from today." in page and "0 of 40 stars" in page
    assert "Every job done: 14 stars a week" in page and "Put it in the budget" in page
    assert _post(c, "/family/routines", {"op": "allowance", "member": "Sam"}, token).status_code == 200
    assert "allowance line in the budget" in c.get("/family/routines").text
    tablet, _, _, _ = wall
    _pair(tablet, W)
    chores = tablet.get("/wall/chores?part=morning").text
    assert "New bike" in chores and "0 of 40" in chores and 'class="w-0"' in chores
    assert _post(c, "/family/routines", {"op": "goal_clear", "member": "Sam"}, token).status_code == 200
    assert "New bike" not in tablet.get("/wall/chores?part=morning").text


def test_lists_on_the_wall_show_who_added_an_item(wall, modules):
    c, W, _, _ = wall
    L = modules("lists")
    con = W._con()
    lid = L.new_list(con, "Wall picnic", "shopping", "family", by="Alex")
    L.add_item(con, lid, "Lemonade", by="Sam")
    L.add_item(con, lid, "Cups", by="Kitchen wall")
    con.commit()
    con.close()
    _pair(c, W)
    page = c.get("/wall/lists").text
    assert 'aria-label="added by Sam"' in page and "added by Kitchen wall" not in page


def test_the_wall_has_the_logo_popups_and_no_money_card(wall):
    """The Mitra Home icon in the rail, a tap on an item opens its details (a hidden .pop for wall.js), Week | Month,
    and Today carries Coming up instead of the money card (Money stays behind the PIN in the rail)."""
    c, W, _, _ = wall
    _pair(c, W)
    today = c.get("/wall").text
    assert '<img src="/static/icon.svg"' in today and 'id="wpop"' in today
    assert "Money this week" not in today and "Coming up" in today
    week = c.get("/wall/week").text
    assert 'href="/wall/month"' in week and 'aria-current="page">Week' in week
    month = c.get("/wall/month").text
    assert 'class="month mrows-' in month and 'aria-current="page">Month' in month
    assert c.get("/wall/month?m=2026-01").status_code == 200 and "January 2026" in c.get("/wall/month?m=2026-01").text


def test_the_popup_has_a_colour_header_an_x_and_grouped_days(wall, modules):
    """R4: the one dialog closes with an X; every hidden .pop carries the person's colour class for the header band (only
    c0..c5 / ch reach the dialog: wall.js checks), a day's popup groups its things (At a time, All day, Late)."""
    c, W, _, _ = wall
    _pair(c, W)
    con = W._con()
    con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES ('Kid', NULL, 'Pop test swim', ?)",
                (modules("dates").today().isoformat() + " 16:30",))
    con.execute("INSERT INTO life_items(domain, title, due_date, status) VALUES ('chore', 'Pop test porch', ?, 'open')",
                (modules("dates").today().isoformat(),))
    con.commit()
    try:
        week = c.get("/wall/week").text
        assert 'class="wpx"' in week and 'aria-label="Close"' in week and ">Close</button>" not in week
        assert re.findall(r'class="pop" hidden data-cls="([^"]+)"', week) and all(
            re.fullmatch(r"c[0-5]|ch", x) for x in re.findall(r'data-cls="([^"]+)"', week))
        assert '<small class="pg">At a time</small>' in week and '<small class="pg">All day</small>' in week
        assert '<span class="ptime">4:30 PM</span>' in week and "Pop test porch" in week
        for path in ("/wall", "/wall/day", "/wall/month"):
            assert 'class="phead"' in c.get(path).text, path
    finally:
        con.execute("DELETE FROM appointments WHERE purpose='Pop test swim'")
        con.execute("DELETE FROM life_items WHERE title='Pop test porch'")
        con.commit()
        con.close()


def test_today_marks_now_between_events_and_no_now_pill_after_the_last_one(wall, monkeypatch):
    """The Now pill sits before the first event that has not ended; when every timed event is over the agenda says
    so in plain words instead of a Now pill beside the last (faded) event, which read as a badge on it."""
    c, W, routes, _ = wall
    _pair(c, W)
    orig = routes.WD.today

    def ev(title, past):
        return {"title": title, "time": "4:30 PM", "end": "5:30 PM", "cls": "c1", "kind": "Class", "day": "Today",
                "who": [], "people": [], "past": past, "now": False}

    monkeypatch.setattr(routes.WD, "today", lambda con, now: {**orig(con, now), "line": [ev("Soccer", True)]})
    page = c.get("/wall").text
    assert "Nothing more today" in page and 'class="nowmark"' not in page
    monkeypatch.setattr(routes.WD, "today", lambda con, now: {**orig(con, now), "line": [ev("Soccer", True), ev("Piano", False)]})
    page = c.get("/wall").text
    assert 'class="nowmark"' in page and "Nothing more today" not in page
    assert page.index('class="nowmark"') < page.index("<b>Piano</b>")


def test_settings_sets_the_wall_screen_and_adds_and_removes_photos(pc, monkeypatch, modules):
    """Settings > Phones > Mitra Wall > Wall screen: the face and the schedule, photos up as the raw body (made again
    without EXIF), thumbnails for adults only, Remove."""
    pytest.importorskip("PIL.Image")
    import io
    from PIL import Image
    c, _W, _, app_mod = pc
    WS = modules("wall_screen")
    for n in WS.photos():
        WS.remove_photo(n)
    token = _sign_in(c, monkeypatch, app_mod)
    page = c.get("/settings?group=phones&tab=walls").text
    assert 'hx-post="/settings/wall/screen"' in page and 'data-upload-to="/settings/wall/photo"' in page
    r = _post(c, "/settings/wall/screen", {"clock": "analog", "photos": "1", "photo_seconds": "20", "clock_seconds": "40",
                                            "per_turn": "3", "photos_from": "07:30", "photos_to": "20:00",
                                            "night_from": "21:30", "night_to": "06:30"}, token)
    assert r.headers.get("hx-redirect", "").startswith("/settings")
    assert WS.settings()["clock"] == "analog" and WS.settings()["night_from"] == "21:30"
    buf = io.BytesIO()
    Image.new("RGB", (300, 200), (10, 120, 200)).save(buf, "JPEG")
    up = c.post("/settings/wall/photo", content=buf.getvalue(),
                headers={"X-CSRF-Token": token, "X-Filename": "beach.jpg", "Content-Type": "application/octet-stream"})
    assert up.status_code == 200 and up.json()["ok"], up.text
    name = WS.photos()[0]
    assert f'src="/settings/wall/photo/{name}"' in c.get("/settings?group=phones&tab=walls").text
    assert c.get(f"/settings/wall/photo/{name}").headers["content-type"] == "image/jpeg"
    bad = c.post("/settings/wall/photo", content=b"not a photo",
                 headers={"X-CSRF-Token": token, "X-Filename": "x.jpg", "Content-Type": "application/octet-stream"})
    assert bad.status_code == 400 and not bad.json()["ok"]
    _post(c, "/settings/wall/photo/remove", {"name": name}, token)
    assert WS.photos() == []
    with modules("config").family_edit() as cfg:
        (cfg.get("wall") or {}).pop("screen", None)


def test_rewards_children_ask_with_their_stars_and_adults_answer(pc, monkeypatch, wall, modules):
    """Family > Routines adds rewards; a child asks on the wall (stars held), an adult gives it (spent) or says not now
    (stars back); Today tells the adults; the child's own page asks too, only for themself."""
    c, W, ea, app_mod = pc
    wc = wall[0]
    con = W._con()
    for t in ("reward_claims", "rewards"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    ok, _ = ea.routine_add(ADULT, "Sam", "morning", "Make the bed", stars=5)
    con = W._con()
    rid = con.execute("SELECT id FROM routines WHERE title='Make the bed'").fetchone()[0]
    for day in ("2026-10-12", "2026-10-13", "2026-10-14"):  # 15 stars earned
        con.execute("INSERT INTO routine_done(routine_id, day, stars, done_at) VALUES (?, ?, 5, ?)", (rid, day, day + "T08:00:00"))
    con.commit()
    con.close()
    token = _sign_in(c, monkeypatch, app_mod)
    assert _post(c, "/family/routines", {"op": "reward_add", "title": "Screen time", "stars": "10", "member": ""}, token).status_code == 200
    assert "Added the reward" in c.get("/family/routines").text
    for bad in ({"op": "reward_add", "title": "", "stars": "3"}, {"op": "reward_add", "title": "x", "stars": "0"},
                {"op": "reward_add", "title": "x", "stars": "3", "member": "Alex"}):
        _post(c, "/family/routines", bad, token)
        assert 'class="alert"' in c.get("/family/routines").text, bad
    con = W._con()
    wid = con.execute("SELECT id FROM rewards WHERE title='Screen time'").fetchone()[0]
    assert W.star_balance(con, "Sam") == 15
    con.close()
    # the child asks on the wall: the stars are held
    _pair(wc, W)
    page = wc.get("/wall/chores?part=morning").text
    assert "Screen time" in page and "15 to spend" in page
    wt = _token(wc)
    r = _post(wc, "/wall/reward", {"reward": str(wid), "member": "Sam"}, wt)
    assert r.status_code == 303
    con = W._con()
    assert W.star_balance(con, "Sam") == 5
    con.close()
    assert "Asked" in wc.get("/wall/chores?part=morning").text
    assert _post(wc, "/wall/reward", {"reward": str(wid), "member": "Sam"}, wt).status_code == 303, "asking twice is a no-op"
    ok, msg = ea.reward_add(ADULT, "Big trip", 100)
    con = W._con()
    big = con.execute("SELECT id FROM rewards WHERE title='Big trip'").fetchone()[0]
    con.close()
    r = _post(wc, "/wall/reward", {"reward": str(big), "member": "Sam"}, wt)
    assert r.status_code == 409 and "takes 100" in r.text
    # the adults see it on Today and answer it
    assert "Sam asked for a reward" in c.get("/").text
    page = c.get("/family/routines").text
    assert "Sam</b> asks for Screen time" in page
    con = W._con()
    claim = con.execute("SELECT id FROM reward_claims WHERE status='asked'").fetchone()[0]
    con.close()
    assert _post(c, "/family/routines", {"op": "reward_no", "id": str(claim)}, token).status_code == 200
    con = W._con()
    assert W.star_balance(con, "Sam") == 15, "not now: the stars come back"
    con.close()
    assert "Sam asked for a reward" not in c.get("/").text
    _post(wc, "/wall/reward", {"reward": str(wid), "member": "Sam"}, wt)
    con = W._con()
    claim = con.execute("SELECT id FROM reward_claims WHERE status='asked'").fetchone()[0]
    con.close()
    _post(c, "/family/routines", {"op": "reward_give", "id": str(claim)}, token)
    con = W._con()
    assert W.star_balance(con, "Sam") == 5 and con.execute("SELECT status FROM reward_claims WHERE id=?", (claim,)).fetchone()[0] == "given"
    con.close()
    assert "already answered" in ea.reward_decide(ADULT, claim, True)[1]
    # who may ask: the child for themself, never for another child; nobody else
    assert not ea.reward_ask({"name": "Kid", "role": "limited"}, wid, "Sam")[0]
    assert not ea.reward_decide({"name": "Sam", "role": "limited"}, claim, True)[0]
    log = (modules("paths").LOGS / "edits.log").read_text(encoding="utf-8")
    assert "reward_ask\tid=" in log and "reward_given\tid=" in log and "reward_declined\tid=" in log


def test_a_child_asks_for_a_reward_on_their_own_page(wall, modules):
    _, W, _, ea = wall
    kd = modules("kid_data")
    con = W._con()
    for t in ("reward_claims", "rewards"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    ea.routine_add(ADULT, "Sam", "morning", "Brush teeth", stars=5)
    con = W._con()
    rid = con.execute("SELECT id FROM routines WHERE title='Brush teeth'").fetchone()[0]
    con.execute("INSERT INTO routine_done(routine_id, day, stars, done_at) VALUES (?, '2026-10-12', 5, '2026-10-12T08:00:00')", (rid,))
    con.commit()
    con.close()
    ea.reward_add(ADULT, "Ice cream", 4, "Sam")
    sam = {"name": "Sam", "role": "limited"}
    v = kd.view(sam)
    rw = v["jobs"]["rewards"]
    assert rw["balance"] == 5 and rw["rewards"][0]["title"] == "Ice cream" and rw["rewards"][0]["can"]
    wid = rw["rewards"][0]["id"]
    ok, msg = kd.act(sam, "reward", {"reward": str(wid)})
    assert ok and "asked for" in msg
    assert kd.view(sam)["jobs"]["rewards"]["rewards"][0]["asked"]
    assert not kd.act(sam, "reward", {"reward": "x"})[0]


def test_a_wall_can_have_its_own_screen(pc, monkeypatch, wall, modules):
    """Settings > Phones > Walls > a wall's window: its own clock and night tone (walls.screen, migration 064); the
    other walls and the app copy keep the household's; unticked = back to the household's."""
    c, W, _, app_mod = pc
    wc = wall[0]
    WS = modules("wall_screen")
    _pair(wc, W)
    wid = _wall_id(W)
    token = _sign_in(c, monkeypatch, app_mod)
    page = c.get("/settings?group=phones&tab=walls").text
    assert 'hx-post="/settings/wall/own"' in page and f'data-ptab="w{wid}-night"' in page and 'data-ptab="wd-clock"' in page
    assert 'hx-post="/settings/wall/own" data-own-auto' in page and "data-own-hint" in page, "a change ticks Its own screen"
    assert "closest('form[data-own-auto]')" in c.get("/static/app.js").text
    form = {"id": str(wid), "own": "1", "clock": "typograph", "photos": "", "photo_seconds": "15", "clock_seconds": "45",
            "per_turn": "4", "photos_from": "07:00", "photos_to": "21:00", "night_from": "20:30", "night_to": "07:00",
            "night_tone": "red"}
    assert _post(c, "/settings/wall/own", form, token).headers["hx-redirect"].endswith("tab=walls")
    assert "Saved for Kitchen wall: Roman clock" in c.get("/settings?group=phones&tab=walls").text
    assert WS.settings(wall_id=wid)["night_tone"] == "red"
    assert WS.settings(wall_id=wid)["clock"] == "typograph" and WS.settings(wall_id=wid)["night_from"] == "20:30"
    assert "face-typograph tone-red" in wc.get("/wall/rest").text
    assert WS.settings(wall_id=wid + 999) == WS.settings(), "an unknown wall gets the household's"
    con = W._con()
    try:
        assert modules("wall_copy").extras(con, wall_id=wid)["screen"]["clock"] == "typograph"
    finally:
        con.close()
    _post(c, "/settings/wall/own", {**form, "night_from": "bad"}, token)
    assert 'class="alert"' in c.get("/settings?group=phones&tab=walls").text
    assert WS.settings(wall_id=wid)["night_from"] == "20:30", "a refused form changes nothing"
    _post(c, "/settings/wall/own", {"id": str(wid)}, token)
    assert "follows the household" in c.get("/settings?group=phones&tab=walls").text
    assert WS.own_screen(wid) is None and WS.settings(wall_id=wid) == WS.settings()
    assert _post(c, "/settings/wall/own", {**form, "id": "999999"}, token).status_code == 200
    assert "no longer paired" in c.get("/settings?group=phones&tab=walls").text


def test_word_clock_lights_the_right_words(modules):
    WS = modules("wall_screen")
    assert WS.word_lit(9, 0) == ["it", "is", "hnine", "oclock"]
    assert WS.word_lit(21, 7) == ["it", "is", "m5", "minutes", "past", "hnine", "d1", "d2"]
    assert WS.word_lit(9, 45) == ["it", "is", "quarter", "to", "hten"]
    assert WS.word_lit(11, 58) == ["it", "is", "m5", "minutes", "to", "htwelve", "d1", "d2", "d3"]
    assert WS.word_lit(0, 30) == ["it", "is", "half", "past", "htwelve"]
    assert WS.word_lit(3, 25)[2:4] == ["m20", "m5"]
    rows = modules("webapp.routes_wall").WORD_ROWS
    keys = {k for row in rows for k, _ in row}
    for h in range(24):
        for m in range(60):
            assert {w for w in WS.word_lit(h, m) if not w.startswith("d")} <= keys, (h, m)


def test_kids_day_ring_and_flip_cards(modules):
    import datetime as dt
    R = modules("webapp.routes_wall")
    assert R.day_angle(6 * 60) == R.DAY_GAP / 2 and R.day_angle(22 * 60) == 360 - R.DAY_GAP / 2
    assert R.day_angle(0) == R.day_angle(6 * 60), "the night sits in the gap"
    ring = R.day_ring([{"title": "Swim", "s": 17 * 60, "e": 18 * 60, "cls": "c1", "past": False},
                       {"title": "Late", "s": 23 * 60, "e": 23 * 60 + 30, "cls": "c2", "past": False}],
                      dt.datetime(2026, 10, 24, 17, 30))
    assert ring["part"] == "Evening" and ring["awake"] and len(ring["events"]) == 1 and ring["events"][0]["d"].startswith("M ")
    assert [p["key"] for p in ring["parts"]] == ["morning", "afternoon", "evening"]
    assert R.day_ring([], dt.datetime(2026, 10, 24, 23, 0))["part"] == "Night"
    assert R.flip_digits(dt.datetime(2026, 10, 24, 21, 5)) == ["", "9", "0", "5"]
    assert R.flip_digits(dt.datetime(2026, 10, 24, 12, 40)) == ["1", "2", "4", "0"]


def test_each_new_face_draws_and_the_wall_picks_its_own(pc, monkeypatch, wall, modules):
    """The resting screen draws flip, word, two-city and kids' day; the clock button posts /wall/face, which gives this
    wall its own screen (the household's stays); a face not in the list is refused; the zone is checked."""
    c, W, ea, app_mod = pc
    wc = wall[0]
    WS = modules("wall_screen")
    _pair(wc, W)
    wid = _wall_id(W)
    page = wc.get("/wall/rest").text
    assert 'id="wface"' in page and 'name="clock" value="kidsday"' in page and "data-face-open" in page
    t = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    for face, mark in (("flip", 'data-fd="3"'), ("word", 'data-w="oclock"'), ("dual", 'data-tz="Asia/Kolkata"'),
                       ("kidsday", 'class="dayring"')):
        r = _post(wc, "/wall/face", {"clock": face}, t)
        assert r.status_code == 303 and r.headers["location"] == "/wall/rest", face
        page = wc.get("/wall/rest").text
        assert f"face-{face}" in page and mark in page, face
    assert WS.settings()["clock"] != "kidsday" and WS.own_screen(wid)["clock"] == "kidsday"
    assert _post(wc, "/wall/face", {"clock": "sundial"}, t).status_code == 409
    assert ea.wall_face_set(ADULT, "flip")[0] is False, "an adult picks per wall in Settings"
    token = _sign_in(c, monkeypatch, app_mod)
    form = {"clock": "dual", "photos": "", "photo_seconds": "15", "clock_seconds": "45", "per_turn": "4",
            "photos_from": "07:00", "photos_to": "21:00", "night_from": "22:00", "night_to": "06:00", "zone": "Europe/London"}
    _post(c, "/settings/wall/screen", form, token)
    assert WS.settings()["zone"] == "Europe/London"
    _post(c, "/settings/wall/screen", {**form, "zone": "Mars/Base"}, token)
    assert "other place" in c.get("/settings?group=phones&tab=walls").text and WS.settings()["zone"] == "Europe/London"
    assert 'value="Europe/London" selected' in c.get("/settings?group=phones&tab=walls").text
    with modules("config").family_edit() as cfg:
        (cfg.get("wall") or {}).pop("screen", None)



def test_photo_styles_and_the_month_a_photo_was_taken(pc, monkeypatch, wall, modules):
    """Photos tab > Photo style (fade, slow zoom, blurred fill, collage, frame and date) per wall; the day a photo was
    taken is read from its EXIF before the EXIF is dropped and kept as the day only (taken.json), shown as 'July 2024'."""
    pytest.importorskip("PIL.Image")
    import io
    from PIL import Image
    c, W, ea, app_mod = pc
    WS = modules("wall_screen")
    for n in WS.photos():
        WS.remove_photo(n)
    im = Image.new("RGB", (300, 200), (200, 120, 10))
    ex = Image.Exif()
    ex[306] = "2024:07:04 18:30:00"
    buf = io.BytesIO()
    im.save(buf, "JPEG", exif=ex)
    assert WS.taken_on(buf.getvalue()) == "2024-07-04"
    assert WS.taken_on(b"not a photo") is None
    name = WS.add_photo("beach.jpg", buf.getvalue())
    assert WS.taken() == {name: "2024-07-04"} and WS.taken_label("2024-07-04") == "July 2024"
    with Image.open(WS.photo_path(name)) as kept:
        assert not kept.getexif(), "the kept copy has no EXIF"
    plain = io.BytesIO()
    im.save(plain, "JPEG")
    other = WS.add_photo("plain.jpg", plain.getvalue())
    assert other not in WS.taken()
    _pair(wall[0], W)
    wid = _wall_id(W)
    token = _sign_in(c, monkeypatch, app_mod)
    form = {"id": str(wid), "own": "1", "clock": "digital", "photos": "1", "photo_seconds": "15", "clock_seconds": "45",
            "per_turn": "4", "photos_from": "00:00", "photos_to": "23:59", "night_from": "02:00", "night_to": "03:00",
            "night_tone": "dim", "zone": "Asia/Kolkata", "photo_style": "frame"}
    _post(c, "/settings/wall/own", form, token)
    assert WS.settings(wall_id=wid)["photo_style"] == "frame" and WS.settings()["photo_style"] == "fade"
    page = wall[0].get("/wall/rest").text
    assert 'class="stage st-frame"' in page and 'data-photo-look="frame"' in page and "July 2024" in page
    assert page.count('class="ly"') == 2
    con = W._con()
    try:
        ph = modules("wall_copy").photos(wid)
    finally:
        con.close()
    assert {p["name"]: p["taken"] for p in ph} == {name: "July 2024", other: ""}
    _post(c, "/settings/wall/own", {**form, "photo_style": "spin"}, token)
    assert "photo style" in c.get("/settings?group=phones&tab=walls").text
    assert 'value="collage"' in c.get("/settings?group=phones&tab=walls").text
    WS.remove_photo(name)
    assert WS.taken() == {}
    WS.remove_photo(other)


def test_the_rail_starts_the_clock_or_the_photos_at_once(pc, wall, modules):
    """Wall rail: Clock (always) opens the resting screen now; Photos (only with photos on and kept) starts the photos
    now via ?photos=1, which only marks the page (wall.js drops it from the address)."""
    pytest.importorskip("PIL.Image")
    import io
    from PIL import Image
    c, W, _, _ = pc
    WS = modules("wall_screen")
    for n in WS.photos():
        WS.remove_photo(n)
    wc = wall[0]
    _pair(wc, W)
    page = wc.get("/wall").text
    assert 'class="tab quick" href="/wall/rest"' in page and "/wall/rest?photos=1" not in page, "no photos kept yet"
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), (1, 2, 3)).save(buf, "JPEG")
    name = WS.add_photo("a.jpg", buf.getvalue())
    assert 'href="/wall/rest?photos=1"' in wc.get("/wall/week").text
    assert 'data-start-photos="1"' in wc.get("/wall/rest?photos=1").text
    assert "data-start-photos" not in wc.get("/wall/rest").text
    WS.remove_photo(name)


def test_the_rail_calendar_button_opens_the_day_and_stays_lit_on_week_and_month(pc, wall):
    """The rail says Calendar and opens the Day view; Day, Week and Month all light it, and each page has the Day | Week | Month switch."""
    c, W, _, _ = pc
    wc = wall[0]
    _pair(wc, W)
    for path in ("/wall", "/wall/day", "/wall/week", "/wall/month"):
        page = wc.get(path).text
        assert re.search(r'class="tab[^"]*" href="/wall/day"', page) and ">Calendar<" in page, path
        assert 'href="/wall/week">Week</a>' not in re.search(r'<nav class="wrail".*?</nav>', page, re.S).group(0), "the rail has no Week button"
    for path in ("/wall/day", "/wall/week", "/wall/month"):
        page = wc.get(path).text
        assert re.search(r'class="tab on" href="/wall/day"', page), path + " lights the Calendar button"
        assert 'aria-label="Calendar view"' in page and 'href="/wall/day"' in page and 'href="/wall/week"' in page and 'href="/wall/month"' in page


def test_wall_pages_can_be_swiped_but_not_money(pc, wall):
    """wall.js turns a horizontal swipe into the rail's next / previous page, never Money, never on the resting clock."""
    c, W, _, _ = pc
    wc = wall[0]
    _pair(wc, W)
    js = wc.get("/static/wall.js").text
    assert "pointerup" in js and "/wall/money" in js and "[data-noswipe]" in js
    assert "touch-action: pan-y" in wc.get("/static/wall.css").text


def test_timed_page_rotation_setting(pc, wall, modules):
    """rotate_seconds: 0 (off) or 10-110, saved with the wall screen, on every page as body data-rotate, turned by wall.js."""
    c, W, _, _ = pc
    wc = wall[0]
    _pair(wc, W)
    ws, ea = modules("wall_screen"), modules("edit_actions")
    assert ws.settings()["rotate_seconds"] == 0
    d = ws.settings()
    base = (d["clock"], d["photos"], d["photo_seconds"], d["clock_seconds"], d["per_turn"], d["photos_from"], d["photos_to"],
            d["night_from"], d["night_to"])
    for bad in ("5", "111", "x"):
        with pytest.raises(ws.ScreenError):
            ws.clean(*base, rotate_seconds=bad)
    ok, _ = ea.wall_screen_set(ADULT, *base, rotate_seconds="30")
    assert ok and ws.settings()["rotate_seconds"] == 30
    assert 'data-rotate="30"' in wc.get("/wall").text
    assert "data-rotate" in wc.get("/static/wall.js").text
    ea.wall_screen_set(ADULT, *base, rotate_seconds="0")


def test_seasonal_looks_show_on_the_resting_clock_and_follow_the_switch(pc, wall, modules, monkeypatch):
    """Wall seasonal looks: a drawn backdrop and a chip on the resting clock on a festival day, the chip on other pages, the colours
    from /wall/season.css, a preview with ?season=, the Settings switch, and the windows the app wall receives."""
    c, W, _, _ = pc
    wc = wall[0]
    _pair(wc, W)
    ea, ws = modules("edit_actions"), modules("wall_season")
    ea.wall_seasonal_set(ADULT, True)
    monkeypatch.setenv("MITRAHOME_TODAY", "2026-03-03")
    page = wc.get("/wall/rest").text
    assert "sbackdrop" not in page and "season-" not in page, "an ordinary day has no look"
    monkeypatch.setenv("MITRAHOME_TODAY", "2026-10-30")
    page = wc.get("/wall/rest").text
    assert 'seasonal season-halloween' in page and 'class="sbackdrop"' in page and '<span class="schip">Halloween</span>' in page
    assert "anim-glow" in page and "anim-sway" in page and "style=" not in re.search(r'<svg class="sbackdrop".*?</svg>', page, re.S).group(0)
    week = wc.get("/wall/week").text
    assert '<span class="schip">Halloween</span>' in week and "sbackdrop" not in week and "/wall/season.css" in week
    css = wc.get("/wall/season.css")
    assert css.status_code == 200 and css.headers["content-type"].startswith("text/css")
    assert "body.season-halloween{--s-bg:#1a1024" in css.text and "body.season-diwali{" in css.text and "body.season-christmas{" in css.text
    monkeypatch.setenv("MITRAHOME_TODAY", "2026-03-03")
    for key, name, cls in (("diwali", "Diwali", "anim-flicker"), ("christmas", "Christmas", "anim-drift")):
        page = wc.get(f"/wall/rest?season={key}").text
        assert f"season-{key}" in page and f'<span class="schip">{name}</span>' in page and cls in page, key
    assert "season-" not in wc.get("/wall/rest?season=bogus").text
    ea.wall_seasonal_set(ADULT, False)
    monkeypatch.setenv("MITRAHOME_TODAY", "2026-10-30")
    assert "season-halloween" not in wc.get("/wall/rest").text, "switched off"
    assert ws.enabled() is False and ws.windows(dt.date(2026, 10, 30), 10, None, ws.enabled()) == []
    ea.wall_seasonal_set(ADULT, True)
    win = ws.windows(dt.date(2026, 10, 20), 20)
    assert [(w["key"], w["from"], w["to"]) for w in win] == [("halloween", "2026-10-28", "2026-10-31")]
    assert win[0]["colours"]["bg"] == "#1a1024" and win[0]["marks"][0]["mark"] == "pumpkin"
    wcopy = modules("wall_copy")
    con = modules("db").connect(modules("paths").DB, readonly=True)
    try:
        x = wcopy.extras(con, dt.datetime(2026, 10, 20, 9, 0))
    finally:
        con.close()
    assert x["season"][0]["key"] == "halloween" and x["season"][0]["to"] == "2026-10-31"
    assert {w["key"] for w in x["season"]} <= set(ws.LOOKS), "later looks in the 60 days (Thanksgiving from the holidays) follow"


def test_the_scrapbook_photo_style_is_offered_and_styled(pc, wall, modules):
    """Photo style Scrapbook page: in the Settings list, accepted by the screen settings, the stage gets st-scrapbook, and the wall's
    script and stylesheet know it (up to three prints, the months they were taken as one caption)."""
    c, W, ea, _ = pc
    WS = modules("wall_screen")
    assert "scrapbook" in WS.STYLES and WS.STYLE_NAMES["scrapbook"] == "scrapbook page"
    s = WS.clean("digital", True, "15", "45", "4", "07:00", "21:00", "22:00", "06:00", photo_style="scrapbook")
    assert s["photo_style"] == "scrapbook"
    pytest.importorskip("PIL.Image")
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), (90, 60, 20)).save(buf, "JPEG")
    photo = WS.add_photo("page.jpg", buf.getvalue())  # the stage is drawn only while some photo is kept
    _pair(wall[0], W)
    wid = _wall_id(W)
    ea_ = modules("edit_actions")
    ok, msg = ea_.wall_screen_own_set(ADULT, wid, True, "digital", True, "15", "45", "4", "07:00", "21:00", "22:00", "06:00",
                                      photo_style="scrapbook")
    assert ok, msg
    page = wall[0].get("/wall/rest").text
    assert 'class="stage st-scrapbook"' in page and 'data-photo-look="scrapbook"' in page
    css = wall[0].get("/static/wall.css").text
    for rule in (".stage.st-scrapbook", ".st-scrapbook .ph.c2", ".st-scrapbook .cap"):
        assert rule in css, rule
    js = wall[0].get("/static/wall.js").text
    assert "style === 'scrapbook'" in js
    ea_.wall_screen_own_set(ADULT, wid, False)  # back to the household's screen
    WS.remove_photo(photo)
