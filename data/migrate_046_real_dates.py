"""Apply migration 046 to data/family.db (idempotent): date CHECKs verify that the day exists, not just its shape.

Migration 025 (and the tables created since) only checked the pattern YYYY-MM-DD, so 2026-02-30 or 2026-04-31 could be
stored and the weekly report crashed reading it. Every CHECK on a date column becomes
    date(col) IS NOT NULL AND date(col) = substr(col, 1, 10)
(a time part after the day is still allowed), and every month-day CHECK becomes the same test in the year 2000 (so
02-29 stays valid). Timestamps written by the code itself (chat, phones, sync: YYYY-MM-DDTHH:MM:SS) are not touched.

SQLite cannot change a CHECK in place, so each table whose DDL still carries a pattern-only date check is rebuilt once
(the 12-step procedure, as in 025): views dropped and re-created, the table's own indexes and triggers put back,
foreign keys off, all in one transaction. Before a table is rebuilt its rows are repaired: a day past the end of its
month is moved to the last day of that month (2026-02-30 -> 2026-02-28, printed), an unreadable value is cleared
where the column allows NULL; a row that cannot be repaired is reported and that one table keeps its old checks
(`python data/migrate.py status` lists it under "unconstrained"; fix the row, then run this file by hand).
"""
import calendar
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import migrate_025_constraints as m25  # noqa: E402
from dates import parse_any  # noqa: E402

DB = paths.DB
ISO_GLOB = re.compile(r"GLOB\s*'\[0-9\]\[0-9\]\[0-9\]\[0-9\]-")   # pattern-only ISO date check (025, 030-036)
TS_GLOB = re.compile(r"GLOB\s*'\[0-9\]\[0-9\]\[0-9\]\[0-9\]-[^']*T\[0-2\]")  # code-written timestamps: leave alone
MD_GLOB = re.compile(r"GLOB\s*'0\[1-9\]-\[0-3\]\[0-9\]'")           # month-day check (025)


def real_date(col):
    """SQL expression: col is a day that exists (optionally followed by a time)."""
    return f"(date({col}) IS NOT NULL AND date({col}) = substr({col},1,10))"


def real_md(col):
    """SQL expression: col is an MM-DD that exists in some year."""
    return f"(date('2000-' || {col}) IS NOT NULL AND date('2000-' || {col}) = '2000-' || {col})"


def _checks(ddl):
    """[(start, end, body)] of every CHECK (...) in the DDL, end exclusive, body without the outer parentheses."""
    out = []
    for m in re.finditer(r"\bCHECK\s*\(", ddl, re.I):
        depth, i = 1, m.end()
        while i < len(ddl) and depth:
            depth += {"(": 1, ")": -1}.get(ddl[i], 0)
            i += 1
        out.append((m.start(), i, ddl[m.end():i - 1]))
    return out


def plan(ddl, cols):
    """(new DDL text, [(col, kind, nullable)]) for the date checks this table still needs to upgrade; kind = date | md.
    A check that already tests date(col) is left as is."""
    todo, pieces, pos = [], [], 0
    for start, end, body in _checks(ddl):
        kind = None
        if TS_GLOB.search(body) or "date(" in body.lower():
            kind = None
        elif ISO_GLOB.search(body):
            kind = "date"
        elif MD_GLOB.search(body):
            kind = "md"
        names = [c for c in cols if re.search(r"\b" + re.escape(c) + r"\b", body)]
        if kind is None or len(names) != 1:
            continue
        col = names[0]
        allow = ""
        if re.search(r"\bIS\s+NULL\b", body, re.I):
            allow += f"{col} IS NULL OR "
        if re.search(r"=\s*''", body):
            allow += f"{col} = '' OR "
        new = allow + (real_date(col) if kind == "date" else real_md(col))
        pieces.append(ddl[pos:start] + "CHECK (" + new + ")")
        pos = end
        todo.append((col, kind, not cols[col]["notnull"]))
    return "".join(pieces) + ddl[pos:], todo


