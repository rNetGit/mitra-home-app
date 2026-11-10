"""Mitra Home onboarding wizard (checklist style).

  python onboard.py            run / resume the checklist
  python onboard.py status     show the checklist without changing anything
  python onboard.py doctor     health check (safe to re-run any time)
  python onboard.py easy       quick start: laptop only, no Google (first run offers this)
  python onboard.py add NAME   add later: drive | google | backup | tax | family | packs | ai
  python onboard.py reset      forget checklist progress (keeps config and data)
  python onboard.py check      is a newer release available?
  python onboard.py update     update code to the latest release (git or zip), then migrate; --from FILE.zip, --yes, --force,
                               --allow-unsigned (accept a release with no signature; a BAD signature always stops)
  python onboard.py upgrade    after copying a newer template over an install: backup, migrate, resync
  python onboard.py home [PATH] keep papers, settings and the database in a folder of their own next to the app
                               (default ../MitraHome_home; moves what is there now); `home --inside` puts them back

Standard library only. Progress is saved to config/onboard_state.json, so you can
stop at any step and come back. Each step is re-runnable.
"""
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "data"))
CONTAINER = os.environ.get("MITRAHOME_CONTAINER") == "1"  # the Docker image sets it: say "server", not "PC"
HERE = "this server" if CONTAINER else "this PC"
DEFAULT_AI = "none" if CONTAINER else "claude_code"  # the image has no Claude Code or other CLI
try:
    import paths  # noqa: E402
except ImportError:  # onboard.py copied on its own (help only): the layout inside the app folder
    class paths:  # noqa: N801
        ROOT = HOME = ROOT
        SEPARATE = False
        FOLDERS = ("inbox", "archive", "brief", "reports", "exports", "logs", "config")
        CONFIG, DB, PRE_UPGRADE = ROOT / "config", ROOT / "data" / "family.db", ROOT / "data" / "backups_pre_upgrade"
        MARKER, LEGACY_MARKER = ROOT / "mitrahome_home.txt", ROOT / "familyagent_home.txt"
        DEFAULT_HOME_NAME = "Mitra-Home-Data"
        folder = staticmethod(lambda name: ROOT / name)
try:
    import dates  # noqa: E402
except ImportError:  # onboard.py copied on its own (help only)
    import datetime as _dt

    class dates:  # noqa: N801
        today = staticmethod(_dt.date.today)
CONFIG = paths.CONFIG / "family.json"
STATE = paths.CONFIG / "onboard_state.json"
DB = paths.DB
FOLDERS = list(paths.FOLDERS)  # the household folders (paths.HOME); data/ is code and always exists
PACKS = {  # key -> (question, example data file in packs/ copied to config/, or None)
    "festivals": ("Festival calendar (dates from config/festivals.json)", ("festivals_indian_2026-27.example.json", "festivals.json")),
    "contracts": ("Work contracts: end-date alerts, timesheet hours, hybrid schedule, monthly invoices", None),
    "amazon": ("Amazon order history matching to card charges", None),
    "shopping": ("Shopping lists with target dates", None),
    "holidays": ("Public holidays for your country (worked out on this PC, no internet)", None),
}
PACKS_ON = ("holidays",)  # packs that are on until the family switches them off
try:
    import task_register  # noqa: E402
    TASKS = task_register.TASKS  # (task name, tasks/<job>.bat + run_task.py job, schtasks schedule args)
    CRON = task_register.CRON  # run_task name -> cron schedule (macOS / Linux)
except ImportError:  # onboard.py copied on its own (help only)
    task_register, TASKS, CRON = None, [], {}


# ---------- small helpers ----------
def load_json(p, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(p, obj):
    """Atomic, and never over a file that exists but does not parse (load_json read it as the default)."""
    try:
        import config
    except ImportError:  # onboard.py copied on its own (help only)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, indent=2), encoding="utf-8")
        return
    config.write_json(p, obj)


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    try:
        v = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        v = ""
    return v or default


def yes(prompt, default=True):
    d = "Y/n" if default else "y/N"
    v = ask(f"{prompt} ({d})").lower()
    return default if not v else v.startswith("y")


def confirm_manual(text):
    print(f"  - {text}")
    return yes("Done?", True)


def py(*args):
    return subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True)


# ---------- Claude login guard ----------
# These override the family's own Claude sign-in and cause "401 failed to authenticate API key".
AUTH_OVERRIDES = ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def _win_env(scope, name):
    """Persistent Windows env var from the registry (scope 'User' or 'Machine'); None if unset."""
    try:
        import winreg
        root, sub = ((winreg.HKEY_CURRENT_USER, "Environment") if scope == "User" else
                     (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
        with winreg.OpenKey(root, sub) as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return None


def claude_auth_overrides():
    """Return [(variable, where)] for anything that would redirect or override Claude sign-in.
    Reports names and locations only, never values (they may be secrets)."""
    found = []
    for name in AUTH_OVERRIDES:
        if os.environ.get(name):
            found.append((name, "this terminal"))
        if platform.system() == "Windows":
            for scope in ("User", "Machine"):
                if _win_env(scope, name):
                    found.append((name, f"{scope} environment"))
    cs = Path.home() / ".claude" / "settings.json"
    txt = cs.read_text(encoding="utf-8", errors="ignore") if cs.exists() else ""
    for key in ("apiKeyHelper",) + AUTH_OVERRIDES:
        if key in txt:
            found.append((key, "~/.claude/settings.json"))
    return found


def print_override_fix(found):
    print("  Claude Code sign-in is being overridden. With these set, your own Claude login is ignored")
    print("  and every request fails with '401 failed to authenticate API key':")
    for name, where in found:
        print(f"    - {name}  ({where})")
    print("  Fix (PowerShell), then open a NEW terminal and run `claude`, then `/status`:")
    for name in sorted({n for n, w in found if w != "~/.claude/settings.json" and n in AUTH_OVERRIDES}):
        print(f'    Remove-Item Env:{name} -ErrorAction SilentlyContinue; '
              f'[Environment]::SetEnvironmentVariable("{name}",$null,"User")')
    if any(w == "~/.claude/settings.json" for _, w in found):
        print("    Edit ~/.claude/settings.json and remove apiKeyHelper / the ANTHROPIC_* entries.")
    if any(w == "Machine environment" for _, w in found):
        print("    Machine-level values need an Administrator PowerShell (same command with \"Machine\").")
    print("  Using a gateway/proxy on purpose? Then ignore this, but it needs its own key.")


# ---------- steps: each returns (ok, note) ----------
def step_prereqs(cfg, st):
    ok = True
    v = sys.version_info
    py_ok = v >= (3, 12)
    print(f"  Python {v.major}.{v.minor}.{v.micro}: {'ok' if py_ok else 'need 3.12+'}")
    ok &= py_ok
    is_win = platform.system() == "Windows"
    print(f"  OS: {platform.system()} {platform.release()}: {'ok' if is_win else ('ok (launchd scheduling; less tested than Windows)' if platform.system() == 'Darwin' else 'ok (cron scheduling; less tested than Windows)')}")
    for mod in ("fastapi", "uvicorn", "jinja2"):
        try:
            __import__(mod)
            print(f"  {mod}: installed")
        except ImportError:
            print(f"  {mod}: missing")
            if yes("Install requirements now (pip install -r requirements.txt)?", True):
                r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], cwd=ROOT)
                ok &= r.returncode == 0
            else:
                ok = False
            break
    claude = shutil.which("claude")
    print(f"  Claude Code CLI: {'found' if claude else 'not found (only needed if you choose a Claude option in the AI step)'}")
    found = claude_auth_overrides() if claude else []
    if found:
        print_override_fix(found)
        ok &= yes("Fixed, or you are intentionally using a gateway?", False)
    elif claude:
        print("  Claude sign-in overrides: none (good)")
    return ok, ""


