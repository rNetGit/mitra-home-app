"""Apply migration 064 to data/family.db (idempotent): each Mitra Wall may have its own resting screen.

walls.screen   NULL = the household's wall screen (family.json `wall.screen`), else this wall's own settings as JSON
               (the same fields, checked by data/wall_screen.py `clean`): a kitchen wall on the modular clock with
               photos, a bedroom wall on a red night clock. Set in Settings > Phones > Walls > the wall's window.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
cols = {r[1] for r in c.execute("PRAGMA table_info(walls)")}
if cols and "screen" not in cols:
    c.execute("ALTER TABLE walls ADD COLUMN screen TEXT CHECK (screen IS NULL OR (json_valid(screen) AND length(screen) <= 2000))")
c.commit()
print("migration 064 ok")
