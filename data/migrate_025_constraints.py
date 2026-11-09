"""Apply migration 025 to data/family.db (idempotent): CHECK constraints on date and status columns, the missing
indexes, and ON DELETE SET NULL on document links.

SQLite cannot add a CHECK constraint to an existing table, so each table in SPEC is rebuilt once (new table with the
same columns plus the constraints, rows copied, old table dropped, new one renamed) inside a single transaction with
foreign keys off: the SQLite "12-step" procedure. Views are dropped first and re-created afterwards from their own
DDL, indexes likewise. A table that already carries its `ck_<table>_...` constraints is left alone.

Before a table is rebuilt its rows are repaired: a date written as 10/15/2026 or 15.10.2026 becomes 2026-10-15; a
date that cannot be read becomes NULL where the column allows it. A row that cannot be repaired (unreadable date in a
NOT NULL column, unknown status word) is reported and that one table keeps running without constraints, so the update
never fails on old data. `python data/migrate.py status` lists such tables under "unconstrained".
"""
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
from dates import parse_any as _parse  # noqa: E402

DB = paths.DB


def iso_ok(col):
    """SQL expression: col is an ISO date (optionally followed by a time)."""
    return (f"(({col} GLOB '[0-9][0-9][0-9][0-9]-0[1-9]-[0-3][0-9]*' OR {col} GLOB '[0-9][0-9][0-9][0-9]-1[0-2]-[0-3][0-9]*') "
            f"AND substr({col},9,2) BETWEEN '01' AND '31')")


def md_ok(col):
    """SQL expression: col is an MM-DD month-day."""
    return f"(({col} GLOB '0[1-9]-[0-3][0-9]' OR {col} GLOB '1[0-2]-[0-3][0-9]') AND substr({col},4,2) BETWEEN '01' AND '31')"


# table -> {"dates": [...], "md": [...], "status": (column, allowed values)}
SPEC = {
    "documents": {"dates": ["doc_date"]},
    "transactions": {"dates": ["txn_date"]},
    "bills": {"dates": ["due_date", "paid_date"], "status": ("status", ["due", "paid", "overdue"])},
    "subscriptions": {"dates": ["next_renewal"]},
    "investments": {"dates": ["as_of", "maturity_date"]},
    "interest_income": {"dates": ["period_end"]},
    "appointments": {"dates": ["appt_datetime", "followup_due"]},
    "events": {"dates": ["event_date"]},
    "policies": {"dates": ["term_start", "term_end"],
                 "status": ("status", ["active", "expired", "replaced", "cancelled", "superseded"])},
    "vehicles": {"dates": ["registration_expires", "inspection_expires"],
                 "status": ("status", ["active", "sold", "totaled", "inactive"])},
    "life_items": {"dates": ["due_date", "last_done"], "status": ("status", ["open", "done", "dropped"])},
    "loans": {"dates": ["balance_date", "start_date", "payoff_date"], "status": ("status", ["active", "paid_off"])},
    "contracts": {"dates": ["start_date", "end_date"], "status": ("status", ["active", "renewed", "ended"])},
    "shopping_items": {"dates": ["target_date", "bought_date"], "status": ("status", ["todo", "bought", "dropped"])},
    "seasonal_tasks": {"md": ["start_md", "end_md"]},
    "seasonal_log": {"dates": ["done_date"]},
    "recurring_items": {"dates": ["last_done"]},
    "recurring_log": {"dates": ["done_date"]},
    "account_balances": {"dates": ["as_of"]},
    "home_assets": {"dates": ["purchase_date", "warranty_end"]},
    "vehicle_log": {"dates": ["log_date"]},
    "id_documents": {"dates": ["issued", "expires"]},
    "amazon_orders": {"dates": ["order_date"]},
    "home_office_expenses": {"dates": ["expense_date"]},
    "statement_cycles": {"dates": ["period_start", "period_end"]},
    "members": {"md": ["birth_month_day"]},
}
INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_documents_type ON documents(doc_type)",
    "CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(doc_date)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_ref ON transactions(ref)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(txn_date)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_acct_date ON transactions(account_id, txn_date)",
    "CREATE INDEX IF NOT EXISTS idx_bills_status_due ON bills(status, due_date)",
    "CREATE INDEX IF NOT EXISTS idx_subscriptions_active ON subscriptions(active)",
    "CREATE INDEX IF NOT EXISTS idx_investments_maturity ON investments(maturity_date)",
    "CREATE INDEX IF NOT EXISTS idx_appointments_when ON appointments(appt_datetime)",
    "CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date)",
    "CREATE INDEX IF NOT EXISTS idx_life_member ON life_items(member)",
    "CREATE INDEX IF NOT EXISTS idx_life_status ON life_items(status, due_date)",
    "CREATE INDEX IF NOT EXISTS idx_id_documents_expires ON id_documents(expires)",
    "CREATE INDEX IF NOT EXISTS idx_policies_term_end ON policies(term_end)",
]
SET_NULL_REFS = ("documents",)  # deleting a filed document unlinks rows instead of being refused