def set_home(dest):
    """Move the household (folders, database, pre-upgrade copies) to `dest` and point mitrahome_home.txt at it.
    `dest` = None puts everything back inside the app folder. Returns the new household folder.

    Everything moves first and the pointer is written last; a move that fails puts back what had moved, so the app
    never points at a folder without the database."""
    global CONFIG, STATE, DB, TAX_CFG
    import importlib
    old = {name: paths.folder(name) for name in paths.FOLDERS}
    old_db, old_bk = paths.DB, paths.PRE_UPGRADE
    if dest is not None:
        dest = Path(dest).expanduser().resolve()
        if dest == ROOT.resolve() or ROOT.resolve() in dest.parents or dest in ROOT.resolve().parents:
            raise SystemExit(f"the household folder must be outside the app folder (asked for {dest})")
        dest.mkdir(parents=True, exist_ok=True)
    home = dest if dest is not None else ROOT  # the same layout paths.py derives from the pointer
    new = {name: home / name for name in paths.FOLDERS}
    new_db = home / "family.db" if dest is not None else ROOT / "data" / "family.db"
    new_bk = home / "backups_pre_upgrade" if dest is not None else ROOT / "data" / "backups_pre_upgrade"
    try:  # WAL: fold the side file into the .db first; whatever is left of it moves along below
        import db as _db
        _db.checkpoint(old_db)
    except Exception:  # noqa: BLE001 (a locked or missing file: the side files move with it)
        pass
    sides = [(Path(str(old_db) + x), Path(str(new_db) + x)) for x in ("-journal", "-wal", "-shm")]
    plan = [(old_db, new_db)] + sides + [(old_bk, new_bk)]
    for name in paths.FOLDERS:
        src, dst = old[name], new[name]
        if src.resolve() == dst.resolve() or not src.is_dir():
            continue
        for child in list(src.iterdir()):
            if child.name == ".gitkeep" or child.name.endswith(".example.json"):  # shipped examples are code: they stay
                continue
            plan.append((child, dst / child.name))
    done = []
    try:
        for src, dst in plan:
            if src.resolve() != dst.resolve() and src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                done.append((src, dst))
    except OSError as e:
        for src, dst in reversed(done):
            try:
                shutil.move(str(dst), str(src))
            except OSError:
                print(f"  could not move {dst} back to {src}: move it by hand")
        raise SystemExit(f"The household folder was not moved ({e}); everything stays where it was.") from None
    moved = len(done)
    if dest is not None:
        paths.MARKER.write_text(str(dest) + "\n", encoding="utf-8")
    else:
        paths.MARKER.unlink(missing_ok=True)
    paths.LEGACY_MARKER.unlink(missing_ok=True)  # the name from before the rename; MARKER replaces it
    importlib.reload(paths)
    paths.ensure()
    CONFIG, STATE = paths.CONFIG / "family.json", paths.CONFIG / "onboard_state.json"
    DB, TAX_CFG = paths.DB, paths.CONFIG / "tax_prep.json"
    _agent_dirs()
    print(f"  Household folder: {paths.HOME}" + (f" ({moved} item(s) moved)" if moved else ""))
    return paths.HOME


def _agent_dirs():
    """Let the Claude Code agents (when a family uses them) reach the household folder: .claude/settings.local.json
    (kept by updates) lists it as an extra directory and allows writes under its archive/, reports/, brief/, inbox/."""
    f = ROOT / ".claude" / "settings.local.json"
    try:
        cur = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
    except ValueError:
        cur = {}
    perms = cur.setdefault("permissions", {})
    names = (paths.DEFAULT_HOME_NAME, "MitraHome_home", "FamilyAgent_home")  # the default name now and before 0.110
    allow = [a for a in perms.get("allow", []) if not any(n in a for n in names) and not a.startswith(("Write(//", "Edit(//"))]
    dirs = [d for d in perms.get("additionalDirectories", []) if not d.endswith(names) and d != str(paths.HOME)]
    if paths.SEPARATE:
        h = paths.HOME.as_posix().lstrip("/")
        allow += [f"Write(//{h}/{d}/**)" for d in ("archive", "reports", "brief", "inbox")] + [f"Edit(//{h}/archive/**)",
                  f"Write(//{h}/config/category_rules.json)", f"Edit(//{h}/config/category_rules.json)"]
        dirs.append(str(paths.HOME))
    perms["allow"], perms["additionalDirectories"] = allow, dirs
    if not perms["allow"]:
        perms.pop("allow")
    if not perms["additionalDirectories"]:
        perms.pop("additionalDirectories")
    if perms:
        save_json(f, cur)
    elif f.exists() and not {k: v for k, v in cur.items() if k != "permissions"}:
        f.unlink()


def choose_home():
    """First run in a terminal, nothing stored yet: offer the household its own folder next to the app (default yes)."""
    if paths.SEPARATE or CONFIG.exists() or DB.exists() or not sys.stdin.isatty():
        return
    default = ROOT.parent / paths.DEFAULT_HOME_NAME
    print("  Your papers, settings and database can live in a folder of their own next to the app, so an update or a\n"
          f"  mistake inside the app folder cannot touch them (recommended):\n    {default}")
    if yes("Use a separate folder?", True):
        set_home(ask("Folder", str(default)) or default)


def step_folders(cfg, st):
    choose_home()
    paths.ensure()
    print(f"  Your folder: {paths.HOME}" + ("" if paths.SEPARATE else "  (inside the app folder)"))
    print("  Folders ready: " + ", ".join(FOLDERS))
    if ROOT.drive and platform.system() == "Windows":
        try:
            import ctypes
            if ctypes.windll.kernel32.GetDriveTypeW(ROOT.drive + "\\") == 2:
                print("  NOTE: this is a removable drive. Scheduled tasks skip runs while it is unplugged.")
        except Exception:
            pass
    return True, ""


def step_profile(cfg, st):
    cfg.setdefault("members", [])
    cfg["family_name"] = ask("Family name", cfg.get("family_name", ""))
    print("  Add household members (blank name to finish). Birthdays are month-day only.")
    if cfg["members"] and not yes("Keep the members already entered?", True):
        cfg["members"] = []
    while True:
        name = ask("Member name")
        if not name:
            break
        role = ask("Role (adult/child/pet)", "adult")
        while True:
            bd = ask("Birthday as month-day MM-DD, like 03-14 (optional)")
            if not bd or re.fullmatch(r"(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])", bd):
                break
            print("    That is not a month-day. Use MM-DD with the month first, for example 03-14. The year comes next.")
        while True:
            by = ask("Birth year, like 1978 (optional, for 'turns N')")
            if not by or (by.isdigit() and 1900 <= int(by) <= dates.today().year):
                break
            print("    Please type a four-digit year such as 1978, or leave it blank.")
        cfg["members"].append({"name": name, "role": role, "birth_month_day": bd,
                               "birth_year": int(by) if by.isdigit() else None})
    sys.path.insert(0, str(ROOT / "data"))
    import country as _country
    import seasonal_packs
    cfg["country"] = _country.normalize(ask("Country (US, UK, CA, AU, NZ, IN or another ISO code; picks tax papers, ID types, "
                                            "units, address fields and the seasonal task pack)", cfg.get("country", "US")))
    prof = _country.load(cfg["country"])
    print(f"  Country profile: {_country.describe(prof)}")
    if cfg["country"] not in _country.codes() or not (ROOT / "packs" / "country" / f"{cfg['country'].lower()}.json").exists():
        print("  (no detailed profile for this country yet: generic tax papers and ID types; copy packs/country/uk.json to "
              f"config/country/{cfg['country'].lower()}.json and edit it to add your own)")
    labels = prof.get("address", {})
    old = cfg.get("region", {})
    cfg["region"] = {"place": ask("City or town (shown in headings, optional)", old.get("place", "")),
                     "state": ask(labels.get("state", "State"), old.get("state", "")),
                     "county": ask(labels.get("county", "County (optional)"), old.get("county", "")),
                     "zip": ask(labels.get("zip", "Postal code (optional)"), old.get("zip", ""))}
    cfg["climate"] = ask("Climate: cold (snowy winters) / mild / hot", cfg.get("climate", "cold" if cfg.get("cold_climate", True) else "mild")).lower()
    if cfg["climate"] not in ("cold", "mild", "hot"):
        cfg["climate"] = "cold"
    cfg["cold_climate"] = cfg["climate"] == "cold"
    cfg["seasonal_pack"] = seasonal_packs.recommend(cfg["country"], cfg["climate"])
    print(f"  Seasonal task pack: {cfg['seasonal_pack']} (change later: python data/seasonal_packs.py list / apply KEY)")
    adds = [k for k, d in seasonal_packs.load_packs().items() if d.get("kind") == "addon"]
    cfg["seasonal_addons"] = [k for k in adds if yes(f"Add-on tasks: {seasonal_packs.load_packs()[k]['title']}?", k in cfg.get("seasonal_addons", []))]
    cfg["currency"] = ask("Currency", cfg.get("currency") or prof.get("currency", "USD")).upper()
    save_json(CONFIG, cfg)  # Gmail / Calendar / Drive are optional: python onboard.py add google
    ok = bool(cfg["family_name"] and cfg["members"])
    return ok, "" if ok else "need a family name and at least one member"


def seed_members(con, cfg):
    """Per-member health reminders (the shared migration seeds only home items)."""
    n = 0
    for m in cfg.get("members", []):
        if m.get("role") == "pet":
            continue
        items = [("Annual physical", 12), ("Dental cleaning", 6)]
        if m.get("role") != "child":
            items.append(("Eye exam", 12))
        for name, iv in items:
            con.execute("INSERT INTO recurring_items(name,category,who,interval_months,notes) "
                        "SELECT ?,?,?,?,'' WHERE NOT EXISTS (SELECT 1 FROM recurring_items WHERE name=? AND who=?)",
                        (name, "Health", m["name"], iv, name, m["name"]))
            n += 1
    con.commit()
    return n


