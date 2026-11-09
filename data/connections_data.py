"""Settings > Connections in the web app: the AI provider and key, the Telegram phone bot, Google (Calendar read-only,
the calendar of its own, Gmail read-only). Every change goes through admin_actions (the same code the earlier screens
and the command line use: adults only, secrets write-only, every change in logs/admin_audit.log). No web code here.

Keys, tokens and the Google client file are taken only from a browser on this PC (`local=True`): on the home Wi-Fi the
web app speaks plain http, so a key typed on a phone could be read by someone else on that network. Google sign-ins
open a browser tab on this PC, so they are offered there only too.
"""
import json
import time

import admin_actions as aa
import brand
import config

LOCAL_ONLY = "Keys, tokens and Google sign-in can be set up only on this PC (not from a phone)."
CLIENT_MAX = 100_000
HORIZONS = (30, 60, 90, 180, 365)
REMINDERS = (0, 1, 2, 3, 7)
_CACHE = {}  # name -> (time, value): Telegram's and Google's answers, so a page view does not call them every time
TTL = {"tg": 120, "gcals": 300}


def _cached(name, fn):
    hit = _CACHE.get(name)
    if hit and time.time() - hit[0] < TTL[name]:
        return hit[1]
    val = fn()
    _CACHE[name] = (time.time(), val)
    return val


def forget(*names):
    for n in names or list(_CACHE):
        _CACHE.pop(n, None)


# ---- what the page shows -------------------------------------------------------------------------------------------
def ai():
    import llm
    s = aa.ai_status()
    providers = [(k, v[0], v[1], v[2]) for k, v in aa.PROVIDERS.items()]
    if s["provider"] not in aa.PROVIDERS:  # set outside this screen (python onboard.py): shown as it is, not as the first entry
        providers.insert(0, (s["provider"], f"{s['provider']} (set outside this screen)", False,
                             "Kept as it is when you press Save; pick another provider to change it."))
    return {"provider": s["provider"], "model": s["model"], "key_hint": s["key_hint"], "paid": s["paid_confirmed"],
            "photos": s["photos"], "providers": providers, "unattended": s["unattended"], "cli": s["cli"],
            "clis": aa.CLIS, "keyed": aa.KEYED, "test_now": aa.TEST_NOW, "can_test": s["provider"] in llm.TEXT,
            "defaults": {k: (llm.DEFAULTS.get(k, ("", ""))[0]) for k, *_ in providers}}


def telegram(check=True):
    """{token, hint, bot, problem, running, autostart, can_autostart, people}. `check` = ask Telegram for the bot's name
    (cached two minutes); without it, no network call."""
    import chat_telegram as ct
    tok = ct.token()
    out = {"token": bool(tok), "hint": aa._ends(tok), "bot": "", "problem": "", "running": aa.bot_running(),
           "people": [m["name"] for m in config.members() if m.get("role") != "pet" and m.get("name")]}
    if tok and check:
        s = _cached("tg", aa.telegram_status)
        out["bot"], out["problem"] = s.get("bot", ""), s.get("problem", "")
    try:
        import autostart
        out["can_autostart"] = autostart.supported()
        out["autostart"] = bool(autostart.status()) if out["can_autostart"] and tok else False
    except Exception:  # noqa: BLE001 (no scheduler here: the switch is simply not offered)
        out["can_autostart"], out["autostart"] = False, False
    return out


def google():
    """{client, signed_in, calendars: [(id, name, chosen)], problem, sync: {...}, gmail: {...}}."""
    import google_calendar as gc
    s = gc.status()
    out = {"client": s["client"], "signed_in": s["signed_in"], "calendars": [], "problem": "", "sync": None, "gmail": None}
    if not (s["client"] and s["signed_in"]):
        return out
    try:
        cals = _cached("gcals", gc.calendars)
    except Exception as e:  # noqa: BLE001 (an expired sign-in: the message is already plain)
        cals, out["problem"] = [], str(e)
    ids = [c["id"] for c in cals]
    chosen = [i for i in (s.get("calendars") or []) if i in ids] or [c["id"] for c in cals if c["primary"]][:1]
    out["calendars"] = [(c["id"], c["name"] + (" (main)" if c["primary"] else ""), c["id"] in chosen) for c in cals]
    import calendar_sync as cs
    cst = cs.status()
    cur = cst.get("settings") or {}
    out["sync"] = {"can_write": cst["can_write"], "horizon": cur.get("horizon", 90), "reminder_days": cur.get("reminder_days", 1),
                   "amounts": bool(cur.get("amounts")), "auto": bool(cur.get("auto")), "events": cst.get("synced_events", 0),
                   "last": cst.get("last_sync") or "", "calendar": bool(cst.get("calendar")), "name": brand.CALENDAR_NAME,
                   "horizons": HORIZONS, "reminders": REMINDERS}
    import google_gmail as gm
    g = gm.status()
    out["gmail"] = {"permission": g["permission"], "enabled": g["enabled"], "label": g["label"]}
    return out


