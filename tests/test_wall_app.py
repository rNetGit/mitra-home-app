"""The Mitra Wall as an app (B1 of the offline plan): the wall code pairs the Mitra Home app in wall mode once; its token
is kept as a hash only, works only on /api/wall/* (never the wall pages, never a phone's /api/ routes, never an adult
page), a removed app wall is told to wipe its copy, and Settings shows a second QR with the PC's key for the app."""
import json

import pytest


@pytest.fixture()
def api(root, modules):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    app_mod, W = modules("webapp.app"), modules("wall")
    con = W._con()
    for t in ("wall_ops", "wall_pairings", "walls"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    modules("auth").clear_failures("#wall")
    return TestClient(app_mod.app, base_url="https://127.0.0.1:8701", follow_redirects=False), W


def _code(W, name="Kitchen wall"):
    con = W._con()
    try:
        return W.pretty_code(W.pair_start(con, name, by="Alex")[0])
    finally:
        con.close()


def _pair(c, W):
    r = c.post("/api/wall/pair", json={"code": _code(W), "version": "0.19.0"})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_app_pairs_once_and_keeps_only_a_hash(api):
    c, W = api
    code = _code(W)
    r = c.post("/api/wall/pair", json={"code": code, "version": "0.19.0"})
    body = r.json()
    assert r.status_code == 200 and body["wall"]["kind"] == "app" and len(body["token"]) == W.TOKEN_LEN
    assert c.post("/api/wall/pair", json={"code": code}).status_code == 401, "a code works once"
    con = W._con()
    rows = [dict(x) for x in con.execute("SELECT * FROM walls")]
    con.close()
    assert body["token"] not in json.dumps(rows) and rows[0]["kind"] == "app" and rows[0]["app_version"] == "0.19.0"
    assert c.post("/api/wall/pair", content=b"not json").status_code == 401


def test_an_app_token_opens_only_the_wall_api(api, modules):
    c, W = api
    tok = _pair(c, W)["token"]
    h = {"Authorization": f"Bearer {tok}"}
    r = c.get("/api/wall/ping", headers=h)
    assert r.status_code == 200 and r.json()["wall"]["name"] == "Kitchen wall"
    assert c.get("/api/wall/ping").status_code == 401
    for path in ("/api/ping", "/api/sync/pull"):
        assert c.get(path, headers=h).status_code == 401, f"a wall is not a phone: {path}"
    c.cookies.set(modules("webapp.routes_wall").COOKIE, tok)
    assert c.get("/wall").status_code == 200 and "Pair this wall" in c.get("/wall").text, "the app token is no cookie"
    c.cookies.clear()
    assert c.get("/money", headers=h).status_code in (303, 401, 403)


def test_a_browser_wall_cookie_never_opens_the_api_and_a_removed_app_wall_wipes(api, modules):
    c, W = api
    con = W._con()
    btok, bw = W.pair_redeem(con, _code(W, "Hall wall"))
    con.close()
    assert c.get("/api/wall/ping", headers={"Authorization": f"Bearer {btok}"}).status_code == 401
    got = _pair(c, W)
    con = W._con()
    assert W.revoke(con, got["wall"]["id"])
    con.close()
    r = c.get("/api/wall/ping", headers={"Authorization": f"Bearer {got['token']}"})
    assert r.status_code == 401 and r.json() == {"error": "revoked", "wipe": True}


def test_plain_http_from_another_machine_is_refused(modules, api):
    from fastapi.testclient import TestClient
    plain = TestClient(modules("webapp.app").app, base_url="http://192.168.1.50:8601")
    assert plain.post("/api/wall/pair", json={"code": "ABCD-2345"}).status_code == 403
    assert plain.get("/api/wall/ping").status_code == 403


def test_settings_listing_shows_the_kind_and_the_age(api):
    c, W = api
    _pair(c, W)
    con = W._con()
    rows = W.listing(con)
    con.close()
    assert rows[0]["kind"] == "app" and rows[0]["last_sync"] == "" and rows[0]["sync_days"] is None


def test_a_wall_that_has_not_updated_for_two_weeks_gets_a_line_on_today(api, modules):
    import datetime as dt
    c, W = api
    wid = _pair(c, W)["wall"]["id"]
    con = W._con()
    now = dt.datetime.now().replace(microsecond=0)
    assert W.stale(con, now) == [], "paired today: not late yet"
    con.execute("UPDATE walls SET last_sync=? WHERE id=?", ((now - dt.timedelta(days=16)).isoformat(), wid))
    con.commit()
    assert W.stale(con, now) == [{"name": "Kitchen wall", "days": 16}]
    con.close()
    app = modules("webapp.app")
    line = app.wall_line({"name": "Alex", "role": "adult"})
    assert line and "Kitchen wall last updated 16 days ago" in line["text"]
    assert app.wall_line({"name": "Sam", "role": "limited"}) is None


def test_settings_shows_a_second_code_for_the_app(api, modules, monkeypatch):
    sd = modules("settings_data")
    monkeypatch.setattr(modules("auth"), "users", lambda: [{"name": "Alex", "role": "adult"}])  # pairing needs a PIN
    monkeypatch.setattr(sd, "phones_lan", lambda: {"on": True, "ip": "192.168.1.20", "port": 8701, "fp": "ab" * 32,
                                                   "key": "cd" * 32, "fp_pretty": "AB:AB"})
    ok, msg, pair = sd.wall_pair({"name": "Alex", "role": "adult"}, True, "Kitchen wall")
    assert ok, msg
    assert pair["qr"].startswith("data:image/svg") and pair["app_qr"].startswith("data:image/svg")
    assert pair["url"].startswith("https://192.168.1.20:8701/wall?code=")
    # the same payload as text for a tablet without a scanner (Amazon Fire): one paste in the app
    assert json.loads(pair["app_text"]) == {"v": 1, "h": "192.168.1.20", "p": 8701, "fp": "ab" * 32,
                                            "w": pair["code"], "k": "cd" * 32}
    assert pair["app_plain"] == f"192.168.1.20:8701 {pair['code']} {'ab' * 32}"


def test_wall_family_name_is_not_doubled(modules, monkeypatch):
    wc = modules("wall_copy")
    for name, want in (("Rivera", "The Rivera Family"), ("Mock Family", "The Mock Family"), ("The Patels", "The Patels")):
        monkeypatch.setattr(wc.config, "family", lambda n=name: {"family_name": n})
        assert wc.family_name() == want


def _adult_pin(modules, monkeypatch):
    auth = modules("auth")
    users = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
             {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    monkeypatch.setattr(auth, "users", lambda: users)
    return auth


def test_money_on_the_app_wall_needs_an_adults_pin_and_closes_itself(api, modules, monkeypatch):
    c, W = api
    auth = _adult_pin(modules, monkeypatch)
    auth.THROTTLE.unlink(missing_ok=True)
    routes = modules("webapp.routes_wall")
    routes._unlock.clear()
    h = {"Authorization": f"Bearer {_pair(c, W)['token']}"}
    assert c.get("/api/wall/money").status_code == 401, "no token, no money"
    assert c.get("/api/wall/money", headers=h).status_code == 403 and c.get("/api/wall/money", headers=h).json() == {"error": "locked"}
    assert c.post("/api/wall/money/unlock", headers=h, json={"name": "Ann", "pin": "9999"}).status_code == 401
    assert c.post("/api/wall/money/unlock", headers=h, json={"name": "Kid", "pin": "0000"}).status_code == 401, "children never unlock"
    r = c.post("/api/wall/money/unlock", headers=h, json={"name": "Ann", "pin": "1234"})
    assert r.status_code == 200 and r.json() == {"by": "Ann", "seconds": routes.UNLOCK_SECONDS}
    body = c.get("/api/wall/money", headers=h).json()
    assert {"paid", "upcoming", "paid_total", "upcoming_total", "late_n", "seconds"} <= set(body) and 0 < body["seconds"] <= routes.UNLOCK_SECONDS
    assert c.post("/api/wall/money/lock", headers=h).status_code == 200
    assert c.get("/api/wall/money", headers=h).status_code == 403, "the lock button closes it at once"
    routes._unlock.clear()
