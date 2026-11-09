"""The data check: fixed rules that look for records that do not add up, are missing or look entered twice.

  python data/audit.py run [--weekly]      run every check now and keep the result (migration 055)
  python data/audit.py show                the newest run and what it found
  python data/audit.py history [N]         the score of the last N runs (default 8)

Read-only on the household's records: a run only writes `audit_runs` and `audit_findings`. No AI, nothing leaves the
PC, no account numbers (ids, dates, short names and amounts only). Each check returns findings with a level:
  money   numbers that do not add up (a phone bill whose lines miss its total, the database itself)
  decide  a row that is probably wrong and needs a person (a charge entered twice, a bill listed twice)
  note    something to know or do (spending with no category, a filed paper missing on disk, a quiet account)
A check that cannot run (an older database, an unreadable folder) is recorded in `errors` and does not stop the others.
The weekly digest task runs it (`run --weekly`); Settings > Data > Data check runs it on demand and shows the result.
"""
import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import db  # noqa: E402
import dates  # noqa: E402
import paths  # noqa: E402

LEVELS = ("money", "decide", "note")
CAP = 50                 # findings kept per check and run
RECENT_DAYS = 90         # uncategorized spending counts only this far back
QUIET_DAYS = 45          # an account with no transaction for this long ...
ACTIVE_DAYS = 180        # ... that had some in the half year before
LATE_DAYS = 30           # a bill still open this long after its due date
FUTURE_DAYS = 3          # transactions dated further ahead than this
CENT = 1                 # phone bill lines may differ from the total by this many cents (rounding)


def _f(key, level, summary, detail="", ref=(None, None), payload=None):
    return {"key": key, "level": level, "summary": summary, "detail": detail, "ref_table": ref[0], "ref_id": ref[1],
            "payload": json.dumps(payload, sort_keys=True) if payload else None}


def _money(v):
    try:
        import money
        return money.fmt(v)
    except Exception:  # noqa: BLE001
        return f"{v:,.2f}"


def _d(s):
    """2026-10-05 -> Oct 5, 2026 (anything else as it is)."""
    try:
        d = dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return str(s or "")
    return f"{d:%b} {d.day}, {d.year}"


# ---- the checks: each takes (con, today) and returns findings; a missing table means nothing to check ----

def check_database(con, today):
    out = []
    ok = con.execute("PRAGMA quick_check").fetchone()[0]
    if ok != "ok":
        out.append(_f("db", "money", "The database reports damage", "Restore the newest backup (Settings > Data)."))
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    tables = sorted({r[0] for r in bad})
    for t in tables:
        n = sum(1 for r in bad if r[0] == t)
        out.append(_f(f"fk:{t}", "decide", f"{n} {t} row(s) point at a record that is gone", f"table {t}", (t, None)))
    return out


def check_duplicate_txns(con, today):
    rows = db.rows(con, """
        SELECT account_id, txn_date, amount_cents, UPPER(TRIM(COALESCE(description, ''))) AS d,
               COUNT(*) AS n, GROUP_CONCAT(id) AS ids, MIN(description) AS shown, MIN(amount) AS amount
        FROM transactions GROUP BY account_id, txn_date, amount_cents, d
        HAVING COUNT(*) > 1 AND COUNT(ref) = 0
        ORDER BY txn_date DESC""")
    out = []
    for r in rows:
        ids = sorted(int(x) for x in str(r["ids"]).split(","))
        first = ids[0]
        out.append(_f(f"{r['account_id']}:{r['txn_date']}:{r['amount_cents']}:{r['d'][:40]}", "decide",
                      f"{(r['shown'] or 'A charge')[:60]} on {_d(r['txn_date'])} is listed {r['n']} times",
                      f"{_money(abs(r['amount']))} each, transaction ids {r['ids']}", ("transactions", first),
                      {"fix": "dupe_txn", "ids": ids}))
    return out


def check_uncategorized(con, today):
    since = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()
    r = db.one(con, "SELECT COUNT(*) AS n, COALESCE(SUM(amount), 0) AS total FROM transactions "
                    "WHERE txn_date >= ? AND amount < 0 AND (category IS NULL OR TRIM(category) = '')", (since,))
    if not r or not r["n"]:
        return []
    return [_f("recent", "note", f"{r['n']} payment(s) in the last {RECENT_DAYS} days have no category",
               f"{_money(-r['total'])} in all; a category rule files them next time (Money > Ledger, category Uncategorized)")]


