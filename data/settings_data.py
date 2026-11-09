"""Settings for the web app, with no web code: what each group shows and the changes it offers, through the
same functions as the command line (admin_actions, agent_profile, health). Used by webapp/app.py.

  Household profile  how complete the profile is (meter + "Answer next", which puts the next question in the Inbox),
                     the full names as printed on papers (masked before anything goes to the AI), optional packs,
                     tax papers and how early each kind of expiry is reminded
  Agent              the agent profile (name, tone, brief and digest times, what the Brief watches, phone approvers),
                     sign-in PINs and the items hidden from the Brief (Restore)
  Connections        AI, phone bot and Google: one status line each, no network call (set-up: connections_data.py)
  Phones             paired phones (data/devices.py): add one with a one-time QR code (this PC only, app started
                     for phones), what each may carry, remove
  Data               where things are, Stop (the app runs with no window), the health check, the calendar file and
                     Advanced (back up, restore, updates: maintenance_data.py)

Every change is adults only; the routes check that too. PINs are never stored here, echoed back or logged.
"""
import json
import os
import sqlite3

import admin_actions as aa
import agent_profile as ap
import brand
import config
import dashboard_actions as da
import dates
import db
import paths

GROUPS = [("household", "Household profile"), ("agent", "Home Profile"), ("connections", "Connections"), ("phones", "Phones and walls"),
          ("data", "Data")]
# The pills: Phones is a part of Connections (a card there opens it) and Data is a lane on the Settings home; both still open
# by their own address.
PILLS = [("household", "Household profile"), ("agent", "Home Profile")]  # the chips on those two pages; the other groups have their own card on the home
HOME_LANES = PILLS + [("phones", "Phones and walls"), ("connections", "Connections"), ("data", "Data")]
DEFAULT = "home"  # the Settings home: profile meter, one lane per group, Needs a look
TIMES = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]


def group_of(value):
    return value if value in dict(GROUPS) else DEFAULT


def _ro():
    return db.connect(paths.DB, readonly=True)


def _rw():
    return db.connect(paths.DB, timeout=10)


# ---- Household profile ---------------------------------------------------------------------------------------------
def household(today):
    import profile_gaps
    try:
        con = _ro()
    except sqlite3.Error:
        return {"rows": [], "pct": 0, "next": None, "paper_names": ""}
    try:
        rows = profile_gaps.meter(con, today)
        pct = profile_gaps.overall(con, today)
    except sqlite3.Error:
        rows, pct = [], 0
    finally:
        con.close()
    nxt = next((r for r in rows if r["next"]), None)
    return {"rows": rows, "pct": pct, "next": nxt["label"] if nxt else None,
            "paper_names": "\n".join((config.family().get("privacy") or {}).get("paper_names") or [])}


def answer_next(user, today):
    """Put the next open profile question in the Inbox now. -> (ok, message)."""
    if (user or {}).get("role") != "adult":
        return False, "Only adults can change this."
    import profile_gaps
    con = _ro()
    try:
        nxt = next((r for r in profile_gaps.meter(con, today) if r["next"]), None)
    finally:
        con.close()
    if not nxt:
        return False, "Everything is filled in."
    con = _rw()
    try:
        pid = profile_gaps.ask_now(con, nxt["next"]["key"], today)
    finally:
        con.close()
    return (True, "The next question is at the top of the Inbox.") if pid else (False, "That question is already answered.")


def paper_names_set(user, text):
    return aa.paper_names_set(user, str(text or "")[:4000])


# ---- Agent ---------------------------------------------------------------------------------------------------------
def adults():
    return [m["name"] for m in config.members() if m.get("role") == "adult" and m.get("name")]


def agent():
    p = ap.get()
    times = sorted(set(TIMES) | {p["brief_time"], p["weekly_time"]})
    return {"p": p, "tones": list(ap.TONES.items()), "days": [(d, ap.DAY_NAMES[d]) for d in ap.DAYS],
            "watch": list(ap.WATCH.items()), "adults": adults(), "times": times, "schedule": ap.schedule_text(p)}


