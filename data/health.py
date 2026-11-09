"""Quick health check for the app (Settings > Data > Health check) and `python data/health.py`.

The same ground as `python onboard.py doctor`, but fast and read-only: nothing is sent anywhere, no AI is called, and
no secret value is read or shown (only whether it is there). Each row is {name, status, note, fix, here} with status
ok | warn | info; `fix` is the command or place that clears a warning, `here` the same in household words: the
place in the app (the app shows `here`; commands stay under Settings > Data > Advanced).

  python data/health.py            print every row
"""
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402

BACKUP_MAX_DAYS = 9
SKIP_INBOX = {".gitkeep", "needs_review", "duplicates"}


ADVANCED = "Settings > Data > Advanced"


def _row(name, status, note="", fix="", here=""):
    """here: where to fix it in the app; a command without one points to Advanced."""
    if not here and fix:
        here = ADVANCED if fix.startswith("python") else fix
    return {"name": name, "status": status, "note": note, "fix": fix, "here": here}


def _con():
    p = paths.DB
    if not p.exists():
        return None
    return sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=5)


def checks(today=None):
    today = today or dates.today()
    cfg = config.family()
    out = []

    con = _con()
    if con is None:
        out.append(_row("Database", "warn", "no database yet", "python onboard.py", "Open the app and answer the setup questions"))
    else:
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            out.append(_row("Database", "ok" if ok else "warn", "integrity ok" if ok else "integrity check failed",
                            "" if ok else "restore the newest backup: python data/restore_backup.py",
                            "" if ok else "Settings > Data > Restore from backup"))
            try:
                import migrate
                todo = migrate.pending(con)
                out.append(_row("Database updates", "warn" if todo else "ok",
                                f"{len(todo)} waiting" if todo else "all applied",
                                "python onboard.py upgrade" if todo else "", "Settings > Data > Check for updates" if todo else ""))
            except Exception as e:  # noqa: BLE001 (a missing table must not hide the other rows)
                out.append(_row("Database updates", "warn", type(e).__name__, "python data/migrate.py"))
        except sqlite3.Error as e:
            out.append(_row("Database", "warn", type(e).__name__, "python onboard.py doctor"))

    # scheduled tasks
    try:
        import heartbeat
        if not cfg.get("tasks_registered"):
            out.append(_row("Scheduled tasks", "warn", "not registered, so nothing runs by itself",
                            "python onboard.py (step 11, 'Register the scheduled tasks')",
                            "Settings > Data > Runs on its own"))
        else:
            stale = heartbeat.stale(today)
            if stale:
                for task, msg in stale:
                    out.append(_row(f"Task {task}", "warn", msg, f"python tasks/run_task.py {task}"))
            else:
                out.append(_row("Scheduled tasks", "ok", "all ran recently"))
    except Exception as e:  # noqa: BLE001
        out.append(_row("Scheduled tasks", "warn", type(e).__name__))

    # backups
    try:
        import action_items as ai
        for label, newest, age, path in ai.backup_status(ROOT, today):
            if newest is None:
                out.append(_row(f"Backup ({label})", "warn", "no backup yet", "python tasks/run_task.py weekly_backup",
                                "Settings > Data > Back up now"))
            elif age is not None and age > BACKUP_MAX_DAYS:
                out.append(_row(f"Backup ({label})", "warn", f"last one {age} days ago ({newest})",
                                "python tasks/run_task.py weekly_backup", "Settings > Data > Back up now"))
            else:
                out.append(_row(f"Backup ({label})", "ok", f"newest {newest}"))
    except Exception as e:  # noqa: BLE001
        out.append(_row("Backup", "warn", type(e).__name__))
    if cfg.get("backup_encrypt"):
        try:
            import crypto_box
            has = bool(crypto_box.load_passphrase())
        except Exception:  # noqa: BLE001
            has = False
        out.append(_row("Backup passphrase", "ok" if has else "warn",
                        "found on this PC (keep a copy somewhere else too)" if has else "not found: backups cannot be made or restored",
                        "" if has else "python onboard.py add backup"))
    else:
        out.append(_row("Backup encryption", "info", "backups are not encrypted", "python onboard.py add backup"))
    if not (cfg.get("backup_dest") or "").strip():
        out.append(_row("Second backup place", "info", "none: backups sit next to the project folder", "python onboard.py add backup"))

    # AI provider (is it set up; no call is made)
    prov = ((cfg.get("ai") or {}).get("provider") or "none").lower()
    if prov in ("none", ""):
        out.append(_row("AI provider", "info", "none: files wait for you or Claude Code", "python onboard.py add ai",
                        "Settings > Connections > AI provider"))
    elif prov in ("anthropic", "openai", "gemini", "openrouter"):
        try:
            import llm
            has = bool(llm.api_key(prov))
        except Exception:  # noqa: BLE001
            has = False
        out.append(_row("AI provider", "ok" if has else "warn", f"{prov}" + (", key found" if has else ", no key found"),
                        "" if has else "python onboard.py add ai", "" if has else "Settings > Connections > AI provider"))
    else:
        out.append(_row("AI provider", "ok", prov))
    if prov not in ("none", ""):  # names only leave this PC when an AI reads the papers
        try:
            import pii
            if pii.names_on_papers_missing(cfg):
                out.append(_row("Names on papers", "warn", "full names printed on papers are not hidden from the AI yet", "",
                                "Settings > Household profile > Names on your papers"))
        except Exception:  # noqa: BLE001
            pass

    # update token (only needed while the project's releases are private)
    try:
        import updater
        has = bool(updater._token())
    except Exception:  # noqa: BLE001
        has = False
    out.append(_row("Update token", "ok" if has else "info",
                    "set" if has else "not set: fine while the releases are public; a private project needs one to check for updates",
                    "" if has else "set MITRAHOME_TOKEN to a read-only GitHub token"))
    try:  # the daily look for new versions (update_notice.py): silent unless it has failed for a week
        import update_notice
        note = update_notice.health_row(today)
    except Exception:  # noqa: BLE001
        note = None
    if note:
        out.append(_row("New versions", "warn", note, "set MITRAHOME_TOKEN to a read-only GitHub token (it may have run out)",
                        "Settings > Data > Updates"))

    # chat bots
    chat = cfg.get("chat") or {}
    for name in ("telegram", "discord"):
        if (chat.get(name) or {}).get("enabled"):
            try:
                mod = __import__(f"chat_{name}")
                has = bool(mod.token())
            except Exception:  # noqa: BLE001
                has = False
            out.append(_row(f"{name.title()} bot", "ok" if has else "warn", "token found" if has else "token missing",
                            "" if has else f"python onboard.py add {name}",
                            "" if has or name != "telegram" else "Settings > Connections > Phone bot"))

    # bank sync (SimpleFIN), if the family set it up: a good pull in the last three days
    try:
        import bank_sync
        if bank_sync.configured():
            bs = bank_sync.status(today)
            here = "Settings > Connections > Bank sync"
            if bs["stale_days"] is None:
                out.append(_row("Bank sync", "warn", "set up but no pull has worked yet" + (f": {bs['error']}" if bs["error"] else ""),
                                "python data/bank_sync.py pull", here))
            elif bs["stale_days"] > bank_sync.STALE_DAYS:
                out.append(_row("Bank sync", "warn", f"last good pull {bs['stale_days']} days ago"
                                + (f": {bs['error']}" if bs["error"] else ""), "python data/bank_sync.py pull", here))
            else:
                out.append(_row("Bank sync", "ok", f"last good pull {bs['last_ok'][:10]}"))
    except Exception:  # noqa: BLE001
        pass

    # Google Calendar (read-only), if the family turned it on
    try:
        import brand
        import google_calendar as gc
        gs = gc.status()
        if gs["enabled"]:
            if gs["client"] and gs["signed_in"]:
                out.append(_row("Google Calendar", "ok", "signed in" + (f", keeps the {brand.CALENDAR_NAME} calendar"
                                                                       if gc.can_write() else " (read-only)")))
            else:
                out.append(_row("Google Calendar", "warn", "turned on but not signed in", "python onboard.py add calendar",
                                "Settings > Connections > Google Calendar"))
    except Exception:  # noqa: BLE001
        pass

    # Gmail (read-only), if the family turned it on
    try:
        import google_gmail as gm
        gs = gm.status()
        if gs["enabled"]:
            if gs["signed_in"] and gs["permission"]:
                out.append(_row("Gmail", "ok", f"reading the label '{gs['label']}'"))
            else:
                out.append(_row("Gmail", "warn", "turned on but not allowed", "python onboard.py add gmail",
                                "Settings > Connections > Google"))
    except Exception:  # noqa: BLE001
        pass

    # work waiting for a person
    try:
        inbox = paths.INBOX
        waiting = [p for p in inbox.iterdir() if p.name not in SKIP_INBOX and not p.name.startswith(".")] if inbox.is_dir() else []
        if waiting:
            out.append(_row("Inbox", "info", f"{len(waiting)} file(s) waiting to be filed",
                            "the Inbox page (File them now), or: python data/ai_intake.py",
                            "Inbox > File them now"))
    except OSError:
        pass
    if con is not None:
        try:
            n = con.execute("SELECT COUNT(*) FROM review_queue WHERE resolved=0").fetchone()[0]
            if n:
                out.append(_row("Review queue", "warn", f"{n} file(s) need you to say what they are", "the Inbox page"))
            no_bd = con.execute("SELECT COUNT(*) FROM members WHERE role IN ('adult','child') AND "
                                "(birth_month_day IS NULL OR birth_month_day='')").fetchone()[0]
            if no_bd:
                out.append(_row("Birthdays", "info", f"{no_bd} person(s) have no birthday", "Family > People"))
            acc = con.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
            if not acc:
                out.append(_row("Accounts", "info", "no bank or card accounts yet", "Money > Accounts > Add an account"))
        except sqlite3.Error:
            pass
        try:  # the weekly data check (data/audit.py): silent until it has run once
            import audit
            dc = audit.health_row(con, today)
            if dc:
                out.append(_row("Data check", dc[0], dc[1], "python data/audit.py show" if dc[0] == "warn" else "",
                                "Settings > Data > Data check" if dc[0] == "warn" else ""))
        except Exception:  # noqa: BLE001 (an older database has no audit tables yet)
            pass
        con.close()
    return out


if __name__ == "__main__":
    icon = {"ok": "[x]", "warn": "[!]", "info": "(i)"}
    for r in checks():
        print(f"{icon[r['status']]} {r['name']}" + (f": {r['note']}" if r["note"] else "") + (f"   -> {r['fix']}" if r["fix"] else ""))
