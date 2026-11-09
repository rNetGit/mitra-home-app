"""What the app's Chat page and Settings buttons do, as plain functions (no web code), so they are testable and
every button calls code that already exists: the AI choice and key, the Telegram bot, the phone-bot process, the
assistant, backups, exports. Adults only: the dashboard shows these screens to adults.

Secrets are write-only here: a key or token is saved to config/secrets.env and never returned, shown or logged
(only "saved, ends in ABCD" for the last four characters). Every change is written to logs/admin_audit.log
(who, what, when; never a secret or a message).
"""
import datetime as dt
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import brand  # noqa: E402

CONFIG = paths.CONFIG / "family.json"
LOGS = paths.LOGS
BOT_PID = LOGS / "telegram_bot.pid"
BOT_STOP = LOGS / "telegram_bot.stop"
BOT_FRESH_SECONDS = 120  # the bot touches its pid file at least every poll (<= 50 s)

# provider -> (label, needs key, plain-language note)
PROVIDERS = {
    "claude_code": ("Claude Code (your own Claude login)", False, "Best for statements. Runs only when you open Claude Code."),
    "gemini": ("Google Gemini (API key, paid tier)", True, "About $0.40 a month for a family. Use a key with billing enabled."),
    "openai": ("OpenAI (API key)", True, "About $0.20 a month: the cheapest hosted option."),
    "anthropic": ("Anthropic Claude (API key)", True, "About $1 a month for a family."),
    "openrouter": ("OpenRouter (one API key, many models; recommended)", True,
                   "About 20 to 60 cents a month for a family ($5 of credit lasts most families a year); any model, "
                   "default google/gemini-2.5-flash. Only hosts that neither keep nor train on prompts are used."),
    "claude_cli": ("Your Claude plan (the Claude Code you signed in to)", False,
                   "No extra cost on a Claude Pro / Max plan. Inbox filing and Chat; text only, so no photos. "
                   "Install Claude Code from Anthropic and sign in yourself first."),
    "ollama": ("Ollama (a model on this PC)", False, "Free, nothing leaves this PC, lower accuracy."),
    "none": ("No AI", False, "Files wait for you; digests and the dashboard still work."),
}
KEYED = ("anthropic", "openai", "gemini", "openrouter")  # = llm.KEYED (kept literal: llm is imported lazily here)
TEST_NOW = KEYED + ("ollama",)                          # = llm.API
# Signed-in CLIs offered here. gemini_cli stays terminal-only (Google's CLI terms and its free tier) and so does codex_cli:
# its read-only sandbox still lets the model read any file on this PC, so a document steering it could reach unmasked
# originals; it comes back here once a real Codex run shows its shell can be switched off (COMPLIANCE.md).
CLIS = {"claude_cli": "claude"}   # = llm.CLI without gemini_cli and codex_cli


def _audit(who, action, detail=""):
    LOGS.mkdir(exist_ok=True)
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}\t{(who or {}).get('name') or 'local'}\t{action}\t{detail[:200]}\n"
    with open(LOGS / "admin_audit.log", "a", encoding="utf-8") as f:
        f.write(line)


def _is_adult(user):
    return (user or {}).get("role", "adult") == "adult"


def _ends(secret):
    return "…" + secret[-4:] if secret and len(secret) >= 8 else ""


# ---------- AI provider
def ai_status():
    """{provider, model, key_hint, paid_confirmed, photos}: never the key itself."""
    import llm
    s = llm.settings()
    hint = ""
    if s["provider"] in KEYED:
        try:
            hint = _ends(llm.api_key(s["provider"]))
        except Exception:  # noqa: BLE001 (no key yet)
            hint = ""
    ai = config.family().get("ai") or {}
    return {"provider": s["provider"], "model": ai.get("model") or "",
            "key_hint": hint, "paid_confirmed": s["paid_tier"], "photos": s["read_photos"],
            "unattended": bool(ai.get("allow_unattended_cli")), "cli": {k: cli_found(k) for k in CLIS}}


def cli_found(provider):
    """Where this PC finds the vendor's CLI for `provider` ('' = not found). No call: only a look on PATH (or ai.cli_path
    when that provider is the one chosen). Whether it is signed in shows only with Test."""
    import shutil
    import llm
    s = llm.settings()
    if s["provider"] == provider and s["cli_path"]:
        return s["cli_path"] if pathlib.Path(s["cli_path"]).is_file() else ""
    return shutil.which(llm.CLI[provider]) or ""


