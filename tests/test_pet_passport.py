"""Pets get no passport placeholder (migration 013 stopped making them; migration 041 removes old ones)."""
import sqlite3

from conftest import run


def _people(root):
    con = sqlite3.connect(root / "data" / "family.db")
    rows = con.execute("SELECT person, doc_type FROM id_documents").fetchall()
    con.close()
    return rows


def test_pet_has_no_passport_placeholder(root):
    people = {p for p, _ in _people(root)}
    assert "Biscuit" not in people and "Alex" in people  # Biscuit is the test family's pet


def test_migration_removes_only_untouched_pet_placeholders(root):
    con = sqlite3.connect(root / "data" / "family.db")
    con.execute("INSERT INTO id_documents(person, doc_type, notes) VALUES ('Biscuit','passport','Placeholder: no scan filed yet; expiry unknown.')")
    con.execute("INSERT INTO id_documents(person, doc_type, expires, notes) VALUES ('Biscuit','other','2030-01-01','vet certificate')")
    con.commit()
    con.close()
    r = run(["data/migrate_041_pet_passports.py"], root)
    assert r.returncode == 0, r.stderr
    left = [d for p, d in _people(root) if p == "Biscuit"]
    assert left == ["other"]