def step_database(cfg, st):
    r = py("data/migrate.py")
    print(r.stdout.rstrip())
    if r.returncode:
        print(r.stderr)
        return False, "migrations failed (python data/migrate.py status)"
    con = sqlite3.connect(DB)
    sys.path.insert(0, str(ROOT / "data"))
    import seasonal_packs
    climate = cfg.get("climate", "cold" if cfg.get("cold_climate", True) else "mild")
    pack = cfg.get("seasonal_pack") or seasonal_packs.recommend(cfg.get("country", "US"), climate)
    add, upd, off = seasonal_packs.apply(con, pack, cfg.get("seasonal_addons", []))
    print(f"  Seasonal pack '{pack}': {add} added, {upd} updated, {off} deactivated.")
    n = seed_members(con, cfg)
    con.close()
    r = py("data/members.py", "sync")
    print("  " + r.stdout.strip().splitlines()[0] if r.stdout.strip() else "")
    print(f"  Database ready; {n} health reminders for {len(cfg.get('members', []))} member(s).")
    return True, ""


def step_agent_account(cfg, st):
    """Optional. Everything else works on this PC without Google; this adds mail, calendar and the phone drop box."""
    print("  Optional: Google Drive (phone drop box + briefs) and an agent Gmail + Calendar. Skip now; add any time:")
    print("    python onboard.py add drive      python onboard.py add google")
    if yes("Set up Google Drive now (phone drop box and briefs)?", False):
        ok, note = add_drive(cfg, st)
        if not ok:
            return False, note
    if yes("Connect an agent Gmail + Calendar now (needs Claude Code)?", False):
        return add_google(cfg, st)
    return True, "optional parts skipped"


def add_google(cfg, st=None):
    cfg["agent_email"] = ask("Household agent Gmail (a NEW account, not your personal one)", cfg.get("agent_email", ""))
    if not re.match(r".+@.+\..+", cfg["agent_email"]):
        cfg.pop("agent_email", None)
        return False, "need a valid email address"
    save_json(CONFIG, cfg)
    em = cfg["agent_email"]
    ok = True
    ok &= confirm_manual(f"Create the household agent Gmail {em} if it does not exist yet.")
    ok &= confirm_manual("In Claude Code, run /mcp and connect Gmail and Google Calendar for that account.")
    ok &= confirm_manual("In Gmail create labels: MitraHome, MitraHome/Processed, MitraHome/Needs review.")
    print("  For the phone drop box and briefs on Google Drive run: python onboard.py add drive")
    return ok, ""


def add_drive(cfg, st=None):
    """Guided Google Drive setup: finds Drive for Desktop, creates MitraHome/Inbox + Brief, tests the sweep, schedules it."""
    sys.path.insert(0, str(ROOT / "data"))
    import drive_setup
    print("  Phone -> PC: drop documents into Drive > MitraHome > Inbox; this PC sweeps them into its own inbox/ folder.")
    print("  PC -> phone: only the daily brief and weekly digest (PDF) go to Drive > MitraHome > Brief.")
    print("  Needs Google Drive for Desktop installed and signed in with the Google account you want to use (the head of the family's).")
    print("  Raw documents, the database and backups never go to Drive. Briefs show vendor names and amounts: share the Brief folder")
    print("  only with people who may see them, and share Inbox with no one you would not trust to drop files into your records.")
    roots = drive_setup.find_drive_roots()
    for i, r in enumerate(roots, 1):
        print(f"   {i}. {r}")
    pick = ask("Drive folder (number from the list, or type the 'My Drive' path)", "1" if roots else "")
    root = str(roots[int(pick) - 1]) if pick.isdigit() and 1 <= int(pick) <= len(roots) else pick
    if not root:
        print("  Not found. Install Google Drive for Desktop (drive.google.com/drive/download), sign in, then run this again.")
        return False, "no Drive folder"
    try:
        fa = drive_setup.prepare(root)
    except OSError as e:
        print(f"  {e}")
        return False, "Drive folder not usable"
    cfg["drive_path"] = str(fa)
    save_json(CONFIG, cfg)
    print(f"  Created {fa / 'Inbox'} and {fa / 'Brief'}")
    checks = drive_setup.selftest(fa)
    for name, ok, note in checks:
        print(f"  [{'x' if ok else '!'}] {name}{(': ' + note) if note else ''}")
    if not all(c[1] for c in checks):
        return False, "Drive self-test failed"
    print("  In Drive for Desktop settings, set the MitraHome folder to 'Mirror files' (or 'Available offline') so it is always on this PC.")
    print("  On your phone: open the Drive app, find MitraHome/Inbox, use + > Scan or Upload to send a document. It reaches this PC after the next sweep.")
    if DRY:
        return True, "dry run: sweep task not registered"
    if not yes("Check the Drive Inbox every 15 minutes (no AI; just moves files to this PC)?", True):
        return True, "sweep not scheduled; run python tasks/run_task.py inbox_sweep by hand"
    ok = register_sweep()
    cfg["sweep_registered"] = bool(ok)
    save_json(CONFIG, cfg)
    return True, "" if ok else "sweep task not registered"


def register_sweep():
    if platform.system() != "Windows":
        return register_posix(["inbox_sweep"])
    name, job, sched = task_register.SWEEP_TASK
    ok, msg = task_register.create_windows(name, job, sched, root=ROOT)
    print(f"  {name}: {('registered' + (f' ({msg})' if msg else '')) if ok else 'FAILED ' + msg}")
    if ok:
        task_register._drop_windows(task_register.legacy_name(name))
    return ok


def add_telegram(cfg, st=None):
    """Guided Telegram bot setup: BotFather steps, hidden token paste, live check, logon task, first pairing code."""
    ensure_migrated()
    sys.path.insert(0, str(ROOT / "data"))
    import chat_telegram
    import config as _config
    print("  The family can message Mitra Home from Telegram on their phones: /due, /week. Replies come from this PC.")
    print("  This PC must be on (and signed in) for the bot to answer. Nothing is opened to the internet.")
    print("  Privacy: Telegram bot chats are not end-to-end encrypted. Children never get money information;")
    print("  adults get bills and amounts only in a private chat with the bot. Full steps: docs/CHAT.md")
    have = chat_telegram.token()
    if have and chat_telegram.check(have)[0] and not yes("A working bot token is already saved. Replace it?", False):
        ok, name = chat_telegram.check(have)
    else:
        ok = True
        ok &= confirm_manual("On your phone, open Telegram, search for @BotFather (blue tick) and send /newbot.")
        ok &= confirm_manual("Pick a display name (e.g. 'Our Mitra Home') and a username ending in 'bot'.")
        print("  BotFather replies with a token like 123456789:AA... Treat it like a password: anyone with it can be your bot.")
        import getpass
        tok = getpass.getpass("  Paste the token (hidden; saved only in config/secrets.env): ").strip()
        good, name = chat_telegram.check(tok)
        if not good:
            print(f"  {name}")
            return False, "token not accepted"
        if DRY:
            print("  Dry run: token checked, not saved.")
            return True, "dry run"
        _config.write_secret(chat_telegram.TOKEN_NAME, tok)
    print(f"  Bot {name} works.")
    print("  Recommended in @BotFather: /setjoingroups -> Disable (so nobody adds your bot to other groups).")
    chat = cfg.setdefault("chat", {})
    chat["telegram"] = {"enabled": True, "bot": name}
    save_json(CONFIG, cfg)
    if not DRY and yes("Start the bot automatically when you sign in to this PC?", True):
        chat["telegram"]["task_registered"] = bool(register_chat_task("telegram"))
        save_json(CONFIG, cfg)
    else:
        print("  Start it by hand when needed: python data/chat_telegram.py run")
    print("  Link each family member (one code per person, made here on this PC):")
    print("      python data/chat_core.py invite NAME")
    print(f"  They open {name} in Telegram, press Start, and send /start CODE.")
    return ok, ""