def save_ai(user, provider, model="", key="", paid_confirmed=False, consent=False, photos=False, unattended=False):
    """Choose the AI provider. -> (ok, message). Nothing is saved unless every rule passes. A provider set outside this
    screen (python onboard.py, e.g. gemini_cli) may be kept as it is: it shows in the list as the current choice."""
    if not _is_adult(user):
        return False, "Only adults can change the AI provider."
    provider = (provider or "").strip().lower()
    import llm
    kept = provider not in PROVIDERS and provider == llm.settings()["provider"] and provider in llm.TEXT
    if provider not in PROVIDERS and not kept:
        return False, "Pick one of the providers in the list."
    model = (model or "").strip()
    if model and not all(c.isalnum() or c in "-._:/" for c in model):
        return False, "The model name has a character that is not allowed (letters, digits, - . _ : / only)."
    if provider == "gemini" and not paid_confirmed:
        return False, ("Google's free tier may train on your documents. Tick the box only if billing is enabled on the key's "
                       "Google project; otherwise choose another provider.")
    if (provider in KEYED or provider in CLIS) and not consent:
        return False, ("Tick the box to confirm you understand the text of your documents (identifiers masked) goes to that "
                       "provider under your own account.")
    if provider in CLIS and not cli_found(provider):
        return False, (f"'{CLIS[provider]}' was not found on this PC. Install it from its maker, sign in to it yourself in a "
                       "terminal, then press Save again.")
    key = (key or "").strip()
    if provider in KEYED:
        if key:
            if provider == "anthropic" and key.startswith("sk-ant-oat"):
                return False, "That is a Claude subscription token, which only Claude Code may use. Create an API key in the Anthropic Console."
            if len(key) < 16 or any(c.isspace() for c in key):
                return False, "That does not look like an API key (too short, or it has spaces). Copy it again."
            llm.store_key(provider, key)
        else:
            try:
                llm.api_key(provider)
            except llm.LLMError:
                return False, f"Paste your {provider} API key; none is saved yet."
    with config.family_edit() as cfg:
        ai = dict(cfg.get("ai") or {})
        ai["provider"] = provider
        ai["model"] = model
        if provider == "gemini":
            ai["gemini_paid_tier_confirmed"] = True
        if provider in TEST_NOW:
            ai["read_receipt_photos"] = bool(photos)
        if provider in CLIS:
            ai["allow_unattended_cli"] = bool(unattended)
        ai.setdefault("max_runs_per_day", 12)
        ai.setdefault("max_calls_per_day", 200)
        cfg["ai"] = ai
    _audit(user, "ai_provider", f"{provider} model={model or 'default'} key_changed={bool(key)}"
           + (f" unattended={bool(unattended)}" if provider in CLIS else ""))
    return True, f"Saved: {PROVIDERS[provider][0] if provider in PROVIDERS else provider}."


def test_ai():
    import llm
    return llm.ping()


# ---------- Telegram bot
def telegram_status():
    """{token, bot, running}: whether a token is saved, the bot's @name (a quick call to Telegram), whether it is running."""
    import chat_telegram as ct
    tok = ct.token()
    out = {"token": bool(tok), "bot": "", "running": bot_running(), "hint": _ends(tok)}
    if tok:
        ok, msg = ct.check(tok)
        out["bot"] = msg if ok else ""
        out["problem"] = "" if ok else msg
    return out


def save_telegram(user, token):
    """Check the token with Telegram, then save it and switch the bot on. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can set up the phone bot."
    import chat_telegram as ct
    token = (token or "").strip()
    good, msg = ct.check(token)
    if not good:
        return False, msg
    config.write_secret(ct.TOKEN_NAME, token)
    with config.family_edit() as cfg:
        chat = dict(cfg.get("chat") or {})
        chat["telegram"] = {**(chat.get("telegram") or {}), "enabled": True, "bot": msg}
        cfg["chat"] = chat
    _audit(user, "telegram_token", f"bot={msg}")
    return True, f"Bot {msg} works and is saved."


def pairing_code(user, name):
    """A one-time code (15 minutes) for one family member to send to the bot. -> (ok, message, code)."""
    if not _is_adult(user):
        return False, "Only adults can link phones.", ""
    import chat_core
    import db
    con = db.connect(paths.DB)
    try:
        code, member, role, exp = chat_core.invite(con, name, platform="telegram")
    except ValueError as e:
        return False, str(e), ""
    finally:
        con.close()
    _audit(user, "pairing_code", f"member={member} role={role}")
    return True, f"Code for {member} ({role}), valid 15 minutes. In Telegram open your bot, press Start, then send: /start {code}", code


def bot_running(now=None):
    now = now or time.time()
    try:
        return BOT_PID.exists() and now - BOT_PID.stat().st_mtime < BOT_FRESH_SECONDS
    except OSError:
        return False


def bot_start(user):
    """Start the phone bot in the background (no new window). -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can start the phone bot."
    import chat_telegram as ct
    if not ct.token():
        return False, "Save the bot token first."
    if bot_running():
        return True, "The bot is already running."
    LOGS.mkdir(exist_ok=True)
    BOT_STOP.unlink(missing_ok=True)
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x08000000 | 0x00000200  # no console window, own process group
    else:
        kw["start_new_session"] = True
    logf = open(LOGS / "chat_telegram_bot.log", "a", encoding="utf-8")  # noqa: SIM115 (the child keeps it)
    subprocess.Popen([sys.executable, str(HERE / "chat_telegram.py"), "run"], cwd=ROOT, stdout=logf, stderr=logf,
                     stdin=subprocess.DEVNULL, **kw)
    _audit(user, "bot_start")
    return True, "Starting the bot. It takes a few seconds."


def bot_stop(user):
    """Ask the bot to stop (it exits within about a minute). -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can stop the phone bot."
    LOGS.mkdir(exist_ok=True)
    BOT_STOP.write_text(dt.datetime.now().isoformat(timespec="seconds"), encoding="utf-8")
    _audit(user, "bot_stop")
    return True, "Stop requested. The bot exits within a minute."


def bot_autostart(user, on):
    """The "Start with this PC" toggle: start the phone bot at every sign-in, or stop doing that. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change how the phone bot starts."
    import autostart
    ok, msg = autostart.enable("telegram") if on else autostart.disable("telegram")
    _audit(user, "bot_autostart", f"on={bool(on)} ok={ok}")
    return ok, msg


