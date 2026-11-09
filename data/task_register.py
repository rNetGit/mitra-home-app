"""Register Mitra Home's scheduled jobs with the operating system, without asking questions (standard library only).

Windows: Task Scheduler (`schtasks`). macOS: launchd LaunchAgents (`~/Library/LaunchAgents/ai.mitrahome.<job>.plist`;
cron needs Full Disk Access on a Mac and then fails silently; cron lines left from before are removed). Linux: cron
lines marked `# MitraHome`. The wizard (`onboard.py`, step
"Scheduled tasks") and Settings > Data > "Runs on its own" (Switch them all on) both call `register()`; that card also switches one job on or off (`set_job`) and shows its state (`job_state`); the dashboard never sees
a passphrase or a folder, those stay in the wizard.

Before the rename the tasks were called "Mitra Home Daily Digest" ... and the cron lines were marked `# Mitra Home`.
`adopt_legacy()` (run by `onboard.py upgrade`) moves them to the new names, so no job runs twice or goes missing.
"""
import os
import pathlib
import platform
import plistlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import brand  # noqa: E402

P = brand.TASK_PREFIX
TASKS = [  # (task name, tasks/<job>.bat + run_task.py job, schtasks schedule args)
    (f"{P} Daily Digest", "daily_digest", ["/sc", "daily", "/st", "07:00"]),
    (f"{P} Weekly Digest", "weekly_digest", ["/sc", "weekly", "/d", "SUN", "/st", "18:00"]),
    (f"{P} Weekly Backup", "weekly_backup", ["/sc", "weekly", "/d", "SUN", "/st", "09:00"]),
]
INBOX_TASK = (f"{P} Inbox Cycle", "inbox_cycle", ["/sc", "hourly", "/mo", "2"])
SWEEP_TASK = (f"{P} Inbox Sweep", "inbox_sweep", ["/sc", "minute", "/mo", "15"])
MARK = "# " + brand.SLUG
LEGACY_MARK = "# " + brand.LEGACY_SLUG
CRON = {  # run_task name -> cron schedule (macOS / Linux)
    "daily_digest": "0 7 * * *", "weekly_digest": "0 18 * * 0", "weekly_backup": "0 9 * * 0", "inbox_cycle": "0 */2 * * *",
    "inbox_sweep": "*/15 * * * *",
}


def _profile():
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import agent_profile
    return agent_profile


def cron(job):
    """The cron schedule; the daily and weekly digest follow the agent profile (Settings > Home Profile)."""
    try:
        return _profile().cron_line(job) or CRON[job]
    except Exception:  # noqa: BLE001 (an unreadable profile falls back to the fixed times)
        return CRON[job]


def sched(job, default):
    try:
        return _profile().schtasks_args(job) or default
    except Exception:  # noqa: BLE001
        return default


def jobs(inbox_cycle=False):
    return [t[1] for t in TASKS] + (["inbox_cycle"] if inbox_cycle else [])


def legacy_name(name):
    """The name a task had before the rename ("Mitra Home Daily Digest" -> "FamilyAgent Daily Digest")."""
    return brand.LEGACY_TASK_PREFIX + name[len(brand.TASK_PREFIX):] if name.startswith(brand.TASK_PREFIX) else None


def _ours(line):
    return line.rstrip().endswith((MARK, LEGACY_MARK))


def cron_lines(job_names):
    return [f"{cron(j)} cd '{ROOT}' && '{sys.executable}' tasks/run_task.py {j}  {MARK}" for j in job_names]


def install_crontab(lines):
    """Replace this app's cron lines (either marker) with `lines`. -> (ok, message)."""
    cur = _sched(["crontab", "-l"], capture_output=True, text=True)
    keep = [x for x in (cur.stdout.splitlines() if cur.returncode == 0 else []) if not _ours(x)]
    r = _sched(["crontab", "-"], input="\n".join(keep + lines) + "\n", text=True, capture_output=True)
    return r.returncode == 0, ("installed" if r.returncode == 0 else "FAILED " + r.stderr.strip())


