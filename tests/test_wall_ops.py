"""Taps an app wall made while the PC was off (B3 of the offline plan): applied in order through edit_actions as the wall,
once each (a repeat gets the first answer), a job ticked on an earlier day counts for that day, the PC refuses what the
wall may not do, and /api/wall/push serves a paired app wall only."""
import datetime as dt
import itertools

import pytest

TODAY = dt.date(2026, 10, 14)   # a Wednesday
_N = itertools.count(1)


@pytest.fixture()
def wo(modules, root):
    W, ops = modules("wall"), modules("wall_ops")
    con = W._con()
    for t in ("wall_ops", "wall_pairings", "walls"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    code = W.pair_start(con, "Kitchen wall", by="Alex")[0]
    _, w = W.pair_redeem(con, code, kind="app")
    yield W, ops, con, w
    con.close()


def _ids():
    n = next(_N)
    return lambda k: f"tap-{n:04d}-{k:04d}"


def _routine(con, weekdays="MO,WE"):
    n = next(_N)
    member = con.execute("SELECT name FROM members WHERE lower(role) IN ('child','limited','kid') ORDER BY id").fetchone()
    who = member[0] if member else "Sam"
    rid = con.execute("INSERT INTO routines(member, part, title, stars, weekdays, created_at) VALUES "
                      "(?, 'morning', ?, 2, ?, '2026-10-01T10:00:00')", (who, f"Job {n}", weekdays)).lastrowid
    con.commit()
    return rid, who


def _list(con, audience="family"):
    n = next(_N)
    lid = con.execute("INSERT INTO lists(name, kind, audience, created_at) VALUES (?,?,?,'2026-10-01T10:00:00')",
                      (f"List {n}", "shopping", audience)).lastrowid
    con.commit()
    return lid


def test_a_tick_from_an_earlier_day_counts_for_that_day_once(wo):
    W, ops, con, w = wo
    rid, _ = _routine(con)
    i = _ids()
    tap = [{"id": i(1), "op": "routine_tick", "routine_id": rid, "day": "2026-10-12", "done": True}]  # Monday
    res = ops.push(con, w, tap, today=TODAY)
    assert res[0]["status"] == "ok", res
    assert con.execute("SELECT day FROM routine_done WHERE routine_id=?", (rid,)).fetchall()[0][0] == "2026-10-12"
    again = ops.push(con, w, tap, today=TODAY)
    assert again[0]["status"] == "ok" and again[0]["repeat"] is True
    assert con.execute("SELECT COUNT(*) FROM routine_done WHERE routine_id=?", (rid,)).fetchone()[0] == 1


def test_ticks_the_pc_refuses(wo):
    W, ops, con, w = wo
    rid, _ = _routine(con)
    i = _ids()
    res = ops.push(con, w, [
        {"id": i(1), "op": "routine_tick", "routine_id": rid, "day": "2026-10-13", "done": True},   # Tuesday: not due
        {"id": i(2), "op": "routine_tick", "routine_id": rid, "day": "2026-09-14", "done": True},   # too long ago
        {"id": i(3), "op": "routine_tick", "routine_id": rid, "day": "2026-10-19", "done": True},   # not yet
        {"id": i(4), "op": "routine_tick", "routine_id": rid, "day": "yesterday"},
        {"id": i(5), "op": "bill_paid", "bill_id": 1},
        {"id": "x", "op": "list_add"},
    ], today=TODAY)
    assert [r["status"] for r in res] == ["rejected"] * 6
    assert "not due" in res[0]["message"] and "too late" in res[1]["message"] and "not come" in res[2]["message"]
    assert "does not know" in res[4]["message"]
    assert con.execute("SELECT COUNT(*) FROM routine_done WHERE routine_id=?", (rid,)).fetchone()[0] == 0


def test_list_taps_family_lists_only_and_in_order(wo):
    W, ops, con, w = wo
    fam, adl = _list(con), _list(con, "adults")
    i = _ids()
    res = ops.push(con, w, [{"id": i(1), "op": "list_add", "list_id": fam, "text": "milk"},
                            {"id": i(2), "op": "list_add", "list_id": adl, "text": "secret"}], today=TODAY)
    assert [r["status"] for r in res] == ["ok", "rejected"]
    item = con.execute("SELECT id FROM list_items WHERE list_id=? AND text='milk'", (fam,)).fetchone()[0]
    res = ops.push(con, w, [{"id": i(3), "op": "list_tick", "item_id": item, "done": True}], today=TODAY)
    assert res[0]["status"] == "ok"
    assert con.execute("SELECT status FROM list_items WHERE id=?", (item,)).fetchone()[0] == "done"
    assert con.execute("SELECT COUNT(*) FROM list_items WHERE list_id=?", (adl,)).fetchone()[0] == 0


def test_a_busy_database_is_retried_and_later_taps_wait(wo, monkeypatch, modules):
    W, ops, con, w = wo
    fam = _list(con)
    ea = modules("edit_actions")
    monkeypatch.setattr(ea, "list_item_add", lambda *a, **k: (False, ea.BUSY))
    i = _ids()
    res = ops.push(con, w, [{"id": i(1), "op": "list_add", "list_id": fam, "text": "a"},
                            {"id": i(2), "op": "list_add", "list_id": fam, "text": "b"}], today=TODAY)
    assert [r["status"] for r in res] == ["retry", "retry"]
    assert con.execute("SELECT COUNT(*) FROM wall_ops WHERE client_id IN (?,?)", (i(1), i(2))).fetchone()[0] == 0


def test_api_push_for_a_paired_app_wall_only(root, modules, wo):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    W, ops, con, w = wo
    code = W.pretty_code(W.pair_start(con, "Hall wall", by="Alex")[0])
    modules("auth").clear_failures("#wall")
    c = TestClient(modules("webapp.app").app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    tok = c.post("/api/wall/pair", json={"code": code}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    fam = _list(con)
    i = _ids()
    r = c.post("/api/wall/push", json={"ops": [{"id": i(1), "op": "list_add", "list_id": fam, "text": "eggs"}]}, headers=h)
    assert r.status_code == 200 and r.json()["results"][0]["status"] == "ok"
    assert c.post("/api/wall/push", json={"ops": []}).status_code == 401
    assert c.post("/api/wall/push", json={"ops": "x"}, headers=h).status_code == 400
    assert c.post("/api/wall/push", json={"ops": [{}] * 51}, headers=h).status_code == 400


def test_a_face_picked_on_the_app_wall_becomes_its_own_screen(wo, modules):
    W, ops, con, w = wo
    WS = modules("wall_screen")
    i = _ids()
    res = ops.push(con, w, [{"id": i(1), "op": "face_set", "clock": "word"},
                            {"id": i(2), "op": "face_set", "clock": "sundial"}], today=TODAY)
    assert [r["status"] for r in res] == ["ok", "rejected"], res
    assert WS.own_screen(w["id"])["clock"] == "word"



def test_a_photo_look_picked_on_the_app_wall_becomes_its_own_screen(wo, modules):
    W, ops, con, w = wo
    WS = modules("wall_screen")
    i = _ids()
    res = ops.push(con, w, [{"id": i(1), "op": "photo_style_set", "style": "scrapbook"},
                            {"id": i(2), "op": "photo_style_set", "style": "polaroid"},
                            {"id": i(3), "op": "photo_style_set", "style": 3}], today=TODAY)
    assert [r["status"] for r in res][:2] == ["ok", "rejected"], res
    assert res[2]["status"] != "ok"
    assert WS.own_screen(w["id"])["photo_style"] == "scrapbook"
    assert WS.settings()["photo_style"] != "scrapbook", "only that wall changed"