# ---------- Google Calendar (read-only)
def save_google_client(user, raw_bytes):
    """Validate and save the Desktop-app client file downloaded from Google Cloud. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can connect a calendar."
    import tempfile

    import google_calendar as gc
    with tempfile.TemporaryDirectory() as d:
        p = pathlib.Path(d) / "client.json"
        p.write_bytes(raw_bytes[:100_000])
        try:
            gc.load_client(p)
        except gc.CalendarError as e:
            return False, str(e)
        gc.CLIENT_FILE.parent.mkdir(exist_ok=True)
        gc.CLIENT_FILE.write_bytes(p.read_bytes())
    _audit(user, "google_client_saved")
    return True, "Client file saved. Now sign in."


def google_sign_in(user, browser=None, timeout=240):
    """Open the browser on this PC, wait for the sign-in. -> (ok, message). The token goes to secrets.env only."""
    if not _is_adult(user):
        return False, "Only adults can connect a calendar."
    import google_calendar as gc
    notes = []
    try:
        gc.authorize(browser=browser, timeout=timeout, say=notes.append)
    except gc.CalendarError as e:
        return False, str(e)
    _audit(user, "google_sign_in")
    return True, "Signed in (read-only)."


def google_pick(user, ids):
    if not _is_adult(user):
        return False, "Only adults can connect a calendar."
    with config.family_edit() as cfg:
        cfg["google_calendar"] = {**(cfg.get("google_calendar") or {}), "enabled": True,
                                  "calendars": [str(i) for i in ids][:20] or ["primary"]}
    _audit(user, "google_calendars", f"{len(ids) or 1} calendar(s)")
    return True, "Saved. See them on Calendar."


def paper_names_set(user, text):
    """Full names as printed on papers, one per line -> privacy.paper_names (masked before anything goes to an AI).
    The audit line holds the count only, never the names."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    import pii
    names, problems = pii.clean_paper_names(text)
    if problems:
        return False, problems[0]
    with config.family_edit() as cfg:
        cfg["privacy"] = {**(cfg.get("privacy") or {}), "paper_names": names}
    _audit(user, "paper_names", f"{len(names)} name(s)")
    return True, "Saved. These names are masked before anything is sent to the AI." if names else "Saved."


# ---------- sign-in PINs (needed before the dashboard may be opened from a phone)
def pin_people():
    """[{'name','role','has_pin'}] for every member the dashboard can ask for a PIN (adults and children, never pets)."""
    import auth
    have = {u["name"] for u in auth.users()}
    out = []
    for m in config.members():
        n = m.get("name")
        if n and m.get("role") != "pet":
            out.append({"name": n, "role": "adult" if m.get("role") == "adult" else "limited", "has_pin": n in have})
    return out


def pin_set(user, name, pin, again, current=""):
    """Give a member a sign-in PIN, or replace theirs. Adults only (a signed-in adult, or the first PIN while the PC is
    open to this machine). The old PIN is not asked: a forgotten PIN must be easy to replace (owner, 2026-11-01), so
    `current` is accepted and ignored. The change is audited (name, never the PIN) and signs that person out everywhere."""
    import auth
    if not _is_adult(user):
        return False, "Only adults can change sign-in PINs."
    person = next((p for p in pin_people() if p["name"] == name), None)
    if not person:
        return False, "Choose a person from the list."
    if pin != again:
        return False, "The two PINs are not the same."
    if len(pin) < 4:
        return False, "A PIN needs at least 4 characters."
    if len(set(pin)) == 1:
        return False, "Use something less easy to guess than one repeated character."
    auth.set_user(name, person["role"], pin)
    _audit(user, "pin_set", name)
    return True, f"Saved. {name} signs in with this PIN."


# ---------- running on its own, optional packs, tax papers (first-run gaps the wizard used to cover)
PACK_LABELS = {  # onboard.PACKS key -> (title, plain-language note)
    "festivals": ("Festival calendar", "Festival dates on Today and the Calendar. A starter list is added for you to edit."),
    "contracts": ("Work contracts", "End-date alerts, timesheet hours, hybrid schedule and monthly invoices."),
    "amazon": ("Amazon orders", "Match Amazon order history to card charges."),
    "shopping": ("Shopping lists", "Things to buy by a target date."),
    "holidays": ("Public holidays", "Your country's public holidays on the Calendar and the Brief, worked out on this PC."),
}
PACK_DEFAULT_ON = ("holidays",)  # = onboard.PACKS_ON


def tasks_status():
    cfg = config.family()
    return {"registered": bool(cfg.get("tasks_registered")), "inbox_cycle": bool(cfg.get("inbox_cycle"))}


MAIN_JOBS = ("daily_digest", "weekly_digest", "weekly_backup")
STATE_TEXT = {"on": "On", "paused": "Paused in Task Scheduler", "off": "Off", "unknown": "Not checked (test mode)",
              "elsewhere": "Used by another copy of the app"}


