"""The agent profile: the short card a household changes when they say "update the agent" (Settings > Home Profile, or from
Chat: "send the brief at 6 instead", with the usual confirm card).

Stored under "agent" in config/family.json:
  name         what the household calls its agent (rail, page title, Chat, Brief, the assistant's own wording)
  tone         "brief" (short and plain) or "warm" (a little more detail)
  brief_time   when the daily brief is made, HH:MM (the daily scheduled task)
  weekly_day   MON..SUN, weekly_time HH:MM (the weekly digest task)
  watch        which kinds of things the Brief shows (WATCH keys); a kind that is switched off is quiet
  approvers    adults whose linked phones may decide Inbox items (/ok, /no); empty = every adult

Hidden single items stay in action_state (Settings > Home Profile lists them with Restore). Changing the schedule re-registers
the two scheduled tasks when they are already registered on this PC; nothing else is touched.

CLI:  python data/agent_profile.py show
      python data/agent_profile.py set FIELD VALUE        (name, tone, brief_time, weekly_day, weekly_time,
                                                           watch_on KEY, watch_off KEY)
      python data/agent_profile.py approvers [NAME ...]   (no names = every adult)
"""
import argparse
import platform
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import config  # noqa: E402
import brand  # noqa: E402

TONES = {"brief": "Brief and plain", "warm": "Warm and a little more detail"}
DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
DAY_NAMES = dict(zip(DAYS, ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]))
WATCH = {"bills": "Bills, loans and tax dates", "renewals": "Renewals and things that expire",
         "checkups": "Checkups and appointments", "seasonal": "Seasonal home tasks", "school": "School, activities and events",
         "dates": "Birthdays, holidays and festivals", "money": "Money alerts (price rises, unusual spending)",
         "home": "Home: warranties, cars, shopping", "work": "Work hours and invoices"}
# Brief row kind -> watch key. A kind not listed here (and the backup / stopped-task warnings) is always shown.
KIND_WATCH = {"Bill": "bills", "Loan": "bills", "Tax": "bills", "Benefit": "bills", "Investment": "bills",
              "Renewal": "renewals", "ID": "renewals", "Subscription": "renewals", "Cancel": "renewals", "Deal": "renewals",
              "Appointment": "checkups", "Checkup": "checkups", "Health": "checkups",
              "Seasonal": "seasonal", "Event": "school", "School": "school", "Activity": "school", "Class": "school",
              "No school": "school", "Early dismissal": "school",
              "Birthday": "dates", "Festival": "dates", "Holiday": "dates", "Price change": "money", "Spike": "money",
              "Warranty": "home", "Car": "home", "Shopping": "home", "Work": "work", "Contract": "work"}
DEFAULTS = {"name": brand.AGENT, "tone": "brief", "brief_time": "07:00", "weekly_day": "SUN", "weekly_time": "18:00",
            "backup_day": "SUN", "backup_time": "09:00", "watch": list(WATCH), "approvers": []}
FIELDS = ("name", "tone", "brief_time", "weekly_day", "weekly_time", "backup_day", "backup_time", "watch_on", "watch_off")
SCHEDULE = ("brief_time", "weekly_day", "weekly_time", "backup_day", "backup_time")
JOB_OF = {"brief_time": "daily_digest", "weekly_day": "weekly_digest", "weekly_time": "weekly_digest",
          "backup_day": "weekly_backup", "backup_time": "weekly_backup"}  # schedule field -> the scheduled job it moves
TASK_NAMES = {"daily_digest": f"{brand.TASK_PREFIX} Daily Digest", "weekly_digest": f"{brand.TASK_PREFIX} Weekly Digest",
              "weekly_backup": f"{brand.TASK_PREFIX} Weekly Backup"}


# ------------------------------------------------------------------ checking values (each returns the clean value or raises ValueError)
def clean_name(v):
    s = " ".join(str(v or "").split())
    if not s:
        raise ValueError("Give the agent a name.")
    if len(s) > 40:
        raise ValueError("Keep the name to 40 characters.")
    if not re.fullmatch(r"[\w .'&-]+", s):
        raise ValueError("Use letters, numbers, spaces, apostrophes or hyphens in the name.")
    return s


def clean_time(v):
    """'6', '6:30', '06:30', '6pm', '6:30 pm', '18:00' -> 'HH:MM'."""
    s = str(v or "").strip().lower().replace(".", ":").replace(" ", "")
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", s)
    if not m:
        raise ValueError("Give a time such as 7:00 or 6:30 pm.")
    h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap:
        if not 1 <= h <= 12:
            raise ValueError("Give a time such as 7:00 or 6:30 pm.")
        h = h % 12 + (12 if ap == "pm" else 0)
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        raise ValueError("Give a time such as 7:00 or 6:30 pm.")
    return f"{h:02d}:{mi:02d}"


