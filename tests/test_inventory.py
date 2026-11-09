"""Household inventory (migration 028 + data/assets.py): location, manual, status; rows/summary/alerts skip items that
are gone; the CLI (add/set/attach/dispose/summary); edit_actions gate; intake files a manual; digest section."""
import datetime as D

import pytest

from conftest import db, q, run

TODAY = D.date(2026, 10, 8)
ADULT, KID = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}


@pytest.fixture(scope="module")
def inv(root, modules):
    con = db(root)
    con.execute("DELETE FROM home_assets")
    con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES ('2026/receipts/2026-09-01_zapp_receipt.pdf', 'receipt', 'Zapp Store', '2026-09-01')")
    con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES ('2026/manuals/2026-09-01_zapp_manual.pdf', 'manual', 'Zapp', '2026-09-01')")
    con.commit()
    con.close()
    return modules("assets")


def _doc(root, typ):
    return q(root, "select id from documents where doc_type=? and vendor like 'Zapp%'", typ)[0][0]


def test_migration_added_columns_and_defaults(root, inv):
    cols = {r[1] for r in q(root, "pragma table_info(home_assets)")}
    assert {"location", "manual_document_id", "status", "disposed_date"} <= cols
    assert q(root, "select name from schema_migrations where name='migrate_028_inventory.py'")
    r = run(["data/migrate_028_inventory.py"], root)
    assert r.returncode == 0 and "already present" in r.stdout, "idempotent"


def test_cli_add_set_attach_dispose_summary(root, inv):
    rid, mid = _doc(root, "receipt"), _doc(root, "manual")
    r = run(["data/assets.py", "add", "Zapp washer", "--category", "appliance", "--purchase-date", "2026-09-01", "--price", "650",
             "--warranty-years", "2", "--location", "Utility room", "--store", "Zapp Store"], root)
    assert r.returncode == 0, r.stderr[-300:]
    assert run(["data/assets.py", "add", "Zapp kettle", "--price", "40"], root).returncode == 0
    assert run(["data/assets.py", "add", "Zapp old tv", "--price", "900", "--purchase-date", "2020-01-01"], root).returncode == 0
    assert run(["data/assets.py", "add", "Zapp bad", "--serial-last4", "123456"], root).returncode != 0
    assert run(["data/assets.py", "attach", "washer", str(mid), "--as", "manual"], root).returncode == 0
    assert run(["data/assets.py", "attach", "washer", str(rid)], root).returncode == 0
    assert run(["data/assets.py", "attach", "washer", "999999"], root).returncode != 0
    assert run(["data/assets.py", "set", "kettle", "--location", "Kitchen", "--serial-last4", "K9"], root).returncode == 0
    assert run(["data/assets.py", "set", "Zapp"], root).returncode != 0, "needs an option"
    assert run(["data/assets.py", "set", "nothing-here", "--location", "x"], root).returncode != 0
    assert run(["data/assets.py", "dispose", "old tv", "--how", "sold", "--date", "2026-10-01"], root).returncode == 0
    assert q(root, "select location, serial_last4 from home_assets where name='Zapp kettle'") == [("Kitchen", "K9")]
    assert q(root, "select status, disposed_date from home_assets where name='Zapp old tv'") == [("sold", "2026-10-01")]
    con = db(root)
    try:
        rows = inv.rows(con, TODAY)
        names = [r["name"] for r in rows]
        assert "Zapp old tv" not in names and "Zapp washer" in names and "Zapp kettle" in names
        w = [r for r in rows if r["name"] == "Zapp washer"][0]
        assert w["expires"] == D.date(2028, 9, 1) and w["has_receipt"] and w["has_manual"] and w["location"] == "Utility room"
        assert w["status"] == "under warranty" and not w["needs_receipt"]
        allrows = inv.rows(con, TODAY, all=True)
        tv = [r for r in allrows if r["name"] == "Zapp old tv"][0]
        assert tv["status"] == "sold 2026-10-01" and not tv["needs_receipt"], "a sold item never asks for a receipt"
        s = inv.summary(con, TODAY)
        assert s == {"count": 2, "value": 690.0, "under_warranty": 1, "needs_receipt": 0, "no_manual": 1, "gone": 1}
        assert not [a for a in inv.alerts(con, TODAY) if "old tv" in a["title"]], "gone items raise no alerts"
        import expiries
        assert not [r for r in expiries.rows(con, TODAY) if "old tv" in r["what"]], "and leave the expiry list"
    finally:
        con.close()
    out = run(["data/assets.py", "summary"], root).stdout
    assert "2 items in use, value 690.00, 1 under warranty, 0 need a receipt, 1 without a manual, 1 sold/disposed/lost" in out, out
    assert "Zapp old tv" not in run(["data/assets.py", "list"], root).stdout
    assert "Zapp old tv" in run(["data/assets.py", "list", "--all"], root).stdout