def _last_run(rec, now=None):
    """heartbeat row -> {"text", "ok", "note"} for people ("Today 07:00", "Yesterday 18:00", "Oct 12 09:00"), or None."""
    if not rec:
        return None
    try:
        at = dt.datetime.fromisoformat(rec["at"])
    except (KeyError, ValueError, TypeError):
        return None
    days = ((now or dt.datetime.now()).date() - at.date()).days
    day = "Today" if days == 0 else "Yesterday" if days == 1 else f"{at:%b} {at.day}"
    return {"text": f"{day} {at:%H:%M}", "ok": bool(rec.get("ok")), "note": str(rec.get("note") or "")[:200]}


def task_jobs(cfg=None, run=None, now=None):
    """One row per scheduled job for Settings > Data > Runs on its own: label, when it runs (and the day / time to
    change), whether it is on here, and the last run from logs/heartbeat.json. The phone drop box sweep is listed
    once Google Drive is set up or the task exists."""
    import agent_profile
    import heartbeat
    import task_register
    cfg = cfg if cfg is not None else config.family()
    prof, beats, rows = agent_profile.get(), heartbeat._load(), []
    for job in list(MAIN_JOBS) + ["inbox_cycle", "inbox_sweep"]:
        state, where = task_register.job_state(job, run)
        if job == "inbox_sweep" and state in ("off", "unknown") and not (cfg.get("sweep_registered") or cfg.get("drive")):
            continue
        day_f, time_f = {"daily_digest": (None, "brief_time"), "weekly_digest": ("weekly_day", "weekly_time"),
                         "weekly_backup": ("backup_day", "backup_time")}.get(job, (None, None))
        rows.append({"job": job, "label": task_register.LABELS[job],
                     "when": agent_profile.when_text(job, prof) or task_register.EVERY[job],
                     "day": prof[day_f] if day_f else None, "time": prof[time_f] if time_f else None,
                     "state": state, "state_text": STATE_TEXT[state], "where": where if state == "elsewhere" else "",
                     "on": state in ("on", "paused"), "last": _last_run(beats.get(job), now)})
    return rows


def _remember_job(job, on):
    """Keep family.json in step with one job: `tasks_off` (jobs the family switched off, so the health check does not
    ask for them), `tasks_registered`, `inbox_cycle`, `sweep_registered`."""
    with config.family_edit() as cfg:
        off = [j for j in cfg.get("tasks_off") or [] if j != job] + ([] if on else [job])
        cfg["tasks_off"] = sorted(set(off))
        if job in MAIN_JOBS:
            if on:
                cfg["tasks_registered"] = True
            elif all(j in cfg["tasks_off"] for j in MAIN_JOBS):
                cfg["tasks_registered"] = False
        elif job == "inbox_cycle":
            cfg["inbox_cycle"] = bool(on)
        elif job == "inbox_sweep":
            cfg["sweep_registered"] = bool(on)


def task_set(user, job, on, run=None):
    """Switch one scheduled job on or off on this PC. -> (ok, message)."""
    import task_register
    if not _is_adult(user):
        return False, "Only adults can change what runs on its own."
    if job not in task_register.ALL:
        return False, "Unknown job."
    label = task_register.LABELS[job]
    ok, detail = task_register.set_job(job, bool(on), run)
    _audit(user, "task_set", f"job={job} on={bool(on)} ok={ok}")
    if not ok:
        return False, f"{label}: this PC did not allow it ({detail or 'no reason given'}). Nothing else was changed."
    _remember_job(job, bool(on))
    if os.environ.get("AIFA_DRY_RUN") == "1" or detail.startswith("test mode"):
        return True, f"Test mode: {label} was not changed on this PC."
    return True, f"{label} now runs on its own on this PC." if on else f"{label} is off. It no longer runs by itself on this PC."


def task_time(user, job, day="", time_=""):
    """Change when the daily brief, weekly digest or weekly backup runs; a job that is on here is registered again at
    the new time. -> (ok, message)."""
    import agent_profile
    if not _is_adult(user):
        return False, "Only adults can change what runs on its own."
    fields = {"daily_digest": (None, "brief_time"), "weekly_digest": ("weekly_day", "weekly_time"),
              "weekly_backup": ("backup_day", "backup_time")}.get(job)
    if not fields:
        return False, "This one runs at a fixed interval."
    new = {fields[1]: time_}
    if fields[0]:
        new[fields[0]] = day
    ok, msgs = agent_profile.set_profile(new)
    if not ok:
        return False, " ".join(msgs)
    _audit(user, "task_time", f"job={job}")
    import task_register
    when = agent_profile.when_text(job)
    state, _ = task_register.job_state(job)
    tail = "" if state in ("on", "paused", "unknown") else " It is off on this PC: switch it on to run it."
    return True, f"{task_register.LABELS[job]}: {when.lower() if when.startswith('Every') else when}.{tail}"


def tasks_register(user, inbox_cycle=False):
    """Make the daily brief, weekly digest and weekly backup (and optionally the two-hourly inbox check) run on their own:
    Task Scheduler on Windows, cron elsewhere. -> (ok, message). Backup encryption's passphrase is not handled here."""
    if not _is_adult(user):
        return False, "Only adults can change what runs on its own."
    if os.environ.get("AIFA_DRY_RUN") == "1":
        return True, "Test mode: nothing was registered."
    import task_register
    ok, results = task_register.register(bool(inbox_cycle))
    with config.family_edit() as cfg:
        cfg["inbox_cycle"] = bool(inbox_cycle)
        if ok:
            cfg["tasks_registered"] = True
    failed = [name for name, one_ok, _ in results if not one_ok]
    _audit(user, "tasks_register", f"ok={ok} inbox_cycle={bool(inbox_cycle)}")
    if ok:
        return True, ("The daily brief, the weekly digest and the weekly backup now run by themselves"
                      + (" and the inbox is checked every two hours." if inbox_cycle else "."))
    return False, "This PC did not allow it for: " + ", ".join(failed or ["the schedule"]) + ". Nothing else was changed."