# ---- changes -------------------------------------------------------------------------------------------------------
def ai_save(user, d, local):
    """-> (ok, message). After a good save of a provider that answers at once, one small test call."""
    if not local and (d.get("key") or "").strip():
        return False, LOCAL_ONLY
    ok, msg = aa.save_ai(user, d.get("provider", ""), d.get("model", ""), d.get("key", ""), d.get("paid") == "1",
                         d.get("consent") == "1", d.get("photos") == "1", d.get("unattended") == "1")
    if ok and d.get("provider") in aa.TEST_NOW:
        good, said = aa.test_ai()
        msg += (" Test call: " if good else " Test call failed: ") + str(said)[:300]
        ok = ok and good
    elif ok and d.get("provider") in aa.CLIS:  # a CLI call can take a minute: the person presses Test when ready
        msg += " Press Test the AI now to check it is signed in."
    return ok, msg


def ai_test(user):
    if (user or {}).get("role") != "adult":
        return False, "Only adults can do this."
    ok, msg = aa.test_ai()
    return ok, str(msg)[:300]


def telegram_act(user, op, d, local):
    if op == "token":
        if not local:
            return False, LOCAL_ONLY
        res = aa.save_telegram(user, d.get("token", ""))
        forget("tg")
        return res
    if op == "start":
        return aa.bot_start(user)
    if op == "stop":
        return aa.bot_stop(user)
    if op == "autostart":
        return aa.bot_autostart(user, d.get("on") == "1")
    if op == "code":
        ok, msg, _code = aa.pairing_code(user, d.get("who", ""))
        return ok, msg
    return False, "That cannot be done here."


def google_client(user, raw, local):
    if not local:
        return False, LOCAL_ONLY
    if len(raw) > CLIENT_MAX:
        return False, "That file is too large to be a Google client file."
    try:
        json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return False, "That is not the .json client file from Google Cloud."
    return aa.save_google_client(user, raw)


def google_act(user, op, d, local, ids=()):
    """Every Google button. Sign-ins open a browser tab on this PC and wait up to four minutes."""
    import webbrowser
    if op in ("sign_in", "allow_gmail", "allow_write") and not local:
        return False, LOCAL_ONLY
    if op == "sign_in":
        res = aa.google_sign_in(user, browser=webbrowser.open)
    elif op == "allow_gmail":
        res = aa.gmail_sign_in(user, browser=webbrowser.open)
    elif op == "allow_write":
        res = aa.calendar_write_sign_in(user, browser=webbrowser.open)
    elif op == "pick":
        known = {c[0] for c in google()["calendars"]}
        res = aa.google_pick(user, [i for i in ids if i in known])
    elif op == "gmail":
        res = aa.gmail_settings(user, d.get("enabled") == "1", d.get("label", ""))
    elif op == "gmail_now":
        res = aa.gmail_pull_now(user)
    elif op == "sync_settings":
        try:
            hz, rd = int(d.get("horizon", "")), int(d.get("reminder_days", ""))
        except ValueError:
            return False, "Pick how far ahead and the reminder from the lists."
        if hz not in HORIZONS or rd not in REMINDERS:
            return False, "Pick how far ahead and the reminder from the lists."
        res = aa.calendar_sync_settings(user, hz, rd, d.get("amounts") == "1", d.get("auto") == "1")
    elif op == "sync_apply":
        res = aa.calendar_sync_apply(user)
    elif op == "sync_remove":
        if d.get("sure") != "1":
            return False, f"Tick the box to confirm deleting the {brand.CALENDAR_NAME} calendar."
        res = aa.calendar_sync_remove(user)
    elif op == "disconnect":
        if d.get("sure") != "1":
            return False, "Tick the box to confirm disconnecting Google."
        res = aa.google_disconnect(user)
    else:
        return False, "That cannot be done here."
    forget("gcals")
    return res[0], res[1]


