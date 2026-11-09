"""Start a phone bot, or the web app itself, with this PC (at every sign-in), or stop doing that. Windows only for now.

A logon scheduled task is tried first; when Windows refuses it (some PCs need admin for logon tasks), a small launcher in
the user's Startup folder does the same. Mac and Linux get a crontab line to add by hand (Settings > Data > Advanced).

The web app (`web`) is started through launch.py (no browser window, `--lan` for phones) by a task that ticks every 5
minutes: it starts the app within 5 minutes of signing in, and starts it again after it stopped or crashed, because
launch.py exits at once while the app is up (a sign-in trigger needs admin on some PCs, a repeating one does not; the task
has no time limit, see task_register.SERVICE_SETTINGS). To stop it for good, switch it off (`off web`). The Startup folder
fallback starts it at sign-in but cannot restart it.

  python data/autostart.py status [telegram|discord|web]
  python data/autostart.py on|off [telegram|discord|web] [--lan] [--home FOLDER] [--no-start]

`--home FOLDER` (web only) is what the Windows installer passes: launch.py then makes the household folder there on the
first start, not next to the app, and nothing is written to family.json (a settings file in the app folder before the
first start would make the install look already set up). `--no-start` registers without starting now.
"""
import os
import pathlib
import platform
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import brand  # noqa: E402
import config  # noqa: E402

CHAT_TASK = {"telegram": (f"{brand.TASK_PREFIX} Telegram Bot", "chat_telegram"),
             "discord": (f"{brand.TASK_PREFIX} Discord Bot", "chat_discord"),
             "web": (f"{brand.TASK_PREFIX} Web App", "web_app")}  # all three: a task at sign-in running tasks/<script>.bat
LABEL = {"telegram": "phone bot", "discord": "Discord bot", "web": "web app"}


def supported():
    return platform.system() == "Windows"


def _startup_file(name):
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return pathlib.Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / f"{name}.cmd"


def _run(cmd):
    """schtasks through task_register's runner: in test mode (MITRAHOME_NO_SCHEDULER / AIFA_DRY_RUN) nothing runs."""
    import task_register
    return task_register._sched(cmd, capture_output=True, text=True)


def crontab_line(kind="telegram", lan=False):
    if kind == "web":
        return f"@reboot cd '{ROOT}' && '{sys.executable}' launch.py --no-browser{' --lan' if lan else ''}  # {brand.SLUG}"
    return f"@reboot cd '{ROOT}' && '{sys.executable}' data/{CHAT_TASK[kind][1]}.py run  # {brand.SLUG}"


def status(kind="telegram"):
    """-> "task" (logon scheduled task), "startup" (Startup-folder launcher) or "" (not started with this PC)."""
    if not supported():
        return ""
    name = CHAT_TASK[kind][0]
    if _run(["schtasks", "/query", "/tn", name]).returncode == 0:
        return "task"
    f = _startup_file(name)
    return "startup" if f is not None and f.exists() else ""


def _remember(kind, on, lan=False):
    with config.family_edit() as cfg:
        if kind == "web":
            cfg["web_autostart"] = {"task_registered": bool(on), "lan": bool(on and lan)}
            return
        chat = dict(cfg.get("chat") or {})
        chat[kind] = {**(chat.get(kind) or {}), "task_registered": bool(on)}
        cfg["chat"] = chat


