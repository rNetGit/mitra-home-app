"""Apply migration 013 to data/family.db (idempotent): id_documents.

One row per person per document. expires NULL = "needs a date" (placeholder, nothing scanned yet).
Vehicle registrations live in `vehicles.registration_expires` and are NOT duplicated here.
Numbers: last4 only. Manage with data/id_docs.py.
"""
import sqlite3
import pathlib
import sys

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS id_documents (
  id INTEGER PRIMARY KEY,
  person TEXT NOT NULL,
  doc_type TEXT NOT NULL DEFAULT 'other',  -- passport|drivers_license|permit|state_id|green_card|vehicle_registration|insurance_card|other
  number_last4 TEXT,
  issued TEXT,
  expires TEXT,                            -- ISO date, NULL = needs a date
  issuing_authority TEXT,
  document_id INTEGER REFERENCES documents(id),
  notes TEXT,
  active INTEGER DEFAULT 1,
  UNIQUE(person, doc_type)
);
""")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402  (members come from config/family.json)
S = [(p, "passport", "US Dept of State") for p in config.member_names()]
S += [(p, "drivers_license", "State DMV") for p in config.member_names("adult")]
for p, t, auth in S:
    c.execute("INSERT OR IGNORE INTO id_documents(person,doc_type,issuing_authority,notes) VALUES(?,?,?,?)",
              (p, t, auth, "Placeholder: no scan filed yet; expiry unknown."))
c.commit()
print("migration 013 ok;", c.execute("SELECT COUNT(*) FROM id_documents").fetchone()[0], "id documents")