def agent_save(user, data, watch, approvers):
    """data = the form's single fields; watch / approvers = the ticked boxes. -> (ok, message)."""
    if (user or {}).get("role") != "adult":
        return False, "Only adults can change this."
    ok, msgs = ap.set_profile({"name": data.get("name", ""), "tone": data.get("tone", ""),
                               "brief_time": data.get("brief_time", ""), "weekly_day": data.get("weekly_day", ""),
                               "weekly_time": data.get("weekly_time", ""), "watch": watch, "approvers": approvers})
    if ok:
        aa._audit(user, "agent_profile", "saved")
        return True, "Saved."
    return False, " ".join(msgs)


def pins():
    people = aa.pin_people()
    return {"people": people}


def pin_set(user, who, pin, again, current):
    return aa.pin_set(user, who, pin, again, current)


def hidden(today):
    try:
        con = _ro()
    except sqlite3.Error:
        return []
    try:
        return da.handled_rows(con, today)
    except sqlite3.Error:
        return []
    finally:
        con.close()


def restore(user, key, today):
    """Show a hidden Brief item again; only a key from the hidden list is accepted. -> (ok, message)."""
    if (user or {}).get("role") != "adult":
        return False, "Only adults can change this."
    row = next((r for r in hidden(today) if r["key"] == key), None)
    if not row:
        return False, "That item is not hidden any more."
    da.restore(row["key"])
    return True, f"{row['title'] or 'The item'} shows on Today again."


# ---- optional packs, tax papers, reminder lead times -----------------------------------------------------------------
def packs():
    """[(key, title, note, on)] for Settings > Household profile > Optional features."""
    import config
    cur = config.family().get("packs") or {}
    return [(k, t, n, bool(cur.get(k, k in aa.PACK_DEFAULT_ON))) for k, (t, n) in aa.PACK_LABELS.items()]


def packs_save(user, on_keys):
    return aa.packs_set(user, {k: k in on_keys for k in aa.PACK_LABELS})


def traditions():
    """{'text', 'lookup', 'ai'} for Settings > Household profile > Traditions and holidays."""
    try:
        import traditions as T
        st = T.get()
        why = T.ai_ready()
    except Exception:  # noqa: BLE001 (the page must still render)
        return {"text": "", "lookup": False, "ai": "", "holidays": ""}
    try:
        import holidays as H
        r = H.rules(H.code()) or {}
        reg = H.region_of(r, H._region())  # noqa: SLF001
        hol = (r.get("title") or "") + (f" + {reg['name']}" if reg and r.get("title") else "")
    except Exception:  # noqa: BLE001
        hol = ""
    return {"text": "\n".join(st["traditions"]), "lookup": st["lookup"], "ai": why, "holidays": hol}


def traditions_save(user, d):
    if d.get("op") == "now":
        return aa.traditions_now(user)
    return aa.traditions_set(user, str(d.get("names", ""))[:600], d.get("lookup") in ("1", "on", "yes"))


def tax_names():
    import config
    cur = config.data_file("tax_prep.json") or {}
    return {"payers": ", ".join(cur.get("payers", [])), "state": ", ".join(cur.get("state_tax_keywords", [])),
            "tuition": ", ".join(cur.get("education_payee_patterns", []))}


def tax_save(user, d):
    return aa.tax_prep_set(user, str(d.get("payers", ""))[:2000], str(d.get("state", ""))[:2000], str(d.get("tuition", ""))[:2000])


def leads():
    """[{type, label, lead_days, default, custom}] for the reminder lead table."""
    try:
        import expiries
        return [{**r, "label": r["type"].replace("_", " ")} for r in expiries.leads()]
    except Exception:  # noqa: BLE001 (the page must still render)
        return []


def lead_save(user, typ, days, reset=False):
    import edit_actions as ea
    return ea.expiry_lead_set(user, typ, None if reset else str(days or "").strip())


