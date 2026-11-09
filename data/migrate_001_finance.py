"""Apply migration 001 to data/family.db (idempotent): transactions.payee / txn_type (and ref, see below)."""
import sqlite3
import pathlib
import paths  # noqa: E402
db = paths.DB
c = sqlite3.connect(db)
cols = {r[1] for r in c.execute("PRAGMA table_info(transactions)")}
# `ref` belongs to migration 002, but schema.sql (run just below) indexes it, so a database from before 002
# must get the column here or the index creation fails.
for col in ("payee", "txn_type", "ref"):
    if col not in cols:
        c.execute(f"ALTER TABLE transactions ADD COLUMN {col} TEXT")
# create_if_not_exists tables/views from schema.sql (CREATE TABLE IF NOT EXISTS is a no-op for existing tables)
c.executescript(pathlib.Path(__file__).with_name("schema.sql").read_text())
c.commit()
