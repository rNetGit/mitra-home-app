"""Apply migration 035 to data/family.db (idempotent): full-text search over filed documents.

`doc_search` is an SQLite FTS5 index of the text of each filed document (one row per documents.id). The text is
read with the same extractor intake uses (data/doc_text.py) and masked first (data/pii.py: full account and card
numbers, SSNs, emails, phones become placeholders), so the index never holds an identifier the documents table would
not. `doc_search_state` remembers what was indexed and from which file version, so `data/archive_search.py index`
only reads new or changed files. Scans and photos have no text layer: they are recorded as 'scanned' and found by
vendor, type and file name only. Rebuild any time with `python data/archive_search.py index --rebuild`.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE VIRTUAL TABLE IF NOT EXISTS doc_search USING fts5(title, vendor, doc_type, body, tokenize='unicode61 remove_diacritics 2');
CREATE TABLE IF NOT EXISTS doc_search_state (
  doc_id INTEGER PRIMARY KEY,
  file_key TEXT,
  status TEXT NOT NULL CHECK (status IN ('ok','scanned','unsupported','missing','error')),
  chars INTEGER NOT NULL DEFAULT 0,
  indexed_at TEXT NOT NULL
);
""")
c.commit()
print("migration 035 ok;", c.execute("SELECT COUNT(*) FROM doc_search_state").fetchone()[0], "documents indexed")