def advanced(rows):
    """Read-only facts for Settings > Data > Advanced: where things are, the last run of each task, and the terminal
    command for each check that is not fine. Folders and commands appear only here."""
    import config
    cfg = config.family()
    facts = [("AI provider", ((cfg.get("ai") or {}).get("provider") or "claude_code")),
             ("Your folder (papers, settings, database)", str(paths.HOME) + ("" if paths.SEPARATE else
                                                                             "  (inside the app folder; python onboard.py home moves it out)")),
             ("App folder (code)", str(paths.ROOT)), ("Backups on this drive", str(paths.BACKUPS)),
             ("Google Drive folder", cfg.get("drive_path") or "not set up (python onboard.py add drive)"),
             ("Second backup location", cfg.get("backup_dest") or "none (python onboard.py add backup)")]
    try:
        import heartbeat as hb
        beats = [{"task": k, "result": "ok" if v["ok"] else "FAILED", "at": v["at"], "note": v["note"]}
                 for k, v in sorted(hb._load().items())]
    except Exception:  # noqa: BLE001
        beats = []
    try:
        import health as H
        full = {r["name"]: r for r in H.checks(None)}
    except Exception:  # noqa: BLE001
        full = {}
    cmds = [(r["name"], full[r["name"]]["fix"]) for r in rows
            if r["status"] != "ok" and r["name"] in full and str(full[r["name"]].get("fix", "")).startswith("python")]
    import autostart
    cron = "" if autostart.supported() else autostart.crontab_line("telegram")
    return {"facts": facts, "beats": beats, "cmds": cmds, "cron": cron}


# ---- Connections ---------------------------------------------------------------------------------------------------
def connections():
    """[(title, level, word, line)] without any network call."""
    out = []
    s = aa.ai_status()
    prov = s["provider"]
    name = aa.PROVIDERS.get(prov, (prov,))[0]
    if prov in ("none", ""):
        out.append(("AI provider", "info", "Not set up",
                    "Choose an AI to read your papers and answer questions. Everything else works without one."))
    elif prov in aa.KEYED and not s["key_hint"]:
        out.append(("AI provider", "warn", "Needs attention", f"{name} is chosen but no key is saved."))
    else:
        out.append(("AI provider", "ok", "Connected", name))
    try:
        import chat_telegram as ct
        tok = bool(ct.token())
    except Exception:  # noqa: BLE001 (no bot module setup yet: same as not set up)
        tok = False
    if tok:
        out.append(("Phone bot (Telegram)", "ok", "Set up", "A bot token is saved · " +
                    ("running" if aa.bot_running() else "stopped") + "."))
    else:
        out.append(("Phone bot (Telegram)", "info", "Not set up",
                    "Family members ask what is due and send papers from their phones."))
    try:
        import google_calendar as gc
        g = gc.status()
    except Exception:  # noqa: BLE001
        g = {"client": False, "signed_in": False}
    if g["client"] and g["signed_in"]:
        out.append(("Google (Calendar, Gmail)", "ok", "Connected", "Your Google Calendar shows on Calendar."))
    elif g["client"]:
        out.append(("Google (Calendar, Gmail)", "warn", "Needs attention", "The client file is saved; sign in to finish."))
    else:
        out.append(("Google (Calendar, Gmail)", "info", "Not set up",
                    "Advanced, optional: your Google Calendar next to the family's dates (read-only) and bills that "
                    "arrive by email. Phones do not need it: pair them in Settings > Phones."))
    try:
        import bank_sync
        bs = bank_sync.status() if bank_sync.configured() else None
    except Exception:  # noqa: BLE001 (same as not set up)
        bs = None
    if bs is None:
        out.append(("Bank sync (SimpleFIN)", "info", "Not set up",
                    "Optional, for power users: balances and new transactions pulled every morning through SimpleFIN "
                    "Bridge (a service the family pays about $1.50 a month). Statements in the Inbox work without it."))
    elif bs["error"] or (bs["stale_days"] is not None and bs["stale_days"] > bank_sync.STALE_DAYS):
        out.append(("Bank sync (SimpleFIN)", "warn", "Needs attention",
                    bs["error"] or f"The last good pull was {bs['stale_days']} days ago."))
    else:
        n = sum(1 for a in bs["accounts"] if a["chosen"])
        out.append(("Bank sync (SimpleFIN)", "ok", "Connected", f"{n} account(s) pulled every morning."
                    + (f" Last good pull {bs['last_ok'][:10]}." if bs["last_ok"] else " No pull yet.")))
    return out


