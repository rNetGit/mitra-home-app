"""Apply migration 068 to data/family.db (idempotent): the paperwork of a job.

work_papers  one row per filed paper (documents.id) kept with a job (contracts.id): offer letter, contract, W-2, 1099,
             timesheet, benefits or other. Only the link: the paper itself stays where it was filed under archive/.
             Removing a link never removes the paper.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS work_papers (
  id INTEGER PRIMARY KEY,
  contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK (kind IN ('offer_letter','contract','w2','form_1099','timesheet','benefits','other')),
  added_at TEXT,
  UNIQUE (contract_id, document_id)
);
""")
c.commit()
print("migration 068 ok")
