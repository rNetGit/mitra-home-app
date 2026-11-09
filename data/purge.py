"""Remove one person's data, or the whole household's, from this installation. Dry run unless --yes.

  python data/purge.py person NAME            show what would go (nothing changes)
  python data/purge.py person NAME --yes      do it: a snapshot copy of the database is kept in data/backups_pre_upgrade/
  python data/purge.py copies [--yes]         the older database copies in backups_pre_upgrade (they still hold people
                                              removed since); the newest snapshot made before a purge stays
  python data/purge.py all                    show what a full wipe would remove
  python data/purge.py all --yes [--archive]  empty every table, remove config/*.json, briefs, reports, logs and the
                                              pre-upgrade backups; --archive also deletes inbox/ and archive/ originals

person: rows that belong to the person by name (life items, appointments, ID documents, contracts, recurring
checkups and their log, home-office figures, seasonal tasks assigned to them, their private saved items, the members
row) are deleted; shared
money rows keep their numbers but forget the name (transactions.cardholder, accounts.owner, vehicles.owner); their
hide/snooze state, config/family.json entry, dashboard login and login-throttle entry go too. Other people's rows are
untouched. The database is VACUUMed afterwards so deleted rows do not linger in free pages.
Reports and briefs already written may still mention the person: they are listed, not edited.

all: the schema stays (schema_migrations, meta) so `python onboard.py` can start again in the same folder.
Backups outside this folder (../Mitra-Home-Backup, config backup_dest) and the exports/ folder are NOT touched:
their paths are printed so the family can delete them. Scheduled tasks are not unregistered (python onboard.py doctor
lists them).

A receipt with row counts (no row contents) is written to logs/purge_<timestamp>.json.
"""
import argparse
import datetime as dt
import json
import pathlib
import shutil
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

ROOT = HERE.parent
DB = paths.DB
# (table, column[, extra condition]): rows deleted when column == name
OWNED = [("saved_items", "owner", "audience='private'"), ("life_items", "member"), ("appointments", "person"), ("id_documents", "person"), ("contracts", "person"),
         ("home_office_expenses", "who"), ("home_office_profile", "who"), ("recurring_items", "who"),
         ("seasonal_tasks", "who"), ("chat_links", "member"), ("chat_invites", "member"),
         ("device_pairings", "member"), ("policy_drivers", "name"),
         ("mobile_bill_lines", "person"), ("mobile_bill_lines", "member"), ("activity_schedules", "member"),
         ("calendar_days", "member"), ("member_info", "member"), ("wallet_cards", "member"), ("vaccinations", "member"), ("routines", "member"),
         ("reward_claims", "member"), ("rewards", "member"), ("members", "name")]
# (table, column): the name is cleared, the row stays (shared money data, shared lists)
SHARED = [("transactions", "cardholder"), ("accounts", "owner"), ("vehicles", "owner"), ("vehicles", "primary_driver"),
          ("policy_vehicles", "assigned_driver"),
          ("lists", "created_by"), ("list_items", "assigned_to"), ("list_items", "added_by"), ("list_items", "done_by"),
          ("saved_items", "owner"), ("chat_log", "member"), ("recipes", "added_by"), ("meal_plan", "added_by"),
          ("proposals", "decided_by"), ("devices", "created_by"), ("device_pairings", "created_by"),
          ("audit_runs", "actor"), ("audit_fixes", "done_by"), ("audit_fixes", "undone_by"), ("routine_done", "done_by"),
          ("walls", "created_by"), ("wall_pairings", "created_by"), ("reward_claims", "asked_by"),
          ("reward_claims", "decided_by")]
# The person's phones are revoked, not deleted: the row (token hash) stays so the phone is told to wipe its copy the
# next time it calls; the person's name on it is replaced.
REVOKED_NAME = "(removed)"
NOT_NULL = {("audit_fixes", "done_by")}  # SHARED columns that cannot be emptied: the name is replaced with REVOKED_NAME
CHILD = {"life_items": [("vaccinations", "life_item_id")], "recurring_items": [("recurring_log", "item_id")], "seasonal_tasks": [("seasonal_log", "task_id")],
         "contracts": [("work_hours", "contract_id"), ("work_invoices", "contract_id"), ("work_match_rules", "contract_id"), ("work_papers", "contract_id")],
         "mobile_bill_lines": [("mobile_bill_items", "line_id")], "routines": [("routine_done", "routine_id")],
         "rewards": [("reward_claims", "reward_id")]}