def check_txn_dates(con, today):
    out = []
    ahead = (today + dt.timedelta(days=FUTURE_DAYS)).isoformat()
    for r in db.rows(con, "SELECT id, txn_date, description FROM transactions WHERE txn_date > ? ORDER BY txn_date LIMIT ?",
                     (ahead, CAP)):
        out.append(_f(f"future:{r['id']}", "decide", f"{(r['description'] or 'A transaction')[:60]} is dated {_d(r['txn_date'])}",
                      "a date in the future: probably misread", ("transactions", r["id"])))
    r = db.one(con, "SELECT COUNT(*) AS n FROM transactions WHERE amount_cents = 0")
    if r and r["n"]:
        out.append(_f("zero", "note", f"{r['n']} transaction(s) have an amount of 0", "often a misread line"))
    r = db.one(con, "SELECT COUNT(*) AS n FROM transactions WHERE account_id IS NULL")
    if r and r["n"]:
        out.append(_f("no_account", "note", f"{r['n']} transaction(s) belong to no account", "they are left out of account totals"))
    return out


def check_quiet_accounts(con, today):
    quiet = (today - dt.timedelta(days=QUIET_DAYS)).isoformat()
    active = (today - dt.timedelta(days=ACTIVE_DAYS)).isoformat()
    out = []
    for r in db.rows(con, """
            SELECT a.id, a.name, MAX(t.txn_date) AS last FROM accounts a JOIN transactions t ON t.account_id = a.id
            GROUP BY a.id HAVING MAX(t.txn_date) < ? AND MAX(t.txn_date) >= ? ORDER BY a.name""", (quiet, active)):
        out.append(_f(str(r["id"]), "note", f"Nothing on {r['name']} since {_d(r['last'])}",
                      "a statement may be missing; drop it in the Inbox", ("accounts", r["id"])))
    return out


def check_bills(con, today):
    out = []
    for r in db.rows(con, "SELECT id, name, due_date FROM bills WHERE status = 'paid' AND (paid_date IS NULL OR paid_date = '')"):
        out.append(_f(f"nodate:{r['id']}", "note", f"{r['name']} (due {_d(r['due_date'])}) is paid with no paid date",
                      "", ("bills", r["id"])))
    for r in db.rows(con, """SELECT name, due_date, COUNT(*) AS n, MIN(id) AS id, GROUP_CONCAT(id) AS ids FROM bills
                             GROUP BY LOWER(TRIM(name)), due_date HAVING COUNT(*) > 1"""):
        out.append(_f(f"twice:{r['name'].lower()}:{r['due_date']}", "decide",
                      f"{r['name']} due {_d(r['due_date'])} is listed {r['n']} times", "", ("bills", r["id"]),
                      {"fix": "dupe_bill", "ids": sorted(int(x) for x in str(r["ids"]).split(","))}))
    late = (today - dt.timedelta(days=LATE_DAYS)).isoformat()
    for r in db.rows(con, "SELECT id, name, due_date, amount FROM bills WHERE status IN ('due', 'overdue') AND due_date < ? "
                          "ORDER BY due_date LIMIT ?", (late, CAP)):
        out.append(_f(f"late:{r['id']}", "decide", f"{r['name']} due {_d(r['due_date'])} is still open",
                      (f"{_money(r['amount'])}; " if r["amount"] else "") + "paid already? mark it paid with the day you paid",
                      ("bills", r["id"]), {"fix": "late_bill", "bill_id": r["id"]}))
    return out


def check_phone_bills(con, today):
    out = []
    for r in db.rows(con, """
            SELECT b.id, b.carrier, b.bill_date, b.bill_total,
                   ROUND((COALESCE(SUM(l.line_total), 0) + COALESCE(b.account_wide, 0)) * 100) AS lines_c,
                   ROUND(b.bill_total * 100) AS total_c
            FROM mobile_bills b LEFT JOIN mobile_bill_lines l ON l.bill_id = b.id GROUP BY b.id"""):
        gap = int(r["total_c"]) - int(r["lines_c"])
        if abs(gap) > CENT:
            out.append(_f(str(r["id"]), "money", f"{r['carrier']} bill of {_d(r['bill_date'])} is off by {_money(abs(gap) / 100)}",
                          f"bill says {_money(r['bill_total'])}, the lines and account-wide charges add up to {_money(int(r['lines_c']) / 100)}",
                          ("mobile_bills", r["id"])))
    return out