def clean_day(v):
    s = str(v or "").strip().upper()[:3]
    if s not in DAYS:
        raise ValueError("Give a day of the week, such as Sunday.")
    return s


def clean_tone(v):
    s = str(v or "").strip().lower()
    if s not in TONES:
        raise ValueError("Tone is brief or warm.")
    return s


def clean_watch_key(v):
    s = str(v or "").strip().lower()
    if s not in WATCH:
        raise ValueError(f"Watch is one of: {', '.join(WATCH)}.")
    return s


CLEAN = {"name": clean_name, "tone": clean_tone, "brief_time": clean_time, "weekly_day": clean_day, "weekly_time": clean_time,
         "backup_day": clean_day, "backup_time": clean_time, "watch_on": clean_watch_key, "watch_off": clean_watch_key}


# ------------------------------------------------------------------ reading
def get():
    """The profile with every field filled (defaults for anything missing or broken in family.json)."""
    raw = config.family().get("agent") or {}
    out = dict(DEFAULTS)
    for k in ("name", "tone") + SCHEDULE:
        try:
            out[k] = CLEAN[k](raw[k]) if raw.get(k) not in (None, "") else DEFAULTS[k]
        except ValueError:
            out[k] = DEFAULTS[k]
    w = raw.get("watch")
    out["watch"] = [k for k in WATCH if k in w] if isinstance(w, list) else list(WATCH)
    a = raw.get("approvers")
    out["approvers"] = [str(x) for x in a if str(x).strip()] if isinstance(a, list) else []
    return out


def name():
    return get()["name"]


def watched(kind, profile=None):
    """True when a Brief row of this kind should be shown."""
    key = KIND_WATCH.get(kind)
    return key is None or key in (profile or get())["watch"]


def may_approve(member, profile=None):
    """True when this member's linked phone may decide Inbox items (they must be an adult as well)."""
    ap = (profile or get())["approvers"]
    return not ap or str(member or "").lower() in {a.lower() for a in ap}


def tone_rule(profile=None):
    if (profile or get())["tone"] == "warm":
        return "Write warmly, in two to four sentences, with a little helpful detail."
    return "Keep replies short and plain: one or two sentences."


def schedule_text(profile=None):
    p = profile or get()
    return f"Daily brief at {p['brief_time']}; weekly digest {DAY_NAMES[p['weekly_day']]} at {p['weekly_time']}"


def schtasks_args(job, profile=None):
    """Windows schtasks schedule arguments for the daily brief, weekly digest and weekly backup from the profile; None for
    other jobs (they run at fixed intervals)."""
    p = profile or get()
    if job == "daily_digest":
        return ["/sc", "daily", "/st", p["brief_time"]]
    if job == "weekly_digest":
        return ["/sc", "weekly", "/d", p["weekly_day"], "/st", p["weekly_time"]]
    if job == "weekly_backup":
        return ["/sc", "weekly", "/d", p["backup_day"], "/st", p["backup_time"]]
    return None


def cron_line(job, profile=None):
    """cron schedule for the daily brief, weekly digest and weekly backup from the profile (macOS / Linux); None for
    other jobs."""
    p = profile or get()
    if job == "daily_digest":
        h, m = p["brief_time"].split(":")
        return f"{int(m)} {int(h)} * * *"
    if job in ("weekly_digest", "weekly_backup"):
        day, at = (p["weekly_day"], p["weekly_time"]) if job == "weekly_digest" else (p["backup_day"], p["backup_time"])
        h, m = at.split(":")
        return f"{int(m)} {int(h)} * * {(DAYS.index(day) + 1) % 7}"
    return None


def when_text(job, profile=None):
    """'Every day at 07:00', 'Sundays at 18:00'; None for the fixed-interval jobs."""
    p = profile or get()
    if job == "daily_digest":
        return f"Every day at {p['brief_time']}"
    if job in ("weekly_digest", "weekly_backup"):
        day, at = (p["weekly_day"], p["weekly_time"]) if job == "weekly_digest" else (p["backup_day"], p["backup_time"])
        return f"{DAY_NAMES[day]}s at {at}"
    return None


# ------------------------------------------------------------------ changing
def _save(profile):
    with config.family_edit() as cfg:
        cfg["agent"] = {k: profile[k] for k in DEFAULTS}


