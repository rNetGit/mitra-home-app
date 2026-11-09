"""Card Wallet (migration 053, wallet.py, /wallet): cards from IDs, cars, policies and wallet_cards; whole numbers only for
the plate and membership / store / library cards; adults only; synced to phones with the ids scope; not in ask_sql."""
import datetime as D
import re
import sqlite3

import pytest

from conftest import db, q, run

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


def test_cards_numbers_and_rules(root, modules):
    ea = modules("edit_actions")
    ok, msg = ea.wallet_card_add(ADULT, kind="membership", title="Warehouse club", number="1110 2233 4455",
                                 where_hint="back, under the barcode", expires="2030-01-31")
    assert ok, msg
    assert q(root, "SELECT number, number_last4 FROM wallet_cards WHERE title='Warehouse club'") == [("1110 2233 4455", "4455")]
    assert ea.wallet_card_add(ADULT, kind="travel", title="Known traveler", number="TT1234567")[0] is False, \
        "only membership, store and library cards keep the whole number"
    assert ea.wallet_card_add(ADULT, kind="travel", title="Known traveler", number_last4="4567")[0] is True
    assert ea.wallet_card_add(ADULT, kind="home", title="Home", details="Wi-Fi Maple-Home, trash Tuesday")[0] is True
    assert ea.wallet_card_add(ADULT, kind="home", title="Home", details="acct 123456789012")[0] is False, "no full numbers in text"
    assert ea.wallet_card_add(KID, kind="library", title="Library", number="29001004211")[0] is False, "children cannot add"
    assert ea.wallet_card_add(ADULT, kind="bogus", title="X")[0] is False
    assert ea.wallet_card_add(ADULT, kind="other", title="X", member="Nobody")[0] is False
    with pytest.raises(sqlite3.IntegrityError):  # the table refuses a whole number on any other kind, too
        with db(root) as con:
            con.execute("INSERT INTO wallet_cards(kind, title, number) VALUES ('health', 'Plan', '123456789')")
    rid = q(root, "SELECT id FROM wallet_cards WHERE title='Warehouse club'")[0][0]
    assert ea.wallet_card_update(ADULT, rid, title="Club", number="")[0] is True
    assert q(root, "SELECT title, number FROM wallet_cards WHERE id=?", rid) == [("Club", None)]
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "wallet_card_add\tid=" in log and "2233" not in log and "Maple" not in log, "ids only in the edit log"
    assert ea.wallet_card_drop(KID, rid)[0] is False
    assert ea.wallet_card_drop(ADULT, rid)[0] is True and ea.wallet_card_drop(ADULT, rid)[0] is False

    r = run(["data/ask_sql.py", "SELECT number FROM wallet_cards"], root)
    assert r.returncode != 0 and "refused" in (r.stdout + r.stderr)


def test_car_plate_and_the_page_data(root, modules):
    ea, wl = modules("edit_actions"), modules("wallet")
    today = D.date.today()
    with db(root) as con:
        vid = con.execute("INSERT INTO vehicles(year, make, model, vin_last4, registration_expires, status) "
                          "VALUES (2021, 'Honda', 'CR-V', '4821', ?, 'active')",
                          ((today + D.timedelta(days=20)).isoformat(),)).lastrowid
        con.execute("INSERT OR REPLACE INTO id_documents(person, doc_type, number_last4, expires, active) "
                    "VALUES ('Alex', 'passport', '0918', ?, 1)", ((today - D.timedelta(days=3)).isoformat(),))
    ok, msg = ea.vehicle_details(ADULT, vid, color="Blue", body_type="suv", plate="kxr 482", plate_region="nj")
    assert ok, msg
    assert q(root, "SELECT plate, plate_region, plate_last4, color FROM vehicles WHERE id=?", vid) == [("KXR 482", "NJ", "R482", "blue")]
    assert ea.vehicle_details(ADULT, vid, plate="<script>")[0] is False
    assert ea.vehicle_details(ADULT, vid, body_type="spaceship")[0] is False
    assert ea.vehicle_details(KID, vid, plate="ABC")[0] is False
    assert ea.vehicle_details(ADULT, 99999, plate="ABC")[0] is False

    cards = wl.cards(today)
    car = next(c for c in cards if c["ref"] == f"vehicles:{vid}")
    assert car["group"] == "car" and car["plate"] == {"text": "KXR 482", "region": "NJ", "full": True}
    assert car["due"] == ("due in 20 days", "warn") and "windshield" in car["hint"] and "SUV" in car["sub"]
    pp = next(c for c in cards if c["title"] == "Passport" and "Alex" in c["sub"])
    assert pp["num"].endswith("0918") and pp["due"] == ("expired", "bad") and "photo page" in pp["hint"]
    assert all("0918" not in c["num"] or c["num"].startswith("•") for c in cards), "IDs show last4 only"
    p = wl.page("car", today)
    assert [g for g, _, _ in p["groups"]] == ["car"] and p["soon"] >= 2
    assert wl.due("2099-05-01", today) == ("May 2099", "ok") and wl.due(None, today) is None
    assert wl.grouped("111022334455") == "1110 2233 4455" and wl.grouped("2 9001 0042 1187") == "2 9001 0042 1187"