def view_mode_set(user, mode):
    """Switch the app between the Simple and the Advanced view. Display only: no data, feature or page changes.
    -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    import view_mode
    mode = str(mode or "").strip().lower()
    if mode not in view_mode.MODES:
        return False, "Choose Simple or Advanced."
    with config.family_edit() as cfg:
        cfg["ui"] = {**(cfg.get("ui") or {}), "mode": mode}
    _audit(user, "view_mode_set", mode)
    return True, "Showing the Simple view." if mode == "simple" else "Showing everything (Advanced)."


def update_check_set(user, on):
    """Settings > Data > Updates: "Check for new versions every day" (config updates.daily_check). Off = no network
    call at all from the daily task. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    with config.family_edit() as cfg:
        cfg["updates"] = {**(cfg.get("updates") or {}), "daily_check": bool(on)}
    _audit(user, "update_check_set", "on" if on else "off")
    return True, ("I will look for new versions once a day." if on else
                  "Daily look switched off. Use Check for updates when you want to know.")


def phones_set(user, on):
    """Settings > Phones > Connection: "Let phones and walls on the home Wi-Fi connect" (config phones.lan, read by
    launch.py at every start). Takes effect at the next start or with Restart. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    with config.family_edit() as cfg:
        cfg["phones"] = {**(cfg.get("phones") or {}), "lan": bool(on)}
    _audit(user, "phones_set", "on" if on else "off")
    return True, ("Phones and walls on the home Wi-Fi may connect (once an adult has a PIN)." if on else
                  "From the next start, only this PC opens the app. Paired phones and walls wait until it is on again.")


def firewall_allow(user, local, port, lan_ip=None):
    """Ask Windows (UAC) for the one inbound rule the phones need (data/firewall.py). Adults, this PC only: Windows'
    prompt appears on this PC's screen. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    if not local:
        return False, "Windows asks for permission on the PC's own screen: do this from the PC."
    import firewall
    ok, msg = firewall.allow(port, lan_ip)
    _audit(user, "firewall_allow", f"port={int(port)} ok={ok}")
    return ok, msg


def packs_set(user, packs):
    """Switch optional packs on or off ({key: bool}). Turning one on copies its example data when the household has none;
    an existing file is never overwritten. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change the optional packs."
    sys.path.insert(0, str(ROOT))
    import onboard
    unknown = [k for k in packs if k not in onboard.PACKS]
    if unknown:
        return False, "Unknown pack: " + ", ".join(unknown)
    with config.family_edit() as cfg:
        cur = dict(cfg.get("packs") or {})
        copied = []
        for key, on in packs.items():
            cur[key] = bool(on)
            example = onboard.PACKS[key][1]
            if on and example:
                src, dst = ROOT / "packs" / example[0], paths.CONFIG / example[1]
                if src.exists() and not dst.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(src.read_bytes())
                    copied.append(key)
        cfg["packs"] = cur
    _audit(user, "packs_set", ",".join(k for k, v in sorted(cur.items()) if v))
    msg = "Saved."
    if copied:
        msg += " A starter list was added for " + ", ".join(PACK_LABELS[k][0].lower() for k in copied) + ": edit it to match your family."
    return True, msg


def traditions_set(user, text, lookup):
    """The family's traditions (one per line) and the yearly AI look-up switch. Kept only in config/family.json on
    this PC (data/traditions.py). -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    import traditions as T
    names = [x.strip() for x in str(text or "").replace(",", "\n").splitlines() if x.strip()]
    try:
        clean = T.save(names, lookup)
    except T.TraditionError as e:
        return False, str(e)
    _audit(user, "traditions_set", f"n={len(clean)} lookup={bool(lookup) and bool(clean)}")
    if not clean:
        return True, "Saved: no traditions."
    msg = "Saved: " + ", ".join(clean) + "."
    if lookup:
        why = T.ai_ready()
        msg += (f" The yearly look-up waits until {why}." if why else
                " Their dates are looked up with your AI the next morning and wait in the Inbox for you.")
    return True, msg


def traditions_now(user):
    """Ask for what is due now (this year's dates; next year's from October), the same step the daily task runs."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    import traditions as T
    if not T.get()["lookup"]:
        return False, "Turn on the yearly look-up first."
    why = T.ai_ready()
    if why:
        return False, f"Not asked: {why}."
    out = T.auto()
    _audit(user, "traditions_now", f"n={len(out)}")
    return True, " ".join(out) if out else "Every tradition's dates were asked for already this year. See the Inbox."


def _split(text):
    return [x.strip() for x in (text or "").replace("\n", ",").split(",") if x.strip()]


def tax_prep_set(user, payers="", state_words="", tuition=""):
    """Names the tax-prep checklist looks for: who sends interest forms, words on state tax payments, the tuition payee.
    Institution names only: anything that looks like an account number is refused. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can change the tax papers."
    import re
    lists = {"payers": _split(payers), "state_tax_keywords": _split(state_words), "education_payee_patterns": _split(tuition)}
    for items in lists.values():
        for item in items:
            if re.search(r"\d{6,}", item.replace(" ", "").replace("-", "")):
                return False, "Please write names only, no account or ID numbers."
            if len(item) > 80:
                return False, "Each name should be short (80 characters at most)."
    f = paths.CONFIG / "tax_prep.json"
    cur = config.data_file("tax_prep.json") or {}
    config.write_json(f, {**cur, **lists})
    _audit(user, "tax_prep_set", ",".join(f"{k}={len(v)}" for k, v in lists.items()))
    return True, "Saved."


