"""Apply migration 041 to data/family.db (idempotent): no passport placeholder for pets.

Migration 013 made an empty "passport needs a date" row for every member, pets included, which showed up in the Brief
as an ID document without an expiry. Pets lose only the untouched placeholder (no expiry, no number, no document);
a pet passport the family filled in stays.
"""
import sqlite3
import sys
import pathlib

import paths  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402
c = sqlite3.connect(paths.DB)
n = 0
if c.execute("SELECT name FROM sqlite_master WHERE name='id_documents'").fetchone():
    for pet in config.member_names("pet"):
        n += c.execute("DELETE FROM id_documents WHERE person=? AND doc_type='passport' AND expires IS NULL "
                       "AND number_last4 IS NULL AND document_id IS NULL AND notes LIKE 'Placeholder:%'", (pet,)).rowcount
    c.commit()
print("migration 041 ok;", n, "pet placeholder(s) removed")
