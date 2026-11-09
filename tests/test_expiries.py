"""Expiry reminders generalised (data/expiries.py): one list across ID documents, vehicles, warranties, vaccinations and
insurance terms; a lead time per type (config/expiries.json over the country profile over built-in defaults) that the
existing alert providers read; no duplicate warranty rows; the edit_actions gate; the CLI and the digest section."""
import datetime as D
import json

import pytest

from conftest import db, q, run

TODAY = D.date(2026, 10, 8)


@pytest.fixture(scope="module")
def ex(root, modules):
    con = db(root)
    con.execute("DELETE FROM id_documents")
    con.execute("DELETE FROM home_assets")
    con.execute("DELETE FROM vehicles")
    con.execute("DELETE FROM policies")
    con.execute("DELETE FROM life_items WHERE domain='vaccine'")
    con.execute("INSERT INTO id_documents(person, doc_type, number_last4, expires) VALUES ('Alex', 'passport', 'A123', '2027-05-01')")  # 205d: inside 274
    con.execute("INSERT INTO id_documents(person, doc_type, expires) VALUES ('Alex', 'drivers_license', '2027-05-01')")  # 205d: outside 120
    con.execute("INSERT INTO id_documents(person, doc_type) VALUES ('Sam', 'passport')")  # needs a date
    con.execute("INSERT INTO vehicles(year, make, model, plate_last4, status, registration_expires, inspection_expires) "
                "VALUES (2019, 'Zorro', 'Wagon', 'Z999', 'active', '2026-11-20', '2027-03-01')")  # reg 43d (in 60), insp 144d (out of 45)
    con.execute("INSERT INTO home_assets(name, category, warranty_end) VALUES ('Zephyr fridge', 'appliance', '2026-12-01')")  # 54d: in 90
    con.execute("INSERT INTO life_items(domain, member, title, due_date, lead_days, status) VALUES ('vaccine', 'Sam', 'Tetanus booster', '2026-10-30', 14, 'open')")  # 22d
    con.execute("INSERT INTO policies(kind, carrier, policy_last4, term_end, status) VALUES ('auto', 'Zenith Mutual', '7788', '2026-10-20', 'active')")  # 12d
    con.commit()
    con.close()
    (root / "config" / "expiries.json").unlink(missing_ok=True)
    return modules("expiries")


def _by(rows, typ, who=None):
    return [r for r in rows if r["type"] == typ and (who is None or r["who"] == who)]


def test_rows_cover_every_source_with_status_and_lead(root, ex):
    con = db(root)
    try:
        rows = ex.rows(con, TODAY)
    finally:
        con.close()
    types = {r["type"] for r in rows}
    assert {"passport", "drivers_license", "vehicle_registration", "vehicle_inspection", "warranty", "vaccination", "insurance"} <= types
    p = _by(rows, "passport", "Alex")[0]
    assert p["lead_days"] == 274 and p["days_left"] == 205 and p["status"].startswith("renew soon") and p["last4"] == "A123"
    assert _by(rows, "drivers_license")[0]["status"] == "ok" and _by(rows, "drivers_license")[0]["lead_days"] == 120
    assert _by(rows, "passport", "Sam")[0]["status"] == "needs a date" and rows[-1]["status"] == "needs a date", "no date sorts last"
    reg, insp = _by(rows, "vehicle_registration")[0], _by(rows, "vehicle_inspection")[0]
    assert reg["who"] == "2019 Zorro Wagon" and reg["lead_days"] == 60 and reg["status"].startswith("renew soon")
    assert insp["lead_days"] == 45 and insp["status"] == "ok" and insp["last4"] == "Z999"
    w = _by(rows, "warranty")[0]
    assert w["what"] == "Zephyr fridge warranty" and w["lead_days"] == 90 and w["status"].startswith("renew soon")
    vx = _by(rows, "vaccination")[0]
    assert vx["who"] == "Sam" and vx["what"] == "Tetanus booster" and vx["lead_days"] == 30 and vx["status"].startswith("renew soon")
    ins = _by(rows, "insurance")[0]
    assert ins["who"] == "Zenith Mutual" and ins["what"] == "auto policy" and ins["ref"] == ("policies", ins["ref"][1])
    assert rows[0]["expires"] == min(r["expires"] for r in rows if r["expires"]), "soonest first"
    con = db(root)
    try:
        soon = ex.soon(con, TODAY)
        need = ex.needs_date(con, TODAY)
    finally:
        con.close()
    assert {r["type"] for r in soon} == {"passport", "vehicle_registration", "warranty", "vaccination", "insurance"}
    assert [r["who"] for r in need] == ["Sam"]
    assert {r["type"] for r in ex.leads()} == set(ex.types()) and not any(r["custom"] for r in ex.leads())


def test_lead_precedence_config_over_country_over_default(root, ex):
    assert ex.lead_days("passport") == 274 and ex.lead_days("drivers_license") == 120 and ex.lead_days("warranty") == 90
    assert ex.set_lead("warranty", 10) == 10 and ex.lead_days("warranty") == 10
    saved = json.loads((root / "config" / "expiries.json").read_text(encoding="utf-8"))
    assert saved["lead_days"] == {"warranty": 10}
    assert [r for r in ex.leads() if r["type"] == "warranty"][0] == {"type": "warranty", "lead_days": 10, "default": 90, "custom": True}
    with pytest.raises(ValueError):
        ex.set_lead("warranty", 9999)
    with pytest.raises(ValueError):
        ex.set_lead("spaceship", 5)
    (root / "config" / "expiries.json").write_text('{"lead_days": {"passport": "lots"}}', encoding="utf-8")
    assert ex.lead_days("passport") == 274, "a bad value falls back"
    (root / "config" / "expiries.json").write_text("not json", encoding="utf-8")
    assert ex.lead_days("warranty") == 90, "a broken file falls back"
    assert ex.set_lead("warranty", None) == 90
    assert json.loads((root / "config" / "expiries.json").read_text(encoding="utf-8")) == {"lead_days": {}}