def gmail_sign_in(user, browser=None, timeout=240):
    """Sign in again with the one extra permission (read mail). -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can allow this."
    import google_gmail as gm
    notes = []
    try:
        gm.gc.authorize(browser=browser, timeout=timeout, say=notes.append, gmail=True)
    except gm.gc.CalendarError as e:
        return False, str(e)
    if not gm.has_permission():
        return False, "Google did not grant the permission to read mail. Tick every box on Google's screen and try again."
    _audit(user, "gmail_allowed")
    return True, "Allowed. Mail with your label can now be filed from Gmail."


def gmail_settings(user, enabled, label):
    if not _is_adult(user):
        return False, "Only adults can change this."
    import re
    import google_gmail
    label = " ".join(str(label or "").split())[:60] or google_gmail.settings()["label"]
    if re.search(r"[\x00-\x1f]", label):
        return False, "That label name has characters Gmail does not allow."
    with config.family_edit() as cfg:
        cfg["gmail"] = {**(cfg.get("gmail") or {}), "enabled": bool(enabled), "label": label}
    _audit(user, "gmail_settings", f"enabled={bool(enabled)}")
    return True, "Saved." if enabled else "Saved. Gmail is off; nothing is read."


def gmail_pull_now(user):
    """Copy new labelled mail into the inbox now. -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can do this."
    import google_gmail as gm
    try:
        r = gm.pull()
    except gm.gc.CalendarError as e:
        return False, str(e)
    _audit(user, "gmail_pull", f"files={r['files']} texts={r['texts']}")
    if not (r["files"] or r["texts"]):
        return True, "Nothing new with your label."
    return True, f"Copied {r['files']} file(s) and {r['texts']} message text(s) into the inbox."


def mail_folder_set(user, enabled, address, host, port, folder, password, local):
    """Settings > Connections > Mail folder: the mailbox made for Mitra Home and its app password (the password only on
    this PC, write-only; blank = keep the one saved). Audited without the address or the password."""
    if not _is_adult(user):
        return False, "Only adults can change this."
    import mail_folder as mf
    try:
        s = mf.clean(address, host, port, folder)
    except mf.MailError as e:
        return False, str(e)[:1].upper() + str(e)[1:] + "."
    password = "".join(str(password or "").split())  # app passwords are often shown in groups of four
    if password:
        if not local:
            return False, "Type the app password on this PC."
        if len(password) > 200:
            return False, "That is not an app password."
        config.write_secret(mf.MAIL_SECRET, password)
    elif enabled and not mf.has_password():
        return False, (f"Type the mailbox's app password (made for {brand.PRODUCT} in the mail provider's security "
                       "settings).")
    old = mf.settings()
    moved = any(s[k] != old[k] for k in ("address", "host", "port"))
    if moved and not local and mf.has_password():
        # the saved password signs in wherever the settings point: a phone must not be able to send it to another server
        return False, "Change the mailbox's address or server on this PC (the saved app password goes with them)."
    with config.family_edit() as cfg:
        cfg["mail_folder"] = {**s, "enabled": bool(enabled)}
    _audit(user, "mail_folder_set", f"enabled={bool(enabled)} host={s['host']} password={'new' if password else 'kept'}")
    return True, "Saved." if enabled else "Saved. The mail folder is off; nothing is read."


def mail_folder_test(user):
    if not _is_adult(user):
        return False, "Only adults can do this."
    import mail_folder as mf
    try:
        n = mf.test()
    except mf.MailError as e:
        return False, str(e)[:1].upper() + str(e)[1:] + "."
    _audit(user, "mail_folder_test", "ok")
    return True, f"Signed in: {n} message{'s' if n != 1 else ''} in the folder. Nothing was changed."


def mail_folder_pull_now(user):
    if not _is_adult(user):
        return False, "Only adults can do this."
    import mail_folder as mf
    try:
        r = mf.pull()
    except mf.MailError as e:
        mf.note_error(e)
        return False, str(e)[:1].upper() + str(e)[1:] + "."
    _audit(user, "mail_folder_pull", f"files={r['files']} texts={r['texts']}")
    if not (r["files"] or r["texts"]):
        return True, "Nothing new in the mail folder."
    return True, f"Copied {r['files']} file(s) and {r['texts']} message text(s) into the inbox."


def mail_folder_forget(user):
    if not _is_adult(user):
        return False, "Only adults can do this."
    import mail_folder as mf
    mf.forget()
    _audit(user, "mail_folder_forget", "")
    return True, "Forgot the app password and what was read. Also delete the app password at the mail provider."