def add_calendar(cfg, st=None):
    """Guided Google Calendar (read-only) setup with the family's OWN Google Cloud project. No Claude needed."""
    sys.path.insert(0, str(ROOT / "data"))
    import google_calendar as gc
    print("  Show your Google Calendar events in Mitra Home (dashboard, and later the digest). Read-only: nothing here can")
    print("  create, change or delete an event. No Claude account is needed. Each family uses its own free Google Cloud project,")
    print("  so no credentials are shared. About 15 minutes the first time. Full guide with every click: docs/GOOGLE_CALENDAR.md")
    try:
        gc.load_client()
        have = True
    except gc.CalendarError:
        have = False
    if not have or yes("A Google client file is already saved. Replace it?", False):
        print("  In a browser, signed in to the Google account that owns the calendar:")
        steps = [
            "Open https://console.cloud.google.com/ and create a project (name it Mitra Home).",
            "APIs & Services > Library > search 'Google Calendar API' > Enable.",
            "APIs & Services > OAuth consent screen (Google Auth platform): User type External, app name Mitra Home, "
            "your email as support and contact. You do not add scopes yet.",
            "Branding: fill Application home page and Application privacy policy link (any public page about the app; "
            "Mitra Home's own is https://rnetgit.github.io/mitra-home/ ) and add its domain (rnetgit.github.io) under "
            "Authorized domains. Do not upload a logo (that starts a Google review). Save.",
            "Audience: press 'Publish app' so the status reads 'In production'. In 'Testing' Google cancels the sign-in "
            "every 7 days. Google will call the app 'unverified': it is your own app, that is expected.",
            "Credentials > Create credentials > OAuth client ID > Application type: Desktop app > Create > Download JSON.",
        ]
        for n, line in enumerate(steps, 1):
            if not confirm_manual(f"Step {n}: {line}"):
                return False, "not finished"
        raw = ask("Path of the downloaded .json file (drag the file into this window)").strip().strip('"')
        if not raw:
            return False, "no file given"
        try:
            gc.load_client(raw)
        except gc.CalendarError as e:
            print(f"  {e}")
            return False, "client file not accepted"
        if DRY:
            print("  Dry run: client file checked, not saved.")
            return True, "dry run"
        shutil.copyfile(raw, gc.CLIENT_FILE)
        print("  Saved as config/google_client.json (you can delete the downloaded copy).")
    if not gc.refresh_token() or yes("Sign in to Google again?", False):
        if DRY:
            print("  Dry run: would open the browser to sign in.")
            return True, "dry run"
        print("  A browser tab opens. Pick the account. If Google says it has not verified this app, choose Advanced >")
        print("  'Go to Mitra Home (unsafe)' and allow the two read-only calendar permissions.")
        try:
            gc.authorize()
        except gc.CalendarError as e:
            print(f"  {e}")
            return False, "sign-in failed"
    try:
        cals = gc.calendars()
    except gc.CalendarError as e:
        print(f"  {e}")
        return False, "could not list calendars"
    print("  Calendars on this account:")
    for i, c in enumerate(cals, 1):
        print(f"   {i}. {c['name']}" + ("  (main)" if c["primary"] else ""))
    pick = ask("Which to show? numbers separated by commas (blank = the main calendar only)", "")
    chosen = [cals[int(x) - 1]["id"] for x in re.split(r"[,\s]+", pick) if x.isdigit() and 0 < int(x) <= len(cals)]
    chosen = chosen or ["primary"]
    cfg["google_calendar"] = {**(cfg.get("google_calendar") or {}), "enabled": True, "calendars": chosen}
    save_json(CONFIG, cfg)
    try:
        ev = gc.events(14)
        print(f"  Works: {len(ev)} event(s) in the next 14 days.")
    except gc.CalendarError as e:
        print(f"  Signed in, but reading events failed: {e}")
        return False, "events failed"
    print("  See them in the app: Calendar. Stop any time: python data/google_calendar.py revoke")
    return True, ""


def add_gmail(cfg, st=None):
    """Read mail with a label straight from Google, using the calendar's Google sign-in. No Claude needed."""
    sys.path.insert(0, str(ROOT / "data"))
    import google_calendar as gc
    import google_gmail as gm
    print("  File bills and statements from Gmail: mail you label MitraHome has its attachments (or text) copied into")
    print("  inbox/. Read-only: nothing is sent, labelled, archived or deleted. No Claude account is needed.")
    print("  It uses the same Google sign-in as the calendar (docs/GOOGLE_GMAIL.md).")
    try:
        gc.load_client()
    except gc.CalendarError:
        print("  First set up the Google client file: python onboard.py add calendar")
        return False, "no client file"
    if not confirm_manual("In Google Cloud (same project) open APIs & Services > Library > 'Gmail API' > Enable."):
        return False, "not finished"
    if not confirm_manual("In Gmail create a label named MitraHome and apply it (or a filter) to the mail to file."):
        return False, "not finished"
    if not gm.has_permission() or yes("Sign in to Google again?", False):
        if DRY:
            print("  Dry run: would open the browser to allow the Gmail permission.")
            return True, "dry run"
        print("  A browser tab opens. Pick the same account and allow 'Read your email' (gmail.readonly).")
        try:
            gc.authorize(gmail=True)
        except gc.CalendarError as e:
            print(f"  {e}")
            return False, "sign-in failed"
        if not gm.has_permission():
            print("  Google did not grant the Gmail permission. Run this again and tick every box.")
            return False, "permission missing"
    label = ask("Gmail label to read", (cfg.get("gmail") or {}).get("label", "MitraHome")).strip() or "MitraHome"
    cfg["gmail"] = {**(cfg.get("gmail") or {}), "enabled": True, "label": label}
    save_json(CONFIG, cfg)
    try:
        r = gm.pull(dry_run=True)
        print(f"  Works: {r['messages']} labelled message(s) would be copied ({r['files']} file(s), {r['texts']} text(s)).")
    except gc.CalendarError as e:
        print(f"  Signed in, but reading mail failed: {e}")
        return False, "mail failed"
    print("  The inbox task copies new labelled mail every cycle. Now: python data/google_gmail.py pull")
    return True, ""


CHAT_TASK = {"telegram": ("Mitra Home Telegram Bot", "chat_telegram"),
             "discord": ("Mitra Home Discord Bot", "chat_discord")}


def add_discord(cfg, st=None):
    """Guided Discord bot setup: Developer Portal steps, hidden token paste, live check, invite link, package, task."""
    ensure_migrated()
    sys.path.insert(0, str(ROOT / "data"))
    import chat_discord
    import config as _config
    print("  The family can use Mitra Home from Discord: /due, /week in your family server or in a direct message.")
    print("  This PC must be on (and signed in) for the bot to answer. Nothing is opened to the internet.")
    print("  Privacy: Discord does not end-to-end encrypt bot messages. Children never get money information;")
    print("  adults get bills and amounts only in a direct message, never in the server. Full steps: docs/CHAT.md")
    have = chat_discord.token()
    found = chat_discord.check(have) if have else (False, "", None)
    if found[0] and not yes("A working bot token is already saved. Replace it?", False):
        ok, name, app_id = found
    else:
        ok = True
        ok &= confirm_manual("If the family has no server yet: in Discord press + > Create My Own > For me and my friends.")
        ok &= confirm_manual("On a computer open discord.com/developers/applications > New Application, name it (e.g. 'Our Mitra Home').")
        ok &= confirm_manual("Installation: set Install Link to None. Bot: turn OFF 'Public Bot'. Leave all Privileged Gateway Intents OFF.")
        ok &= confirm_manual("Bot > Reset Token > Copy. Treat it like a password: anyone with it can be your bot.")
        import getpass
        tok = getpass.getpass("  Paste the token (hidden; saved only in config/secrets.env): ").strip()
        good, name, app_id = chat_discord.check(tok)
        if not good:
            print(f"  {name}")
            return False, "token not accepted"
        if DRY:
            print("  Dry run: token checked, not saved.")
            return True, "dry run"
        _config.write_secret(chat_discord.TOKEN_NAME, tok)
    print(f"  Bot {name} works.")
    print("  Add it to your family server (open this link, pick the server, Authorise):")
    print(f"      {chat_discord.invite_url(app_id)}")
    chat = cfg.setdefault("chat", {})
    chat["discord"] = {"enabled": True, "bot": name.split(" (")[0]}
    save_json(CONFIG, cfg)
    import importlib.util
    have_pkg = importlib.util.find_spec("discord") is not None
    if not have_pkg:
        print('  The bot needs the discord.py package (about 2 MB, from PyPI).')
        if not DRY and yes('Install it now (pip install "discord.py>=2.3")?', True):
            r = subprocess.run([sys.executable, "-m", "pip", "install", "discord.py>=2.3"], capture_output=True, text=True)
            have_pkg = r.returncode == 0
            print("  installed" if have_pkg else "  install FAILED: " + (r.stderr.strip().splitlines() or [""])[-1])
    if not have_pkg:
        print('  Install it later with: pip install "discord.py>=2.3"')
    if have_pkg and not DRY and yes("Start the bot automatically when you sign in to this PC?", True):
        chat["discord"]["task_registered"] = bool(register_chat_task("discord"))
        save_json(CONFIG, cfg)
    else:
        print("  Start it by hand when needed: python data/chat_discord.py run")
    print("  Link each family member (one code per person, made here on this PC):")
    print("      python data/chat_core.py invite NAME")
    print("  They send the bot a direct message: /start CODE (in the server, codes are refused).")
    return ok, ""