def sync_preview(user):
    """-> (ok, summary line, rows[{what, date, title}]); nothing is sent to Google."""
    return aa.calendar_sync_preview(user)


# ---- Bank sync (SimpleFIN) --------------------------------------------------------------------------------------
BANK_LOCAL_ONLY = "The SimpleFIN setup token can be pasted only on this PC (not from a phone)."


def bank():
    """{configured, accounts: [{id, name, last4, org, chosen}], last_ok, last_pull, error, last, stale}. No network call,
    never the access URL."""
    import bank_sync as bs
    s = bs.status()
    s["stale"] = s["stale_days"] is not None and s["stale_days"] > bs.STALE_DAYS
    return s


def mail():
    """Settings > Connections > Mail folder: the settings, whether an app password is saved (never the password)."""
    import mail_folder as mf
    return mf.status()


def mail_act(user, op, d, local):
    if op == "save":
        return aa.mail_folder_set(user, d.get("enabled") == "1", d.get("address", ""), d.get("host", ""),
                                  d.get("port", ""), d.get("folder", ""), d.get("password", ""), local)
    if op == "test":
        return aa.mail_folder_test(user)
    if op == "pull":
        return aa.mail_folder_pull_now(user)
    if op == "forget":
        if d.get("sure") != "1":
            return False, "Tick the box to confirm forgetting the mail folder."
        return aa.mail_folder_forget(user)
    return False, "That cannot be done here."


FEEDS_LOCAL_ONLY = "Add a calendar's address on this PC: it is a private link."


def feeds():
    """Settings > Connections > Other calendars: [{'id','name','host','fetched_at','error','n'}] (never the address)."""
    import calendar_feeds as cf
    cache = cf._load_cache()
    return [{"id": f["id"], "name": f["name"], "host": cf.host_of(f["url"]),
             "fetched_at": (cache.get(f["id"]) or {}).get("fetched_at", ""), "error": (cache.get(f["id"]) or {}).get("error", ""),
             "n": len((cache.get(f["id"]) or {}).get("events") or [])} for f in cf.feeds()]


def feeds_act(user, op, d, local):
    """add (this PC only) / refresh / remove a calendar feed. Adults; audited by name and host, never the address."""
    import calendar_feeds as cf
    if not aa._is_adult(user):
        return False, "Only adults can change the calendars."
    try:
        if op == "add":
            if not local:
                return False, FEEDS_LOCAL_ONLY
            fid, name = cf.add(d.get("name", ""), d.get("url", ""))
            feed = next(f for f in cf.feeds() if f["id"] == fid)
            aa._audit(user, "calendar_feed_add", f"id={fid} host={cf.host_of(feed['url'])}")
            ok, msg = cf.refresh(feed)
            return True, f"Added {name}: " + (msg if ok else f"it could not be read yet ({msg}).")
        if op == "refresh":
            feed = next((f for f in cf.feeds() if f["id"] == d.get("id")), None)
            if not feed:
                return False, "That calendar is already gone."
            ok, msg = cf.refresh(feed)
            return ok, f"{feed['name']}: {msg}."
        if op == "remove":
            name = cf.remove(d.get("id", ""))
            aa._audit(user, "calendar_feed_remove", f"id={d.get('id', '')}")
            return True, f"Removed {name}."
    except cf.FeedError as e:
        return False, str(e)[:1].upper() + str(e)[1:] + "."
    return False, "That cannot be done here."


def bank_act(user, op, d, local, ids=()):
    if op == "token":
        if not local:
            return False, BANK_LOCAL_ONLY
        return aa.bank_setup(user, d.get("token", ""))
    if op == "pick":
        known = {a["id"] for a in bank()["accounts"]}
        return aa.bank_pick(user, [i for i in ids if i in known])
    if op == "pull":
        return aa.bank_pull_now(user)
    if op == "forget":
        if d.get("sure") != "1":
            return False, "Tick the box to confirm forgetting the bank connection."
        return aa.bank_forget(user)
    return False, "That cannot be done here."
