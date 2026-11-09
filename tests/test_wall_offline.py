"""The Mitra Wall when the PC is off (A1 of the offline plan): /wall/ping answers a paired wall, refuses a removed one and
plain http from another machine; every wall page carries the time it was made and the offline line; wall.js asks the PC
before every reload or page change instead of navigating blindly."""
import re

import pytest


@pytest.fixture()
def wall(root, modules):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    app_mod, routes, W = modules("webapp.app"), modules("webapp.routes_wall"), modules("wall")
    con = W._con()
    for t in ("wall_pairings", "walls"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    code = W.pair_start(con, "Kitchen wall", by="Alex")[0]
    con.close()
    routes._csrf.clear()
    c = TestClient(app_mod.app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    assert c.get("/wall/ping").status_code == 401, "no wall yet"
    assert c.post("/wall/pair", data={"code": W.pretty_code(code)}).status_code == 303
    return c, W


def test_ping_answers_a_paired_wall_and_refuses_a_removed_one(wall, modules):
    c, W = wall
    r = c.get("/wall/ping")
    assert r.status_code == 204 and r.content == b"" and r.headers["cache-control"] == "no-store"
    con = W._con()
    wid = con.execute("SELECT id FROM walls WHERE revoked_at IS NULL").fetchone()[0]
    W.revoke(con, wid)
    con.commit()
    con.close()
    assert c.get("/wall/ping").status_code == 401, "removed: wall.js opens the pairing page"
    from fastapi.testclient import TestClient
    plain = TestClient(modules("webapp.app").app, base_url="http://192.168.1.50:8601", follow_redirects=False)
    assert plain.get("/wall/ping").status_code == 403, "plain http from another machine"


def test_pages_carry_the_time_they_were_made_and_the_offline_line(wall):
    c, _ = wall
    for path in ("/wall", "/wall/rest", "/wall/week", "/wall/month", "/wall/lists"):  # Chores is off until ticked
        page = c.get(path).text
        assert re.search(r'data-made="\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d"', page), path
        assert 'id="woff"' in page and " style=" not in page, path


def test_wall_js_asks_the_pc_before_leaving_a_screen(modules):
    js = (modules("paths").ROOT / "data" / "webapp" / "static" / "wall.js").read_text(encoding="utf-8")
    assert "/wall/ping" in js and "showOffline" in js
    nav = re.findall(r"location\.(?:reload\(\)|href\s*=|replace\()", js)
    assert len(nav) == 5, "only go() after a ping, and the follow-up of a POST the PC just answered"
    css = (modules("paths").ROOT / "data" / "webapp" / "static" / "wall.css").read_text(encoding="utf-8")
    assert ".woff" in css