def register_windows(inbox_cycle=False):
    """-> (all ok, [(task name, ok, detail)])."""
    out = []
    for name, job, default in TASKS + ([INBOX_TASK] if inbox_cycle else []):
        ok, msg = create_windows(name, job, sched(job, default))
        out.append((name, ok, ("registered" + (f" ({msg})" if msg else "")) if ok else "FAILED " + msg))
        if ok:
            _drop_windows(legacy_name(name))
    return all(ok for _, ok, _ in out), out


# Task Scheduler's defaults skip a run on battery, stop a running job when the plug comes out and drop a run missed while
# the PC slept; on a laptop that silently skips every job. `schtasks /create` cannot change them, so each task is given
# these settings right after it is created (the rest of its settings are kept as they are).
LAPTOP_SETTINGS = ("$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction Stop; $s = $t.Settings; "
                   "$s.DisallowStartIfOnBatteries = $false; $s.StopIfGoingOnBatteries = $false; $s.StartWhenAvailable = $true; "
                   "Set-ScheduledTask -TaskName '{name}' -Settings $s -ErrorAction Stop | Out-Null")


def laptop_settings_cmd(name):
    """The PowerShell command that lets the task `name` start and keep running on battery and run a missed start at the
    next wake."""
    script = LAPTOP_SETTINGS.format(name=name.replace("'", "''"))
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]


# The web app is a long-running job, not a short one (autostart.py, kind "web": a task that ticks every 5 minutes and runs
# launch.py, which exits at once when the app is already up). Besides the battery settings, a task made with
# `schtasks /create` is stopped after 72 hours (ExecutionTimeLimit); this lets it run without a time limit and never
# starts a second copy while the first still runs (MultipleInstances IgnoreNew), so the next tick after the app dies
# starts it again.
SERVICE_SETTINGS = ("$t = Get-ScheduledTask -TaskName '{name}' -ErrorAction Stop; $s = $t.Settings; "
                    "$s.DisallowStartIfOnBatteries = $false; $s.StopIfGoingOnBatteries = $false; $s.StartWhenAvailable = $true; "
                    "$s.ExecutionTimeLimit = 'PT0S'; $s.MultipleInstances = 'IgnoreNew'; "
                    "Set-ScheduledTask -TaskName '{name}' -Settings $s -ErrorAction Stop | Out-Null")


def service_settings_cmd(name):
    """The PowerShell command that gives the task `name` the settings of a long-running job (see SERVICE_SETTINGS)."""
    script = SERVICE_SETTINGS.format(name=name.replace("'", "''"))
    return ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script]