def ensure_migrated():
    """Chat tables come from migrations; make sure they exist before pairing codes are made."""
    if not DRY:
        r = py("data/migrate.py")
        if r.returncode:
            print(f"  warning: migrations failed; run python data/migrate.py ({r.stderr.strip()[:200]})")


def register_chat_task(kind):
    """Start the bot at every sign-in (data/autostart.py; also the "Start with this PC" toggle in Settings)."""
    sys.path.insert(0, str(ROOT / "data"))
    import autostart
    if not autostart.supported():
        print(f"  Add this line to your crontab (crontab -e):\n    {autostart.crontab_line(kind)}")
        return False
    ok, msg = autostart.enable(kind)
    print(f"  {CHAT_TASK[kind][0]}: {msg}")
    return ok


AI_CHOICES = [
    ("claude_code", "Claude Code agents under YOUR OWN Claude login" + ("" if CONTAINER else " (default)") + ". Best accuracy for statements. Uses your plan's limits. ~$20/mo plan"),
    ("claude_cli", "Your signed-in Claude (Pro etc.) as a cheap text-only model, Haiku. Inbox filing + chat; no statements/brief. ~$20/mo plan"),
    ("codex_cli", "Your signed-in OpenAI Codex CLI (ChatGPT plan). Inbox filing + chat; text only; it CAN READ files on " + HERE),
    ("gemini_cli", "Your signed-in Gemini CLI. Inbox filing + chat. Free tier trains on your prompts: avoid for family papers"),
    ("anthropic", "Anthropic API key, pay per use (about $1/month for a family) for inbox filing + chat"),
    ("openai", "OpenAI API key, pay per use (about $0.20/month): cheapest hosted option"),
    ("gemini", "Google Gemini API key, pay per use (about $0.40/month); use the paid tier"),
    ("openrouter", "OpenRouter API key: one key, many models (Gemini, GPT, Claude, Llama...), pay per use, cents/month"),
    ("ollama", f"Local model on {HERE} via Ollama. Free, nothing leaves {HERE}; lower accuracy"),
    ("none", "No AI in the Python pipeline. You process the inbox yourself or with Claude Code by hand"),
]


TEXT_CLIS = ("claude_cli", "codex_cli", "gemini_cli")
KEYED_PROVS = ("anthropic", "openai", "gemini", "openrouter")
TEXT_PROVS = KEYED_PROVS + ("ollama",) + TEXT_CLIS


def step_ai(cfg, st):
    """Choose which AI reads your documents, with plain consent. API keys only; never a subscription login token."""
    print("  Which AI should read the documents you drop in inbox/? (COMPLIANCE.md has the rules)")
    if CONTAINER:
        print("  In Docker: the signed-in options (claude_code, claude_cli, codex_cli, gemini_cli) need a CLI that is not in the image.")
        print("  Pick an API key option (anthropic, openai, gemini, openrouter), ollama on another machine, or none (Enter = none).")
    for i, (k, d) in enumerate(AI_CHOICES, 1):
        print(f"   {i}. {k:<12} {d}")
    cur = (cfg.get("ai") or {}).get("provider", DEFAULT_AI)
    keys = [k for k, _ in AI_CHOICES]
    pick = ask("Number", str(keys.index(cur if cur in keys else DEFAULT_AI) + 1))
    provider = AI_CHOICES[int(pick) - 1][0] if pick.isdigit() and 1 <= int(pick) <= len(AI_CHOICES) else DEFAULT_AI
    ai = dict(cfg.get("ai") or {})
    ai["provider"] = provider
    if provider in ("gemini", "gemini_cli"):
        print("  Google's FREE tier (AI Studio keys without billing, the free Gemini CLI) may use your prompts and the documents in them")
        print("  to improve Google products. Mitra Home refuses to send family papers there.")
        if not yes("I am on a PAID Gemini tier with billing enabled (prompts not used for training)", False):
            print("  Choose anthropic, openai, ollama (nothing leaves the PC) or claude_cli instead.")
            return False, "free-tier provider refused"
        ai["gemini_paid_tier_confirmed"] = True
    if provider in KEYED_PROVS:
        print(f"  What is sent: the TEXT of each document you drop goes to {provider} under your own API account, after masking:")
        print("  SSN/ID numbers, account and card numbers (last 4 kept), emails, phones, dates of birth, street addresses and your")
        print("  family's names are replaced before sending. Preview any file: python data/llm.py redact-preview FILE")
        print("  Check that provider's data-retention and training terms for API use. Use an API key, never a chat-subscription login token.")
        if not yes("I understand and want to use this provider", False):
            return False, "consent not given"
        sys.path.insert(0, str(ROOT / "data"))
        import getpass
        import llm
        key = getpass.getpass(f"  Paste your {provider} API key (hidden; saved only in config/secrets.env): ").strip()
        if key:
            try:
                if provider == "anthropic" and key.startswith("sk-ant-oat"):
                    print("  That is a Claude subscription token, which only Claude Code may use. Create an API key in the Anthropic Console.")
                    return False, "subscription token refused"
                llm.store_key(provider, key)
            except Exception as e:
                print(f"  Could not save the key: {e}")
                return False, "key not saved"
        ai["model"] = ask("Model (blank = default; model names change, check the provider's docs)", ai.get("model", ""))
    elif provider == "ollama":
        ai["model"] = ask("Ollama model name (install with: ollama pull llama3.1)", ai.get("model", "llama3.1"))
    elif provider in TEXT_CLIS:
        vendor = {"claude_cli": "Anthropic", "codex_cli": "OpenAI", "gemini_cli": "Google"}[provider]
        print("  What is sent: the TEXT of each document (identifiers and family names masked; preview with python data/llm.py redact-preview FILE)")
        print(f"  goes to {vendor} through the CLI YOU installed and signed in to.")
        print("  We never read or copy that login; the CLI runs with no tools in an empty folder. Your plan's own limits and terms apply.")
        print("  Unattended (scheduled) runs through a personal sign-in stay OFF unless you set ai.allow_unattended_cli. An API key or Ollama suits unattended use better.")
        if not yes("I understand and want to use this", False):
            return False, "consent not given"
        ai["model"] = ask("Model (blank = default; claude_cli default is haiku)", ai.get("model", ""))
    elif provider == "claude_code":
        print("  Tip: on a Pro plan, 'haiku' uses far less of your quota than 'sonnet' (statements may be less accurate).")
        ai["claude_model"] = ask("Claude model for scheduled runs (blank = haiku for the brief, sonnet for the inbox)", ai.get("claude_model", ""))
        print("  Agents normally open documents with their own Read tool, so the full text goes to Anthropic under your account.")
        print("  With masking on, agents read documents through python data/pii.py (SSN/ID/account numbers, emails, phones, addresses")
        print("  and family names replaced; last four digits kept). Scanned images then cannot be read by agents at all.")
        ai["agents_read_redacted"] = yes("Mask identifiers before agents read documents?", bool(ai.get("agents_read_redacted", False)))
    if provider in KEYED_PROVS + ("ollama",):
        print("  Receipt photos: the AI can read store, date and total from a receipt photo in the inbox and match it to")
        print("  the card charge. A photo cannot be masked first: what is printed on it goes to the provider" +
              (" (Ollama: stays on this PC)." if provider == "ollama" else "."))
        ai["read_receipt_photos"] = yes("Let the AI read receipt photos?", bool(ai.get("read_receipt_photos", False)))
    if provider in TEXT_PROVS:
        print("  Chat with your records any time (no Claude Code needed):  python data/assistant.py")
        print("  Rough cost/limits per provider:  python data/llm.py matrix")
    ai.setdefault("max_runs_per_day", 12)
    ai.setdefault("max_calls_per_day", 200)
    cfg["ai"] = ai
    save_json(CONFIG, cfg)
    if provider in TEXT_PROVS and not DRY:
        sys.path.insert(0, str(ROOT / "data"))
        import llm
        ok, msg = llm.ping()
        print(f"  Test call: {'OK' if ok else 'FAILED'} - {msg}")
        return ok, "" if ok else "provider test call failed"
    return True, ""


def step_safety(cfg, st):
    print("  Rules in CLAUDE.md that stay on:")
    print("   * never log in to bank/tax sites or handle passwords; you download statements yourself")
    print("   * never delete originals; they move to archive/")
    print("   * last4 only for account/policy/ID numbers in the database")
    print("   * agents ask before sending email or changing calendar events")
    print("  Compliance (full text: COMPLIANCE.md):")
    print("   * Sign in to Claude yourself with YOUR OWN account (18+). Do not share the login with relatives or friends.")
    print("   * Never paste a Claude login token into any tool. Other tools need an API key, not your subscription.")
    print("   * Check your Claude privacy setting about using chats to improve models; opt out if you prefer.")
    print("   * Answers are AI-assisted records, not tax/legal/medical/insurance advice.")
    print(f"  Privacy, plainly: the database, archive and backups stay on {HERE}. But when an AI agent")
    print("  reads a statement or email, that content is sent to your Claude account (Anthropic) to be read.")
    print("  Phone briefs copied to Google Drive contain vendor names and amounts. Back up to an encrypted drive")
    print("  (BitLocker / FileVault / VeraCrypt): backups contain your full financial database.")
    if CONTAINER:
        print("  In Docker: keep the Mitra-Home-Backup volume on an encrypted disk and copy it off the server too.")
    ok = yes("I understand and accept these rules", True)
    return ok, ""


