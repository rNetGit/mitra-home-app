"""Scheduled-task heartbeat: logs/heartbeat.json  {task: {"ok": bool, "at": ISO, "note": str}}.

  python data/heartbeat.py ok|fail TASK [note]     record a run (used by tasks/run_task.py)
  python data/heartbeat.py show                     print last runs and anything stale

Dashboard and doctor use stale() to warn when a registered task has stopped running.
"""
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
import paths  # noqa: E402
import dates  # noqa: E402
sys.path.insert(0, str(HERE))
import config  # noqa: E402

FILE = paths.LOGS / "heartbeat.json"
MAX_AGE_DAYS = {"daily_digest": 3, "weekly_digest": 9, "weekly_backup": 9, "inbox_cycle": 1, "inbox_sweep": 1}
OPTIONAL = {"inbox_cycle": "inbox_cycle", "inbox_sweep": "sweep_registered"}  # watched once the family switched it on, or once it has run


def _load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def record(task, ok, note=""):
    data = _load()
    data[task] = {"ok": bool(ok), "at": dt.datetime.now().isoformat(timespec="seconds"), "note": note[:300]}
    config.write_json(FILE, data)


def stale(today=None, assume_registered=False):
    """[(task, message)] for registered tasks that never ran, last failed, or ran too long ago.
    Only reports once the wizard recorded `tasks_registered` in config/family.json, unless the caller knows the jobs
    run (keepup.py: a recent heartbeat is proof enough) and passes assume_registered."""
    if not assume_registered and not config.family().get("tasks_registered"):
        return []
    today = today or dates.today()
    data, out = _load(), []
    off = set(config.family().get("tasks_off") or [])  # switched off in Settings > Data: not expected to run
    for task, limit in MAX_AGE_DAYS.items():
        r = data.get(task)
        if task in off or (task in OPTIONAL and not config.family().get(OPTIONAL[task]) and not r):
            continue
        if not r:
            out.append((task, "has not run yet"))
            continue
        age = (today - dt.datetime.fromisoformat(r["at"]).date()).days
        if not r["ok"]:
            out.append((task, f"last run FAILED ({r['note'] or 'see logs/'}) {age}d ago"))
        elif age > limit:
            out.append((task, f"last ran {age} days ago"))
    return out


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    if cmd in ("ok", "fail") and len(sys.argv) >= 3:
        record(sys.argv[2], cmd == "ok", " ".join(sys.argv[3:]))
    else:
        for t, r in sorted(_load().items()):
            print(f"{t}: {'ok' if r['ok'] else 'FAILED'} at {r['at']} {r['note']}")
        for t, m in stale():
            print(f"STALE {t}: {m}")