def test_vehicle_update_edits_details_and_keeps_the_plate_whole(root, modules, web):
    ea, wl = modules("edit_actions"), modules("wallet")
    with db(root) as con:
        vid = con.execute("INSERT INTO vehicles(year, make, model, vin_last4, plate_last4, status, notes) "
                          "VALUES (2019, 'Tesla', 'Model 3', '9295', '7486', 'active', 'old')").lastrowid
    car = next(c for c in wl.cards() if c["ref"] == f"vehicles:{vid}")
    assert car["plate"] == {"text": "\u2022\u2022\u2022\u2022 7486", "region": "", "full": False}, "last4 masked until a plate is entered"
    ok, msg = ea.vehicle_update(ADULT, vid, year="2020", make="Tesla", model="Model Y", plate="abc 7486", plate_region="ny",
                                owner="Sam & Pat", primary_driver="Pat", registration_expires="2027-03-23",
                                inspection_expires="2027-04-30", status="active", notes="")
    assert ok, msg
    assert q(root, "SELECT year, model, plate, plate_last4, plate_region, owner, primary_driver, registration_expires, "
                   "inspection_expires, notes, vin_last4 FROM vehicles WHERE id=?", vid) == [
        (2020, "Model Y", "ABC 7486", "7486", "NY", "Sam & Pat", "Pat", "2027-03-23", "2027-04-30", None, "9295")]
    car = next(c for c in wl.cards() if c["ref"] == f"vehicles:{vid}")
    assert car["plate"]["text"] == "ABC 7486" and car["plate"]["full"] is True
    assert ea.vehicle_update(ADULT, vid, notes="kept")[0] and q(root, "SELECT plate FROM vehicles WHERE id=?", vid) == [("ABC 7486",)], "None leaves a field alone"
    for bad in ({"plate": "<script>"}, {"year": "1800"}, {"registration_expires": "soon"}, {"status": "gone"},
                {"make": ""}, {"vin_last4": "12345"}):
        assert ea.vehicle_update(ADULT, vid, **bad)[0] is False, bad
    assert ea.vehicle_update(KID, vid, make="X")[0] is False and ea.vehicle_update(ADULT, 99999, make="X")[0] is False
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/records", params={"ref": f"vehicles:{vid}"}).text
    assert 'name="plate"' in page and 'value="ABC 7486"' in page and "Save details" in page
    assert "ABC 7486" in c.get("/wallet").text


def test_phone_sync_carries_the_wallet_to_adults_with_ids(root, modules):
    sy, dv = modules("sync_data"), modules("devices")
    adult = {"member": "Alex", "role": "adult", "scopes": ["ids"]}
    assert {"vehicles", "policies", "wallet_cards"} <= set(sy.sources_for(adult))
    assert not {"vehicles", "policies", "wallet_cards"} & set(sy.sources_for({**adult, "scopes": ["calendar"]}))
    assert not {"vehicles", "wallet_cards"} & set(sy.sources_for({"member": "Sam", "role": "limited", "scopes": ["ids"]}))
    with db(root) as con:
        assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE 'sync_wallet_cards_%'").fetchone()[0] == 3
    assert "ids" in dv.SCOPES


@pytest.fixture()
def web(root, modules):
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    return TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)


def _csrf(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)