def set_field(field, value):
    """Change one field. -> (ok, plain message). Schedule changes also move the scheduled task when it is registered."""
    if field not in CLEAN:
        return False, "That is not something the agent profile has."
    try:
        v = CLEAN[field](value)
    except ValueError as e:
        return False, str(e)
    p = get()
    if field == "watch_on":
        p["watch"] = [k for k in WATCH if k in p["watch"] or k == v]
        msg = f"The Brief shows {WATCH[v].lower()} again."
    elif field == "watch_off":
        p["watch"] = [k for k in p["watch"] if k != v]
        msg = f"The Brief leaves out {WATCH[v].lower()} now."
    else:
        p[field] = v
        if field == "tone":
            msg = f"Tone set to: {TONES[v].lower()}."
        elif field == "weekly_day":
            msg = f"The weekly digest comes on {DAY_NAMES[v]} from now on."
        elif field == "backup_day":
            msg = f"The weekly backup runs on {DAY_NAMES[v]} from now on."
        else:
            msg = {"name": f"The agent is called {v} now.", "brief_time": f"The daily brief is made at {v} from now on.",
                   "weekly_time": f"The weekly digest comes at {v} from now on.",
                   "backup_time": f"The weekly backup runs at {v} from now on."}[field]
    _save(p)
    if field in SCHEDULE:
        moved = reschedule(JOB_OF[field], p)
        if moved is False:
            msg += " The scheduled task could not be moved; the health check in Settings shows it."
    return True, msg


def set_profile(new):
    """Save several fields at once (the Settings form). -> (ok, [problems] or [message])."""
    p, problems = get(), []
    for k in ("name", "tone") + SCHEDULE:
        if k in new:
            try:
                p[k] = CLEAN[k](new[k])
            except ValueError as e:
                problems.append(str(e))
    if "watch" in new:
        bad = [w for w in new["watch"] if w not in WATCH]
        if bad:
            problems.append(f"Unknown watch item: {', '.join(bad)}.")
        p["watch"] = [k for k in WATCH if k in new["watch"]]
    if "approvers" in new:
        adults = {m["name"].lower(): m["name"] for m in config.members() if m.get("role") == "adult" and m.get("name")}
        bad = [a for a in new["approvers"] if str(a).lower() not in adults]
        if bad:
            problems.append(f"Only adults in the household can approve: {', '.join(map(str, bad))}.")
        p["approvers"] = [adults[str(a).lower()] for a in new["approvers"] if str(a).lower() in adults]
    if problems:
        return False, problems
    old = get()
    _save(p)
    for job in dict.fromkeys(JOB_OF.values()):
        if any(old[f] != p[f] for f, j in JOB_OF.items() if j == job):
            reschedule(job, p)
    return True, ["Saved."]


def reschedule(job, profile=None, run=None):
    """Move a registered scheduled task to the profile's time. -> True moved, False failed, None not registered by this
    install (a task of the same name that runs another copy of the app is left alone; the next registration uses the
    profile). macOS / Linux: the cron line is rewritten when this install has one."""
    import task_register
    name, run = TASK_NAMES.get(job), task_register.live_runner(run)
    if not name or run is None:
        return None
    if platform.system() != "Windows":
        if task_register.job_state(job, run) != ("on", "crontab"):
            return None
        return task_register.set_job(job, True, run)[0]
    try:
        q = run(["schtasks", "/query", "/tn", name, "/xml"], capture_output=True, text=True, errors="replace")
        if q.returncode != 0 or str(ROOT / "tasks").lower() not in (getattr(q, "stdout", "") or "").lower():
            return None
        return task_register.create_windows(name, job, schtasks_args(job, profile), run, ROOT)[0]
    except OSError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(description="The agent profile (name, tone, brief schedule, watch list, approvers).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    s = sub.add_parser("set")
    s.add_argument("field", choices=FIELDS)
    s.add_argument("value")
    a = sub.add_parser("approvers")
    a.add_argument("names", nargs="*")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        p = get()
        print(f"Name: {p['name']}\nTone: {TONES[p['tone']]}\n{schedule_text(p)}")
        print("Watching: " + (", ".join(WATCH[k] for k in p["watch"]) or "nothing"))
        print("Approvers: " + (", ".join(p["approvers"]) or "every adult"))
        return 0
    if args.cmd == "set":
        ok, msg = set_field(args.field, args.value)
    else:
        ok, msgs = set_profile({"approvers": args.names})
        msg = " ".join(msgs)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
