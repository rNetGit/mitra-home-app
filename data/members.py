"""Household members and birthdays.

  python data/members.py sync                 mirror config/family.json members into the DB
  python data/members.py list
  python data/members.py add NAME [--role adult|child|pet] [--birthday MM-DD] [--year YYYY]
  python data/members.py birthday NAME MM-DD [--year YYYY]

Library: resolve(con, name) -> canonical name (case/spacing-insensitive, first-name match), alerts(con, today).
"""
import argparse
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402

DB = paths.DB
ROLES = ("adult", "child", "pet")


def role_ok(role):
    return role in ROLES


def sync(con, skipped=None):
    """Mirror config/family.json members into the DB. A member with an unknown role is left out (never stored) and its
    name/role appended to `skipped`, so one typo cannot stop the daily run."""
    n = 0
    for m in config.members():
        if not m.get("name"):
            continue
        role = m.get("role", "adult")
        if not role_ok(role):
            if skipped is not None:
                skipped.append((m["name"].strip(), role))
            continue
        con.execute("INSERT INTO members(name, role, birth_month_day, birth_year) VALUES (?,?,?,?) "
                    "ON CONFLICT(name) DO UPDATE SET role=excluded.role, "
                    "birth_month_day=COALESCE(NULLIF(excluded.birth_month_day,''), members.birth_month_day), "
                    "birth_year=COALESCE(excluded.birth_year, members.birth_year)",
                    (m["name"].strip(), role, (m.get("birth_month_day") or "").strip(), m.get("birth_year")))
        n += 1
    con.commit()
    return n


def names(con):
    try:
        return [r[0] for r in con.execute("SELECT name FROM members ORDER BY id")]
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return []


def resolve(con, who):
    """Canonical member name for a free-text `who`; returns the input stripped if no match."""
    if not who:
        return who
    w = " ".join(str(who).split()).lower()
    known = names(con)
    for n in known:
        if n.lower() == w:
            return n
    hits = [n for n in known if n.lower().split()[0] == w.split()[0]]
    return hits[0] if len(hits) == 1 else str(who).strip()


def _next_birthday(md, today):
    return dates.next_annual(md, today)


def alerts(con, today):
    out = []
    try:
        rows = con.execute("SELECT name, role, birth_month_day, birth_year, id FROM members "
                           "WHERE birth_month_day IS NOT NULL AND birth_month_day != ''").fetchall()
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
        return out
    for name, role, md, by, mid in rows:
        d = _next_birthday(md, today)
        if d:
            age = f" (turns {d.year - by})" if by else ""
            out.append({"date": d, "kind": "Birthday", "title": f"{name}'s birthday{age}",
                        "detail": "Gift / card / plan something?" if role != "pet" else "", "amount": None,
                        "ref": ("members", mid)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["sync", "list", "add", "birthday"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("value", nargs="?")
    ap.add_argument("--role", default="adult")
    ap.add_argument("--birthday")
    ap.add_argument("--year", type=int)
    a = ap.parse_args()
    con = db.connect(DB)
    if a.cmd == "sync":
        skipped = []
        print(f"synced {sync(con, skipped)} member(s) from config/family.json")
        for name, role in skipped:
            print(f"skipped {name}: role {role!r} is not one of {', '.join(ROLES)}; fix it in config/family.json",
                  file=sys.stderr)
    elif a.cmd == "add" and a.name:
        if not role_ok(a.role):
            sys.exit(f"role {a.role!r} is not one of {', '.join(ROLES)}")
        con.execute("INSERT OR IGNORE INTO members(name, role, birth_month_day, birth_year) VALUES (?,?,?,?)",
                    (a.name, a.role, a.birthday, a.year))
        con.commit()
    elif a.cmd == "birthday" and a.name and a.value:
        con.execute("UPDATE members SET birth_month_day=?, birth_year=COALESCE(?, birth_year) WHERE name=?",
                    (a.value, a.year, resolve(con, a.name)))
        con.commit()
    for r in con.execute("SELECT name, role, birth_month_day, birth_year FROM members ORDER BY id"):
        print(r)


if __name__ == "__main__":
    main()
