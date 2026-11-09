"""What the inbox run is doing right now, file by file, for the Inbox page's progress panel.

One small JSON file in logs/ (intake_progress.json), rewritten at every step by data/ai_intake.py (the scheduled inbox
check and "File them now" both run it). No file contents, only names, the step and the outcome line ai_intake prints.

  {"started": ts, "updated": ts, "finished": ts | null, "files": [{"name", "step", "status", "info"}]}

step: queued -> checking -> reading -> sorting -> done. status (when done): filed | review | duplicate | waiting | skipped
| stopped (the run ended before this file: close_open).
"""
import json
import os
import time

import paths

NAME = "intake_progress.json"
STEPS = ("queued", "checking", "reading", "sorting", "done")
STALE_S = 20 * 60  # no write for this long: the run died; the page stops showing it as running
RECENT_S = 15 * 60  # a finished run's results stay on the page this long


OUTCOMES = "intake_outcomes.json"  # the last outcome of each file still in inbox/ (waiting, skipped, stopped)
KEEP = ("waiting", "skipped", "stopped")
OUTCOMES_MAX = 500


def path():
    return paths.LOGS / NAME


def outcomes():
    """{file name: {"status", "info", "at"}} for files a run left in inbox/, so the page can still say why after the
    run's own panel is gone. {} when none."""
    try:
        d = json.loads((paths.LOGS / OUTCOMES).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _remember(updates):
    """updates = {name: (status, info)}: a file left in inbox/ is remembered with its reason, any other end forgets it."""
    cur = outcomes()
    for name, (status, info) in updates.items():
        if status in KEEP:
            cur[name] = {"status": status, "info": str(info)[:160], "at": time.time()}
        else:
            cur.pop(name, None)
    if len(cur) > OUTCOMES_MAX:
        cur = dict(sorted(cur.items(), key=lambda kv: kv[1].get("at", 0))[-OUTCOMES_MAX:])
    p = paths.LOGS / OUTCOMES
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(cur), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:  # a nicety, as the panel itself
        pass


def _write(state):
    state["updated"] = time.time()
    p = path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state), encoding="utf-8")
        os.replace(tmp, p)
    except OSError:  # progress is a nicety: a full disk or a locked file must never stop the filing
        pass


class Run:
    """ai_intake.run's reporter: start(names), step(name, step), done(name, status, info), finish()."""

    def __init__(self, names):
        self.state = {"started": time.time(), "finished": None,
                      "files": [{"name": n, "step": "queued", "status": "", "info": ""} for n in names]}
        self.by = {f["name"]: f for f in self.state["files"]}
        _write(self.state)

    def step(self, name, step):
        f = self.by.get(name)
        if f is not None and f["step"] != step:
            f["step"] = step
            _write(self.state)

    def done(self, name, status, info=""):
        f = self.by.get(name)
        if f is not None:
            f.update(step="done", status=status, info=str(info)[:160])
            _write(self.state)
            _remember({name: (status, info)})

    def finish(self):
        self.state["finished"] = time.time()
        _write(self.state)


def read(now=None):
    """The last run as a dict plus "running" (bool) and "recent" (finished in the last RECENT_S), or None."""
    try:
        state = json.loads(path().read_text(encoding="utf-8"))
        files = state["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    now = now or time.time()
    fin, upd = state.get("finished"), state.get("updated") or 0
    state["running"] = not fin and now - upd < STALE_S
    state["recent"] = bool(fin) and now - fin < RECENT_S
    state["files"] = [f for f in files if isinstance(f, dict) and f.get("name")]
    return state


def starting(names):
    """Written by the web app the moment it starts a run, so the page shows the queue before Python has even loaded."""
    Run(names)


def close_open(reason):
    """A run that ended without finish() (it never started because another one held the inbox, it crashed or it was
    stopped): every file not done yet becomes status "stopped" with `reason`, and the run is marked finished, so the
    page stops showing a spinner. Returns how many files it closed; 0 when the last run had finished."""
    try:
        state = json.loads(path().read_text(encoding="utf-8"))
        files = state["files"]
    except (OSError, ValueError, KeyError, TypeError):
        return 0
    if state.get("finished"):
        return 0
    n, left = 0, {}
    for f in files:
        if isinstance(f, dict) and f.get("step") != "done":
            f.update(step="done", status="stopped", info=str(reason)[:160])
            left[f.get("name", "")] = ("stopped", reason)
            n += 1
    state["finished"] = time.time()
    _write(state)
    _remember({k: v for k, v in left.items() if k})
    return n