def test_edit_actions_for_adults_only(root, inv, modules):
    ea = modules("edit_actions")
    rid, mid = _doc(root, "receipt"), _doc(root, "manual")
    assert not ea.asset_add(KID, "Zapp kid item")[0]
    ok, msg = ea.asset_add(ADULT, "Zapp fridge", category="appliance", price=1200, purchase_date="2026-10-01", location="Kitchen",
                           warranty_years=1, serial_last4="F4")
    assert ok and "Zapp fridge" in msg
    fid = q(root, "select id from home_assets where name='Zapp fridge'")[0][0]
    assert not ea.asset_add(ADULT, "zapp FRIDGE")[0], "names are unique"
    assert not ea.asset_add(ADULT, "Zapp x", category="spaceship")[0]
    assert not ea.asset_add(ADULT, "Zapp x", serial_last4="123456789")[0]
    assert not ea.asset_add(ADULT, "Zapp x", purchase_date="01/02/2026")[0]
    assert not ea.asset_add(ADULT, "Zapp x", receipt_document_id=999999)[0]
    assert not ea.asset_update(ADULT, fid, colour="red")[0]
    ok, _ = ea.asset_update(ADULT, fid, receipt_document_id=rid, manual_document_id=mid, store="Zapp Store", price="")
    assert ok and q(root, "select receipt_document_id, manual_document_id, store, price from home_assets where id=?", fid) == [(rid, mid, "Zapp Store", None)]
    assert ea.asset_update(ADULT, fid, receipt_document_id="")[0] and q(root, "select receipt_document_id from home_assets where id=?", fid) == [(None,)]
    assert not ea.asset_update(ADULT, fid, name="Zapp kettle")[0], "cannot take another item's name"
    assert not ea.asset_dispose(KID, fid)[0] and not ea.asset_dispose(ADULT, fid, "eaten")[0]
    ok, msg = ea.asset_dispose(ADULT, fid, "lost", "2026-10-05")
    assert ok and q(root, "select status, disposed_date from home_assets where id=?", fid) == [("lost", "2026-10-05")]
    assert not ea.asset_update(ADULT, fid, location="x")[0], "gone items are read-only"
    elog = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "asset_add" in elog and "asset_update" in elog and "asset_dispose" in elog and "F4" not in elog and "Zapp" not in elog


def test_intake_files_a_manual_and_digest_has_the_section(root, inv, modules):
    ai = modules("ai_intake")
    assert "manual" in ai.TYPES and ai.CATEGORY["manual"] == "manuals"
    f = root / "inbox" / "dishwasher-guide.pdf"
    f.write_bytes(b"%PDF-1.4 manual")
    con = db(root)
    try:
        did, dest = ai.file_document(con, f, "manual", "Zapp Appliances", "2026-10-02")
        con.commit()
    finally:
        con.close()
    assert dest.exists() and "manuals" in dest.as_posix() and dest.name == "2026-10-02_zapp_appliances_manual.pdf"
    assert q(root, "select doc_type from documents where id=?", did) == [("manual",)]
    assert run(["data/assets.py", "attach", "kettle", str(did), "--as", "manual"], root).returncode == 0
    assert run(["data/make_digest.py"], root).returncode == 0
    digest = next((root / "brief").glob("*_weekly_digest.md")).read_text(encoding="utf-8")
    assert "## Household inventory" in digest and "2 items, value $690.00" in digest, digest.split("## Household inventory")[1][:200]
