"""Start Mitra Home: prepare Python once, then open the app in the browser. Standard library only.

  python launch.py            what `Start Mitra Home.bat` (Windows) and `Start Mitra Home.command` (Mac) run
  python launch.py --check    say what it would do, change nothing
  python launch.py --no-browser
                              Phones and walls on the home Wi-Fi can connect too, unless Settings > Phones > Connection
                              switched that off (family.json phones.lan); either way only once an adult has a PIN
  python launch.py --lan      for phones even when that setting is off
  python launch.py --pc-only  this PC only, whatever the setting says
  python launch.py --home PATH  on a brand-new install, make the household folder at PATH instead of next to the app
                              (the Windows installer passes Documents/Mitra-Home-Data; ignored once a household exists)
  pythonw launch.py --quiet   no window (the Windows installer's shortcuts): the app runs on by itself after this
                              exits, the messages go to %LOCALAPPDATA%/MitraHome/logs/launch.log, a failure is shown in
                              a message box; Settings > Data > Stop Mitra Home ends it
  python launch.py --prepare  only step 1 and 2 below (the Windows installer runs it, so the first start is quick)
  python launch.py --stop     end this app folder's own running app (the uninstaller runs it)
  python launch.py --keep-alive --no-browser
                              what the 5-minute start task runs (tasks/web_app.bat); does nothing after Settings > Data >
                              Stop Mitra Home until a start by hand or the next restart of the PC
  (--web is still accepted and changes nothing: the web app is the only app since 0.99.0)

First time on a PC it
  1. makes a private Python environment (`.venv/` in the app folder; on Windows `%LOCALAPPDATA%/MitraHome/venv`,
     because of the 260-character path limit). Nothing is installed system-wide,
  2. installs requirements.txt into it (again only when that file changes, for example after an update); the Windows
     installer ships the packages next to its own Python (`mitrahome-wheels/`), tried first so no download is needed,
  3. finishes an update that stopped before the database was brought up to date (an older updater could stop
     there): when migrations are waiting it runs `onboard.py upgrade --no-doctor` first (database backed up first),
  4. on a brand-new install, makes the household folder `../Mitra-Home-Data` (papers, settings, database) so an
     update or a mistake inside the app folder can never touch them,
  5. starts the web app (port 8601 up) and opens it in the browser, where the setup asks the questions.
Closing this window stops it (not with --quiet: there is no window).
"""
import hashlib
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "data"))
import dashboard_record  # noqa: E402
import lan_tls  # noqa: E402
MIN_PYTHON = (3, 12)
PORTS = range(8601, 8611)
DOWNLOAD_PAGE = "https://www.python.org/downloads/"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200  # CREATE_NEW_PROCESS_GROUP: the app runs on after this starter exits
QUIET = False  # main() sets it: started with no window (--quiet, --prepare, or pythonw.exe)
SAID = []  # what this start said, for the message box of a quiet start that failed


def python_ok(version=None):
    return tuple((version or sys.version_info)[:2]) >= MIN_PYTHON


def venv_dir(root=ROOT):
    """Where the private Python environment lives. Windows: `%LOCALAPPDATA%/MitraHome/venv`, because a package inside
    the app folder can pass Windows' 260-character path limit (some packages ship very long file names); a PC set up
    before the rename keeps using `%LOCALAPPDATA%/FamilyAgent/venv` (no second download). Mac/Linux: `.venv` in the app
    folder. `MITRAHOME_VENV` (or the older `FAMILYAGENT_VENV`) overrides both."""
    override = os.environ.get("MITRAHOME_VENV") or os.environ.get("FAMILYAGENT_VENV")
    if override:
        return Path(override)
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        new, old = local / "MitraHome" / "venv", local / "FamilyAgent" / "venv"
        if wheels_dir():  # started by the installer's own Python: never borrow an environment made from another one
            return new
        return old if not new.exists() and old.exists() else new
    return root / ".venv"


def venv_python(root=ROOT):
    v = venv_dir(root)
    return v / "Scripts" / "python.exe" if os.name == "nt" else v / "bin" / "python"