def test_wallet_page_add_change_and_roles(root, web):
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/wallet")
    assert page.status_code == 200 and "Add a card" in page.text and 'href="/wallet"' in page.text
    assert "Reference copies, not official IDs" in page.text
    h = {"X-CSRF-Token": _csrf(c)}
    r = c.post("/wallet/card", data={"op": "add", "kind": "library", "title": "City library", "number": "2 9001 0042 1187"},
               headers=h)
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/wallet"
    page = c.get("/wallet").text
    assert "City library" in page and "2 9001 0042 1187" in page and "Added City library" in page
    rid = q(root, "SELECT id FROM wallet_cards WHERE title='City library'")[0][0]
    r = c.post("/wallet/card", data={"op": "drop", "id": str(rid)}, headers=h)
    assert "Tick" in c.get("/wallet").text and q(root, "SELECT status FROM wallet_cards WHERE id=?", rid) == [("active",)]
    c.post("/wallet/card", data={"op": "drop", "id": str(rid), "sure": "1"}, headers=h)
    assert q(root, "SELECT status FROM wallet_cards WHERE id=?", rid) == [("dropped",)]
    assert c.post("/wallet/card", data={"op": "nope"}, headers=h).status_code == 400
    with db(root) as con:
        vid = con.execute("INSERT INTO vehicles(year, make, model, status) VALUES (2019, 'Ford', 'Focus', 'active')").lastrowid
    c.post("/wallet/car", data={"id": str(vid), "plate": "ABC-1234", "plate_region": "NY", "color": "silver"}, headers=h)
    page = c.get("/wallet?g=car").text
    assert "ABC-1234" in page and "Plate and colour" in page
    assert c.get("/wallet?g=<script>").status_code == 200
    c.post("/logout", headers=h)
    k = web
    k.post("/login", data={"name": "Kid", "pin": "0000"})
    assert k.get("/wallet").status_code == 403



def test_search_parking_reminders_and_shortcut(root, modules, web):
    ea, wl, ex, ai = modules("edit_actions"), modules("wallet"), modules("expiries"), modules("action_items")
    today = D.date.today()
    with db(root) as con:
        vid = con.execute("INSERT INTO vehicles(year, make, model, status) VALUES (2020, 'Mazda', 'CX-5', 'active')").lastrowid
        vid2 = con.execute("INSERT INTO vehicles(year, make, model, plate_last4, status) VALUES (2012, 'Ford', 'Van', '7788', "
                           "'active')").lastrowid
    assert ea.vehicle_details(ADULT, vid, plate="ZZT 4410", plate_region="NY")[0]
    soon = (today + D.timedelta(days=10)).isoformat()
    assert ea.wallet_card_add(ADULT, kind="library", title="Town library", number="29001004211", expires=soon)[0]
    assert ea.wallet_card_add(ADULT, kind="home", title="Cabin", details="Wi-Fi Lakeview-5G")[0]

    assert [c["title"] for g in wl.page(q="lakeview wi-fi")["groups"] for c in g[2]] == ["Cabin"]
    assert any(c["plate"] and c["plate"]["text"] == "ZZT 4410" for g in wl.page(q="zzt")["groups"] for c in g[2])
    assert wl.page(q="nothing like this")["groups"] == []
    p = wl.parking()
    assert p["car"]["plate"]["full"], "opens on a car with a whole plate"
    assert wl.parking(vid)["car"]["plate"]["text"] == "ZZT 4410"
    assert wl.parking(vid2)["car"]["plate"] == {"text": "•••• 7788", "region": "", "full": False}
    assert {i for i, _ in p["cars"]} >= {vid, vid2}

    with db(root) as con:
        row = next(r for r in ex.rows(con, today) if r["type"] == "wallet_card")
        assert row["what"] == "Town library card" and row["days_left"] == 10 and row["ref"][0] == "wallet_cards"
        items = ai.collect_items(con, today, 60)
    assert any(i["title"] == "Town library card expires" and i["ref"][0] == "wallet_cards" for i in items)
    assert modules("records").where("wallet_cards", {})[0] == "papers"

    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    page = c.get("/wallet", params={"q": "zzt"}).text
    assert "ZZT 4410" in page and "Town library" not in page and 'for "zzt"' in page
    assert 'href="/wallet/park"' not in page and ">Parking<" not in page, "the Parking button is gone from the Family header"
    park = c.get("/wallet/park", params={"car": str(vid)}).text
    assert "ZZT 4410" in park and "data-wake" in park and 'data-copy="ZZT 4410"' in park
    assert "Only the last four" in c.get("/wallet/park", params={"car": str(vid2)}).text
    m = c.get("/manifest.webmanifest").json()
    assert any(s["url"] == "/wallet/park" for s in m["shortcuts"])


PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def test_photo_draft_ai_fill_check_save_and_the_scan_on_the_back(root, modules, web, monkeypatch):
    wl, llm = modules("wallet"), modules("llm")
    assert "document_id" in {r[1] for r in db(root).execute("PRAGMA table_info(wallet_cards)")}, "migration 054"
    assert wl.save_draft("card.exe", PNG)[0] is False and wl.save_draft("card.png", b"<html>")[0] is False
    ok, tok = wl.save_draft("card.png", PNG)
    assert ok and wl.draft_path(tok).name == f"{tok}.png" and wl.draft_path("../x") is None
    monkeypatch.setattr(llm, "photos_allowed", lambda s=None: "reading photos with AI is off")
    fields, msg = wl.read_photo(wl.draft_path(tok))
    assert fields == {} and "Not read by AI" in msg
    wl.drop_draft(tok)
    assert wl.draft_path(tok) is None

    monkeypatch.setattr(llm, "photos_allowed", lambda s=None: "")
    monkeypatch.setattr(llm, "extract_image_json", lambda *a, **k: ({
        "is_card": True, "kind": "library", "title": "Riverside library", "issuer": "Riverside Public Library",
        "number_last4": "1187", "expires": "2031-05-31", "where_hint": "back, under the barcode", "confidence": 0.9}, []))
    c = web
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    h = {"X-CSRF-Token": re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)}
    assert "Add a card from a photo" in c.get("/wallet").text
    r = c.post("/wallet/photo?ai=1", content=PNG, headers={**h, "X-Filename": "library.png",
                                                            "Content-Type": "application/octet-stream"})
    assert r.json() == {"ok": True, "redirect": "/wallet#wcheck"}
    page = c.get("/wallet").text
    assert "Check the card" in page and 'value="Riverside library"' in page and 'value="1187"' in page
    assert "Read by AI: check every field" in page
    img = c.get("/wallet/draft-photo")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    r = c.post("/wallet/card", data={"op": "add", "draft": "1", "kind": "library", "title": "Riverside library",
                                     "number": "2 9001 0042 1187", "expires": "2031-05-31"}, headers=h)
    assert r.headers["HX-Redirect"] == "/wallet"
    doc = q(root, "SELECT document_id FROM wallet_cards WHERE title='Riverside library'")[0][0]
    path = q(root, "SELECT filed_path FROM documents WHERE id=?", doc)[0][0]
    assert "/ids/" in path and path.endswith("_id.png") and (root / "archive" / path).is_file()
    page = c.get("/wallet").text
    assert "Check the card" not in page and f'src="/wallet/scan/{doc}"' in page
    s = c.get(f"/wallet/scan/{doc}")
    assert s.status_code == 200 and s.headers["content-type"] == "image/png"
    assert c.get("/wallet/scan/999999").status_code == 404

    c.post("/wallet/photo", content=PNG, headers={**h, "X-Filename": "x.png", "Content-Type": "application/octet-stream"})
    assert "Check the card" in c.get("/wallet").text
    c.post("/wallet/card", data={"op": "discard"}, headers=h)
    assert "Check the card" not in c.get("/wallet").text and c.get("/wallet/draft-photo").status_code == 404
    bad = c.post("/wallet/photo", content=b"MZ\x90\x00", headers={**h, "X-Filename": "x.png",
                                                                  "Content-Type": "application/octet-stream"})
    assert bad.status_code == 400 and not bad.json()["ok"]


def test_a_car_card_carries_its_filed_insurance_id_card(root, modules):
    wl = modules("wallet")
    with db(root) as con:
        a = con.execute("INSERT INTO vehicles(year, make, model, vin_last4, status) VALUES (2016, 'Mercedes-Benz', 'GLC', '8413', 'active')").lastrowid
        con.execute("INSERT INTO vehicles(year, make, model, vin_last4, status) VALUES (2019, 'Tesla', 'Model 3', '9295', 'active')")
        con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES "
                    "('2025/insurance/2025-10-10_acme_auto_5687_idcard_vin8413.pdf', 'policy', 'ACME', '2025-10-10')")
        new = con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES "
                          "('2026/insurance/2026-10-10_acme_auto_5687_idcard_vin8413.pdf', 'policy', 'ACME', '2026-10-10')").lastrowid
        con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES "
                    "('2026/insurance/2026-09-01_acme_auto_5687_declarations.pdf', 'policy', 'ACME', '2026-09-01')")
        con.commit()
    assert a
    cars = {c["title"]: c for c in wl.cards() if c["group"] == "car"}
    merc = cars["2016 Mercedes-Benz GLC"]["scan"]
    assert merc["id"] == new and merc["label"] == "insurance ID card" and merc["image"] is False, "the newest card of that VIN"
    assert cars["2019 Tesla Model 3"]["scan"] is None, "no ID card filed for that VIN"