def _cols(con, table):
    return {r[1]: {"notnull": bool(r[3]), "type": r[2]} for r in con.execute(f"PRAGMA table_info({table})")}


def _ddl(con, table):
    row = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    return row[0] if row else None


def repair(con, table, spec, cols):
    """Make every row satisfy the constraints the table is about to get. Returns a list of problems (empty = ok)."""
    problems = []
    for col in spec.get("dates", []):
        if col not in cols:
            continue
        bad = con.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL AND NOT {iso_ok(col)}").fetchall()
        for rid, val in bad:
            d = _parse(val)
            if d is not None:
                tail = str(val)[10:] if re.match(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", str(val)) else ""
                con.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (d.isoformat() + tail, rid))
            elif not cols[col]["notnull"]:
                con.execute(f"UPDATE {table} SET {col}=NULL WHERE rowid=?", (rid,))
                print(f"  {table}.{col} row {rid}: unreadable date {val!r} cleared")
            else:
                problems.append(f"{table}.{col} row {rid}: unreadable date {val!r}")
    for col in spec.get("md", []):
        if col not in cols:
            continue
        for rid, val in con.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} != '' AND NOT {md_ok(col)}").fetchall():
            m = re.match(r"^\s*(\d{1,2})[-/.](\d{1,2})\s*$", str(val))
            if m and 1 <= int(m.group(1)) <= 12 and 1 <= int(m.group(2)) <= 31:
                con.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (f"{int(m.group(1)):02d}-{int(m.group(2)):02d}", rid))
            elif not cols[col]["notnull"]:
                con.execute(f"UPDATE {table} SET {col}=NULL WHERE rowid=?", (rid,))
                print(f"  {table}.{col} row {rid}: unreadable month-day {val!r} cleared")
            else:
                problems.append(f"{table}.{col} row {rid}: unreadable month-day {val!r}")
    if "status" in spec and spec["status"][0] in cols:
        col, allowed = spec["status"]
        marks = ",".join("?" * len(allowed))
        for rid, val in con.execute(f"SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL AND {col} NOT IN ({marks})", allowed).fetchall():
            low = str(val).strip().lower()
            if low in allowed:
                con.execute(f"UPDATE {table} SET {col}=? WHERE rowid=?", (low, rid))
            else:
                problems.append(f"{table}.{col} row {rid}: unknown status {val!r} (allowed: {', '.join(allowed)})")
    return problems


def constraints(table, spec, cols):
    out = []
    for col in spec.get("dates", []):
        if col in cols:
            null = "" if cols[col]["notnull"] else f"{col} IS NULL OR "
            out.append(f"CONSTRAINT ck_{table}_{col} CHECK ({null}{iso_ok(col)})")
    for col in spec.get("md", []):
        if col in cols:
            out.append(f"CONSTRAINT ck_{table}_{col} CHECK ({col} IS NULL OR {col} = '' OR {md_ok(col)})")
    if "status" in spec and spec["status"][0] in cols:
        col, allowed = spec["status"]
        vals = ",".join(f"'{v}'" for v in allowed)
        out.append(f"CONSTRAINT ck_{table}_{col} CHECK ({col} IS NULL OR {col} IN ({vals}))")
    return out