def create_windows(name, job, schedule, run=None, root=ROOT):
    """Create (or replace) the task `name` running tasks/<job>.bat on `schedule` (schtasks arguments), then set it to run
    on battery and after a missed start. Both calls go through `run` (default `_sched`, so test mode touches nothing).
    -> (ok, message): not ok = the task was not created (message = the scheduler's error); ok with a message = created,
    but the battery settings could not be set (it then runs only on mains power, as before)."""
    run = run or _sched
    kw = {"capture_output": True, "text": True}
    if platform.system() == "Windows":
        kw["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = run(["schtasks", "/create", "/f", "/tn", name, "/tr", f'"{root / "tasks" / (job + ".bat")}"', *schedule], **kw)
    if r.returncode != 0:
        return False, (r.stderr or "").strip()[:200]
    try:
        s = run(laptop_settings_cmd(name), **kw)
    except OSError as e:
        return True, f"runs only on mains power: {e}"[:200]
    return True, "" if s.returncode == 0 else ("runs only on mains power: " + ((s.stderr or "").strip() or "settings refused"))[:200]


def _exists_windows(name):
    return bool(name) and _sched(["schtasks", "/query", "/tn", name], capture_output=True, text=True).returncode == 0


def _drop_windows(name):
    """Delete the task `name` if it exists (the pre-rename copy of a task just registered under its new name)."""
    if _exists_windows(name):
        _sched(["schtasks", "/delete", "/f", "/tn", name], capture_output=True, text=True)


def adopt_legacy():
    """Move tasks registered before the rename to the new names (same job, schedule from the profile), then remove the
    old ones. Cron lines just get the new marker. -> names moved (empty when there was nothing to move)."""
    if platform.system() != "Windows":
        cur = _sched(["crontab", "-l"], capture_output=True, text=True)
        lines = cur.stdout.splitlines() if cur.returncode == 0 else []
        if not any(x.rstrip().endswith(LEGACY_MARK) for x in lines):
            return []
        new = [x.rstrip()[:-len(LEGACY_MARK)] + MARK if x.rstrip().endswith(LEGACY_MARK) else x for x in lines]
        r = _sched(["crontab", "-"], input="\n".join(new) + "\n", text=True, capture_output=True)
        return ["crontab"] if r.returncode == 0 else []
    moved = []
    for name, job, default in TASKS + [INBOX_TASK, SWEEP_TASK]:
        old = legacy_name(name)
        if not _exists_windows(old):
            continue
        if create_windows(name, job, sched(job, default))[0]:
            _drop_windows(old)
            moved.append(name)
    return moved


def remove_windows(root=ROOT):
    """Delete this install's scheduled tasks and the phone bot's start-at-sign-in task or Startup launcher (the Windows
    uninstaller runs it). A task or launcher pointing at another app folder is left alone. -> names removed."""
    import autostart
    gone = []
    bots = [name for name, _script in autostart.CHAT_TASK.values()]
    for name in [t[0] for t in TASKS + [INBOX_TASK, SWEEP_TASK]] + bots:
        for n in (name, legacy_name(name)):
            f = autostart._startup_file(n) if name in bots else None
            try:
                if f is not None and f.exists() and str(root / "tasks").lower() in f.read_text(encoding="ascii", errors="replace").lower():
                    f.unlink()
                    gone.append(str(f.name))
            except OSError:
                pass
            q = _sched(["schtasks", "/query", "/tn", n, "/xml"], capture_output=True, text=True)
            if q.returncode == 0 and str(root / "tasks").lower() in q.stdout.lower():
                if _sched(["schtasks", "/delete", "/f", "/tn", n], capture_output=True, text=True).returncode == 0:
                    gone.append(n)
    return gone


# ------------------------------------------------------------------ one job at a time (Settings > Data > Runs on its own)
ALL = {job: (name, default) for name, job, default in TASKS + [INBOX_TASK, SWEEP_TASK]}
LABELS = {"daily_digest": "Daily brief", "weekly_digest": "Weekly digest and family meeting", "weekly_backup": "Weekly backup",
          "inbox_cycle": "Inbox check", "inbox_sweep": "Phone drop box (Google Drive)"}
EVERY = {"inbox_cycle": "Every two hours", "inbox_sweep": "Every 15 minutes"}  # fixed intervals; the others follow the profile


def live_runner(run=None):
    """The command runner for the real Task Scheduler / crontab, or None when it must not be touched: test mode
    (AIFA_DRY_RUN=1, or MITRAHOME_NO_SCHEDULER=1 which the test suite sets). A runner passed in (tests) is used as is."""
    if run is not None:
        return run
    if os.environ.get("AIFA_DRY_RUN") == "1" or os.environ.get("MITRAHOME_NO_SCHEDULER") == "1":
        return None
    return subprocess.run


def _sched(cmd, **kw):
    """Run one schtasks / crontab / launchctl command through `live_runner`; in test mode nothing runs and the answer
    is a failure, so registering, moving or removing a task never reaches the PC's real scheduler."""
    run = live_runner()
    if run is None:
        return subprocess.CompletedProcess(cmd, 1, "", "test mode: the scheduler was not touched")
    return run(cmd, **kw)


def _folder(root=ROOT):
    return str(root / "tasks").lower()


def job_state(job, run=None, root=ROOT):
    """-> (state, where): "on" (this install runs it), "paused" (registered here but switched off in Task Scheduler),
    "off" (not registered), "elsewhere" (the task name is used by another copy of the app; `where` = its command)
    or "unknown" (test mode, or the scheduler could not be asked)."""
    run = live_runner(run)
    if run is None or job not in ALL:
        return "unknown", ""
    try:
        if platform.system() == "Windows":
            q = run(["schtasks", "/query", "/tn", ALL[job][0], "/xml"], capture_output=True, text=True, errors="replace")
            if q.returncode != 0:
                return "off", ""
            cmd = (re.search(r"<Command>([^<]*)</Command>", q.stdout or "") or [None, ""])[1].strip().strip('"')
            if _folder(root) not in cmd.lower():
                return "elsewhere", cmd
            return ("paused" if "<Enabled>false</Enabled>" in (q.stdout or "") else "on"), cmd
        if is_mac():
            return mac_state(job, run, root)
        cur = run(["crontab", "-l"], capture_output=True, text=True)
        mine = [x for x in (cur.stdout.splitlines() if cur.returncode == 0 else [])
                if _ours(x) and f"run_task.py {job} " in x]
        if not mine:
            return "off", ""
        return ("on", "crontab") if any(f"cd '{root}'" in x for x in mine) else ("elsewhere", mine[0])
    except OSError:
        return "unknown", ""


def adopt_flags(run=None, root=ROOT):
    """Write `tasks_registered` / `inbox_cycle` into family.json when this install's own scheduled jobs exist but the
    flags were never set (jobs made by the installer, an update or by hand): without them the health check says "not
    registered" and heartbeat.stale() stays silent. Never turns a flag off. -> the keys it set; [] when the scheduler
    cannot be asked (test mode) or nothing was missing."""
    import config
    cfg = config.family()
    want = {}
    if not cfg.get("tasks_registered"):
        if any(job_state(j, run, root)[0] in ("on", "paused") for j in ("daily_digest", "weekly_digest", "weekly_backup")):
            want["tasks_registered"] = True
    if not cfg.get("inbox_cycle") and job_state("inbox_cycle", run, root)[0] in ("on", "paused"):
        want["inbox_cycle"] = True
    if want:
        with config.family_edit() as c:
            c.update(want)
    return sorted(want)


def set_job(job, on, run=None, root=ROOT):
    """Switch one job on (register it here at the profile's time; a task of another copy is taken over) or off (only
    when it belongs to this install). -> (ok, message)."""
    if job not in ALL:
        return False, "Unknown job."
    run = live_runner(run)
    if run is None:
        return True, "test mode: nothing changed"
    name, default = ALL[job]
    if platform.system() == "Windows":
        if on:
            ok, msg = create_windows(name, job, sched(job, default), run, root)
            if ok:
                _drop_windows(legacy_name(name))
            return ok, msg
        state, _ = job_state(job, run, root)
        if state == "elsewhere":
            return False, "another copy of the app uses this task; it was left alone"
        if state in ("on", "paused"):
            r = run(["schtasks", "/delete", "/f", "/tn", name], capture_output=True, text=True)
            return r.returncode == 0, "" if r.returncode == 0 else (r.stderr or "").strip()[:200]
        return True, ""
    if is_mac():
        if on:
            return mac_on(job, run, root)
        state, _ = mac_state(job, run, root)
        if state == "elsewhere":
            return False, "another copy of the app uses this job; it was left alone"
        return mac_off(job, run) if state != "off" else (True, "")
    cur = run(["crontab", "-l"], capture_output=True, text=True)
    lines = cur.stdout.splitlines() if cur.returncode == 0 else []
    keep = [x for x in lines if not (_ours(x) and f"run_task.py {job} " in x)]
    new = keep + (cron_lines([job]) if on else [])
    r = run(["crontab", "-"], input="\n".join(new) + "\n", text=True, capture_output=True)
    return r.returncode == 0, "" if r.returncode == 0 else (r.stderr or "").strip()[:200]


# ------------------------------------------------------------------ macOS: launchd LaunchAgents
AGENT_PREFIX = "ai.mitrahome."
DOW = {"0": 0, "7": 0, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}


def is_mac():
    return platform.system() == "Darwin"


def agents_dir(home=None):
    return pathlib.Path(home or pathlib.Path.home()) / "Library" / "LaunchAgents"


def label(job):
    return AGENT_PREFIX + job.replace("_", "-")


def launchd_when(spec):
    """A cron schedule -> the launchd keys: {"StartInterval": seconds} for "*/N * * * *" and "0 */N * * *", else
    {"StartCalendarInterval": {...}} (a list when a field has several values, e.g. weekdays "1,3")."""
    m, h, dom, mon, dow = spec.split()
    if m.startswith("*/") and h == "*":
        return {"StartInterval": int(m[2:]) * 60}
    if h.startswith("*/") and m.isdigit():
        return {"StartInterval": int(h[2:]) * 3600}
    base = {}
    if m != "*":
        base["Minute"] = int(m)
    if h != "*":
        base["Hour"] = int(h)
    if dom != "*":
        base["Day"] = int(dom)
    if mon != "*":
        base["Month"] = int(mon)
    if dow == "*":
        return {"StartCalendarInterval": base}
    cal = [dict(base, Weekday=DOW[d]) for d in dow.split(",")]
    return {"StartCalendarInterval": cal[0] if len(cal) == 1 else cal}


def plist_for(job, root=ROOT, python=None):
    """The LaunchAgent for one job: run `tasks/run_task.py <job>` from this install's folder on the profile's schedule."""
    d = {"Label": label(job), "ProgramArguments": [python or sys.executable, str(root / "tasks" / "run_task.py"), job],
         "WorkingDirectory": str(root), "RunAtLoad": False, "ProcessType": "Background"}
    d.update(launchd_when(cron(job)))
    return plistlib.dumps(d, sort_keys=True)


def _domain():
    return f"gui/{os.getuid()}"


def _agent(job, home=None):
    return agents_dir(home) / f"{label(job)}.plist"


def _agent_root(job, home=None):
    """The install folder a job's LaunchAgent runs from, or None when there is none (or it cannot be read)."""
    try:
        return plistlib.loads(_agent(job, home).read_bytes()).get("WorkingDirectory")
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def mac_on(job, run, root=ROOT, home=None):
    f = _agent(job, home)
    f.parent.mkdir(parents=True, exist_ok=True)
    run(["launchctl", "bootout", f"{_domain()}/{label(job)}"], capture_output=True, text=True)
    f.write_bytes(plist_for(job, root))
    r = run(["launchctl", "bootstrap", _domain(), str(f)], capture_output=True, text=True)
    return r.returncode == 0, "" if r.returncode == 0 else (r.stderr or "").strip()[:200]


def mac_off(job, run, home=None):
    run(["launchctl", "bootout", f"{_domain()}/{label(job)}"], capture_output=True, text=True)
    try:
        _agent(job, home).unlink()
    except FileNotFoundError:
        pass
    return True, ""


def mac_state(job, run, root=ROOT, home=None):
    where = _agent_root(job, home)
    if where is None:
        return "off", ""
    if pathlib.Path(where) != pathlib.Path(root):
        return "elsewhere", where
    q = run(["launchctl", "print", f"{_domain()}/{label(job)}"], capture_output=True, text=True)
    return ("on" if q.returncode == 0 else "paused"), str(_agent(job, home))


def _drop_old_cron(run):
    """Cron lines from before LaunchAgents (macOS) are removed so no job runs twice."""
    cur = run(["crontab", "-l"], capture_output=True, text=True)
    lines = cur.stdout.splitlines() if cur.returncode == 0 else []
    if any(_ours(x) for x in lines):
        run(["crontab", "-"], input="\n".join(x for x in lines if not _ours(x)) + "\n", text=True, capture_output=True)


def register_mac(inbox_cycle=False, run=None, root=ROOT, home=None):
    run = run or _sched
    out = [(label(j),) + mac_on(j, run, root, home) for j in jobs(inbox_cycle)]
    _drop_old_cron(run)
    return all(ok for _, ok, _ in out), [(n, ok, "registered" if ok else "FAILED " + msg) for n, ok, msg in out]


def remove_mac(root=ROOT, run=None, home=None):
    """Remove this install's LaunchAgents (a LaunchAgent of another app folder is left alone). -> labels removed."""
    run = run or _sched
    gone = []
    for job in ALL:
        where = _agent_root(job, home)
        if where is not None and pathlib.Path(where) == pathlib.Path(root):
            mac_off(job, run, home)
            gone.append(label(job))
    return gone


def register(inbox_cycle=False):
    """Register every job without a question. -> (ok, [(what, ok, detail)])."""
    if platform.system() == "Windows":
        return register_windows(inbox_cycle)
    if is_mac():
        return register_mac(inbox_cycle)
    ok, msg = install_crontab(cron_lines(jobs(inbox_cycle)))
    return ok, [("crontab", ok, msg)]


if __name__ == "__main__":
    if sys.argv[1:] == ["remove"] and platform.system() in ("Windows", "Darwin"):
        for n in (remove_windows() if platform.system() == "Windows" else remove_mac()):
            print(f"  removed {n}")
    else:
        print("usage (Windows, macOS): python data/task_register.py remove")
