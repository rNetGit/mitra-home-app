"""Test-suite guard: nothing the tests start may change this PC's real scheduled tasks.

conftest.py puts this folder first on PYTHONPATH, so every Python process the suite starts (a copy's onboard.py, an
older release's code, run_task.py) imports this file at start-up; conftest installs it in the test process too. It wraps
subprocess.Popen: schtasks, crontab, launchctl and the PowerShell *-ScheduledTask commands never run, a stand-in that
exits 1 runs instead (the tool answers "not found" / "failed"). A command that would have CHANGED a task is appended to
the file named by MITRAHOME_SCHEDULER_TRIPWIRE, and conftest fails the test that caused it.

This backs up task_register's own test mode (MITRAHOME_NO_SCHEDULER=1): code that predates it, or a new call that forgets
it, still cannot reach the real scheduler.
"""
import json
import os
import subprocess
import sys

TOOLS = {"schtasks", "crontab", "launchctl"}
SHELLS = {"cmd", "powershell", "pwsh", "sh", "bash"}


def _words(args):
    if isinstance(args, bytes):
        args = args.decode(errors="replace")
    if isinstance(args, str):
        return args.replace('"', " ").replace("'", " ").split()
    if isinstance(args, os.PathLike):
        return [os.fsdecode(args)]
    return [os.fsdecode(x) if isinstance(x, (bytes, os.PathLike)) else str(x) for x in args]


def _tool(word):
    name = os.path.basename(word.replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


def scheduler_call(args):
    """-> None (not a scheduler command), "read" (it only asks) or "change" (it would register, change, run or remove)."""
    words = _words(args)
    if not words:
        return None
    first = _tool(words[0])
    if first in SHELLS:  # cmd /c schtasks ..., powershell Register-ScheduledTask ...
        for i, w in enumerate(words[1:], 1):
            if _tool(w) in TOOLS:
                words, first = words[i:], _tool(w)
                break
        else:
            hits = [w.lower() for w in words if "scheduledtask" in w.lower()]
            if not hits:
                return None
            return "read" if all(h.startswith("get-") for h in hits) else "change"
    if first not in TOOLS:
        return None
    rest = [w.lower() for w in words[1:]]
    if first == "schtasks":
        verb = next((w for w in rest if w.startswith("/")), "/query")
        return "read" if verb == "/query" else "change"
    if first == "crontab":
        return "read" if rest == ["-l"] else "change"
    return "read" if rest[:1] in (["print"], ["list"]) else "change"  # launchctl


def _note(args):
    path = os.environ.get("MITRAHOME_SCHEDULER_TRIPWIRE")
    if not path:
        return
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"cmd": _words(args), "pid": os.getpid(), "cwd": os.getcwd()}) + "\n")
    except OSError:
        pass


def install():
    if getattr(subprocess.Popen, "_mitrahome_scheduler_guard", False):
        return
    real = subprocess.Popen

    class Popen(real):
        _mitrahome_scheduler_guard = True

        def __init__(self, args, *a, **kw):
            kind = scheduler_call(args)
            if kind:
                if kind == "change":
                    _note(args)
                args = [sys.executable, "-c", "raise SystemExit(1)"]
                kw["shell"] = False
                kw.pop("executable", None)
            super().__init__(args, *a, **kw)

    subprocess.Popen = Popen


install()