def new_ddl(ddl, table, extra):
    """The existing CREATE TABLE text, renamed to _new_<table>, with the constraints appended and ON DELETE SET NULL
    added to document links. Every column, default and index-free detail of the family's table is kept as is."""
    head = re.compile(r"^\s*CREATE TABLE\s+(?:IF NOT EXISTS\s+)?[\"'`\[]?" + re.escape(table) + r"[\"'`\]]?\s*\(", re.I)
    m = head.match(ddl)
    if not m:
        raise ValueError(f"cannot parse DDL of {table}")
    body = ddl[m.end():]
    end = body.rstrip().rfind(")")
    body = body[:end].rstrip().rstrip(",") + ",\n  " + ",\n  ".join(extra) + "\n)"
    for ref in SET_NULL_REFS:
        body = re.sub(r"(REFERENCES\s+" + ref + r"\s*\(\s*id\s*\))(?!\s*ON\s+DELETE)", r"\1 ON DELETE SET NULL", body, flags=re.I)
    return f"CREATE TABLE _new_{table} (" + body


def rebuild(con, table, spec):
    ddl = _ddl(con, table)
    if ddl is None:
        return "absent"
    if f"ck_{table}_" in ddl:
        return "already"
    cols = _cols(con, table)
    extra = constraints(table, spec, cols)
    if not extra:
        return "nothing"
    problems = repair(con, table, spec, cols)
    if problems:
        for p in problems:
            print("  " + p)
        print(f"  {table}: left without constraints until the rows above are fixed")
        return "skipped"
    indexes = [r[0] for r in con.execute("SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (table,))]
    names = ", ".join(f'"{c}"' for c in cols)
    con.execute(new_ddl(ddl, table, extra))
    con.execute(f"INSERT INTO _new_{table} ({names}) SELECT {names} FROM {table}")
    con.execute(f"DROP TABLE {table}")
    con.execute(f"ALTER TABLE _new_{table} RENAME TO {table}")
    for sql in indexes:
        con.execute(sql)
    return "rebuilt"


def run(path=DB):
    con = sqlite3.connect(path)
    con.isolation_level = None
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("PRAGMA legacy_alter_table=ON")  # renaming must not re-validate views that are re-created below
    views = con.execute("SELECT name, sql FROM sqlite_master WHERE type='view'").fetchall()
    done = {}
    con.execute("BEGIN")
    try:
        for name, _ in views:
            con.execute(f"DROP VIEW IF EXISTS {name}")
        for table, spec in SPEC.items():
            done[table] = rebuild(con, table, spec)
        for _, sql in views:
            con.execute(sql)
        for sql in INDEXES:
            try:
                con.execute(sql)
            except sqlite3.OperationalError as e:
                if "no such table" not in str(e) and "no such column" not in str(e):
                    raise
        dup = con.execute("SELECT COUNT(*) FROM (SELECT account_id, ref FROM transactions WHERE ref IS NOT NULL AND ref != '' "
                          "GROUP BY account_id, ref HAVING COUNT(*) > 1)").fetchone()[0]
        if dup:
            print(f"  transactions: {dup} (account, ref) pairs repeat; the unique index is not created (re-import dedupe stays in code)")
        else:
            con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_acct_ref ON transactions(account_id, ref) "
                        "WHERE ref IS NOT NULL AND ref != ''")
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sync_log'").fetchone():
            import sync_data  # re-run by hand after 044: put the change-log triggers back on rebuilt tables
            sync_data.ensure_triggers(con)
        bad_fk = con.execute("PRAGMA foreign_key_check").fetchall()
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")
        con.close()
    if bad_fk:
        print(f"  note: {len(bad_fk)} existing rows point at a document or account that no longer exists (left as is)")
    return done


if __name__ == "__main__":
    result = run()
    counts = {}
    for v in result.values():
        counts[v] = counts.get(v, 0) + 1
    print("migration 025 ok;", ", ".join(f"{n} {k}" for k, n in sorted(counts.items())))