# ---- Data ----------------------------------------------------------------------------------------------------------
def health(today):
    """[{status, name, note, here}] (the terminal command `fix` is left out: commands appear only under Advanced)."""
    try:
        import health as H
        return [{"status": r["status"], "name": r["name"], "note": r["note"], "here": r["here"]} for r in H.checks(today)]
    except Exception:  # noqa: BLE001 (the page must still render)
        return []


def calendar_file(today, horizon=365):
    """The calendar file's text (every due date for the next `horizon` days; names, amounts and last-4 digits only)."""
    import export_ics
    con = _ro()
    try:
        items = export_ics.collect(con, today, horizon)
    finally:
        con.close()
    return export_ics.build(items, today)


# ---- Phones ----------------------------------------------------------------------------------------------------------
def phones_lan():
    """Is the app open to phones right now (started with --lan), on which address and port, with which certificate."""
    import lan_tls
    port = os.environ.get("MITRAHOME_WEB_LAN_PORT", "")
    on = os.environ.get("MITRAHOME_WEB_LAN") == "1" and port.isdigit()
    fp = lan_tls.fingerprint()
    ip = lan_tls.lan_ip() if on else None
    url = f"https://{ip}:{port}/" if on and ip else ""
    url_qr = ""
    if url:  # the address only (no secret): a phone camera opens it in the browser, sign-in still needs a PIN
        try:
            import qr
            url_qr = qr.data_uri(url)
        except Exception:  # noqa: BLE001 (the page must still render)
            url_qr = ""
    remote = lan_tls.remote_ip() if on else None
    return {"on": on, "ip": ip, "port": int(port) if on else None, "fp": fp, "key": lan_tls.key_fingerprint() if fp else None,
            "fp_pretty": lan_tls.pretty(fp) if fp else "", "url": url, "url_qr": url_qr,
            "remote_url": f"https://{remote}:{port}/" if remote else ""}


def phones_mode():
    """Settings > Phones > Connection: the switch (config.phones_wanted), whether the running app matches it, and the
    phones' HTTPS port for the firewall check. `restart` = the app should start again to match the switch."""
    import auth
    import lan_tls
    lan = phones_lan()
    want, pins = config.phones_wanted(), bool(auth.users())
    port = lan["port"] or lan_tls.lan_port(int(os.environ.get("MITRAHOME_WEB_PORT") or 8601))
    return {"want": want, "on": lan["on"], "pins": pins, "port": port, "windows": os.name == "nt",
            "restart": (want and pins and not lan["on"]) or (not want and lan["on"])}


def phones_restart_lan():
    """The mode a restart from Settings > Phones starts in: for phones when the switch is on and an adult has a PIN."""
    m = phones_mode()
    return m["want"] and m["pins"]


WHERE = (("app", "The app", "code; replaced by every update"),
         ("home", "Household folder", "papers, settings and the database; never touched by an update"),
         ("archive", "Filed papers", "by year and kind, renamed YYYY-MM-DD_vendor_type"),
         ("inbox", "Waiting to be filed", ""),
         ("backups", "Backups", "the weekly backup and the copies made before updates"),
         ("exports", "Exports", "Settings > Data > Export all my data"),
         ("logs", "Logs", "what the app and its jobs did, never document text"))


def _where_path(key):
    import paths
    return {"app": paths.ROOT, "home": paths.HOME, "archive": paths.ARCHIVE, "inbox": paths.INBOX,
            "backups": paths.BACKUPS, "exports": paths.EXPORTS, "logs": paths.LOGS}.get(key)