def _archive_files():
    root = paths.ARCHIVE
    if not root.is_dir():
        return root, set()
    files = set()
    for p in root.rglob("*"):
        rel = p.relative_to(root)
        if p.is_file() and rel.parts[0] != "duplicates" and not p.name.startswith("."):
            files.add(rel.as_posix())
    return root, files


def check_papers(con, today):
    import archive_search
    root, files = _archive_files()
    out, known = [], set()
    for r in db.rows(con, "SELECT id, filed_path, doc_type, vendor, doc_date FROM documents ORDER BY id"):
        p = archive_search.resolve(r["filed_path"], root)
        if p is None:
            continue
        rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else None
        if rel:
            known.add(rel)
        if not p.is_file() and len(out) < CAP:
            what = " ".join(x for x in (r["vendor"], r["doc_type"]) if x) or "A paper"
            out.append(_f(f"gone:{r['id']}", "note", f"{what} ({_d(r['doc_date'])}) is on record but its file is missing",
                          "moved or removed outside the app; restore it from a backup", ("documents", r["id"])))
    loose = sorted(files - known)
    if loose:
        sample = ", ".join(loose[:3]) + (f" and {len(loose) - 3} more" if len(loose) > 3 else "")
        out.append(_f("loose", "note", f"{len(loose)} file(s) in the archive are not on record",
                      f"{sample}; drop them in the Inbox to file them properly"))
    return out


CHECKS = [  # (key, label shown in Settings, function)
    ("database", "Database is sound", check_database),
    ("duplicate_txns", "Charges entered twice", check_duplicate_txns),
    ("uncategorized", "Spending with a category", check_uncategorized),
    ("txn_dates", "Transaction dates and amounts", check_txn_dates),
    ("quiet_accounts", "Accounts kept up to date", check_quiet_accounts),
    ("bills", "Bills paid and listed once", check_bills),
    ("phone_bills", "Phone bills add up", check_phone_bills),
    ("papers", "Filed papers match the records", check_papers),
]
LABELS = {k: lbl for k, lbl, _ in CHECKS}


# ---- running and reading ----

def run(trigger="now", actor=None, today=None, path=None, fix=True):
    """Make the safe fixes (audit_fix.auto, each undoable), then run every check and keep the result -> run id.
    Never raises for one failing check; a failing fix is logged and the checks still run."""
    today = today or dates.today()
    started = dates.now_iso()
    found, errors = {}, []
    with db.open(path or paths.DB) as con:
        rid = con.execute("INSERT INTO audit_runs(started_at, trigger, actor) VALUES (?, ?, ?)",
                          (started, trigger, actor)).lastrowid
    fixed = []
    if fix:
        try:
            import audit_fix
            with db.open(path or paths.DB) as con:
                fixed = audit_fix.auto(con, rid)
        except Exception as e:  # noqa: BLE001 (the checks still run; nothing half-done: one transaction)
            errors.append("auto_fix")
            _logger().warning("auto fix failed: %s", type(e).__name__)
    with db.open(path or paths.DB, readonly=True) as con:
        for key, _label, fn in CHECKS:
            try:
                found[key] = fn(con, today)[:CAP]
            except sqlite3.OperationalError as e:
                if db.missing(e):
                    found[key] = []
                else:
                    errors.append(key)
            except Exception:  # noqa: BLE001 (one broken check must not hide the others)
                errors.append(key)
    total = len(CHECKS) - len([e for e in errors if e in {k for k, _l, _f in CHECKS}])
    ok = sum(1 for k, v in found.items() if not v)
    score = round(100 * ok / total) if total else None
    with db.open(path or paths.DB) as con:
        con.execute("UPDATE audit_runs SET finished_at=?, checks_total=?, checks_ok=?, score=?, errors=? WHERE id=?",
                    (dates.now_iso(), total, ok, score, ",".join(errors) or None, rid))
        con.executemany("INSERT INTO audit_findings(run_id, check_key, level, dedupe_key, summary, detail, ref_table, ref_id, "
                        "payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [(rid, k, f["level"], f"{k}:{f['key']}", f["summary"], f["detail"], f["ref_table"], f["ref_id"],
                          f["payload"]) for k, fs in found.items() for f in fs])
    _logger().info("run %s (%s): score %s, %s finding(s), %s fix(es), errors %s", rid, trigger, score,
                   sum(len(v) for v in found.values()), len(fixed), ",".join(errors) or "none")
    return rid


def _logger():
    import log
    return log.get("audit")


