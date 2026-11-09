"""One run of a job at a time, across processes (the web app, scheduled tasks, a terminal).

  with joblock.held("intake"):      # raises joblock.Busy when another live process holds it
      ...
  with joblock.job("bank_sync"):    # the same, and Busy while an update or restore is running
      ...
  with joblock.maintenance():       # update, restore, migrate: everything else waits or skips its turn
      ...

The lock is logs/<name>.lock holding the owner's process id and start time. A lock whose process is gone, or that is
older than `stale_after` seconds, is taken over (a crash or a power cut never blocks the job for good).

Maintenance (an update, a restore, a migration) changes the database file itself, so nothing may write while it runs:
- it waits for the running jobs in JOBS to finish first (Busy when they do not),
- `job()` refuses to start while it runs, scheduled tasks skip their turn (tasks/run_task.py),
- `db.connect` waits for it and then answers "database is locked" (shown as "busy, try again"),
- its own child processes (the migrate steps) inherit ENV and are let through.
"""
import contextlib
import os
import time

import paths


class Busy(Exception):
    """Another process is running this job right now."""


MAINTENANCE = "maintenance"
ENV = "MITRAHOME_MAINTENANCE"  # set inside a maintenance run and inherited by its child processes
JOBS = ("intake", "bank_sync", "backup")  # jobs that write and run on their own (scheduled or from a button)
FRESH = 5  # seconds: a lock file still empty this young is being written by its owner, not stale


def _alive(pid):
    if pid <= 0:
        return False
    if os.name == "nt":  # os.kill on Windows would end the process: ask for its exit code instead
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return bool(ok) and code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _owner(path):
    """(pid, started) from a lock file, or None when it is missing, empty or half-written."""
    try:
        pid, started = (int(x) for x in path.read_text(encoding="utf-8").split()[:2])
    except (OSError, ValueError):
        return None
    return pid, started


def _stale(path, stale_after):
    o = _owner(path)
    if o is None:
        try:  # empty: its owner may be between creating and writing it
            return time.time() - path.stat().st_mtime > FRESH
        except FileNotFoundError:
            return True
    pid, started = o
    return not _alive(pid) or time.time() - started > stale_after


def lock_path(name):
    return paths.LOGS / f"{name}.lock"


def is_held(name, stale_after=6 * 3600):
    """True when a live process (this one included) holds the lock."""
    p = lock_path(name)
    return p.exists() and not _stale(p, stale_after)


@contextlib.contextmanager
def held(name, stale_after=6 * 3600, wait=0.0):
    """Hold logs/<name>.lock; `wait` seconds to keep trying before Busy (0 = answer at once)."""
    path = lock_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    end = time.time() + wait
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if _stale(path, stale_after):
                _unlink(path, tries=1)
                continue
        except PermissionError:  # Windows: another holder is deleting or reading the file right now
            pass
        if time.time() >= end:
            raise Busy(name) from None
        time.sleep(0.05)
    try:
        os.write(fd, f"{os.getpid()} {int(time.time())}\n".encode())
    finally:
        os.close(fd)
    try:
        yield
    finally:
        _unlink(path)


def _unlink(path, tries=40):
    """Remove a lock file; on Windows a process reading it at that moment makes the delete fail for a moment."""
    for _ in range(tries):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except PermissionError:
            time.sleep(0.05)


def in_maintenance():
    """True inside a maintenance run (this process or a child it started)."""
    return os.environ.get(ENV) == "1"


def maintenance_running():
    """True while another process runs an update, restore or migration (never for that run's own processes)."""
    return not in_maintenance() and is_held(MAINTENANCE, stale_after=MAINTENANCE_STALE)


MAINTENANCE_STALE = 3 * 3600  # an update may take half an hour on a slow line; a crashed one never blocks for good


@contextlib.contextmanager
def job(name, stale_after=6 * 3600):
    """A job that writes on its own: one run at a time, never while an update or restore is running."""
    if maintenance_running():
        raise Busy(MAINTENANCE)
    with held(name, stale_after):
        yield


@contextlib.contextmanager
def maintenance(wait_jobs=60.0):
    """Update, restore or migrate: first wait (up to `wait_jobs` s) for running jobs, then hold everything else off.
    Re-entrant through ENV: a migration started by an update runs inside the update's hold."""
    if in_maintenance():
        yield
        return
    with held(MAINTENANCE, stale_after=MAINTENANCE_STALE):
        os.environ[ENV] = "1"
        try:
            end = time.time() + wait_jobs
            while True:
                busy = [j for j in JOBS if is_held(j)]
                if not busy:
                    break
                if time.time() >= end:
                    raise Busy(busy[0])
                time.sleep(0.5)
            yield
        finally:
            os.environ.pop(ENV, None)
