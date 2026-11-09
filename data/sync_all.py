"""One Sync: bank pull + Google Drive inbox pull + Gmail label + mail folder, in one background run.

  python data/sync_all.py status      what the last run did
  python data/sync_all.py run         do it now (the Sync button starts this in the background)

The same scripts the scheduled inbox check and daily task run, one after another, each only when the family set it up.
No AI: papers that arrive wait in the Inbox (the two-hourly inbox check or "File them now" reads them). A step that
fails does not stop the next. Progress and the last result live in logs/sync_all.json (step labels and each script's
last output line, never file contents); one run at a time (joblock "sync_all", never during an update or restore).
"""
import datetime as dt
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402

ROOT = HERE.parent
STATE = paths.LOGS / "sync_all.json"
STEP_TIMEOUT = 300
LINE_MAX = 160
RECENT_MINUTES = 15   # how long a finished run still shows on Today


def steps():
    """[(key, label, argv)] for what this household set up, in the order they run."""
    out = []
    # bank_sync's own gate (the SimpleFIN access URL), read here so this module stays out of the import cycle
    # that bank_sync / admin_actions / proposals form (tests/test_import_cycles.py)
    if config.read_secret("SIMPLEFIN_ACCESS_URL"):
        out.append(("bank", "Bank", [sys.executable, str(HERE / "bank_sync.py"), "pull"]))
    if config.drive_path() is not None:
        out.append(("drive", "Google Drive inbox", [sys.executable, str(HERE / "sync_drive.py"), "pull"]))
    fam = config.family()
    if (fam.get("gmail") or {}).get("enabled") and (HERE / "google_gmail.py").exists():
        out.append(("gmail", "Gmail label", [sys.executable, str(HERE / "google_gmail.py"), "pull"]))
    if (fam.get("mail_folder") or {}).get("enabled") and (HERE / "mail_folder.py").exists():
        out.append(("mail", "Mail folder", [sys.executable, str(HERE / "mail_folder.py"), "pull"]))
    return out


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _save(state):
    config.write_json(STATE, state)


def read():
    """The last run: {"running", "step", "lines", "started", "finished", "ok"} or None. A run whose process is gone
    (crash, PC off) is reported as stopped, never as still running."""
    import joblock
    try:
        import json
        s = json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if s.get("running") and not joblock.is_held("sync_all"):
        s.update(running=False, ok=False, finished=s.get("finished") or s.get("started"))
        s["lines"] = (s.get("lines") or []) + ["Stopped before it finished."]
    return s


def recent(now=None, minutes=RECENT_MINUTES):
    """read(), but None once a finished run is older than `minutes`."""
    s = read()
    if not s or s.get("running"):
        return s
    try:
        at = dt.datetime.fromisoformat(s["finished"])
    except (KeyError, ValueError, TypeError):
        return None
    return s if ((now or dt.datetime.now()) - at) <= dt.timedelta(minutes=minutes) else None


def start():
    """Start a run in the background. -> (ok, message); returns at once."""
    import joblock
    todo = steps()
    if not todo:
        return False, "Nothing to sync yet: set up bank sync, the Google Drive inbox or a mail folder in Settings > Connections."
    if joblock.is_held("sync_all"):
        return True, "Already syncing. The Keep up card shows how far it is."
    if joblock.maintenance_running():
        return False, "An update or restore is running. Press Sync again in a few minutes."
    _save({"running": True, "step": todo[0][1], "lines": [], "started": _now(), "finished": "", "ok": True})
    try:
        subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "run"], cwd=ROOT,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    except OSError:
        _save({"running": False, "step": "", "lines": ["Sync did not start."], "started": _now(), "finished": _now(), "ok": False})
        return False, "Sync did not start. Try again in a moment."
    return True, "Syncing: " + ", ".join(label.lower() for _, label, _ in todo) + "."


def _last_line(text):
    for ln in reversed((text or "").splitlines()):
        if ln.strip():
            return ln.strip()[:LINE_MAX]
    return "done"


def run():
    """Do every step now; -> True when all steps worked."""
    import joblock
    todo = steps()
    try:
        with joblock.job("sync_all"):
            state = {"running": True, "step": "", "lines": [], "started": _now(), "finished": "", "ok": True}
            for key, label, argv in todo:
                state["step"] = label
                _save(state)
                try:
                    r = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, errors="replace", timeout=STEP_TIMEOUT)
                    ok = r.returncode == 0
                    said = _last_line((r.stdout or "") + (r.stderr or "")) if not ok or r.stdout else "done"
                except subprocess.TimeoutExpired:
                    ok, said = False, "took too long and was stopped"
                except OSError as e:
                    ok, said = False, f"could not start ({e.__class__.__name__})"
                state["ok"] = state["ok"] and ok
                state["lines"].append(f"{label}: {said}" if ok else f"{label}: did not finish ({said})")
            state.update(running=False, step="", finished=_now())
            _save(state)
            return state["ok"]
    except joblock.Busy as e:
        _save({"running": False, "step": "", "lines": [str(e)], "started": _now(), "finished": _now(), "ok": False})
        return False


def main(argv=None):
    cmd = (argv or sys.argv[1:] or ["status"])[0]
    if cmd == "run":
        return 0 if run() else 1
    s = read()
    if not s:
        print("No sync has run yet.")
        return 0
    print(("Running: " + s["step"]) if s["running"] else f"Finished {s['finished']} ({'ok' if s['ok'] else 'with problems'})")
    for ln in s["lines"]:
        print("  " + ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
