"""Apply migration 023 to data/family.db (idempotent): tag seasonal tasks with the pack they came from.

seasonal_tasks.pack: NULL = added by the family (never touched by packs); otherwise the pack key
(packs/seasonal/<key>.json). Tasks seeded by migration 006 are the `us_cold` pack. Switching packs
(`python data/seasonal_packs.py apply KEY`) deactivates tasks of packs no longer selected; nothing is deleted,
so the done-log is kept.
"""
import json
import pathlib
import sqlite3

here = pathlib.Path(__file__).parent
import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
if not any(r[1] == "pack" for r in c.execute("PRAGMA table_info(seasonal_tasks)")):
    c.execute("ALTER TABLE seasonal_tasks ADD COLUMN pack TEXT")
pack = json.loads((here.parent / "packs" / "seasonal" / "us_cold.json").read_text(encoding="utf-8"))
for t in pack["tasks"]:
    c.execute("UPDATE seasonal_tasks SET pack='us_cold' WHERE name=? AND pack IS NULL", (t["name"],))
c.commit()
print("migration 023 ok;", c.execute("SELECT COUNT(*) FROM seasonal_tasks WHERE pack IS NOT NULL").fetchone()[0], "pack-managed tasks")