KEEP_TABLES = {"schema_migrations", "meta"}
CONFIG_KEEP = {"secrets.env"}


def _has(con, table, col=None):
    try:
        cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    except sqlite3.OperationalError:
        return False
    return bool(cols) and (col is None or col in cols)


def _names(con):
    out = []
    if _has(con, "members"):
        out += [n for (n,) in con.execute("SELECT name FROM members ORDER BY name")]
    for m in config.family().get("members") or []:
        if m.get("name") and m["name"] not in out:
            out.append(m["name"])
    return out


def _canonical(con, name):
    want = name.strip().lower()
    for n in _names(con):
        if n.lower() == want:
            return n
    return None


def person_plan(con, name):
    """{table: rows to delete}, {table: rows to anonymise}, action_state keys, mentions in briefs/reports."""
    delete, clear, keys = {}, {}, []
    for t, c, *cond in OWNED:
        if not _has(con, t, c):
            continue
        extra = "".join(f" AND {x}" for x in cond)
        ids = [i for (i,) in con.execute(f"SELECT rowid FROM {t} WHERE {c}=? COLLATE NOCASE{extra}", (name,))]  # rowid == id where there is one
        if not ids:
            continue
        delete[t] = sorted(set(delete.get(t, [])) | set(ids))
        ids = delete[t]
        for ct, cc in CHILD.get(t, []):
            if _has(con, ct, cc):
                q = f"SELECT rowid FROM {ct} WHERE {cc} IN ({','.join('?' * len(ids))})"
                cids = [i for (i,) in con.execute(q, ids)]
                if cids:
                    delete[ct] = cids
    if _has(con, "budget", "category"):  # the person's allowance line (data/budget.py "allowance:<name>")
        ids = [i for (i,) in con.execute("SELECT rowid FROM budget WHERE lower(category)=lower(?)", ("allowance:" + name,))]
        if ids:
            delete["budget"] = ids
    for t, c in SHARED:
        if _has(con, t, c):
            n = con.execute(f"SELECT COUNT(*) FROM {t} WHERE {c}=? COLLATE NOCASE", (name,)).fetchone()[0]
            if n:
                clear[t + "." + c if t in clear else t] = n
    if _has(con, "devices", "member"):
        n = con.execute("SELECT COUNT(*) FROM devices WHERE member=? COLLATE NOCASE", (name,)).fetchone()[0]
        if n:
            clear["devices (phones revoked)"] = n
    if _has(con, "proposals", "ref_table"):  # Inbox items about the person's rows (their summary names the person)
        pids = [pid for t, ids in list(delete.items()) for rid in ids
                for (pid,) in con.execute("SELECT id FROM proposals WHERE ref_table=? AND ref_id=?", (t, rid))]
        if pids:
            delete["proposals"] = pids
    if _has(con, "action_state"):
        for t, ids in delete.items():
            for i in ids:
                keys += [k for (k,) in con.execute("SELECT key FROM action_state WHERE key LIKE ?", (f"{t}:{i}:%",))]
    mentions = []
    for folder in ("brief", "reports"):
        for f in sorted(paths.folder(folder).glob("*.md")) if paths.folder(folder).exists() else []:
            try:
                if name.lower() in f.read_text(encoding="utf-8", errors="replace").lower():
                    mentions.append(paths.rel(f))
            except OSError:
                pass
    return delete, clear, keys, mentions


def snapshot(label):
    d = paths.PRE_UPGRADE
    d.mkdir(exist_ok=True)
    dst = d / f"family_before_{label}_{dt.datetime.now():%Y%m%d_%H%M%S}.db"
    src = sqlite3.connect(DB)
    out = sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    import backup
    return backup.seal_copy(dst)  # encrypted when the family's backups are (audit D4)


def older_copies(keep):
    """Database copies in backups_pre_upgrade other than `keep` (they still hold whoever was just removed)."""
    d = paths.PRE_UPGRADE
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.name.startswith("family_") and ".db" in p.name
                  and p.resolve() != pathlib.Path(keep).resolve())


def receipt(scope, body):
    (paths.LOGS).mkdir(exist_ok=True)
    p = paths.LOGS / f"purge_{dt.datetime.now():%Y%m%d_%H%M%S}.json"
    p.write_text(json.dumps({"scope": scope, "at": dt.datetime.now().isoformat(timespec="seconds"), **body}, indent=1),
                 encoding="utf-8")
    return p


