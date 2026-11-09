"""Apply migration 032 to data/family.db (idempotent): receipts matched to card and bank charges.

One row per receipt: merchant, date, total (and the card's last four digits when the receipt shows them), the filed
original in `documents`, and the charge in `transactions` it belongs to. match_confidence: high (same amount, merchant
word), medium (same amount, the only one), low (possible tip), manual (linked by a person), none. auto=0 once a person
linked, unlinked or ignored it, so the matcher leaves it alone. Manage with data/receipts.py or Money > Receipts.
"""
import sqlite3

DATE = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript(f"""
CREATE TABLE IF NOT EXISTS receipts (
  id INTEGER PRIMARY KEY,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  merchant TEXT NOT NULL CHECK (length(merchant) BETWEEN 1 AND 80),
  receipt_date TEXT NOT NULL CHECK (receipt_date {DATE}),
  total REAL NOT NULL CHECK (total > 0),
  card_last4 TEXT CHECK (card_last4 IS NULL OR card_last4 GLOB '[0-9][0-9][0-9][0-9]'),
  transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
  match_confidence TEXT NOT NULL DEFAULT 'none' CHECK (match_confidence IN ('high','medium','low','manual','none')),
  match_note TEXT,
  auto INTEGER NOT NULL DEFAULT 1 CHECK (auto IN (0,1)),
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','matched','ignored')),
  notes TEXT CHECK (notes IS NULL OR length(notes) <= 200),
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(status, receipt_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_receipts_txn ON receipts(transaction_id) WHERE transaction_id IS NOT NULL;
""")
c.commit()
print("migration 032 ok;", c.execute("SELECT COUNT(*) FROM receipts").fetchone()[0], "receipts")
