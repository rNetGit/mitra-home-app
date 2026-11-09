"""Read-only question helper for agents: run ONE SELECT against the family database.

  python data/ask_sql.py "SELECT category, ROUND(SUM(-amount),2) FROM transactions WHERE txn_date LIKE '2026-09%' GROUP BY 1"
  python data/ask_sql.py --tables            list tables and views with columns

Opens the database read-only and refuses anything but a single SELECT/WITH statement. At most 200 rows are
printed. Never selects from sqlite internals or the PC-only tables. Used by the `family` agent for "how much did we
spend on ...?" and, through `run`, by the chat assistant's query action and the catalog's recipes (schema_catalog.py).
"""
import re
import sys
import db  # noqa: E402

import paths  # noqa: E402
DB = paths.DB
LIMIT = 200
PRIVATE = ("member_info", "home_contacts", "wallet_cards")


def refused(sql):
    """Why a statement may not run, or None: one SELECT / WITH, no second statement, no sqlite_ or private table."""
    s = (sql or "").strip().rstrip(";")
    if ";" in s or not re.match(r"(?is)^(select|with)\b", s):
        return "one SELECT statement only"
    if re.search(r"(?i)\bmain\s*\.", s):
        return "name tables without a schema prefix"
    if re.search(r"(?i)\b(sqlite_|" + "|".join(PRIVATE) + r")", s):
        return "that table is not readable here"
    return None


def run(con, sql):
    """The rows of one read-only SELECT as text: a header line, then ' | ' separated rows, at most LIMIT."""
    why = refused(sql)
    if why:
        raise ValueError(why)
    # The chat does not know who is asking: private jobs and private saved items stay out of its answers (TEMP views shadow the tables).
    con.execute("CREATE TEMP VIEW IF NOT EXISTS saved_items AS SELECT * FROM main.saved_items WHERE COALESCE(audience, 'family') != 'private'")
    con.execute("CREATE TEMP VIEW IF NOT EXISTS contracts AS SELECT * FROM main.contracts WHERE COALESCE(visibility, 'shared') != 'private'")
    for t in ("work_hours", "work_invoices"):
        con.execute(f"CREATE TEMP VIEW IF NOT EXISTS {t} AS SELECT * FROM main.{t} WHERE contract_id IN (SELECT id FROM main.contracts WHERE COALESCE(visibility, 'shared') != 'private')")
    con.execute("PRAGMA query_only = ON")
    cur = con.execute(sql.strip().rstrip(";"))
    lines = [" | ".join(d[0] for d in cur.description)]
    for i, row in enumerate(cur):
        if i >= LIMIT:
            lines.append(f"... truncated at {LIMIT} rows")
            break
        lines.append(" | ".join("" if v is None else str(v) for v in row))
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    con = db.connect(DB, readonly=True)
    if sys.argv[1] == "--tables":
        for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' "
                                "AND name NOT GLOB 'doc_search_[cdi]*' AND name != 'doc_search_config' AND name NOT IN ('member_info', 'home_contacts', 'wallet_cards') ORDER BY 1"):  # FTS5 shadow tables are noise
            print(n, [r[1] for r in con.execute(f"PRAGMA table_info({n})")])
        return
    try:
        print(run(con, sys.argv[1]))
    except ValueError as e:
        raise SystemExit(f"refused: {e}")


if __name__ == "__main__":
    main()