def step_packs(cfg, st):
    cfg.setdefault("packs", {})
    print("  Optional packs (public holidays aside) are off unless you enable them. Enabling a pack with example data copies the")
    print("  example into config/ (never overwrites); edit it to match your family.")
    for k, (desc, example) in PACKS.items():
        on = yes(f"Enable: {desc}?", cfg["packs"].get(k, k in PACKS_ON))
        cfg["packs"][k] = on
        if on and example:
            src, dst = ROOT / "packs" / example[0], paths.CONFIG / example[1]
            if not dst.exists():
                shutil.copy(src, dst)
                print(f"    copied packs/{example[0]} -> config/{example[1]} (EDIT: example dates/pattern)")
    save_json(CONFIG, cfg)
    return True, ""


TAX_CFG = paths.CONFIG / "tax_prep.json"


def _csv(text):
    return [x.strip() for x in text.split(",") if x.strip()]


def step_tax(cfg, st):
    """Optional: banks/brokers that send 1099s, state tax words, tuition payee -> config/tax_prep.json."""
    t = load_json(TAX_CFG, {})
    print("  Used by the tax-prep checklist (python data/tax_prep.py). All answers optional; blank keeps the current value.")
    print("  Do not enter account numbers; institution names only.")
    cur = ", ".join(t.get("payers", []))
    t["payers"] = _csv(ask("Banks/brokers/credit unions that send you a 1099-INT (comma separated)", cur))
    cur = ", ".join(t.get("state_tax_keywords", []))
    t["state_tax_keywords"] = _csv(ask("Words on state estimated-tax payments, e.g. the state tax agency name", cur))
    cur = ", ".join(t.get("education_payee_patterns", []))
    t["education_payee_patterns"] = _csv(ask(
        "Tuition payee as it appears on statements, SQL LIKE style e.g. %UNIVERSITY BURSAR% (comma separated)", cur))
    save_json(TAX_CFG, t)
    print(f"  Saved {paths.rel(TAX_CFG)}")
    return True, ""


DRY = os.environ.get("AIFA_DRY_RUN") == "1"  # test mode: never touch Task Scheduler


def step_family(cfg, st):
    """Starter family-life items, emergency contacts file, home-office tax prep, optional dashboard PIN."""
    r = py("data/life.py", "seed")
    print("  " + (r.stdout.strip() or r.stderr.strip()[-200:]))
    ex, dst = ROOT / "config" / "contacts.example.json", paths.CONFIG / "contacts.json"  # the example is code
    if ex.exists() and not dst.exists():
        shutil.copy(ex, dst)
        print("  Created config/contacts.json: fill in doctors, school, neighbours (used by the emergency sheet).")
    cfg["home_office"] = yes("Does anyone work for themselves / run a business from home (enables home-office tax prep)?",
                             cfg.get("home_office", False))
    if cfg["home_office"]:
        first = (cfg.get("members") or [{"name": "NAME"}])[0]["name"]
        print(f"  Start it later by telling the assistant, or: python data/home_office.py profile {dt_year()} {first} "
              "--office-sqft 120 --home-sqft 1800 --self-employed 1")
    save_json(CONFIG, cfg)
    if yes("Give people their own dashboard login? (adults see everything; children and guests see only their own items)", False):
        import getpass
        sys.path.insert(0, str(ROOT / "data"))
        import auth
        for m in cfg.get("members", []):
            if m.get("role") == "pet":
                continue
            role = "adult" if m.get("role", "adult") == "adult" else "limited"
            pin = getpass.getpass(f"  PIN for {m['name']} ({role}; 4+ characters, blank to skip): ")
            if len(pin) >= 4:
                auth.set_user(m["name"], role, pin)
        print("  Saved (hashed). This keeps people out of the dashboard screen; it is not strong security: see data/auth.py.")
        # auth.set_user wrote config/family.json; refresh the caller's dict IN PLACE so a later step's save_json
        # does not overwrite the new dashboard_users with this stale copy.
        cfg.clear()
        cfg.update(load_json(CONFIG, {}))
    print("  Try the sample data any time: python data/seed_demo.py   (remove: python data/seed_demo.py --remove)")
    return True, ""


def dt_year():
    return dates.today().year




def _profile():
    import agent_profile
    return agent_profile


def _cron(job):
    return task_register.cron(job)


def _sched(job, sched):
    return task_register.sched(job, sched)


def register_posix(jobs):
    """macOS: LaunchAgents after confirmation. Linux: cron lines after confirmation; always print them."""
    if task_register.is_mac():
        print("  LaunchAgents in ~/Library/LaunchAgents: " + ", ".join(task_register.label(j) for j in jobs))
        if not yes("Register them now?", True):
            return False
        ok, rows = task_register.register_mac(inbox_cycle="inbox_cycle" in jobs)
        for name, done, msg in rows:
            print(f"  {name}: {msg}")
        return ok
    lines = task_register.cron_lines(jobs)
    print("  cron lines:")
    for ln in lines:
        print("    " + ln)
    if not yes("Install these into your crontab now?", True):
        return False
    ok, msg = task_register.install_crontab(lines)
    print(f"  crontab: {msg}")
    return ok


def step_tasks(cfg, st):
    if DRY:
        print("  Dry-run: skipped.")
        return True, "skipped"
    bd = ask("Second backup folder on a DIFFERENT drive/device, ideally encrypted (weekly backups already go to the Mitra-Home-Backup volume; blank = none)"
             if CONTAINER else
             "Backup folder on a DIFFERENT drive/device, ideally encrypted (e.g. D:\\MitraHome_backups)", cfg.get("backup_dest", ""))
    cfg["backup_dest"] = bd
    if yes("Encrypt backups (recommended: the backup drive may be lost or stolen)?", cfg.get("backup_encrypt", True)):
        sys.path.insert(0, str(ROOT / "data"))
        try:
            import crypto_box
            crypto_box.available()
        except Exception:
            if yes("The `cryptography` package is needed. Install it now?", True):
                subprocess.run([sys.executable, "-m", "pip", "install", "cryptography"])
        try:
            import crypto_box
            crypto_box.available()
            if not crypto_box.load_passphrase():
                import getpass
                pw = getpass.getpass("  Choose a backup passphrase (12+ characters; write it down and keep a copy OFF " + HERE + "): ")
                if len(pw) >= 12 and pw == getpass.getpass("  Repeat it: "):
                    crypto_box.store_passphrase(pw)
                    print("  Saved to config/secrets.env (git-ignored, never backed up). Without this passphrase the backups cannot be restored.")
                else:
                    print("  Passphrase too short or not repeated identically; encryption NOT enabled.")
                    cfg["backup_encrypt"] = False
            cfg["backup_encrypt"] = cfg.get("backup_encrypt", True) and bool(crypto_box.load_passphrase())
        except Exception as e:
            print(f"  Could not enable encryption: {e}")
            cfg["backup_encrypt"] = False
    else:
        cfg["backup_encrypt"] = False
    inbox_too = yes("Also check the inbox every 2 hours (AI runs only when files are waiting)?", cfg.get("inbox_cycle", False))
    cfg["inbox_cycle"] = inbox_too
    save_json(CONFIG, cfg)
    if not yes("Register the scheduled tasks now?", True):
        return False, "not registered"
    jobs = task_register.jobs(inbox_too)
    if platform.system() != "Windows":
        ok = register_posix(jobs)
    else:
        ok, results = task_register.register_windows(inbox_too)
        for name, one_ok, detail in results:
            print(f"  {name}: {detail}")
    if ok:
        cfg["tasks_registered"] = True
        save_json(CONFIG, cfg)
    return ok, ""


def step_first_data(cfg, st):
    print("  Download statements yourself and drop the files in:")
    print(f"    {paths.INBOX}")
    print("  Suggested order: bank accounts, credit cards (every cardholder), insurance declarations pages, utility bills.")
    prov = (cfg.get("ai") or {}).get("provider", "claude_code")
    if prov in TEXT_PROVS:
        print("  Then file them: open the app (Start Mitra Home) > Inbox > File them now, or run: python data/ai_intake.py")
    else:
        print("  Then open Claude Code in this folder and say: process inbox")
    print(f"  (No Google account needed: everything works on {HERE}. Add Gmail/Calendar/Drive later: python onboard.py add google)")
    return confirm_manual("Understood (you can drop files any time)."), ""


def step_doctor(cfg, st):
    return doctor(), ""


