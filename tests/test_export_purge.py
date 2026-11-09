"""Leaving cleanly (audit item 19): `export_data.py` writes every table as CSV/JSON with a manifest, `purge.py`
removes one person's rows or the whole household. Purge is a dry run unless --yes; a database snapshot and a receipt
are written; config/family.json, dashboard logins and the login throttle forget the person too."""
import csv
import json
import sqlite3
import zipfile


from conftest import copy_template, db, q, read_family, run, seed, write_family


def _tables(root):
    con = db(root)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for (t,) in
                con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                           "AND name NOT LIKE 'doc_search%'")}  # derived search index, checked apart
    finally:
        con.close()


def test_export_every_table_with_manifest(root, tmp_path):
    con = db(root)
    con.execute("INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Quoted, \"name\"', 'Ex Co', 12.5, '2099-01-01', 'due')")
    con.commit()
    con.close()
    out = tmp_path / "exp"
    r = run(["data/export_data.py", "--out", str(out)], root)
    assert r.returncode == 0, r.stderr[-400:]
    counts = _tables(root)
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert man["version"] and man["exported_at"] and man["format"] == "csv"
    assert man["tables"] == counts, "manifest row counts match the database"
    for t, n in counts.items():
        with open(out / f"{t}.csv", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == n, t
    with open(out / "bills.csv", encoding="utf-8", newline="") as f:
        names = [r["name"] for r in csv.DictReader(f)]
    assert 'Quoted, "name"' in names, "commas and quotes survive the round trip"
    assert (out / "README.txt").exists()
    assert "export" in r.stdout and str(len(counts)) in r.stdout


def test_export_json_subset_and_zip(root, tmp_path):
    out = tmp_path / "j"
    r = run(["data/export_data.py", "--out", str(out), "--format", "json", "--tables", "bills,members", "--zip"], root)
    assert r.returncode == 0, r.stderr[-400:]
    data = json.loads((out / "members.json").read_text(encoding="utf-8"))
    assert {m["name"] for m in data} >= {"Alex", "Sam"}
    assert not (out / "transactions.json").exists() and not (out / "bills.csv").exists()
    z = next(tmp_path.glob("j*.zip"))
    assert {"manifest.json", "bills.json", "members.json", "README.txt"} <= set(zipfile.ZipFile(z).namelist())
    r = run(["data/export_data.py", "--tables", "nope"], root)
    assert r.returncode != 0 and "nope" in r.stdout + r.stderr


def _person_rows(root, name):
    con = db(root)
    try:
        return {
            "members": con.execute("SELECT COUNT(*) FROM members WHERE name=?", (name,)).fetchone()[0],
            "life": con.execute("SELECT COUNT(*) FROM life_items WHERE member=?", (name,)).fetchone()[0],
            "appt": con.execute("SELECT COUNT(*) FROM appointments WHERE person=?", (name,)).fetchone()[0],
            "ids": con.execute("SELECT COUNT(*) FROM id_documents WHERE person=?", (name,)).fetchone()[0],
            "rec": con.execute("SELECT COUNT(*) FROM recurring_items WHERE who=?", (name,)).fetchone()[0],
            "txn_holder": con.execute("SELECT COUNT(*) FROM transactions WHERE cardholder=?", (name,)).fetchone()[0],
        }
    finally:
        con.close()


def test_purge_person_dry_run_then_for_real(root):
    con = db(root)
    con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime) VALUES ('Sam', 'Dr Lee', 'Checkup', '2099-03-01 09:00')")
    con.execute("INSERT INTO transactions(account_id, txn_date, description, amount, cardholder) "
                "VALUES ((SELECT id FROM accounts LIMIT 1), '2026-09-01', 'SAM CHARGE', -3.0, 'Sam')")
    con.execute("INSERT INTO recurring_items(category, who, name, interval_months, last_done) VALUES ('health', 'Sam', 'Dentist', 6, '2026-01-01')")
    rid = con.execute("SELECT id FROM recurring_items WHERE who='Sam' AND name='Dentist'").fetchone()[0]
    con.execute("INSERT INTO recurring_log(item_id, done_date) VALUES (?, '2026-01-01')", (rid,))
    lid = con.execute("SELECT id FROM life_items WHERE member='Sam' LIMIT 1").fetchone()[0]
    con.execute("INSERT INTO action_state(key, state) VALUES (?, 'done')", (f"life_items:{lid}:2026-01-01",))
    con.execute("INSERT INTO action_state(key, state) VALUES ('bills:1:2026-01-01', 'done')")
    con.commit()
    con.close()
    fam = read_family(root)
    fam["dashboard_users"] = [{"name": "Alex", "role": "adult", "pin_hash": "x"}, {"name": "Sam", "role": "limited", "pin_hash": "y"}]
    write_family(root, fam)
    (root / "logs").mkdir(exist_ok=True)
    (root / "logs" / "login_throttle.json").write_text(json.dumps({"Sam": {"fails": [1]}, "Alex": {"fails": [2]}}), encoding="utf-8")
    before = _person_rows(root, "Sam")
    assert before["members"] == 1 and before["life"] > 0 and before["appt"] >= 1 and before["txn_holder"] == 1

    r = run(["data/purge.py", "person", "sam"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "dry run" in r.stdout.lower() and "--yes" in r.stdout and "life_items" in r.stdout
    assert _person_rows(root, "Sam") == before, "a dry run changes nothing"
    assert "Sam" in read_family(root)["members"][1]["name"] or any(m["name"] == "Sam" for m in read_family(root)["members"])

    r = run(["data/purge.py", "person", "Sam", "--yes"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    after = _person_rows(root, "Sam")
    assert after == {"members": 0, "life": 0, "appt": 0, "ids": 0, "rec": 0, "txn_holder": 0}, after
    assert q(root, "SELECT COUNT(*) FROM transactions WHERE description='SAM CHARGE'") == [(1,)], "shared money rows stay, only the name goes"
    assert q(root, "SELECT COUNT(*) FROM recurring_log WHERE item_id=?", rid) == [(0,)]
    assert q(root, "SELECT COUNT(*) FROM action_state") == [(1,)], "hide/snooze state for the person's rows is gone, others stay"
    fam = read_family(root)
    assert not any(m["name"] == "Sam" for m in fam["members"]) and any(m["name"] == "Alex" for m in fam["members"])
    assert [u["name"] for u in fam["dashboard_users"]] == ["Alex"]
    assert "Sam" not in json.loads((root / "logs" / "login_throttle.json").read_text(encoding="utf-8"))
    assert _person_rows(root, "Alex")["members"] == 1 and _person_rows(root, "Alex")["life"] > 0, "other people untouched"
    snaps = list((root / "data" / "backups_pre_upgrade").glob("family_before_purge_*.db"))
    assert snaps, "snapshot taken before deleting"
    assert sqlite3.connect(snaps[-1]).execute("SELECT COUNT(*) FROM members WHERE name='Sam'").fetchone()[0] == 1
    rec = sorted((root / "logs").glob("purge_*.json"))[-1]
    body = json.loads(rec.read_text(encoding="utf-8"))
    assert body["scope"] == "person" and body["deleted"]["life_items"] == before["life"] and body["snapshot"]
    r = run(["data/members.py", "sync"], root)
    assert r.returncode == 0 and _person_rows(root, "Sam")["members"] == 0, "a later member sync does not bring the person back"
    r = run(["data/purge.py", "person", "Nobody"], root)
    assert r.returncode != 0 and "Alex" in r.stdout + r.stderr, "unknown name: lists who exists"


def test_purge_all_empties_the_household(tmp_path):
    root = copy_template(tmp_path / "gone")
    seed(root)
    (root / "brief").mkdir(exist_ok=True)
    (root / "brief" / "2026-01-01_weekly_digest.md").write_text("x", encoding="utf-8")
    (root / "archive" / "2026" / "bills").mkdir(parents=True, exist_ok=True)
    (root / "archive" / "2026" / "bills" / "2026-01-01_vendor_bill.pdf").write_bytes(b"%PDF")
    r = run(["data/purge.py", "all"], root)
    assert r.returncode == 0 and "dry run" in r.stdout.lower() and (root / "config" / "family.json").exists()
    r = run(["data/purge.py", "all", "--yes"], root)
    assert r.returncode == 0, r.stdout + r.stderr
    counts = _tables(root)
    assert all(n == 0 for t, n in counts.items() if t not in ("schema_migrations", "meta")), counts
    assert q(root, "select count(*) from doc_search")[0][0] == 0 and q(root, "select count(*) from doc_search_state")[0][0] == 0
    assert counts["schema_migrations"] > 0, "the schema stays so the folder can be set up again"
    assert not (root / "config" / "family.json").exists()
    assert not list((root / "brief").glob("*.md")) and not list((root / "reports").glob("*.md"))
    assert (root / "archive" / "2026" / "bills" / "2026-01-01_vendor_bill.pdf").exists(), "originals are kept unless --archive"
    assert "archive" in r.stdout and "backup" in r.stdout.lower(), "tells the family what is left and where backups live"
    r = run(["data/purge.py", "all", "--yes", "--archive"], root)
    assert r.returncode == 0 and not (root / "archive" / "2026").exists()
