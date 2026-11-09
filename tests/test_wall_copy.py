"""The app wall's copy (B2 of the offline plan): sync_data role "wall" carries what a wall shows (calendar, family lists,
children's jobs, rewards, meals, safe to-dos) for the next weeks and nothing else; wall_copy.extras adds what the PC
works out; /api/wall/pull, /extras and /photo serve them to a paired app wall only."""
import datetime as dt
import itertools
import json

import pytest

NOW = dt.datetime(2026, 10, 14, 9, 0, 0)
_N = itertools.count(1)


@pytest.fixture()
def wc(modules, root):
    s, W, c = modules("sync_data"), modules("wall"), modules("wall_copy")
    con = W._con()
    for t in ("wall_ops", "wall_pairings", "walls"):
        con.execute(f"DELETE FROM {t}")
    con.commit()
    yield s, W, c, con
    con.close()


def _all(s, con, dev, cursor=None, page=500):
    rows = {}
    while True:
        body = s.pull(con, dev, cursor, page=page, today=NOW.date())
        for name, ch in body["changes"].items():
            for r in ch["upsert"]:
                rows.setdefault(name, {})[r["id"]] = r
        cursor = body["cursor"]
        if not body["more"]:
            return rows, body


def _secret_household(con):
    """A few rows of every kind, fresh names each call (the database is shared by this module's tests)."""
    ins, n = con.execute, next(_N)
    fam = ins("INSERT INTO lists(name, kind, audience, created_at) VALUES (?,'shopping','family','2026-10-01T10:00:00')",
              (f"Groceries {n}",)).lastrowid
    adl = ins("INSERT INTO lists(name, kind, audience, created_at) VALUES (?,'todo','adults','2026-10-01T10:00:00')",
              (f"Gifts {n}",)).lastrowid
    ins("INSERT INTO list_items(list_id, text, added_at) VALUES (?, 'milk', '2026-10-01T10:00:00')", (fam,))
    ins("INSERT INTO list_items(list_id, text, added_at) VALUES (?, 'SECRET-BIKE', '2026-10-01T10:00:00')", (adl,))
    ins("INSERT INTO life_items(domain, member, title, due_date, amount, notes) VALUES "
        "('school', 'Sam', 'Field trip form', '2026-10-20', 15.25, 'SECRET-NOTE')")
    ins("INSERT INTO life_items(domain, member, title, due_date) VALUES ('legal', 'Alex', 'SECRET-TRUST', '2026-10-20')")
    ins("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES "
        "('Sam', 'SECRET-DOCTOR', 'Checkup', '2026-10-21T09:00')")
    r = ins("INSERT INTO routines(member, part, title, stars, weekdays, created_at) VALUES "
            "('Sam', 'morning', 'Make bed', 2, 'MO,WE', '2026-10-01T10:00:00')").lastrowid
    ins("INSERT INTO routine_done(routine_id, day, stars, done_by, done_at) VALUES (?, '2026-10-12', 2, 'Sam', '2026-10-12T08:00:00')", (r,))
    ins("INSERT INTO routine_done(routine_id, day, stars, done_by, done_at) VALUES (?, '2026-08-01', 2, 'Sam', '2026-08-01T08:00:00')", (r,))
    ins("INSERT OR REPLACE INTO meal_plan(day, slot, title, added_at) VALUES ('2026-10-15', 'dinner', 'Tacos', '2026-10-01T10:00:00')")
    ins("INSERT OR REPLACE INTO meal_plan(day, slot, title, added_at) VALUES ('2026-08-15', 'dinner', 'Old soup', '2026-08-01T10:00:00')")
    con.commit()
    return fam, adl, r


def test_the_wall_copy_holds_what_a_wall_shows_and_nothing_else(wc):
    s, W, c, con = wc
    fam, adl, rid = _secret_household(con)
    dev = c.device({"id": 1, "name": "Kitchen wall"})
    rows, body = _all(s, con, dev)
    assert set(body["sources"]) == {"people", "appointments", "events", "activities", "days", "lists", "list_items",
                                    "needs", "routines", "routine_done", "rewards", "reward_claims", "meals", "recipes"}
    for money in ("bills", "subscriptions", "transactions", "accounts", "budget", "notes", "id_documents", "vehicles",
                  "policies", "wallet_cards", "life_items", "own"):
        assert money not in body["sources"], money
    assert fam in rows["lists"] and adl not in rows["lists"]
    texts = {r["text"] for r in rows["list_items"].values()}
    assert "milk" in texts and "SECRET-BIKE" not in texts
    titles = {r["title"] for r in rows["needs"].values()}
    assert "Field trip form" in titles and "SECRET-TRUST" not in titles
    assert all(set(r) == {"id", "person", "purpose", "appt_datetime"} for r in rows["appointments"].values())
    days = {r["day"] for r in rows["routine_done"].values() if r["routine_id"] == rid}
    assert rid in rows["routines"] and days == {"2026-10-12"}, "14 days back"
    meals = {r["title"] for r in rows["meals"].values()}
    assert "Tacos" in meals and "Old soup" not in meals
    flat = json.dumps(rows)
    for secret in ("SECRET-BIKE", "SECRET-NOTE", "SECRET-TRUST", "SECRET-DOCTOR", "15.25", "amount", "provider"):
        assert secret not in flat, secret


