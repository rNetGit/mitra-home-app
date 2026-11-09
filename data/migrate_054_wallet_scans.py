"""Apply migration 054 to data/family.db (idempotent): a wallet card can point at its filed scan.

wallet_cards.document_id  documents.id of the photo or scan of the card (filed under archive/<year>/ids/ when the card was
                          added from a photo on the Wallet page). The Wallet shows it on the back of the card; it never
                          leaves this PC (not in the phone sync columns).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(wallet_cards)")}
if cols and "document_id" not in cols:
    c.execute("ALTER TABLE wallet_cards ADD COLUMN document_id INTEGER REFERENCES documents(id)")
c.commit()
print("migration 054 ok")
