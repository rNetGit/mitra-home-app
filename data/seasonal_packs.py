"""Region-specific seasonal task packs (packs/seasonal/*.json).

  python data/seasonal_packs.py list                          available packs
  python data/seasonal_packs.py apply KEY [--addons a,b]      use a base pack (+ add-ons such as hurricane, wildfire)
  python data/seasonal_packs.py recommend [COUNTRY] [CLIMATE] suggest a pack
  python data/seasonal_packs.py status                        what is active now

Applying a pack updates/creates its tasks and deactivates tasks of packs that are no longer selected.
Tasks you added yourself (pack NULL) and the done-log are never touched. Windows are general guidance: edit
packs/seasonal/*.json (a copy in config/seasonal/ with the same key overrides the shipped one) or the DB rows.
"""
import argparse
import json
import pathlib
import sys
import db  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
import paths  # noqa: E402
DB = paths.DB
SHIPPED = HERE.parent / "packs" / "seasonal"
LOCAL = paths.CONFIG / "seasonal"


def load_packs():
    packs = {}
    for folder in (SHIPPED, LOCAL):  # local overrides shipped
        if folder.exists():
            for f in sorted(folder.glob("*.json")):
                d = json.loads(f.read_text(encoding="utf-8"))
                packs[d.get("key", f.stem)] = d
    return packs


def recommend(country="US", climate="cold"):
    try:
        import country as _country
        packs = _country.load(country).get("seasonal_packs") or {}
        if packs:
            return packs.get((climate or "cold").lower()) or packs.get("cold") or "generic"
    except Exception:
        pass
    c = (country or "US").strip().upper()
    if c in ("CA", "CANADA"):
        return "canada_cold"
    if c in ("UK", "GB", "UNITED KINGDOM", "ENGLAND", "SCOTLAND", "WALES"):
        return "uk"
    if c in ("AU", "NZ", "AUSTRALIA", "NEW ZEALAND"):
        return "australia_nz"
    if c in ("IN", "INDIA"):
        return "india"
    if c in ("US", "USA", "UNITED STATES"):
        return {"cold": "us_cold", "mild": "us_mild", "hot": "us_hot"}.get((climate or "cold").lower(), "us_cold")
    return "generic"


def apply(con, base, addons=()):
    packs = load_packs()
    sel = [base, *addons]
    missing = [k for k in sel if k not in packs]
    if missing:
        raise SystemExit(f"unknown pack(s): {missing}. Available: {sorted(packs)}")
    if not any(r[1] == "pack" for r in con.execute("PRAGMA table_info(seasonal_tasks)")):
        raise SystemExit("run python data/migrate.py first")
    added = updated = 0
    for key in sel:
        for t in packs[key]["tasks"]:
            row = con.execute("SELECT id, pack FROM seasonal_tasks WHERE name=?", (t["name"],)).fetchone()
            if row and row[1] is None:
                continue  # the family's own task with the same name: leave it alone
            vals = (t["category"], t["start"], t["end"], t.get("lead_days", 14), t.get("notes", ""), key)
            if row:
                con.execute("UPDATE seasonal_tasks SET category=?, start_md=?, end_md=?, lead_days=?, notes=?, pack=?, active=1 WHERE id=?",
                            (*vals, row[0]))
                updated += 1
            else:
                con.execute("INSERT INTO seasonal_tasks(name, category, start_md, end_md, lead_days, notes, pack, who) VALUES (?,?,?,?,?,?,?, 'Home')",
                            (t["name"], *vals))
                added += 1
    marks = ",".join("?" * len(sel))
    off = con.execute(f"UPDATE seasonal_tasks SET active=0 WHERE pack IS NOT NULL AND pack NOT IN ({marks})", sel).rowcount
    con.commit()
    return added, updated, off


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "apply", "recommend", "status"])
    ap.add_argument("arg", nargs="?")
    ap.add_argument("arg2", nargs="?")
    ap.add_argument("--addons", default="")
    a = ap.parse_args()
    packs = load_packs()
    if a.cmd == "list":
        for k, d in packs.items():
            print(f"{k:<14} {d.get('kind', 'base'):<6} {len(d['tasks']):>2} tasks  {d['title']}")
    elif a.cmd == "recommend":
        print(recommend(a.arg or "US", a.arg2 or "cold"))
    elif a.cmd == "status":
        con = db.connect(DB)
        for pack, n, act in con.execute("SELECT COALESCE(pack,'(your own)'), COUNT(*), SUM(active) FROM seasonal_tasks GROUP BY 1"):
            print(f"{pack:<14} {n} tasks, {act} active")
    else:
        if not a.arg:
            sys.exit("usage: apply KEY [--addons a,b]")
        con = db.connect(DB)
        add, upd, off = apply(con, a.arg, [x for x in a.addons.split(",") if x])
        print(f"pack {a.arg}: {add} added, {upd} updated, {off} deactivated")


if __name__ == "__main__":
    main()