def history(con, n=8):
    return db.rows(con, "SELECT id, started_at, trigger, score, checks_ok, checks_total FROM audit_runs ORDER BY id DESC LIMIT ?",
                   (n,))


def latest(con):
    """The newest run for Settings: {run, findings (worst first), counts per level, checks [{key, label, state, n}],
    new (dedupe keys not in the run before), history} or None when nothing has run yet."""
    runs = history(con, 8)
    if not runs:
        return None
    r = db.one(con, "SELECT * FROM audit_runs WHERE id = ?", (runs[0]["id"],))
    order = {lv: i for i, lv in enumerate(LEVELS)}
    fs = sorted(db.rows(con, "SELECT * FROM audit_findings WHERE run_id = ? ORDER BY id", (r["id"],)),
                key=lambda f: order.get(f["level"], 9))
    before = {x["dedupe_key"] for x in db.rows(con, "SELECT dedupe_key FROM audit_findings WHERE run_id = ?",
                                               (runs[1]["id"],))} if len(runs) > 1 else set()
    errors = set((r["errors"] or "").split(",")) - {""}
    checks = []
    for key, label, _fn in CHECKS:
        mine = [f for f in fs if f["check_key"] == key]
        state = ("error" if key in errors else "ok" if not mine
                 else min((f["level"] for f in mine), key=lambda lv: order.get(lv, 9)))
        checks.append({"key": key, "label": label, "state": state, "n": len(mine)})
    asked = {}
    try:
        for k, pid, st, out in con.execute("SELECT dedupe_key, id, status, outcome FROM proposals WHERE dedupe_key LIKE 'audit:%'"):
            asked[k[6:]] = {"id": pid, "status": st, "outcome": out}
    except Exception as e:  # noqa: BLE001
        if not db.missing(e):
            raise
    for f in fs:
        f["new"] = bool(before) and f["dedupe_key"] not in before
        f["label"] = LABELS.get(f["check_key"], f["check_key"])
        f["asked"] = asked.get(f["dedupe_key"])
    try:
        import audit_fix
        fixes = audit_fix.recent(con)
    except Exception as e:  # noqa: BLE001
        if not db.missing(e):
            raise
        fixes = []
    return {"run": r, "fixes": fixes, "findings": fs, "counts": {lv: sum(1 for f in fs if f["level"] == lv) for lv in LEVELS},
            "checks": checks, "history": list(reversed(runs))}


def health_row(con, today):
    """(status, note) for the health check: warn when the newest run found money or decide items, or none ran in 15 days."""
    x = db.one(con, "SELECT id, started_at FROM audit_runs ORDER BY id DESC LIMIT 1")
    if not x:
        return None
    n = db.one(con, "SELECT COUNT(*) AS n FROM audit_findings WHERE run_id = ? AND level IN ('money', 'decide')", (x["id"],))["n"]
    age = (today - dt.date.fromisoformat(x["started_at"][:10])).days
    if n:
        return "warn", f"{n} thing{'' if n == 1 else 's'} to look at from {_d(x['started_at'][:10])}"
    if age > 15:
        return "warn", f"last run {age} days ago"
    return "ok", f"nothing wrong on {_d(x['started_at'][:10])}"


# ---- the score in the weekly digest and the monthly report (names, amounts and counts only; no ids, no file names) ----
WEEK_ITEMS = 5


def _fixes(con, start, end):
    try:
        return db.rows(con, "SELECT done_by, undone_at FROM audit_fixes WHERE done_at >= ? AND done_at < ?", (start, end))
    except Exception as e:  # noqa: BLE001
        if db.missing(e):
            return []
        raise