def _clamp(val, md=False):
    """2026-02-30 -> 2026-02-28 (time part kept); 02-30 -> 02-29; None when the month itself is wrong."""
    s = str(val)
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(.*)$", s) if not md else re.match(r"^(\d{2})-(\d{2})$", s)
    if not m:
        return None
    if md:
        mo, day = int(m.group(1)), int(m.group(2))
        y, tail = 2000, ""
    else:
        y, mo, day, tail = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    if not 1 <= mo <= 12:
        return None
    last = calendar.monthrange(y, mo)[1]
    if day < 1 or day > 31:
        return None
    day = min(day, last)
    return f"{mo:02d}-{day:02d}" if md else f"{y:04d}-{mo:02d}-{day:02d}{tail}"


def repair(con, table, todo):
    """Make every row satisfy the new checks. Returns a list of problems (empty = ok)."""
    problems = []
    for col, kind, nullable in todo:
        if kind == "date":
            bad = con.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL AND NOT {real_date(col)}").fetchall()
        else:
            bad = con.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != '' AND NOT {real_md(col)}").fetchall()
        for rid, val in bad:
            fixed = _clamp(val, md=(kind == "md"))
            if fixed is None and kind == "date":
                d = parse_any(val)
                fixed = d.isoformat() if d is not None else None
            if fixed is not None:
                con.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (fixed, rid))
                print(f"  {table}.{col} row {rid}: {val!r} is not a real day, now {fixed!r}")
            elif nullable:
                con.execute(f"UPDATE {table} SET {col}=NULL WHERE rowid=?", (rid,))
                print(f"  {table}.{col} row {rid}: unreadable date {val!r} cleared")
            else:
                problems.append(f"{table}.{col} row {rid}: unreadable date {val!r}")
    return problems


def rebuild(con, table):
    ddl = m25._ddl(con, table)
    if ddl is None:
        return "absent"
    cols = m25._cols(con, table)
    new, todo = plan(ddl, cols)
    if not todo:
        return "already"
    problems = repair(con, table, todo)
    if problems:
        for p in problems:
            print("  " + p)
        print(f"  {table}: keeps its old date checks until the rows above are fixed")
        return "skipped"
    head = re.compile(r"^\s*CREATE TABLE\s+(?:IF NOT EXISTS\s+)?[\"'`\[]?" + re.escape(table) + r"[\"'`\]]?\s*\(", re.I)
    m = head.match(new)
    if not m:
        raise ValueError(f"cannot parse DDL of {table}")
    new = f"CREATE TABLE _new_{table} (" + new[m.end():]
    extras = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type IN ('index', 'trigger') AND tbl_name=? "
                                        "AND sql IS NOT NULL", (table,))]
    names = ", ".join(f'"{c}"' for c in cols)
    con.execute(new)
    con.execute(f"INSERT INTO _new_{table} ({names}) SELECT {names} FROM {table}")
    con.execute(f"DROP TABLE {table}")
    con.execute(f"ALTER TABLE _new_{table} RENAME TO {table}")
    for sql in extras:
        con.execute(sql)
    return "rebuilt"


def run(path=DB):
    con = sqlite3.connect(path)
    con.isolation_level = None
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("PRAGMA legacy_alter_table=ON")  # renaming must not re-validate views that are re-created below
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND sql IS NOT NULL "
                                        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    views = con.execute("SELECT name, sql FROM sqlite_master WHERE type='view'").fetchall()
    done = {}
    con.execute("BEGIN")
    try:
        for name, _ in views:
            con.execute(f"DROP VIEW IF EXISTS {name}")
        for table in tables:
            done[table] = rebuild(con, table)
        for _, sql in views:
            con.execute(sql)
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_log'").fetchone():
            import sync_data  # 044 ran before this file: put the change-log triggers back on rebuilt tables
            sync_data.ensure_triggers(con)
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")
        con.close()
    return done


if __name__ == "__main__":
    result = run()
    counts = {}
    for v in result.values():
        counts[v] = counts.get(v, 0) + 1
    print("migration 046 ok;", ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