def wheels_dir():
    """Packages shipped with the installer's own Python (`<runtime>/mitrahome-wheels`), or None."""
    d = Path(sys.base_prefix) / "mitrahome-wheels"
    return d if d.is_dir() else None


def pip_cmds(py, root=ROOT, wheels=None):
    """pip commands to try in order: the shipped packages (no network) first, then the internet."""
    base = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(root / "requirements.txt")]
    return ([base + ["--no-index", "--find-links", str(wheels)]] if wheels else []) + [base]


def requirements_hash(root=ROOT):
    try:
        return hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()
    except OSError:
        return ""


def needs_install(root=ROOT):
    """True when the environment is missing, or was installed from a different requirements.txt."""
    stamp = venv_dir(root) / "requirements.sha256"
    try:
        return stamp.read_text(encoding="utf-8").strip() != requirements_hash(root) or not venv_python(root).exists()
    except OSError:
        return True


MARKER, LEGACY_MARKER = "mitrahome_home.txt", "familyagent_home.txt"  # names the household folder (data/paths.py)


def is_fresh_install(root=ROOT):
    """No household yet: no marker file, no settings and no database in the app folder."""
    return not ((root / MARKER).exists() or (root / LEGACY_MARKER).exists() or (root / "config" / "family.json").exists()
                or (root / "data" / "family.db").exists())


def web_cmd(py, port, root=ROOT, lan=False):
    return [str(py), str(root / "data" / "web_app.py"), "--port", str(int(port))] + (["--lan"] if lan else [])


def url(port):
    return f"http://127.0.0.1:{int(port)}"


def healthy(port, timeout=1.5):
    """True when the web app answers on this port."""
    try:
        with urllib.request.urlopen(f"{url(port)}/healthz", timeout=timeout) as r:
            return r.status == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def port_free(port):
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", int(port))) != 0


def pick_port(record=None, probe=healthy, free=port_free, ports=PORTS):
    """-> (port, running). `record` = the port this app folder's own web app wrote down: reuse it while it answers.
    Otherwise the first port nobody is using (the app of another install on 8601 is left alone)."""
    if record and probe(record):
        return record, True
    for p in ports:
        if free(p) and not probe(p):
            return p, False
    return None, False


lan_ip = lan_tls.lan_ip