def enable(kind="telegram", start_now=True, lan=False, home=None):
    """Register the bot (or the web app, with `lan` = also for phones and `home` = the household folder for a first
    start) to start at every sign-in (and start it now). -> (ok, message)."""
    name, script = CHAT_TASK[kind]
    if not supported():
        return False, "Starting with the computer is only automatic on Windows. On a Mac or Linux PC, add the line shown in Settings > Data > Advanced to your crontab."
    bat = ROOT / "tasks" / f"{script}.bat"
    args = (" --lan" if lan else "") + (f' --home "{home}"' if home else "") if kind == "web" else ""
    if kind == "web":
        # A sign-in trigger needs admin on some PCs; a trigger that repeats every 5 minutes does not. launch.py exits at
        # once when the app is already up, so a tick after it died starts it again. The .vbs keeps the console hidden.
        vbs = ROOT / "tasks" / f"{script}.vbs"
        create = ["/tr", f'wscript.exe //B //Nologo "{vbs}"{args}', "/sc", "minute", "/mo", "5"]
        if home:  # from the installer: the first tick waits 10 minutes, so it never meets the first start's set-up
            import datetime
            create += ["/st", (datetime.datetime.now() + datetime.timedelta(minutes=10)).strftime("%H:%M")]
    else:
        create = ["/tr", f'"{bat}"', "/sc", "onlogon"]
    r = _run(["schtasks", "/create", "/f", "/tn", name, *create, "/rl", "limited"])
    if r.returncode == 0:
        note = ""
        if kind == "web":  # no 72 hour limit, one copy at a time
            import task_register
            s = _run(task_register.service_settings_cmd(name))
            if s.returncode != 0:
                note = " Windows may end it after 72 hours; it is started again within 5 minutes."
        if start_now:
            _run(["schtasks", "/run", "/tn", name])
        if not home:
            _remember(kind, True, lan)
        if kind == "web":
            return True, ("The web app now starts within 5 minutes of signing in to this PC, and again if it stops"
                          + (" (started now)." if start_now else ".") + note)
        return True, f"The {LABEL[kind]} now starts when you sign in to this PC" + (" (started now)." if start_now else ".") + note
    f = _startup_file(name)  # a logon task needs admin on some PCs; a Startup-folder launcher does not
    try:
        if f is None:
            raise OSError("no Startup folder")
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'@echo off\nstart "" /min "{bat}"{args}\n', encoding="ascii")
        if start_now:
            subprocess.Popen(f'cmd /c start "" /min "{bat}"{args}')
    except OSError as e:
        return False, f"Windows did not allow it ({e.__class__.__name__}). Start the {LABEL[kind]} by hand when needed."
    if not home:
        _remember(kind, True, lan)
    return True, (f"The {LABEL[kind]} now starts when you sign in to this PC" + (" (started now)." if start_now else ".")
                  + (" It is not restarted if it stops." if kind == "web" else ""))


def _legacy(name):
    return brand.LEGACY_TASK_PREFIX + name[len(brand.TASK_PREFIX):]


def adopt_legacy():
    """A bot set to start with the PC before the rename ("FamilyAgent Telegram Bot"): register it under the new name and
    remove the old task or Startup launcher. -> names moved."""
    if not supported():
        return []
    moved = []
    for kind, (name, _) in CHAT_TASK.items():
        old = _legacy(name)
        old_file = _startup_file(old)
        had_task = _run(["schtasks", "/query", "/tn", old]).returncode == 0
        if not had_task and not (old_file is not None and old_file.exists()):
            continue
        ok, _ = enable(kind, start_now=False)
        if not ok:
            continue
        if had_task:
            _run(["schtasks", "/delete", "/f", "/tn", old])
        if old_file is not None and old_file.exists():
            try:
                old_file.unlink()
            except OSError:
                pass
        moved.append(name)
    return moved


def disable(kind="telegram"):
    """Stop starting the bot at sign-in. A bot that is running keeps running until stopped. -> (ok, message)."""
    name = CHAT_TASK[kind][0]
    if not supported():
        return False, f"On a Mac or Linux PC, remove the {brand.PRODUCT} line from your crontab."
    problems = []
    if _run(["schtasks", "/query", "/tn", name]).returncode == 0:
        r = _run(["schtasks", "/delete", "/f", "/tn", name])
        if r.returncode != 0:
            problems.append("the scheduled task")
    f = _startup_file(name)
    if f is not None and f.exists():
        try:
            f.unlink()
        except OSError:
            problems.append("the Startup folder launcher")
    if problems:
        return False, "Could not remove " + " and ".join(problems) + "."
    _remember(kind, False)
    return True, f"The {LABEL[kind]} no longer starts with this PC. Start it by hand when you want it."


def main(argv):
    lan, no_start = "--lan" in argv, "--no-start" in argv
    home = None
    if "--home" in argv:
        i = argv.index("--home")
        home = argv[i + 1] if i + 1 < len(argv) else None
        argv = argv[:i] + argv[i + 2:]
    argv = [a for a in argv if a not in ("--lan", "--no-start")]
    cmd = argv[0] if argv else "status"
    kind = argv[1] if len(argv) > 1 else "telegram"
    if kind not in CHAT_TASK or cmd not in ("status", "on", "off"):
        print(__doc__)
        return 2
    if cmd == "status":
        s = status(kind)
        print({"task": "starts at sign-in (scheduled task)", "startup": "starts at sign-in (Startup folder)"}.get(s, "not started with this PC")
              if supported() else f"not automatic here; crontab line:\n  {crontab_line(kind, lan)}")
        return 0
    ok, msg = enable(kind, start_now=not no_start, lan=lan, home=home if kind == "web" else None) if cmd == "on" else disable(kind)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