def purge_person(name, do_it, drop_old=False):
    if config.broken():  # the person must leave family.json too; a file that cannot be read cannot be rewritten
        raise SystemExit("config/family.json cannot be read, so nothing was removed. Fix it or restore it from a backup first.")
    con = db.connect(DB)
    try:
        canon = _canonical(con, name)
        if not canon:
            names = ", ".join(_names(con)) or "(none)"
            raise SystemExit(f"no member called '{name}'. People here: {names}")
        delete, clear, keys, mentions = person_plan(con, canon)
        print(("" if do_it else "DRY RUN: ") + f"purge person '{canon}'")
        for t, ids in delete.items():
            print(f"  delete {len(ids):>5} row(s) from {t}")
        for t, n in clear.items():
            print(f"  forget the name on {n:>5} row(s) in {t} (rows stay)")
        if keys:
            print(f"  delete {len(keys):>5} hide/snooze state entr{'y' if len(keys) == 1 else 'ies'}")
        print("  remove from config/family.json members and dashboard logins; clear login throttle")
        if mentions:
            print(f"  {len(mentions)} written brief/report file(s) still mention the name (not edited): " + ", ".join(mentions[:6]))
        if not do_it:
            print("Nothing changed. Add --yes to do it (a database snapshot is kept in data/backups_pre_upgrade/).")
            return 0
        snap = snapshot("purge")
        con.execute("BEGIN")
        counts = {}
        # child rows (recurring_log, seasonal_log) go before their parents
        order = sorted(delete, key=lambda t: 0 if any(t == ct for cts in CHILD.values() for ct, _ in cts) else 1)
        for t in order:
            ids = delete[t]
            counts[t] = con.execute(f"DELETE FROM {t} WHERE rowid IN ({','.join('?' * len(ids))})", ids).rowcount
        for t, c in SHARED:
            if _has(con, t, c):
                blank = REVOKED_NAME if (t, c) in NOT_NULL else None
                n = con.execute(f"UPDATE {t} SET {c}=? WHERE {c}=? COLLATE NOCASE", (blank, canon)).rowcount
                if n:
                    counts[t + "." + c] = n
        if _has(con, "devices", "member"):
            counts["devices.revoked"] = con.execute(
                "UPDATE devices SET member=?, revoked_at=COALESCE(revoked_at, ?) WHERE member=? COLLATE NOCASE",
                (REVOKED_NAME, dt.datetime.now().replace(microsecond=0).isoformat(timespec="seconds"), canon)).rowcount
        if keys:
            counts["action_state"] = con.execute(f"DELETE FROM action_state WHERE key IN ({','.join('?' * len(keys))})", keys).rowcount
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()
    with config.family_edit() as fam:
        fam["members"] = [m for m in fam.get("members") or [] if (m.get("name") or "").strip().lower() != canon.lower()]
        if "dashboard_users" in fam:
            fam["dashboard_users"] = [u for u in fam["dashboard_users"] if (u.get("name") or "").lower() != canon.lower()]
        goals = (fam.get("wall") or {}).get("goals") or {}  # the child's Mitra Wall goal
        for k in [k for k in goals if k.lower() == canon.lower()]:
            del goals[k]
    thr = paths.LOGS / "login_throttle.json"
    if thr.exists():
        try:
            d = json.loads(thr.read_text(encoding="utf-8"))
            d = {k: v for k, v in d.items() if k.lower() != canon.lower()}
            thr.write_text(json.dumps(d), encoding="utf-8")
        except (OSError, ValueError):
            pass
    rec = receipt("person", {"deleted": counts, "snapshot": paths.rel(snap), "mentions": mentions})
    print(f"done. Snapshot: {paths.rel(snap)}  Receipt: {paths.rel(rec)}")
    if mentions:
        print("Delete or edit the listed briefs/reports yourself if they must not keep the name.")
    old = older_copies(snap)
    if old and drop_old:
        for p in old:
            p.unlink(missing_ok=True)
        print(f"{len(old)} older database cop{'y' if len(old) == 1 else 'ies'} in backups_pre_upgrade removed (they still "
              f"held {canon}). The snapshot from just before this purge stays.")
    elif old:
        print(f"{len(old)} older database cop{'y' if len(old) == 1 else 'ies'} in backups_pre_upgrade still hold {canon}. "
              "Remove them with: python data/purge.py copies --yes   (the snapshot from just before this purge stays)")
    return 0