def test_changes_reach_the_wall_and_a_wall_cursor_is_no_phone_cursor(wc, modules):
    s, W, c, con = wc
    dev = c.device({"id": 1, "name": "Kitchen wall"})
    fam, _, rid = _secret_household(con)
    _, body = _all(s, con, dev)
    con.execute("INSERT INTO routine_done(routine_id, day, stars, done_by, done_at) VALUES (?, '2026-10-14', 2, 'Sam', "
                "'2026-10-14T08:00:00')", (rid,))
    con.execute("UPDATE lists SET audience='adults' WHERE id=?", (fam,))
    con.commit()
    ch = s.pull(con, dev, body["cursor"])["changes"]
    assert [r["day"] for r in ch["routine_done"]["upsert"]] == ["2026-10-14"]
    assert ch["lists"]["delete"] == [fam] and ch["list_items"]["delete"], "an adults-only list leaves with its items"
    phone = {"id": 9, "member": "Alex", "role": "adult", "scopes": ["calendar", "lists"]}
    assert s.pull(con, phone, body["cursor"])["reset"] is True


def test_extras_carry_settings_days_goals_and_no_money(wc, modules):
    s, W, c, con = wc
    _secret_household(con)
    x = c.extras(con, NOW)
    assert set(x) >= {"made_at", "family", "screen", "people", "special_days", "todo", "children", "weather", "photos"}
    assert x["screen"]["clock"] in modules("wall_screen").FACES
    assert any(d["start"] >= "2026-10-14" for d in x["special_days"]), "the year ahead's holidays"
    sam = next(k for k in x["children"] if k["name"] == "Sam")
    assert sam["balance"] >= 4 and "cents" not in json.dumps(x["children"])
    for t in x["todo"] or []:
        assert set(t) == {"date", "title", "kind", "who", "late"}


@pytest.fixture()
def api(root, modules, wc):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    s, W, c, con = wc
    code = W.pretty_code(W.pair_start(con, "Kitchen wall", by="Alex")[0])
    modules("auth").clear_failures("#wall")
    client = TestClient(modules("webapp.app").app, base_url="https://127.0.0.1:8701", follow_redirects=False)
    tok = client.post("/api/wall/pair", json={"code": code}).json()["token"]
    return client, {"Authorization": f"Bearer {tok}"}, W, con


def test_api_pull_extras_and_photos(api):
    client, h, W, con = api
    body = client.get("/api/wall/pull", headers=h).json()
    assert "routines" in body["sources"] and body["reset"] is True and "cursor" in body
    while body.get("more"):
        body = client.get("/api/wall/pull", params={"cursor": body["cursor"]}, headers=h).json()
    assert W.listing(con)[0]["last_sync"], "Settings shows the last update"
    x = client.get("/api/wall/extras", headers=h).json()
    assert x["family"] and "screen" in x
    assert client.get("/api/wall/photo/0123456789abcdef.jpg", headers=h).status_code == 404
    assert client.get("/api/wall/photo/..%2Ffamily.db", headers=h).status_code == 404
    for path in ("/api/wall/pull", "/api/wall/extras", "/api/wall/photo/0123456789abcdef.jpg"):
        assert client.get(path).status_code == 401, path


def test_todo_leaves_out_life_items_the_wall_has_as_needs(wc, monkeypatch, modules):
    s, W, c, con = wc
    WD = modules("wall_data")
    d = NOW.date()
    monkeypatch.setattr(WD, "todo_items", lambda *a, **k: [
        {"date": d, "title": "Field trip form (Sam)", "kind": "School", "who": ["Sam"], "late": False, "ref": "life_items"},
        {"date": d, "title": "Car inspection", "kind": "Vehicle", "who": [], "late": False, "ref": "vehicles"}])
    assert [t["title"] for t in c.todo(con, d, [])] == ["Car inspection"]