def test_providers_read_the_lead_and_warranties_are_not_doubled(root, ex, modules):
    ai, assets, idd = modules("action_items"), modules("assets"), modules("id_docs")
    con = db(root)
    try:
        items = ai.collect_items(con, TODAY, 365, raw=True)
        titles = [i["title"] for i in items]
        assert titles.count("Zephyr fridge warranty ends") == 1, titles
        assert not any(t.startswith("Warranty ends:") for t in titles), "the old second 'Home' row is gone"
        assert "2019 Zorro Wagon registration expires" in titles and "2019 Zorro Wagon inspection expires" not in titles, \
            "inspection 144 days out is beyond its 45-day lead even at a 365-day horizon"
        assert any(t.startswith("Alex passport expires") for t in titles)
        assert not any(t.startswith("Alex drivers license expires") for t in titles)
        assert any("Tetanus booster" in t for t in titles), "vaccine 22 days out is inside the 30-day vaccination lead (row says 14)"
        ex.set_lead("vehicle_inspection", 200)
        ex.set_lead("vaccination", 5)
        ex.set_lead("warranty", 20)
        ex.set_lead("drivers_license", 365)
        items = ai.collect_items(con, TODAY, 365, raw=True)
        titles = [i["title"] for i in items]
        assert "2019 Zorro Wagon inspection expires" in titles
        assert not any("Tetanus booster" in t for t in titles), "22 days out: type lead 5 and the row's own 14 are both shorter"
        assert not any("Zephyr fridge" in t for t in titles), "warranty 54 days out, lead now 20"
        assert any(t.startswith("Alex drivers license expires") for t in titles)
        assert [r for r in assets.rows(con, TODAY) if r["name"] == "Zephyr fridge"][0]["status"] == "under warranty"
        assert [r for r in idd.rows(con, TODAY) if r["doc_type"] == "drivers_license"][0]["lead_days"] == 365
    finally:
        con.close()
        for t in ("vehicle_inspection", "vaccination", "warranty", "drivers_license"):
            ex.set_lead(t, None)


def test_edit_actions_set_ids_and_leads_for_adults_only(root, ex, modules):
    ea = modules("edit_actions")
    adult, kid = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}
    assert not ea.id_doc_set(kid, "Sam", "passport", "2030-01-01")[0]
    ok, msg = ea.id_doc_set(adult, "sam", "passport", "2030-01-01", "P9")
    assert ok and "Sam" in msg and q(root, "select expires, number_last4, notes from id_documents where person='Sam' and doc_type='passport'") == [("2030-01-01", "P9", None)]
    ok, msg = ea.id_doc_set(adult, "Alex", "state_id", "2031-02-03")
    assert ok and q(root, "select expires from id_documents where person='Alex' and doc_type='state_id'") == [("2031-02-03",)], "created when missing"
    assert not ea.id_doc_set(adult, "Nobody", "passport", "2030-01-01")[0]
    assert not ea.id_doc_set(adult, "Alex", "vehicle_registration", "2030-01-01")[0], "vehicle dates live on the vehicle"
    assert not ea.id_doc_set(adult, "Alex", "passport", "01/02/2030")[0]
    assert not ea.id_doc_set(adult, "Alex", "passport", "2030-01-01", "123456789")[0], "full numbers are refused"
    assert not ea.expiry_lead_set(kid, "warranty", 5)[0]
    ok, msg = ea.expiry_lead_set(adult, "warranty", 45)
    assert ok and "45 days" in msg and ex.lead_days("warranty") == 45
    assert not ea.expiry_lead_set(adult, "warranty", 5000)[0] and not ea.expiry_lead_set(adult, "nope", 5)[0]
    assert ea.expiry_lead_set(adult, "warranty", "")[0] and ex.lead_days("warranty") == 90
    elog = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "id_doc_set" in elog and "expiry_lead_set" in elog and "P9" not in elog


def test_cli_and_digest(root, ex):
    con = db(root)
    con.execute("UPDATE id_documents SET expires=NULL WHERE person='Sam' AND doc_type='passport'")
    con.commit()
    con.close()
    r = run(["data/expiries.py", "list"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert "Zephyr fridge warranty" in r.stdout and "needs a date" in r.stdout, r.stdout
    r = run(["data/expiries.py", "lead", "warranty", "33"], root)
    assert r.returncode == 0 and "33 days" in r.stdout
    r = run(["data/expiries.py", "leads"], root)
    assert "warranty                 33 days  (default 90)" in r.stdout, r.stdout
    assert run(["data/expiries.py", "lead", "warranty", "-1"], root).returncode != 0
    assert run(["data/expiries.py", "lead", "warranty", "default"], root).returncode == 0
    assert "(default" not in run(["data/expiries.py", "leads"], root).stdout
    r = run(["data/expiries.py", "soon"], root)
    assert r.returncode == 0 and "Zephyr fridge" in r.stdout
    assert run(["data/make_digest.py"], root).returncode == 0
    digest = next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")
    assert "## Expiring" in digest and "Zephyr fridge warranty" in digest and "No date yet for 1: Sam passport" in digest, digest.split("## Expiring")[1][:600]
    assert "| Alex | passport |" in digest.split("## Expiring")[1], "a passport 205 days out is in the digest although the horizon is 30 days"