def all_plan(con):
    tables = {}
    for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        if t not in KEEP_TABLES and not (t.startswith("doc_search_") and t != "doc_search_state"):  # FTS5 shadow tables
            tables[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    return tables


def _wipe_dir(p, keep=(".gitkeep",)):
    n = 0
    if not p.exists():
        return 0
    for x in p.iterdir():
        if x.name in keep:
            continue
        if x.is_dir():
            shutil.rmtree(x, ignore_errors=True)
        else:
            x.unlink(missing_ok=True)
        n += 1
    return n


def purge_all(do_it, archive):
    con = db.connect(DB)
    try:
        tables = all_plan(con)
        cfgs = [p for p in (paths.CONFIG).glob("*") if p.is_file() and p.name not in CONFIG_KEEP and not p.name.endswith(".example.json")]
        cfgs += [p for p in (paths.CONFIG).glob("*/") if p.is_dir()]
        folders = ["brief", "reports", "logs", "backups_pre_upgrade"] + (["inbox", "archive"] if archive else [])
        print(("" if do_it else "DRY RUN: ") + "purge ALL household data in this folder")
        print(f"  empty {len(tables)} table(s), {sum(tables.values())} row(s); keep the schema")
        print(f"  remove {len(cfgs)} config file(s)/folder(s): " + ", ".join(p.name for p in cfgs[:8]))
        print("  clear folders: " + ", ".join(folders))
        if not archive:
            print("  KEEP inbox/ and archive/ originals (add --archive to delete them too)")
        if not do_it:
            print("Nothing changed. Add --yes to do it. There is no undo.")
            return 0
        con.execute("PRAGMA foreign_keys = OFF")
        counts = {}
        for t in tables:
            counts[t] = con.execute(f"DELETE FROM {t}").rowcount
        try:  # the deletes above went through the sync triggers (data/sync_data.py): empty the change log last
            con.execute("DELETE FROM sync_log")
        except sqlite3.OperationalError:
            pass
        try:
            con.execute("DELETE FROM sqlite_sequence")
        except sqlite3.OperationalError:
            pass
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()
    for p in cfgs:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    removed = {f: _wipe_dir(paths.PRE_UPGRADE if f == "backups_pre_upgrade" else paths.folder(f)) for f in folders}
    rec = receipt("all", {"deleted": counts, "config_removed": [p.name for p in cfgs], "folders": removed, "archive": archive})
    print(f"done. Receipt: {paths.rel(rec)}")
    print("Still to delete yourself:")
    print(f"  backups: {paths.BACKUPS}" + (f" and {config.family().get('backup_dest')}" if config.family().get("backup_dest") else ""))
    if (paths.EXPORTS).exists() and any((paths.EXPORTS).iterdir()):
        print(f"  exports: {paths.EXPORTS}")
    if not archive:
        print(f"  originals: {paths.INBOX} and {paths.ARCHIVE} (or rerun with --archive)")
    print("  Drive: the MitraHome folder in Google Drive, if you set one up; config/secrets.env if it holds a key")
    print("  scheduled tasks: python onboard.py doctor lists them")
    return 0


def purge_copies(do_it):
    """Delete the database copies in backups_pre_upgrade except the newest one made before a purge (audit D4)."""
    d = paths.PRE_UPGRADE
    snaps = sorted(d.glob("family_before_purge_*")) if d.is_dir() else []
    keep = snaps[-1] if snaps else pathlib.Path("-")
    old = older_copies(keep)
    print(("" if do_it else "DRY RUN: ") + f"{len(old)} database cop{'y' if len(old) == 1 else 'ies'} in backups_pre_upgrade"
          + (f" (kept: {keep.name})" if snaps else ""))
    for p in old:
        print(f"  {p.name}")
        if do_it:
            p.unlink(missing_ok=True)
    if not do_it and old:
        print("Nothing changed. Add --yes to delete them.")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Remove one person's data or everything. Dry run unless --yes.")
    ap.add_argument("scope", choices=["person", "all", "copies"])
    ap.add_argument("name", nargs="?")
    ap.add_argument("--yes", action="store_true", help="actually delete")
    ap.add_argument("--archive", action="store_true", help="all: also delete inbox/ and archive/ originals")
    ap.add_argument("--drop-old-copies", action="store_true",
                    help="person: also delete the older database copies in backups_pre_upgrade (they still hold the person)")
    a = ap.parse_args()
    if a.scope == "person":
        if not a.name:
            raise SystemExit("usage: purge.py person NAME [--yes]")
        return purge_person(a.name, a.yes, a.drop_old_copies)
    if a.scope == "copies":
        return purge_copies(a.yes)
    return purge_all(a.yes, a.archive)


if __name__ == "__main__":
    sys.exit(main())