def google_disconnect(user):
    if not _is_adult(user):
        return False, "Only adults can disconnect a calendar."
    import google_calendar as gc
    gc.revoke()
    with config.family_edit() as cfg:
        cfg["google_calendar"] = {"enabled": False, "calendars": []}
        if cfg.get("gmail"):
            cfg["gmail"] = {**cfg["gmail"], "enabled": False}
    _audit(user, "google_disconnect")
    return True, "Signed out here and access cancelled at Google."


# ---------- Bank sync (SimpleFIN Bridge; the access URL is write-only, like a token)
def bank_setup(user, token):
    """Claim the one-time setup token and save the access URL. -> (ok, message); the URL is never in the message."""
    if not _is_adult(user):
        return False, "Only adults can set up bank sync."
    import bank_sync as bs
    try:
        n = bs.setup(token)
    except bs.BankError as e:
        return False, bs.scrub(e)
    _audit(user, "bank_setup", f"accounts={n}")
    return True, f"Connected to SimpleFIN: {n} account(s) found. Tick the ones to pull, then Pull now."


def bank_pick(user, ids):
    if not _is_adult(user):
        return False, "Only adults can change bank sync."
    import bank_sync as bs
    n = bs.choose(ids)
    _audit(user, "bank_pick", f"chosen={n}")
    return True, f"{n} account(s) will be pulled every morning." if n else "No account is pulled until you tick one."


def bank_pull_now(user):
    if not _is_adult(user):
        return False, "Only adults can do this."
    import bank_sync as bs
    try:
        r = bs.pull()
    except bs.BankError as e:
        _audit(user, "bank_pull", "failed")
        return False, bs.scrub(e)
    _audit(user, "bank_pull", f"inserted={r['inserted']} skipped={r['skipped']}")
    msg = f"Pulled {r['inserted']} new transaction(s); {r['skipped']} were already there."
    if r["warnings"]:
        msg += " Notes: " + "; ".join(r["warnings"][:3])
    if not r["accounts"]:
        msg = "Nothing to pull: tick at least one account first."
    return True, msg


def sync_all_start(user):
    """The Sync button: bank + Drive inbox + mail pulls in one background run (data/sync_all.py). -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can do this."
    import sync_all
    ok, msg = sync_all.start()
    _audit(user, "sync_all", "started" if ok else "not started")
    return ok, msg


def bank_forget(user):
    if not _is_adult(user):
        return False, "Only adults can do this."
    import bank_sync as bs
    bs.forget()
    _audit(user, "bank_forget")
    return True, "Bank sync forgotten: the access URL is removed from this PC. Transactions already pulled stay."


# ---------- Mitra Home calendar sync (writes only to a calendar of its own)
def calendar_write_sign_in(user, browser=None, timeout=240):
    """Sign in again with the one extra permission (its own calendar only). -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can allow this."
    import google_calendar as gc
    try:
        gc.authorize(browser=browser, timeout=timeout, say=lambda *_: None, write=True)
    except gc.CalendarError as e:
        return False, str(e)
    if not gc.can_write():
        return False, "Google did not grant the permission to make a calendar. Tick every box on Google's screen and try again."
    _audit(user, "calendar_write_allowed")
    return True, f"Allowed. {brand.PRODUCT} can now keep its own calendar."


def calendar_sync_settings(user, horizon, reminder_days, amounts, auto):
    if not _is_adult(user):
        return False, "Only adults can change this."
    with config.family_edit() as cfg:
        gcfg = dict(cfg.get("google_calendar") or {})
        gcfg["sync"] = {"horizon": int(horizon), "reminder_days": int(reminder_days), "amounts": bool(amounts), "auto": bool(auto)}
        cfg["google_calendar"] = gcfg
    _audit(user, "calendar_sync_settings", f"horizon={horizon} reminder={reminder_days} amounts={bool(amounts)} auto={bool(auto)}")
    return True, "Saved."


def calendar_sync_preview(user):
    """What would change, nothing sent. -> (ok, summary, rows[{what, date, title}])."""
    if not _is_adult(user):
        return False, "Only adults can sync the calendar.", []
    import calendar_sync as cs
    p = cs.plan()
    rows = [{"what": w, "date": r["date"], "title": r["title"]} for k, w in (("create", "add"), ("update", "change"), ("delete", "remove"))
            for r in p[k]]
    return True, cs.summary_line(p), rows


def calendar_sync_apply(user):
    if not _is_adult(user):
        return False, "Only adults can sync the calendar."
    import calendar_sync as cs
    import google_calendar as gc
    try:
        r = cs.apply()
    except gc.CalendarError as e:
        return False, str(e)
    _audit(user, "calendar_sync", f"added={r['created']} changed={r['updated']} removed={r['deleted']}")
    msg = f"Added {r['created']}, changed {r['updated']}, removed {r['deleted']}."
    if r["problems"]:
        msg += f" {len(r['problems'])} could not be done; run it again."
    return not r["problems"], msg


def calendar_sync_remove(user):
    if not _is_adult(user):
        return False, "Only adults can remove it."
    import calendar_sync as cs
    import google_calendar as gc
    try:
        gone = cs.remove()
    except gc.CalendarError as e:
        return False, str(e)
    _audit(user, "calendar_sync_remove")
    return True, f"The {brand.CALENDAR_NAME} calendar was deleted from Google." if gone else f"There was no {brand.CALENDAR_NAME} calendar."