def markdown_week(con, today):
    """The digest's Data check section: the newest run of the last 8 days, '' when there is none."""
    since = (today - dt.timedelta(days=8)).isoformat()
    runs = db.rows(con, "SELECT id, started_at, score, checks_ok, checks_total FROM audit_runs WHERE finished_at IS NOT NULL "
                        "ORDER BY id DESC LIMIT 2")
    if not runs or runs[0]["started_at"][:10] < since:
        return ""
    r = runs[0]
    fs = db.rows(con, "SELECT level, summary FROM audit_findings WHERE run_id=? ORDER BY "
                      "CASE level WHEN 'money' THEN 0 WHEN 'decide' THEN 1 ELSE 2 END, id", (r["id"],))
    need = sum(1 for f in fs if f["level"] in ("money", "decide"))
    trend = ""
    if len(runs) > 1 and runs[1]["score"] is not None and r["score"] is not None:
        d = r["score"] - runs[1]["score"]
        trend = f" ({'up' if d > 0 else 'down'} {abs(d)} from the run before)" if d else " (same as the run before)"
    fixes = [x for x in _fixes(con, since, (today + dt.timedelta(days=1)).isoformat()) if not x["undone_at"]]
    lines = [f"Data score {r['score']}%{trend}: {r['checks_ok']} of {r['checks_total']} checks clear on {_d(r['started_at'][:10])}. "
             + (f"{need} thing{'' if need == 1 else 's'} to look at" if need else "Nothing to decide")
             + (f", {len(fs) - need} note{'' if len(fs) - need == 1 else 's'}" if len(fs) > need else "") + "."]
    if fixes:
        lines.append(f"{len(fixes)} fix(es) made this week ({sum(1 for x in fixes if x['done_by'] == 'auto')} by itself); "
                     "each can be undone in Settings > Data > Data check.")
    lines += [f"- {f['summary']}" for f in fs[:WEEK_ITEMS]]
    if len(fs) > WEEK_ITEMS:
        lines.append(f"- and {len(fs) - WEEK_ITEMS} more in Settings > Data > Data check")
    return "\n".join(lines)


def markdown_month(con, month):
    """The monthly report's Data check section for YYYY-MM: every run's score, what the last one found, fixes and
    decisions that month."""
    start = f"{month}-01"
    y, m = int(month[:4]), int(month[5:7])
    end = f"{y + (m == 12):04d}-{(m % 12) + 1:02d}-01"
    runs = db.rows(con, "SELECT id, started_at, score FROM audit_runs WHERE finished_at IS NOT NULL AND started_at >= ? "
                        "AND started_at < ? ORDER BY id", (start, end))
    if not runs:
        return "_no data check ran this month_\n"
    scores = [r["score"] for r in runs if r["score"] is not None]
    out = [f"- Runs: {len(runs)}; score " + ", ".join(f"{_d(r['started_at'][:10])} {r['score']}%" for r in runs)
           + (f" (average {round(sum(scores) / len(scores))}%)" if scores else "")]
    last = {lv: 0 for lv in LEVELS}
    for row in db.rows(con, "SELECT level, COUNT(*) AS n FROM audit_findings WHERE run_id=? GROUP BY level", (runs[-1]["id"],)):
        last[row["level"]] = row["n"]
    out.append(f"- Last run found: {last['money']} with numbers off, {last['decide']} to decide, {last['note']} note(s)")
    fixes = _fixes(con, start, end)
    if fixes:
        undone = sum(1 for x in fixes if x["undone_at"])
        out.append(f"- Fixes: {len(fixes)} ({sum(1 for x in fixes if x['done_by'] == 'auto')} by itself"
                   + (f", {undone} undone" if undone else "") + ")")
    try:
        dec = db.rows(con, "SELECT status, COUNT(*) AS n FROM proposals WHERE source='audit' AND decided_at >= ? AND decided_at < ? "
                           "GROUP BY status", (start, end))
    except Exception as e:  # noqa: BLE001
        if not db.missing(e):
            raise
        dec = []
    if dec:
        d = {x["status"]: x["n"] for x in dec}
        out.append(f"- Inbox decisions: {d.get('done', 0)} fixed, {d.get('dismissed', 0)} left as they were")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--weekly", action="store_true")
    sub.add_parser("show")
    h = sub.add_parser("history")
    h.add_argument("n", nargs="?", type=int, default=8)
    a = ap.parse_args(argv)
    if a.cmd == "run":
        rid = run("weekly" if a.weekly else "now")
        print(f"run {rid} done")
    if a.cmd in ("run", "show"):
        with db.open(paths.DB, readonly=True) as con:
            x = latest(con)
        if not x:
            print("no run yet")
            return 0
        print(f"score {x['run']['score']}% ({x['run']['checks_ok']}/{x['run']['checks_total']} checks clear) {x['run']['started_at']}")
        for c in x["checks"]:
            print(f"  [{'x' if c['state'] == 'ok' else '!'}] {c['label']}" + (f": {c['n']}" if c["n"] else "")
                  + (" (could not run)" if c["state"] == "error" else ""))
        for f in x["findings"]:
            print(f"  {f['level']:6} {f['summary']}" + (f" - {f['detail']}" if f["detail"] else ""))
    if a.cmd == "history":
        with db.open(paths.DB, readonly=True) as con:
            for h in reversed(history(con, a.n)):
                print(f"{h['started_at']}  {h['trigger']:6}  {h['score']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
