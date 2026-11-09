"""Settings > Data in the web app: back up, restore, export, updates, the full check, running on its own and the change
log. Every change goes through admin_actions (adults only, logged in logs/admin_audit.log), the same code the earlier
screens and the command line use. No web code here; webapp/app.py draws it.

Restore closes the web app (a separate process does the restore, then starts the web app again on its port) because
the database file is swapped while nothing has it open.
"""
import datetime as dt
import os
import subprocess
import sys
import threading
import time

import admin_actions as aa
import paths

DOCTOR_TIMEOUT = 300
_UPDATE = {"at": 0.0, "newer": None, "error": ""}  # the last "Check for updates" answer, kept ten minutes
UPDATE_TTL = 600


def snapshots():
    """[{i, label, encrypted, need_pass}] newest first: what the Restore list offers (index = position in rb.snapshots())."""
    import crypto_box
    import restore_backup as rb
    have_pass = bool(crypto_box.load_passphrase())
    out = []
    for i, s in enumerate(rb.snapshots()):
        label = f"{s['when']:%a %d %b %Y, %H:%M} · {s['where']}" + (" · locked" if s["encrypted"] else "")
        out.append({"i": i, "label": label, "encrypted": s["encrypted"], "need_pass": s["encrypted"] and not have_pass})
    return out


def _snap(i):
    import restore_backup as rb
    snaps = rb.snapshots()
    try:
        i = int(i)
    except (TypeError, ValueError):
        return None
    return snaps[i] if 0 <= i < len(snaps) else None


def last_restore(today=None):
    """The last restore's result when it is at most three days old: {ok, when, message, kept}."""
    import restore_backup as rb
    last = rb.last_result()
    if not last:
        return None
    since = (dt.datetime.now() - dt.timedelta(days=3)).isoformat()
    if last.get("at", "") < since:
        return None
    return {"ok": bool(last.get("ok")), "when": last["at"][:16].replace("T", " "), "message": last.get("message", ""),
            "kept": bool(last.get("kept"))}


def restore_check(user, i, passphrase=""):
    s = _snap(i)
    if s is None:
        return False, "That backup is no longer there."
    return aa.restore_check(user, s["src"], s["name"], passphrase)


def restore_start(user, i, passphrase, port, lan=False):
    """Check, then start the restore in a separate process and close this web app 2 s later -> (ok, message)."""
    s = _snap(i)
    if s is None:
        return False, "That backup is no longer there."
    if (user or {}).get("role") != "adult":
        return False, "Only adults can restore a backup."
    import restore_backup as rb
    ok, msg = rb.check(s["src"], s["name"], passphrase or None)
    if not ok:
        return False, msg
    aa._audit(user, "restore_start", f"snapshot={s['name']}")
    rb.start_live(s["src"], s["name"], passphrase or None, by=(user or {}).get("name") or "local", port=port, web=True, lan=lan)
    return True, "Closing to restore. This page comes back by itself in about a minute; then sign in again."


def close_soon(seconds=2.0):
    """End this web app a moment after the answer has gone out (the restore waits for it to exit)."""
    threading.Timer(seconds, lambda: os._exit(0)).start()


def backup(user):
    ok, msg = aa.backup_now(user)
    return ok, ("Backup done." if ok else "The backup did not finish: ") + ("" if ok else msg[-300:])


def export(user):
    """-> (ok, message, zip path or None)."""
    return aa.export_now(user)


def export_file(name):
    """An export zip by its file name, only from inside exports/ (no path parts), else None."""
    if not name or "/" in name or "\\" in name or not name.endswith(".zip"):
        return None
    p = (paths.EXPORTS / name)
    try:
        if p.resolve().parent != paths.EXPORTS.resolve() or not p.is_file():
            return None
    except OSError:
        return None
    return p


def check_update(force=False):
    """-> {'current', 'newer' (version or ''), 'error'}; asks GitHub at most every ten minutes unless `force`."""
    cur = _version()
    if force or time.time() - _UPDATE["at"] > UPDATE_TTL:
        try:
            import updater as upd
            _, rel, newer = upd.check(quiet=True)
            _UPDATE["site"] = ""
            if rel is None:
                pub = upd.site_release()  # not open to this PC: the public releases on the Mitra Home site
                if pub:
                    rel, newer = pub, upd.parse(pub["version"]) > upd.parse(cur)
                    _UPDATE["site"] = pub["url"] if newer else ""
            if rel is None:
                _UPDATE.update(newer=None, error="Could not check. Is this PC online? If it is, the update token may have "
                                                 "run out, or be missing: see 'Update token' in the health check.")
            else:
                _UPDATE.update(newer=rel["version"] if newer else "", error="")
        except Exception as e:  # noqa: BLE001 (a check must never break the page)
            _UPDATE.update(newer=None, error=f"Could not check ({type(e).__name__}).")
        _UPDATE["at"] = time.time()
    return {"current": cur, "newer": _UPDATE["newer"], "error": _UPDATE["error"], "checked": _UPDATE["at"] > 0}


