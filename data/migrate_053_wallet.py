"""Apply migration 053 to data/family.db (idempotent): the Card Wallet (data/wallet.py, the Wallet page).

vehicles gains what the car card and parking mode show:
  color        "blue", "silver" ... (at most 20 characters)
  body_type    sedan | suv | truck | van | minivan | hatchback | coupe | wagon | motorcycle | other
  plate        the full plate as printed (letters, digits, spaces, dashes; at most 10). A plate is on the street for
               anyone to read, so it is kept whole (the user's decision of 2026-10-17); VIN stays last4.
  plate_region the state or region on the plate ("NJ"), at most 20 characters

wallet_cards: cards the household carries that no other table holds.
  kind         membership | loyalty | library | travel | health | home | other
  title        "Warehouse club", "City library", "Home" (1-60 characters)
  member       whose card (members.name) or NULL = the household
  issuer       who issued it (at most 60)
  number       the full number, ONLY for low-risk cards a barcode needs (membership, loyalty, library); every other
               kind keeps number_last4 only (known traveler, passport, licence, health and policy numbers stay last4)
  number_last4 last four letters or digits
  where_hint   where the number is printed on the real card ("back, under the barcode"), at most 120
  details      short facts (Wi-Fi name, trash day, filter size), at most 300; never passwords or full numbers
  expires      ISO date or NULL
Never deleted: removing a card sets status 'dropped'. Synced to adult phones with the ids scope; not readable through
ask_sql (the chat's SQL tool). Changes are logged by row id only.
"""
import sqlite3

DATE = "GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'"

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(vehicles)")}
for col in ("color", "body_type", "plate", "plate_region"):
    if cols and col not in cols:
        c.execute(f"ALTER TABLE vehicles ADD COLUMN {col} TEXT")
c.executescript(f"""
CREATE TABLE IF NOT EXISTS wallet_cards (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL DEFAULT 'other' CHECK (kind IN ('membership', 'loyalty', 'library', 'travel', 'health', 'home', 'other')),
  title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 60),
  member TEXT,
  issuer TEXT CHECK (issuer IS NULL OR length(issuer) <= 60),
  number TEXT CHECK (number IS NULL OR (length(number) BETWEEN 4 AND 30 AND kind IN ('membership', 'loyalty', 'library'))),
  number_last4 TEXT CHECK (number_last4 IS NULL OR length(number_last4) <= 4),
  where_hint TEXT CHECK (where_hint IS NULL OR length(where_hint) <= 120),
  details TEXT CHECK (details IS NULL OR length(details) <= 300),
  expires TEXT CHECK (expires IS NULL OR expires {DATE}),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'dropped')),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_wallet_cards ON wallet_cards(status, kind);
""")
import sync_data  # noqa: E402
sync_data.ensure_triggers(c)
c.commit()
print("migration 053 ok")