def where():
    """Settings > Data > Where things are: the version, every folder and the database on this PC, and how phones reach
    it, so a family (or whoever helps them) finds their papers without asking."""
    import paths
    try:
        version = (paths.ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        version = ""
    rows = [{"key": k, "label": label, "note": note, "path": str(_where_path(k)), "exists": _where_path(k).exists()}
            for k, label, note in WHERE]
    lan = phones_lan()
    return {"version": version, "rows": rows, "db": str(paths.DB), "separate": paths.SEPARATE,
            "phones": lan["url"] if lan["on"] else "", "want": config.phones_wanted()}


def stop_note():
    """The note Stop Mitra Home leaves for the keep-alive task (launch.py stop_note: the same file, in the app folder), so
    this install's app stays stopped until a start by hand or the next restart of the PC."""
    return paths.ROOT / ".stopped"


def stop_app():
    """Settings > Data > Stop Mitra Home: leave the note, then the route closes the app. -> the sentence to show."""
    try:
        stop_note().parent.mkdir(parents=True, exist_ok=True)
        stop_note().write_text(dates.now_iso() + "\n", encoding="utf-8")
    except OSError:
        pass
    return (f"{brand.PRODUCT} has stopped. Start it again from the Start menu or the desktop icon. If it is set to "
            "start by itself, it also comes back the next time this PC restarts.")


def _reveal(p):
    """Explorer / Finder / the desktop's file manager on `p` (raises OSError when it cannot)."""
    import subprocess
    import sys as _sys
    if os.name == "nt":
        os.startfile(str(p))  # noqa: S606 (a folder of this install, from a fixed list)
    else:
        subprocess.Popen(["open" if _sys.platform == "darwin" else "xdg-open", str(p)])


def open_folder(user, local, key):
    """Open one of where()'s folders in Explorer / Finder on this PC. -> (ok, message). Adults, this PC only: the window
    opens on the PC's screen, never on a phone."""
    if (user or {}).get("role") != "adult":
        return False, "Only adults can open folders."
    if not local:
        return False, "Folders open on this PC's screen: use it from the PC."
    p = _where_path(str(key or ""))
    if p is None:
        return False, "Unknown folder."
    if not p.exists():
        return False, f"{p} does not exist yet: it is made the first time something is saved there."
    try:
        _reveal(p)
    except OSError as e:
        return False, f"The folder could not be opened ({type(e).__name__}): {p}"
    aa._audit(user, "open_folder", str(key))
    return True, f"Opened {p}"


QUIET_DAYS = 14
DEVICE_TABS = ("phones", "walls", "connection")


def seen_state(last_seen):
    """A device row's pill on Settings > Phones: 'new' (never seen), 'quiet' (not seen for QUIET_DAYS days) or 'ok'."""
    import datetime as dt
    import dates
    try:
        day = dt.date.fromisoformat(str(last_seen or "")[:10])
    except ValueError:
        return "new"
    return "quiet" if (dates.today() - day).days >= QUIET_DAYS else "ok"


def phones():
    """What Settings > Phones shows: paired phones, who may get one, the scope names, the connection."""
    import devices
    rows, removed = [], 0
    try:
        con = devices._con()
    except sqlite3.Error:
        con = None
    if con is not None:
        try:
            rows, removed = devices.listing(con)
        except sqlite3.OperationalError as e:
            if not db.missing(e):
                raise
        finally:
            con.close()
    for r in rows:
        r["state"] = "gone" if r.get("gone") else seen_state(r.get("last_seen"))
    return {"lan": phones_lan(), "rows": rows, "removed": removed, "people": devices.people(),
            "labels": {k: devices.label(k) for k in devices.SCOPES}, "minutes": devices.PAIR_MINUTES,
            "defaults": {r: [devices.label(k) for k in devices.defaults(r)] for r in devices.ROLES}}


PIN_FIRST = ("Please set up a PIN before you connect a phone: Settings > Home Profile > Sign-in PINs. Phones sign in with a PIN, "
             "so the app stays closed to the Wi-Fi until an adult has one.")


def phone_pair(user, local, who, name):
    """Start pairing a phone. -> (ok, message, pair) where pair = {'qr','member','name','until','fp'} is shown once.

    Adults only, from a browser on this PC only (the code is a key to the household for a few minutes), and only while
    the app is open to phones (the code names the address and the certificate)."""
    import brand
    import devices
    import qr
    if (user or {}).get("role") != "adult":
        return False, "Only adults can add a phone.", None
    if not local:
        return False, "Add a phone from this PC: the pairing code is shown only here.", None
    import auth
    if not auth.users():
        return False, PIN_FIRST, None
    lan = phones_lan()
    if not (lan["on"] and lan["ip"] and lan["fp"]):
        return False, (f"Phones cannot reach {brand.PRODUCT} yet: Settings > Phones > Connection > Restart for phones, "
                       "then come back here."), None
    try:
        con = _rw()
    except sqlite3.Error:
        return False, "The database could not be opened.", None
    try:
        secret, info = devices.pair_start(con, who, name, by=(user or {}).get("name") or "")
    except ValueError as e:
        return False, str(e), None
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return False, "The database is not up to date yet. Run the update in Settings > Data, then try again.", None
        raise
    finally:
        con.close()
    code = {"v": 1, "h": lan["ip"], "p": lan["port"], "fp": lan["fp"], "s": secret}
    if lan.get("key"):  # the phone app 0.14+ pins the key, so a renewed certificate keeps it paired
        code["k"] = lan["key"]
    payload = json.dumps(code, separators=(",", ":"))
    aa._audit(user, "phone_pair_code", f"{info['member']}: {info['name']}")
    return True, "", {"qr": qr.data_uri(payload), "member": info["member"], "name": info["name"],
                      "until": info["expires_at"][11:16], "fp": lan["fp_pretty"]}


def _phone_change(user, fn, *args):
    import devices
    if (user or {}).get("role") != "adult":
        return None, "Only adults can change paired phones."
    try:
        con = devices._con()
    except sqlite3.Error:
        return None, "The database could not be opened."
    try:
        return fn(con, *args), ""
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return None, "No phones are paired yet."
        raise
    finally:
        con.close()


def phone_revoke(user, device_id):
    import devices
    if not (str(device_id).isascii() and str(device_id).isdigit()):
        return False, "Pick a phone."
    done, msg = _phone_change(user, devices.revoke, int(device_id))
    if msg:
        return False, msg
    if not done:
        return False, "That phone was already removed."
    aa._audit(user, "phone_revoke", f"device {int(device_id)}")
    return True, "Removed. That phone cannot reach the household any more and wipes its copy the next time it calls."


def phone_scopes(user, device_id, keys):
    import devices
    if not (str(device_id).isascii() and str(device_id).isdigit()):
        return False, "Pick a phone."
    saved, msg = _phone_change(user, devices.set_scopes, int(device_id), list(keys or []))
    if msg:
        return False, msg
    if saved is None:
        return False, "That phone was removed."
    aa._audit(user, "phone_scopes", f"device {int(device_id)}: {','.join(saved) or 'nothing'}")
    return True, "Saved: " + (", ".join(devices.label(k) for k in saved) or "nothing") + "."


# ---- Mitra Wall (a tablet on the wall: wall.py, webapp/routes_wall.py) -------------------------------------------
def walls():
    """What Settings > Phones shows about walls: the paired ones and the address a tablet opens."""
    import wall
    rows = []
    try:
        con = wall._con()
    except sqlite3.Error:
        con = None
    if con is not None:
        try:
            rows = wall.listing(con)
        except sqlite3.OperationalError as e:
            if not db.missing(e):
                raise
        finally:
            con.close()
    lan = phones_lan()
    import wall_screen
    for r in rows:
        r["state"] = seen_state(r.get("last_seen"))
        r["own"] = bool(wall_screen.own_screen(r["id"]))
        r["screen"] = wall_screen.settings(wall_id=r["id"])
        r["face"] = wall_screen.FACE_NAMES[r["screen"]["clock"]]
    import wall_season
    return {"rows": rows, "max": wall.MAX_WALLS, "minutes": wall.PAIR_MINUTES, "screen": wall_screen.settings(),
            "seasonal": wall_season.enabled(), "season_looks": [v["name"] for v in wall_season.LOOKS.values()],
            "photos": wall_screen.photos(), "max_photos": wall_screen.MAX_PHOTOS,
            "zones": sorted(wall_screen.ZONES.items(), key=lambda z: z[1]), "themes": list(wall_screen.THEMES.items()),
            "led_styles": list(wall_screen.LED_STYLES.items()), "led_colours": wall_screen.LED_COLOURS,
            "url": f"https://{lan['ip']}:{lan['port']}/wall" if lan["on"] and lan["ip"] else ""}


def wall_pair(user, local, name, port=None):
    """Start pairing a wall. -> (ok, message, pair) where pair = {'code','qr','url','name','until','fp'} is shown once.

    Adults only, from this PC only. With the app open to phones the code's address is the Wi-Fi one (HTTPS); without,
    only a browser on this PC itself can open the wall (`port` = this app's own port)."""
    import qr
    import wall
    if (user or {}).get("role") != "adult":
        return False, "Only adults can add a wall.", None
    if not local:
        return False, "Add a wall from this PC: the code is shown only here.", None
    label = wall.clean_name(name)
    taken = {str(m.get("name") or "").casefold() for m in config.family().get("members") or []}
    taken |= {str(u.get("name") or "").casefold() for u in config.family().get("dashboard_users") or []}
    if label and label.casefold() in taken:
        return False, "Give the wall a name of its own (not a person's), for example Kitchen wall.", None
    import auth
    if not auth.users():
        return False, PIN_FIRST, None
    lan = phones_lan()
    if lan["on"] and lan["ip"]:
        base = f"https://{lan['ip']}:{lan['port']}"
    elif str(port or "").isdigit():
        base = f"http://127.0.0.1:{int(port)}"
    else:
        return False, ("Open the app to phones first (Settings > Phones > Connection > Restart for phones): the wall "
                       "reaches the PC over the Wi-Fi."), None
    try:
        con = wall._con()
    except sqlite3.Error:
        return False, "The database could not be opened.", None
    try:
        code, info = wall.pair_start(con, label or "", by=(user or {}).get("name") or "")
    except wall.WallError as e:
        return False, str(e), None
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return False, "The database is not up to date yet. Run the update in Settings > Data, then try again.", None
        raise
    finally:
        con.close()
    pretty = wall.pretty_code(code)
    url = f"{base}/wall?code={pretty}"
    app_qr = app_text = None
    if lan["on"] and lan["ip"] and lan["fp"]:  # the same code pairs the Mitra Home app in wall mode (pinned key)
        payload = {"v": 1, "h": lan["ip"], "p": lan["port"], "fp": lan["fp"], "w": pretty}
        if lan.get("key"):
            payload["k"] = lan["key"]
        app_text = json.dumps(payload, separators=(",", ":"))  # also shown as text: a tablet without a scanner pastes it
        app_qr = qr.data_uri(app_text)
    aa._audit(user, "wall_pair_code", info["name"])
    return True, "", {"code": pretty, "qr": qr.data_uri(url), "url": url, "name": info["name"], "app_qr": app_qr,
                      "app_text": app_text, "app_plain": f"{lan['ip']}:{lan['port']} {pretty} {lan['fp']}" if app_text else "",
                      "until": info["expires_at"][11:16], "fp": lan["fp_pretty"] if lan["on"] else "", "lan": lan["on"]}


def wall_revoke(user, wall_id):
    import wall
    if (user or {}).get("role") != "adult":
        return False, "Only adults can remove a wall."
    if not (str(wall_id).isascii() and str(wall_id).isdigit()):
        return False, "Pick a wall."
    try:
        con = wall._con()
    except sqlite3.Error:
        return False, "The database could not be opened."
    try:
        done = wall.revoke(con, int(wall_id))
    except sqlite3.OperationalError as e:
        if db.missing(e):
            return False, "No wall is paired yet."
        raise
    finally:
        con.close()
    if not done:
        return False, "That wall was already removed."
    aa._audit(user, "wall_revoke", f"wall {int(wall_id)}")
    return True, "Removed. That screen shows the pairing page at its next refresh."


# ---- the Settings home: one lane per group, the profile meter and what needs a look --------------------------------
LANES = {"household": ("Who lives here, names on papers, traditions and optional features.", "i-house", "g-over"),
         "agent": ("The agent's name and tone, brief times, sign-in PINs.", "i-agent", "g-cat"),
         "connections": ("AI helper, phone bot, Google and bank sync.", "i-plug", "g-flow"),
         "phones": ("Pair phones on the home Wi-Fi and choose what each carries.", "i-phone", "g-trend"),
         "data": ("Health check, data check, backups, restore, scheduled jobs and updates.", "i-data", "g-high")}
ATTENTION_MAX = 6


def _where_fix(here):
    """The page a health row's "Fix it in" text points at."""
    h = str(here or "").lower()
    for word, url in (("data check", "/settings/audit"), ("inbox", "/add"), ("connections", "/settings?group=connections"),
                      ("phones", "/settings?group=phones"), ("household", "/settings?group=household"),
                      ("agent", "/settings?group=agent"), ("records", "/records")):
        if word in h:
            return url
    return "/settings?group=data"


def overview(today, groups):
    """The Settings home: {"profile": household(), "lanes": [lane], "attention": [(tone, text, url)]}; `groups` = the
    (key, label) pairs shown in this view. lane = {"key", "name", "line", "icon", "g", "big", "big_label", "sub", "tone"}.
    No network call, no AI."""
    h = household(today)
    rows = health(today)
    warn = [r for r in rows if r["status"] == "warn"]
    conns = connections()
    on = [c for c in conns if c[1] == "ok"]
    ph = phones()
    paired = [d for d in ph["rows"] if not d.get("gone")]
    a = agent()["p"]
    pin = pins()
    with_pin = [x for x in pin["people"] if x.get("has_pin")]
    figures = {
        "household": (f"{h['pct']}%", "filled in", f"Next: {h['next']}" if h["next"] else "Everything is filled in",
                      "warn" if h["pct"] < 50 else ""),
        "agent": (a.get("name") or "Agent", "", f"Brief at {a.get('brief_time')}, "
                  f"{len(with_pin)} of {len(pin['people'])} with a PIN" if pin["people"] else f"Brief at {a.get('brief_time')}", ""),
        "connections": (f"{len(on)} of {len(conns)}", "connected", ", ".join(c[0].split(" (")[0] for c in on) or "Nothing connected yet", ""),
        "phones": (str(len(paired)), "phone" if len(paired) == 1 else "phones",
                   "Ready for phones on the Wi-Fi" if ph["lan"]["on"] else "Started for this PC only", ""),
        "data": (str(len(warn)) if warn else "OK", "to fix" if warn else "health check",
                 ", ".join(r["name"] for r in warn[:2]) + (" ..." if len(warn) > 2 else "") if warn else "All checks passed",
                 "bad" if warn else ""),
    }
    lanes = []
    for k, label in groups:
        line, icon, grad = LANES.get(k, ("", "i-data", "g-cat"))
        big, big_label, sub, tone = figures.get(k, ("", "", "", ""))
        lanes.append({"key": k, "name": label, "line": line, "icon": icon, "g": grad, "big": big, "big_label": big_label,
                      "sub": sub, "tone": tone})
    attention = [("bad", f"{r['name']}: {r['note']}", _where_fix(r["here"])) for r in warn]
    keys = dict(groups)
    if "connections" in keys and not any(c[0].startswith("AI") and c[1] == "ok" for c in conns):
        attention.append(("n", "No AI helper yet: papers are filed by hand and Chat answers from the records only",
                          "/settings?group=connections"))
    return {"profile": h, "lanes": lanes, "attention": attention[:ATTENTION_MAX], "more": max(0, len(attention) - ATTENTION_MAX)}