STEPS = [
    ("prereqs", "Prerequisites (Python, packages, Claude Code)", step_prereqs),
    ("folders", "Folders", step_folders),
    ("profile", "Family profile", step_profile),
    ("database", "Database (empty, schema + migrations)", step_database),
    ("agent_account", "Agent Gmail, Calendar, Drive connectors", step_agent_account),
    ("ai", "AI provider (who reads your documents)", step_ai),
    ("safety", "Safety rules", step_safety),
    ("packs", "Optional packs", step_packs),
    ("tax", "Tax-prep payers (banks, state, tuition)", step_tax),
    ("family", "Family life starters, emergency contacts, home office, PIN", step_family),
    ("tasks", "Scheduled tasks and backups", step_tasks),
    ("first_data", "First data drop", step_first_data),
    ("doctor", "Doctor / smoke test", step_doctor),
]


# ---------- doctor ----------
def doctor():
    results = []

    def chk(name, ok, note=""):
        results.append(ok)
        print(f"  [{'x' if ok else '!'}] {name}{(': ' + note) if note else ''}")

    cfg = load_json(CONFIG, {})
    chk("config/family.json present", bool(cfg), "run python onboard.py" if not cfg else "")
    if not cfg.get("agent_email"):
        print("  (info) Gmail/Calendar not connected: fine. Add any time: python onboard.py add google")
    if cfg.get("drive_path"):
        dp = Path(cfg["drive_path"])
        chk("Google Drive folder reachable", (dp / "Inbox").is_dir() and (dp / "Brief").is_dir(),
            "is Google Drive for Desktop running? python onboard.py add drive" if not (dp / "Inbox").is_dir() else "")
    else:
        print("  (info) Google Drive not set up: fine. Phone drop box + briefs: python onboard.py add drive")
    uses_claude = (cfg.get("ai") or {}).get("provider", "claude_code") in ("claude_code", "claude_cli")
    found = claude_auth_overrides() if uses_claude else []
    if uses_claude:
        chk("Claude sign-in not overridden", not found,
            ", ".join(f"{n} ({w})" for n, w in found) + " -> see SETUP_NEW_FAMILY.md Troubleshooting" if found else "")
    for f in FOLDERS:
        if not paths.folder(f).is_dir():
            chk(f"folder {f}/", False)
    chk("household folder" + (" (separate from the app)" if paths.SEPARATE else " (inside the app folder)"), paths.HOME.is_dir(), str(paths.HOME))
    chk("database exists", DB.exists())
    if DB.exists():
        try:
            con = sqlite3.connect(DB)
            chk("database integrity", con.execute("PRAGMA integrity_check").fetchone()[0] == "ok")
            tabs = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
            need = {"documents", "accounts", "transactions", "bills", "subscriptions", "recurring_items"}
            chk("core tables", need <= tabs, "" if need <= tabs else f"missing {sorted(need - tabs)}")
            con.close()
        except Exception as e:
            chk("database readable", False, str(e))
    r = py("data/make_digest.py")
    chk("weekly digest builds", r.returncode == 0, r.stderr.strip().splitlines()[-1] if r.returncode and r.stderr.strip() else "")
    prov = (cfg.get("ai") or {}).get("provider", "claude_code")
    if prov in TEXT_PROVS and not DRY:
        sys.path.insert(0, str(ROOT / "data"))
        try:
            import llm
            ok_ai, msg_ai = llm.ping()
            chk(f"AI provider answers ({prov})", ok_ai, "" if ok_ai else msg_ai)
            row = next((m for m in llm.MATRIX if m[0] == prov), None)
            if row:
                print(f"      pays: {row[1]} | works: {row[2]} | note: {row[3]}")
        except Exception as e:
            chk(f"AI provider answers ({prov})", False, str(e))
    if prov == "claude_code":
        has_perm = (ROOT / ".claude" / "settings.json").exists()
        chk("unattended-run permissions file", has_perm,
            "" if has_perm else "missing .claude/settings.json: scheduled `claude -p` runs would stall on permission prompts")
    if platform.system() == "Windows" and not DRY:
        off = set(cfg.get("tasks_off") or [])
        for name, job, _ in TASKS:
            if job in off:
                continue
            state, where = task_register.job_state(job)
            chk(f"task '{name}'", state in ("on", "unknown"), {
                "off": "not registered: Settings > Data > Runs on its own",
                "paused": "switched off in Task Scheduler: switch it on in Settings > Data > Runs on its own",
                "elsewhere": f"runs another copy of the app ({where}): switch it on in Settings > Data > Runs on its own"}.get(state, ""))
    if (cfg.get("chat") or {}).get("discord", {}).get("enabled") and not DRY:
        sys.path.insert(0, str(ROOT / "data"))
        try:
            import chat_discord
            good, msg, _ = chat_discord.check()
            chk("Discord bot token works", good, msg if not good else "")
        except Exception as e:
            chk("Discord bot token works", False, type(e).__name__)
    if (cfg.get("chat") or {}).get("telegram", {}).get("enabled") and not DRY:
        sys.path.insert(0, str(ROOT / "data"))
        try:
            import chat_telegram
            good, msg = chat_telegram.check()
            chk("Telegram bot token works", good, msg if not good else "")
        except Exception as e:
            chk("Telegram bot token works", False, type(e).__name__)
    sys.path.insert(0, str(ROOT / "data"))
    try:
        import heartbeat
        stale = heartbeat.stale()
        chk("scheduled tasks ran recently", not stale, "; ".join(f"{t}: {m}" for t, m in stale))
    except Exception as e:
        chk("scheduled tasks ran recently", False, str(e))
    if not DRY and uses_claude and shutil.which("claude"):
        try:
            r = subprocess.run(["claude", "-p", "--model", "haiku", "Reply with exactly: ok"], cwd=ROOT,
                               capture_output=True, text=True, timeout=120)
            out = (r.stdout + r.stderr).strip()
            chk("Claude answers (sign-in works)", r.returncode == 0 and "ok" in out.lower(),
                "" if r.returncode == 0 else out.splitlines()[-1][:160] if out else "no output; check /status and SETUP troubleshooting")
        except subprocess.TimeoutExpired:
            chk("Claude answers (sign-in works)", False, "timed out after 120s (401 retry loop? see Troubleshooting)")
    if cfg.get("backup_encrypt"):
        sys.path.insert(0, str(ROOT / "data"))
        try:
            import crypto_box
            crypto_box.available()
            chk("backup encryption ready", bool(crypto_box.load_passphrase()),
                "" if crypto_box.load_passphrase() else "no passphrase (MITRAHOME_BACKUP_PASSPHRASE or config/secrets.env)")
        except Exception as e:
            chk("backup encryption ready", False, str(e))
    else:
        print("  (info) backups are NOT encrypted: they hold your full financial database. Enable in step 11 or `backup_encrypt` in config/family.json.")
    dest = cfg.get("backup_dest")
    if not dest:
        print("  (info) no second backup location set: backups stay next to the project folder. Add an external drive or USB: python onboard.py add backup")
    if dest:
        try:
            Path(dest).mkdir(parents=True, exist_ok=True)
            chk("backup folder writable", os.access(dest, os.W_OK))
        except Exception as e:
            chk("backup folder writable", False, str(e))
    v = py("scripts/verify_clean.py")
    chk("no original-family strings", v.returncode == 0, "run scripts/verify_clean.py" if v.returncode else "")
    if not DRY:
        try:
            sys.path.insert(0, str(ROOT / "data"))
            import updater
            cur, rel, newer = updater.check(quiet=True)
            print(f"  (info) Mitra Home {cur}" + (f"; version {rel['version']} is available: python onboard.py update" if newer else ""))
        except Exception:
            pass
    print(f"\n  {sum(results)}/{len(results)} checks passed")
    return all(results)


# ---------- upgrade ----------
def _held_off(fn):
    """Run an update or upgrade while the web app, the phone bot and the scheduled jobs keep away from the database
    (data/joblock.py): running jobs finish first, new ones skip their turn, the app's pages wait. -> fn() or False."""
    sys.path.insert(0, str(ROOT / "data"))
    import joblock
    try:
        with joblock.maintenance(wait_jobs=120):
            return fn()
    except joblock.Busy as e:
        print("Another update or restore is running; try again when it has finished." if str(e) == joblock.MAINTENANCE
              else f"A {str(e).replace('_', ' ')} run did not finish within two minutes; nothing was changed. Try again shortly.")
        return False


KEEP_DB_COPIES = 5    # database copies an update makes (family_YYYY-MM-DD_HHMMSS.db), newest kept
KEEP_CODE_COPIES = 3  # code copies a zip update makes (code_<version>_<time>/)