def daily_check():
    """{'on', 'checked' (YYYY-MM-DD HH:MM or ''), 'newer'} for the Updates card; no network call."""
    import update_notice
    st = update_notice.state()
    a = update_notice.available()
    return {"on": update_notice.enabled(), "checked": str(st.get("checked_at") or "")[:16].replace("T", " "),
            "newer": a["version"] if a else "", "host": update_notice.HOST,
            "site": a["url"] if a and a["source"] == "site" else ""}


def daily_check_set(user, on):
    return aa.update_check_set(user, on)


def update(user, port=None, lan=False):
    """The signed update -> (ok, message). With `port` (the web app), the app then starts again on that port by itself
    (restore_backup.start_relaunch; the caller closes this process with close_soon), so the new code is what runs."""
    ok, tail = aa.update_now(user)
    _UPDATE.update(at=0.0, newer=None, error="", site="")
    if not ok:
        return False, "The update did not finish. " + tail[-400:]
    if port:
        import restore_backup as rb
        rb.start_relaunch(port, lan)
        return True, "Updated. The app starts again with the new version; this page comes back by itself in a few seconds."
    return True, "Updated. Close the black window and start it again to use the new version."


def full_check():
    """`onboard.py doctor` (tasks, AI, phone bot; about a minute) -> its [x] / [!] / [ ] lines."""
    r = subprocess.run([sys.executable, str(paths.ROOT / "onboard.py"), "doctor"], cwd=paths.ROOT, capture_output=True,
                       text=True, timeout=DOCTOR_TIMEOUT, stdin=subprocess.DEVNULL)
    lines = [ln.strip() for ln in (r.stdout + r.stderr).splitlines()
             if ln.strip().startswith(("[x]", "[!]", "[ ]")) or "checks passed" in ln]
    return lines[-40:] or ["The check did not finish."]


def tasks():
    """The Runs on its own card: overall state, one row per job (on / off, when, last run) and the days to pick from."""
    import agent_profile
    out = aa.tasks_status()
    out["jobs"] = aa.task_jobs()
    out["days"] = list(agent_profile.DAY_NAMES.items())
    return out


def task_set(user, job, on):
    return aa.task_set(user, job, on)


def task_time(user, job, day, time_):
    return aa.task_time(user, job, day, time_)


def tasks_register(user, inbox_cycle):
    return aa.tasks_register(user, inbox_cycle)


def changes():
    return aa.what_changed()


def _version():
    try:
        return (paths.ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


# ---- the data check (data/audit.py) ----
DAYS = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday",
        "SUN": "Sunday"}
_AUDIT_LOCK = threading.Lock()


def audit_state():
    """The Data check page: audit.latest() (None before the first run, or on an older database) plus when it runs."""
    import agent_profile
    import audit
    import db
    try:
        with db.open(paths.DB, readonly=True) as con:
            x = audit.latest(con)
    except Exception:  # noqa: BLE001 (no database or not migrated yet: the page offers "Check now")
        x = None
    p = agent_profile.get()
    import audit_explain
    ex = audit_explain.cached(x["run"]["id"]) if x else None
    if x:
        for f in x["findings"]:
            f["why"] = ((ex or {}).get("items") or {}).get(f["dedupe_key"], "")
    return {"x": x, "when": f"{DAYS.get(p['weekly_day'], p['weekly_day'])}s at {p['weekly_time']}, with the weekly digest",
            "checks": audit.CHECKS, "explain": ex, "ai_ok": audit_explain.provider_ok()}


def audit_run(user):
    """Check now -> (ok, message). Adults only; one run at a time; read-only apart from the audit tables."""
    if (user or {}).get("role") != "adult":
        return False, "Only an adult can run the data check."
    if not _AUDIT_LOCK.acquire(blocking=False):
        return False, "A data check is already running."
    try:
        import audit
        audit.run("now", (user or {}).get("name") or None)
    except Exception as e:  # noqa: BLE001
        return False, f"The data check could not run ({type(e).__name__})."
    finally:
        _AUDIT_LOCK.release()
    try:  # what a person can fix shows up in the Inbox at once, not only after the next task run
        import proposals
        proposals.sync()
    except Exception:  # noqa: BLE001
        pass
    return True, "Data check done."


def audit_explain(user):
    """Explain with AI -> (ok, message). Adults only; one call per run, a few a day (audit_explain.py)."""
    if (user or {}).get("role") != "adult":
        return False, "Only an adult can ask for this."
    import audit_explain
    import db
    if not audit_explain.provider_ok():
        return False, "Set up an AI helper with an API key first (Settings > Connections)."
    try:
        with db.open(paths.DB, readonly=True) as con:
            x = audit_explain.explain(con)
    except Exception as e:  # noqa: BLE001
        return False, f"The AI could not explain it this time ({type(e).__name__})."
    return (True, "Explained below.") if x else (False, "No explanation this time: nothing found, the daily limit was "
                                                       "reached, or the answer could not be checked against the records.")


def audit_undo(user, fix_id):
    import edit_actions as ea
    return ea.audit_fix_undo(user, fix_id)
