"""Apply migration 014 to data/family.db (idempotent): vehicle service log + service rules.

vehicle_log           : one row per service/expense event (kind is free text; common values listed below).
vehicle_service_rules : per vehicle+kind interval (every_months and/or every_miles). Seeded with generic
                        defaults per vehicle - edit rows to match the owner's manual / habits.
Kinds: oil_change|tires|rotation|brakes|battery|inspection|registration|repair|car_wash|fuel|other
       plus rule-only kinds cabin_filter|brake_fluid.
Manage with data/vehicle_log.py. State inspection/registration dates stay in `vehicles` (action_items covers them).
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS vehicle_log (
  id INTEGER PRIMARY KEY,
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  log_date TEXT NOT NULL,
  kind TEXT NOT NULL,
  odometer INTEGER,
  cost REAL,
  vendor TEXT,
  notes TEXT,
  document_id INTEGER REFERENCES documents(id)
);
CREATE INDEX IF NOT EXISTS idx_vlog_vehicle ON vehicle_log(vehicle_id, kind, log_date);
CREATE TABLE IF NOT EXISTS vehicle_service_rules (
  id INTEGER PRIMARY KEY,
  vehicle_id INTEGER NOT NULL REFERENCES vehicles(id),
  kind TEXT NOT NULL,
  every_months INTEGER,
  every_miles INTEGER,
  active INTEGER DEFAULT 1,
  UNIQUE(vehicle_id, kind)
);
""")

# (kind, months, miles). Generic defaults for any car, not a substitute for the owner's manual: edit the rows after.
COMBUSTION = [("oil_change", 6, 5000), ("rotation", 6, 6000), ("brake_fluid", 24, None),
              ("cabin_filter", 12, 15000), ("battery", 48, None)]
ELECTRIC = [("rotation", 6, 6000), ("cabin_filter", 24, None), ("brake_fluid", 48, None), ("battery", 48, None)]
EV_HINTS = ("electric", " ev", "tesla", "leaf", "bolt", "ioniq", "polestar", "rivian", "lucid")
for vid, make, model in c.execute("SELECT id, make, model FROM vehicles WHERE status='active'").fetchall():
    label = f" {make or ''} {model or ''}".lower()
    for kind, mo, mi in (ELECTRIC if any(h in label for h in EV_HINTS) else COMBUSTION):
        c.execute("INSERT OR IGNORE INTO vehicle_service_rules(vehicle_id,kind,every_months,every_miles) "
                  "VALUES(?,?,?,?)", (vid, kind, mo, mi))
c.commit()
print("migration 014 ok;", c.execute("SELECT COUNT(*) FROM vehicle_service_rules").fetchone()[0], "service rules,",
      c.execute("SELECT COUNT(*) FROM vehicle_log").fetchone()[0], "log rows")