def prune_pre_upgrade(bk):
    """Keep only the newest automatic copies in backups_pre_upgrade (audit D4: they piled up, unencrypted, and kept a
    removed person's rows for good). Copies saved there by hand under another name are never touched. -> count removed."""
    import re
    auto_db = re.compile(r"^family_\d{4}-\d{2}-\d{2}_\d{6}\.db(\.enc)?$")
    auto_code = re.compile(r"^code_[\w.]+_\d{8}_\d{6}$")
    n = 0
    try:
        items = list(Path(bk).iterdir())
    except OSError:
        return 0
    for rx, keep, is_dir in ((auto_db, KEEP_DB_COPIES, False), (auto_code, KEEP_CODE_COPIES, True)):
        mine = sorted((p for p in items if rx.match(p.name) and p.is_dir() == is_dir),
                      key=lambda p: p.name[-15:] if is_dir else p.name)  # by time (code_ names start with a version)
        for old in mine[:-keep]:
            try:
                shutil.rmtree(old) if is_dir else old.unlink()
                n += 1
            except OSError:
                pass
    return n


def upgrade(run_doctor=True):
    """After copying a newer template over an existing install: back up, apply new migrations, resync members.
    -> True when the database is up to date. `run_doctor=False` (launch.py, finishing an update on the next start)
    skips the health check at the end."""
    paths.ensure()
    if not DB.exists():
        print("No database yet: run `python onboard.py` first.")
        return False
    stamp = __import__("datetime").datetime.now().strftime("%Y-%m-%d_%H%M%S")
    bk = paths.PRE_UPGRADE
    bk.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    out = sqlite3.connect(bk / f"family_{stamp}.db")
    con.backup(out)
    out.close()
    con.close()
    import backup
    kept = backup.seal_copy(bk / f"family_{stamp}.db")  # encrypted when the family's backups are (audit D4)
    print(f"Backed up database to {kept}" + (" (encrypted with your backup passphrase)" if kept.suffix == ".enc" else ""))
    gone = prune_pre_upgrade(bk)
    if gone:
        print(f"  {gone} older copie{'' if gone == 1 else 's'} from earlier updates removed (the newest {KEEP_DB_COPIES} stay)")
    r = py("data/migrate.py")
    print(r.stdout.rstrip() or "  nothing to apply")
    if r.returncode:
        print(r.stderr)
        print("Upgrade stopped. Your database is unchanged apart from migrations already applied; restore the backup if needed.")
        return False
    py("data/members.py", "sync")
    try:  # tasks registered before the FamilyAgent -> Mitra Home rename move to the new names
        import autostart
        moved = task_register.adopt_legacy() + autostart.adopt_legacy()
        task_register.adopt_flags()
        if moved:
            print("  Scheduled tasks now use the Mitra Home name: " + ", ".join(moved))
    except Exception as e:  # noqa: BLE001
        print(f"  Could not rename the scheduled tasks ({e.__class__.__name__}): Settings > Data > Runs on its own does it.")
    gone = paths.adopt_legacy_backups()  # backups made before 0.110 sit in MitraHome_backups / FamilyAgent_backups
    if gone:
        print(f"  Backup folder {gone} is now {paths.brand.BACKUP_DIR}")
    if not run_doctor:
        print("Upgrade complete.")
        return True
    print("\nUpgrade complete. Running doctor:\n")
    doctor()
    return True


# ---------- main ----------
ADDONS = {  # python onboard.py add <name>
    "drive": ("Google Drive phone drop box + briefs", lambda cfg, st: add_drive(cfg, st)),
    "telegram": ("Telegram bot so the family can ask from their phones", lambda cfg, st: add_telegram(cfg, st)),
    "discord": ("Discord bot (family server + direct messages)", lambda cfg, st: add_discord(cfg, st)),
    "google": ("Agent Gmail + Calendar connectors (needs Claude Code)", lambda cfg, st: add_google(cfg, st)),
    "calendar": ("Google Calendar, read-only, straight from Google (no Claude needed)", lambda cfg, st: add_calendar(cfg, st)),
    "gmail": ("Gmail, read-only, mail with your label filed into the inbox (no Claude needed)", lambda cfg, st: add_gmail(cfg, st)),
    "backup": ("Backups to another drive + weekly schedule", lambda cfg, st: step_tasks(cfg, st)),
    "tax": ("Tax-prep names", lambda cfg, st: step_tax(cfg, st)),
    "family": ("Starter family items, home office, per-person logins", lambda cfg, st: step_family(cfg, st)),
    "packs": ("Optional packs", lambda cfg, st: step_packs(cfg, st)),
    "ai": ("Change the AI provider", lambda cfg, st: step_ai(cfg, st)),
}
EASY = ("prereqs", "folders", "profile", "database", "ai", "safety", "tasks", "first_data", "doctor")


def show(st):
    print("\nMitra Home onboarding checklist\n")
    for i, (key, title, _) in enumerate(STEPS, 1):
        print(f"  [{'x' if st.get('done', {}).get(key) else ' '}] {i:>2}. {title}")
    print()


COMMANDS = {"run", "easy", "status", "doctor", "add", "reset", "check", "update", "upgrade", "home"}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    # help anywhere on the line prints usage and does nothing else (`upgrade --help` used to run the upgrade)
    if cmd in ("-h", "--help", "help", "/?") or any(a in ("-h", "--help") for a in sys.argv[2:]):
        print(__doc__)
        return
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}\n{__doc__}")
        sys.exit(2)
    st = load_json(STATE, {"done": {}})
    cfg = load_json(CONFIG, {})
    if cmd == "status":
        return show(st)
    if cmd == "doctor":
        print("\nDoctor\n")
        sys.exit(0 if doctor() else 1)
    if cmd == "reset":
        STATE.unlink(missing_ok=True)
        print("Checklist progress cleared.")
        return
    if cmd == "upgrade":
        sys.exit(0 if _held_off(lambda: upgrade(run_doctor="--no-doctor" not in sys.argv)) else 1)
    if cmd == "home":
        arg = sys.argv[2] if len(sys.argv) > 2 else ""
        set_home(None if arg == "--inside" else (arg or ROOT.parent / paths.DEFAULT_HOME_NAME))
        print(paths.describe())
        return
    if cmd == "check":
        sys.path.insert(0, str(ROOT / "data"))
        import updater
        return updater.check()
    if cmd == "update":
        sys.path.insert(0, str(ROOT / "data"))
        import updater
        args = sys.argv[2:]
        src = args[args.index("--from") + 1] if "--from" in args and args.index("--from") + 1 < len(args) else None
        def post_update():  # the files on disk are new now: run THEIR upgrade, not this (old) process's
            subprocess.run([sys.executable, str(ROOT / "onboard.py"), "upgrade"], cwd=ROOT)
        ok = _held_off(lambda: updater.run_update(from_zip=src, assume_yes="--yes" in args, force="--force" in args,
                                                  post=post_update, allow_unsigned="--allow-unsigned" in args))
        sys.exit(0 if ok else 1)
    if cmd == "add":
        name = sys.argv[2] if len(sys.argv) > 2 else ""
        if name not in ADDONS:
            print("usage: python onboard.py add " + "|".join(f"{k} ({v[0]})" for k, v in ADDONS.items()))
            return
        ok, note = ADDONS[name][1](cfg, st)
        print(f"  -> {'done' if ok else 'not complete' + (': ' + note if note else '')}")
        return
    if cmd == "run" and not st["done"] and "mode" not in st:
        st["mode"] = "easy" if yes(f"Quick start ({'this server only' if CONTAINER else 'laptop only'}, about 5 minutes, no Google needed) instead of the full setup?", True) else "full"
        save_json(STATE, st)
    easy = cmd == "easy" or st.get("mode") == "easy"
    if easy:
        print(f"\nQuick start: {'this server only' if CONTAINER else 'laptop only'}. Gmail, Calendar, Drive, taxes, packs and logins can be added later (python onboard.py add ...).\n")
    else:
        show(st)
    for i, (key, title, fn) in enumerate(STEPS, 1):
        if st["done"].get(key):
            continue
        if easy and key not in EASY:
            continue
        print(f"Step {i}/{len(STEPS)}: {title}")
        if easy:
            choice = ""
        else:
            choice = ask("Enter to run, 's' to skip for now, 'q' to quit").lower()
        if choice == "q":
            break
        if choice == "s":
            continue
        ok, note = fn(cfg, st)
        st["done"][key] = bool(ok)
        save_json(STATE, st)
        print(f"  -> {'done' if ok else 'not complete' + (': ' + note if note else '')}\n")
        if easy and key == "database" and ok:
            r = py("data/life.py", "seed")
            print("  " + (r.stdout.strip() or r.stderr.strip()[-200:]))
        if easy and not ok:
            print("  Fix that, then run `python onboard.py` again to continue.")
            break
    if not easy:
        show(st)
    print("Re-run `python onboard.py` to continue; `python onboard.py doctor` any time.")


if __name__ == "__main__":
    main()