def family_settings(root=ROOT):
    """config/family.json of this app folder's household ({} when there is none yet or it cannot be read)."""
    import json
    marker = root / MARKER if (root / MARKER).exists() else root / LEGACY_MARKER
    home = root
    try:
        text = marker.read_text(encoding="utf-8").strip()
        if text:
            p = Path(text).expanduser()
            home = p if p.is_absolute() else root / p
    except OSError:
        pass
    try:
        fam = json.loads((home / "config" / "family.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return fam if isinstance(fam, dict) else {}


def pins_set(root=ROOT):
    """True when the app asks for a PIN: at least one person has one (or the older shared PIN is set)."""
    fam = family_settings(root)
    return any(u.get("name") and u.get("pin_hash") for u in fam.get("dashboard_users") or []) or bool(fam.get("dashboard_pin"))


def phones_on(root=ROOT):
    """The Settings > Phones switch (family.json phones.lan): on unless the family switched it off (config.phones_wanted)."""
    ph = family_settings(root).get("phones")
    return not (isinstance(ph, dict) and ph.get("lan") is False)


def want_lan(argv, root=ROOT):
    """-> (lan, asked): for phones or not, and whether the starter asked for it (--pc-only, then --lan) rather than the
    setting deciding."""
    if "--pc-only" in argv:
        return False, True
    if "--lan" in argv:
        return True, True
    return phones_on(root), False


def in_container():
    """True inside the Docker image (it sets MITRAHOME_CONTAINER=1): the start-up text then talks about the server,
    not about a PC, and leaves out the Windows Firewall lines."""
    return os.environ.get("MITRAHOME_CONTAINER") == "1"


def lan_help(ip, port, fp=None):
    """What to tell the family once the app runs for phones. `port` = the app's port; phones use HTTPS on port + 100."""
    phone = lan_tls.lan_port(port)
    fp = fp if fp is not None else lan_tls.fingerprint()
    if in_container():
        return [
            "",
            "  Phones on your home Wi-Fi can open (encrypted with this server's own certificate):",
            f"      https://<server-address>:{phone}   (use the address of the machine that runs Docker, not {ip or 'the container address'})",
            "  Pair the phone app from a phone's browser or the app on the home Wi-Fi: Settings > Phones. A phone's browser warns about the certificate the first time:",
            f"  continue only when its SHA-256 fingerprint starts {lan_tls.pretty(fp)[:23]}" if fp else
            "  check the fingerprint in Settings > Phones before you continue.",
            "  Use your own Wi-Fi, never a guest network or a public one. Publish the port in docker-compose.yml (8701:8701).",
            "  Tip: give the server a fixed address in your router (DHCP reservation) so the link does not change.",
            "",
        ]
    return [
        "",
        "  Phones on this home Wi-Fi can open (encrypted with this PC's own certificate):",
        f"      https://{ip}:{phone}" if ip else "      (could not find this PC's Wi-Fi address; run ipconfig and use the IPv4 address)",
        "  Pair the phone app in Settings > Phones on this PC. A phone's browser warns about the certificate the first time:",
        f"  continue only when its SHA-256 fingerprint starts {lan_tls.pretty(fp)[:23]}" if fp else
        "  check the fingerprint in Settings > Phones before you continue.",
        "  Only while this window stays open and the PC is on. Use your own Wi-Fi, never a guest network or a public one.",
        "  If a phone cannot connect: Settings > Phones > Connection > Allow phones through Windows Firewall, or in",
        "  PowerShell as administrator:",
        f'      netsh advfirewall firewall add rule name="Mitra Home phones" dir=in action=allow protocol=TCP localport={phone} profile=private',
        "  Tip: give this PC a fixed address in your router (DHCP reservation) so the link does not change.",
        "",
    ]


def say(text=""):
    SAID.append(text)
    print(text, flush=True)


def launcher_logs():
    """Where a quiet start writes: %LOCALAPPDATA%/MitraHome/logs on Windows (never the app folder: a first start moves
    the app folder's logs into the household folder, see tasks/web_app.bat), else the app folder's logs/."""
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "MitraHome" / "logs"
    return ROOT / "logs"


def go_quiet():
    """No window to print to: this start's messages and those of the steps it runs go to launch.log."""
    global QUIET
    QUIET = True
    try:
        launcher_logs().mkdir(parents=True, exist_ok=True)
        sys.stdout = sys.stderr = open(launcher_logs() / "launch.log", "a", encoding="utf-8")  # noqa: SIM115
        say(f"\n  --- {time.strftime('%Y-%m-%d %H:%M:%S')}")
    except OSError:
        pass


def step_opts():
    """subprocess options for a step (venv, pip, upgrade): on a quiet start no console window, output into launch.log."""
    if not QUIET:
        return {}
    opts = {"stdin": subprocess.DEVNULL}
    if hasattr(sys.stdout, "fileno"):
        opts.update(stdout=sys.stdout, stderr=subprocess.STDOUT)
    return opts | ({"creationflags": NO_WINDOW} if os.name == "nt" else {})


def app_opts():
    """subprocess options for the web app on a quiet start: no window, its own process group so it outlives this
    starter, output into web_app.out next to launch.log."""
    if not QUIET:
        return {}
    opts = {"stdin": subprocess.DEVNULL}
    try:
        out = open(launcher_logs() / "web_app.out", "a", encoding="utf-8")  # noqa: SIM115 (the app keeps it)
        opts.update(stdout=out, stderr=subprocess.STDOUT)
    except OSError:
        opts.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return opts | ({"creationflags": NO_WINDOW | NEW_GROUP} if os.name == "nt" else {"start_new_session": True})


def tell_failure():
    """A quiet start that did not work: there is no window to read, so a message box with what it said (Windows)."""
    if os.name != "nt":
        return
    lines = [x.strip() for x in SAID if x.strip() and not x.strip().startswith("---")][-6:]
    text = "\n".join(lines) + f"\n\nAll messages: {launcher_logs() / 'launch.log'}"
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "Mitra Home did not start", 0x10)
    except (OSError, AttributeError):
        pass


def stop_note(root=None):
    """Written by Settings > Data > Stop Mitra Home (settings_data.stop_note, the same file): the keep-alive task leaves
    this app folder's app stopped until a start by hand or the next restart of the PC. In the app folder, like
    .webapp.json, so a Stop in one install never holds another install's app."""
    return (root or ROOT) / ".stopped"


def boot_time():
    """When this PC last started (seconds since the epoch; 0 when unknown)."""
    if os.name != "nt":
        return 0.0
    try:
        import ctypes
        ctypes.windll.kernel32.GetTickCount64.restype = ctypes.c_ulonglong
        return time.time() - ctypes.windll.kernel32.GetTickCount64() / 1000
    except (OSError, AttributeError):
        return 0.0


def stopped_on_purpose():
    try:
        return stop_note().stat().st_mtime > boot_time()
    except OSError:
        return False


def stop(root=ROOT, run=subprocess.run):
    """End this app folder's own running web app (never another install's). -> True when it was running."""
    rec = dashboard_record.read(root)
    if not rec:
        return False
    if os.name == "nt":  # /T: the environment's python.exe is a launcher with the real interpreter as its child
        run(["taskkill", "/PID", str(rec["pid"]), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)
    else:
        import signal
        try:
            os.kill(rec["pid"], signal.SIGTERM)
        except OSError:
            pass
    dashboard_record.forget(root)
    return True


def ensure_venv():
    py = venv_python()
    if not py.exists():
        say("  Preparing a private Python environment (one time, about a minute)...")
        r = subprocess.run([sys.executable, "-m", "venv", str(venv_dir())], **step_opts())
        if r.returncode != 0 or not py.exists():
            say("  Could not make the environment. On Debian/Ubuntu run: sudo apt install python3-venv")
            return None
    if needs_install():
        say("  Installing what the app needs (one time, a few minutes; it is repeated only after an update)...")
        for cmd in pip_cmds(py, wheels=wheels_dir()):
            r = subprocess.run(cmd, **step_opts())
            if r.returncode == 0:
                break
        if r.returncode != 0:
            say("  The install did not finish. Check the internet connection and run this again.")
            return None
        (venv_dir() / "requirements.sha256").write_text(requirements_hash() + "\n", encoding="utf-8")
    return py


def home_arg(argv):
    """The PATH after --home, or None."""
    if "--home" in argv:
        i = argv.index("--home")
        if i + 1 < len(argv) and argv[i + 1].strip():
            return Path(argv[i + 1].strip()).expanduser()
    return None


def pending_migrations(root=ROOT):
    """Names of database migrations this code has and the household's database has not applied yet ([] when there is
    no database, or it cannot be read: then the app starts as before and the health check says so)."""
    import sqlite3
    try:
        import paths
        if not paths.DB.exists():
            return []
        con = sqlite3.connect(f"file:{paths.DB.as_posix()}?mode=ro", uri=True)
        try:
            done = {r[0] for r in con.execute("SELECT name FROM schema_migrations")}
        finally:
            con.close()
    except Exception:  # noqa: BLE001 (never stop the app from starting over this check)
        return []
    return [p.name for p in sorted((root / "data").glob("migrate_*.py")) if p.name not in done]


def finish_update(py, root=ROOT, run=subprocess.run):
    """Waiting migrations (an update copied the code but stopped before the database step) -> run the upgrade now.
    -> True when the app may start."""
    todo = pending_migrations(root)
    if not todo:
        return True
    say(f"  Finishing the last update: {len(todo)} database change(s) to apply (the database is backed up first)...")
    r = run([str(py), str(root / "onboard.py"), "upgrade", "--no-doctor"], cwd=root, **step_opts())
    if r.returncode != 0:
        say("  The database could not be brought up to date (see the messages above). Your data is unchanged apart from")
        say("  the steps already done; a copy from just before is in backups_pre_upgrade. Run: python onboard.py upgrade")
        return False
    return True


def make_household_folder(dest=None):
    """Brand-new install: the household gets its own folder, next to the app unless `dest` names one (same code as
    `onboard.py home`)."""
    sys.path.insert(0, str(ROOT))
    import brand
    import onboard
    dest = dest or ROOT.parent / brand.HOME_DIR
    say(f"  Your papers, settings and database will live in: {dest}")
    onboard.set_home(dest)


def main(argv):
    check = "--check" in argv
    if "--quiet" in argv or "--prepare" in argv or sys.stdout is None:  # pythonw.exe has no stdout
        go_quiet()
    say(f"\n  Mitra Home  ({ROOT})")
    if "--stop" in argv:
        say("  Stopped." if stop() else "  Not running.")
        return 0
    if not python_ok():
        v = sys.version_info
        say(f"  Python {v.major}.{v.minor} is too old; Mitra Home needs {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer.")
        say(f"  Install it from {DOWNLOAD_PAGE} and start this again.")
        return 1
    if check:
        say(f"  Python ok. Environment: {'ready' if not needs_install() else 'will be prepared'}. "
            f"Household folder: {'will be made next to the app' if is_fresh_install() else 'already set'}.")
        return 0
    if "--prepare" in argv:
        return 0 if ensure_venv() else 1
    if "--keep-alive" in argv and stopped_on_purpose():
        say("  Stopped in Settings: left stopped until it is started by hand or the PC restarts.")
        return 0
    if "--keep-alive" not in argv:
        stop_note().unlink(missing_ok=True)
    lan, asked = want_lan(argv)
    if lan and not pins_set():
        if asked:
            say("  Phone access needs a PIN first, so strangers on the Wi-Fi cannot open your papers.")
            say("  Starting for this PC only: set a PIN for each adult in the setup, then close this and start for phones again.")
        else:
            say("  Phones and walls can connect once an adult has a PIN (the setup asks for it). For now: this PC only.")
        lan = False
    name = dashboard_record.NAME
    rec = dashboard_record.read(ROOT, name=name)
    port, running = pick_port(rec["port"] if rec else None)
    if running:
        if lan and not rec.get("lan"):
            if asked:
                say("  Mitra Home is already running for this PC only. Close its window, then start it again with --lan.")
                return 1
            say("  Mitra Home is running for this PC only. To let phones and walls connect:")
            say("  Settings > Phones > Connection > Restart for phones.")
        say(f"  Mitra Home is already running: opening {url(port)}")
        if rec.get("lan"):
            for line in lan_help(lan_ip(), port):
                say(line)
        if "--no-browser" not in argv:
            webbrowser.open(url(port))
        return 0
    if port is None:
        say(f"  No free port between {PORTS[0]} and {PORTS[-1]}. Close other copies and try again.")
        return 1
    py = ensure_venv()
    if py is None:
        return 1
    if is_fresh_install():
        make_household_folder(home_arg(argv))
    elif not finish_update(py):
        return 1
    say(f"  Starting on {url(port)}{' (and on the home Wi-Fi)' if lan else ''} ...")
    dashboard_record.forget(ROOT, name=name)
    proc = subprocess.Popen(web_cmd(py, port, lan=lan), cwd=ROOT, env=dict(os.environ), **app_opts())
    dashboard_record.write(port, ROOT, pid=proc.pid, lan=lan, name=name)
    end = time.time() + 90
    while time.time() < end and proc.poll() is None and not healthy(port):
        time.sleep(0.5)
    if proc.poll() is not None:
        say(f"  It stopped right away (see {launcher_logs() / 'web_app.out'})." if QUIET else
            "  It stopped right away (see the messages above).")
        return proc.returncode or 1
    if lan:
        for line in lan_help(lan_ip(), port):
            say(line)
    if "--no-browser" not in argv:
        webbrowser.open(url(port))
    if QUIET:
        say("  Running with no window. Stop it in Settings > Data > Stop Mitra Home.")
        return 0
    say("\n  Mitra Home is running. Keep this window open: closing it stops it.")
    say("  (Press Ctrl+C here to stop it.)\n")
    try:
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 0

if __name__ == "__main__":
    code = main(sys.argv[1:])
    if code and QUIET and "--prepare" not in sys.argv:  # the installer shows its own message for --prepare
        tell_failure()
    sys.exit(code)