# ---------- Ask (the assistant, in the dashboard)
def ask(user, text, history=None):
    """Run one request through the assistant (looks things up, changes nothing).
    -> {lines, answer, needs_confirm, writes, refs, ok}. When needs_confirm, the changes in `writes` wait for the
    person's button, which calls confirm(user, writes): exactly those changes run, the AI is not asked again."""
    empty = {"lines": [], "answer": "", "needs_confirm": False, "writes": [], "refs": [], "ok": True}
    if not _is_adult(user):
        return {**empty, "lines": ["The assistant is for adults."], "ok": False}
    text = (text or "").strip()[:1000]
    if not text:
        return empty
    import assistant
    res = assistant.run(text, history=history, user=user)
    _audit(user, "ask", f"changes={len(res['writes'])} chars={len(text)}")  # the question itself is not logged
    return {"lines": res["lines"], "answer": res["answer"] or res["question"] or "", "needs_confirm": bool(res["writes"]),
            "writes": res["writes"], "refs": res["refs"], "ok": bool(res["ok"])}


def confirm(user, writes):
    """Make the changes an ask() showed, after the person said yes. -> {lines, refs, ok}."""
    if not _is_adult(user):
        return {"lines": ["The assistant is for adults."], "refs": [], "ok": False}
    import assistant
    res = assistant.apply(list(writes or []), user=user)
    _audit(user, "ask_confirm", f"changes={len(writes or [])} ok={res['ok']}")
    return res


# ---------- briefings (the side panel)
BRIEFINGS = {
    "this_week": ("This week", "make_this_week.py"),
    "weekly_digest": ("Weekly digest", "make_digest.py"),
    "family_meeting": ("Family meeting agenda", "make_family_meeting.py"),
    "emergency": ("Emergency sheet", "emergency_sheet.py"),
}


def briefing(user, kind):
    """Build one briefing with the same script the terminal uses. -> (ok, title, markdown or error, file name)."""
    if not _is_adult(user):
        return False, "", "Only adults can open briefings.", ""
    if kind not in BRIEFINGS:
        return False, "", "Unknown briefing.", ""
    title, script = BRIEFINGS[kind]
    r = subprocess.run([sys.executable, str(HERE / script)], cwd=ROOT, capture_output=True, text=True, timeout=180)
    lines = r.stdout.strip().splitlines()
    if r.returncode != 0 or not lines:
        return False, title, (r.stderr or r.stdout).strip()[-400:] or "Could not build it.", ""
    try:
        p = pathlib.Path(lines[-1].strip()).resolve()
        p.relative_to(paths.HOME.resolve())
        text = p.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return False, title, "The briefing was not found.", ""
    _audit(user, "briefing", kind)
    return True, title, text, p.name


# ---------- data
def backup_now(user):
    if not _is_adult(user):
        return False, "Only adults can run a backup."
    r = subprocess.run([sys.executable, str(ROOT / "tasks" / "run_task.py"), "weekly_backup"], cwd=ROOT,
                       capture_output=True, text=True, timeout=900)
    _audit(user, "backup_now", f"rc={r.returncode}")
    tail = (r.stdout + r.stderr).strip()[-600:]
    return r.returncode == 0, tail or ("Backup done." if r.returncode == 0 else "Backup failed; see logs/.")


def restore_check(user, src, name, passphrase=""):
    """Open one backup in a temp folder and check it (the live database is not touched). -> (ok, message)."""
    if not _is_adult(user):
        return False, "Only adults can restore a backup."
    import restore_backup as rb
    return rb.check(src, name, passphrase or None)


def export_now(user):
    """Every table as CSV into a zip under exports/. -> (ok, message, zip_path or None)."""
    if not _is_adult(user):
        return False, "Only adults can export.", None
    r = subprocess.run([sys.executable, str(HERE / "export_data.py"), "--zip"], cwd=ROOT, capture_output=True, text=True, timeout=600)
    _audit(user, "export", f"rc={r.returncode}")
    if r.returncode != 0:
        return False, (r.stdout + r.stderr).strip()[-600:], None
    zips = sorted((paths.EXPORTS).glob("*.zip"), key=lambda p: p.stat().st_mtime)
    return True, (r.stdout.strip().splitlines() or ["Exported."])[0], (zips[-1] if zips else None)


def update_now(user):
    """Run the signed update. -> (ok, output tail). The dashboard must be restarted afterwards."""
    if not _is_adult(user):
        return False, "Only adults can update."
    r = subprocess.run([sys.executable, str(ROOT / "onboard.py"), "update", "--yes"], cwd=ROOT, capture_output=True, text=True,
                       timeout=1800, stdin=subprocess.DEVNULL)
    _audit(user, "update", f"rc={r.returncode}")
    return r.returncode == 0, (r.stdout + r.stderr).strip()[-1500:]


def what_changed():
    """Audit lines, newest first, for Settings > Changes made here."""
    f = LOGS / "admin_audit.log"
    if not f.exists():
        return []
    rows = []
    for line in f.read_text(encoding="utf-8").splitlines()[-30:][::-1]:
        parts = line.split("\t")
        if len(parts) >= 3:
            rows.append({"when": parts[0], "who": parts[1], "what": parts[2], "detail": parts[3] if len(parts) > 3 else ""})
    return rows


if __name__ == "__main__":
    print(json.dumps({"ai": ai_status(), "bot_running": bot_running()}, indent=2))
