"""Which web app process belongs to this app folder (standard library only).

`launch.py` writes the web app's port and process id to `.webapp.json` in the app folder when it starts it, and reads it
to open the app that is already running instead of starting a second one, and never mistakes another install's app on a
nearby port for this one.
"""
import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
NAME = ".webapp.json"
WEB_NAME = NAME  # the name used while the classic dashboard still existed


def path(root=ROOT, name=NAME):
    return pathlib.Path(root) / name


def write(port, root=ROOT, pid=None, lan=False, name=NAME):
    """Remember this process as the dashboard of `root` (best effort; a read-only folder is not an error)."""
    rec = {"port": int(port), "pid": int(pid or os.getpid()), "lan": bool(lan)}
    try:
        old = read(root, alive=False, name=name)
        if old and old.get("lan") and not lan and pid is None:  # the dashboard process itself never knows its address
            rec["lan"] = True
        if old != rec:
            path(root, name).write_text(json.dumps(rec) + "\n", encoding="utf-8")
    except OSError:
        pass


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":  # os.kill(pid, 0) would terminate the process on Windows
        try:
            r = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True, text=True, timeout=15)
            return str(int(pid)) in r.stdout.split()
        except (OSError, subprocess.SubprocessError, ValueError):
            return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # exists, not ours to signal
    return True


def read(root=ROOT, alive=True, name=NAME):
    """-> {"port", "pid", "lan"} or None (no record, unreadable, or the process is gone)."""
    try:
        rec = json.loads(path(root, name).read_text(encoding="utf-8"))
        rec = {"port": int(rec["port"]), "pid": int(rec["pid"]), "lan": bool(rec.get("lan"))}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return rec if not alive or pid_alive(rec["pid"]) else None


def forget(root=ROOT, name=NAME):
    try:
        path(root, name).unlink()
    except OSError:
        pass
