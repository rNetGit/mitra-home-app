"""Chat core for the phone bots (Telegram, Discord): who is writing, what they may see, what the bot replies.

The bots themselves are thin adapters (later slices) that pass every message to `handle()` and send back what it
returns. Nothing here talks to the internet. No AI: replies are built from the database, like the Brief page.

  python data/chat_core.py invite NAME [--role adult|limited] [--platform telegram|discord] [--minutes 15]
  python data/chat_core.py links                      who is linked (platform, member, role, since)
  python data/chat_core.py revoke NAME|ID              unlink one member (all platforms) or one link id
  python data/chat_core.py log [--days 7]              what the bots answered or refused (never the message text)
  python data/chat_core.py alerts NAME on|off          daily private alert for that person (data/chat_alerts.py sends)
  /ask QUESTION (adults, private chat): read-only answer through data/assistant.py's catalog, daily cap; the last
    few questions are remembered in memory (not on disk) for 30 minutes so a follow-up works
  /find WORDS (adults, private chat): filed documents by title, date and type, never their text
  python data/chat_core.py try PLATFORM USER_ID TEXT   run one message through handle() on this PC (testing)

Pairing: an adult runs `invite NAME` here and gets an 8-digit code (shown once, stored as a hash, single use, expires
in 15 minutes). The family member sends `/start CODE` to the bot. Strangers who message the bot get no reply.

Roles: `adult` sees everything the Brief page shows. `limited` (children, teens) gets the limited dashboard's view:
their own school/activity/chore items, birthdays and the family's next two weeks, never money. The role defaults
from config/family.json (child -> limited); `--role` overrides. Money is only sent in a private chat, never in a
group or server channel, whoever asks.
"""
import argparse
import datetime as dt
import hashlib
import pathlib
import secrets
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402
import brand  # noqa: E402
import db as _db  # noqa: E402

DB = paths.DB
PLATFORMS = ("telegram", "discord")
ROLES = ("adult", "limited")
CODE_DIGITS = 8
MAX_BAD_CODES = 5  # per chat account per hour; then /start is refused for the rest of the hour
HORIZON = 7
MAX_LINES = 15
FIND_MAX = 8
ASK_PER_DAY = 20  # per person; config/family.json chat.ask_per_day overrides
ASK_MAX_CHARS = 500
MEMORY_IDLE = 1800  # seconds: /ask remembers the last turns per person (process memory only) until this much quiet
_MEMORY = {}
MAX_FILES_PER_DAY = 20  # per person, all chat apps together
MONEY_KINDS = ("Bill", "Renewal", "Subscription", "Benefit", "Cancel", "Investment", "Loan", "Budget", "Invoice", "Work")

HELP_ADULT = ("Commands: /due (overdue and the next 7 days), /week (same, family calendar only), /whoami, /unlink,\n"
              "/alerts on|off (a private message each morning when something is due),\n"
              "/find WORDS (filed documents by title, date and type),\n"
              "/ask QUESTION (a question about your records, answered by the family's AI; private chat only).\n"
              "/inbox (what is waiting for a decision), /ok ID [N] [DATE] (take choice N, default the first), /no ID.\n"
              "Bills and amounts are only sent in a private chat with me.\n"
              "Send me a photo or PDF of a bill, statement or receipt in a private chat and it goes to the inbox.")
HELP_LIMITED = ("Commands: /due (your things and the family's next two weeks), /week, /whoami, /unlink,\n"
                "/alerts on|off (a message each morning when one of your things is due).")
ALERT_DAYS = 3
INBOX_MAX = 8
# /no ID: the "no" choice of each kind of Inbox item (data/proposals.py OPTIONS)
NO_CHOICE = {"review": "dismiss", "recurring": "ignore", "statement": "dismiss", "price_rise": "dismiss", "undated": "not_sure",
             "renewal": "dismiss", "amazon": "dismiss", "bank_sync": "dismiss", "bank_dupe": "keep", "audit": "keep"}
PC_ONLY = ("days", "info_review", "update", "audit")  # Inbox sources decided on the PC (or the phone app) only, never listed or decided in a chat


def _now():
    return dt.datetime.now().replace(microsecond=0)


def _ts(t):
    return t.isoformat(timespec="seconds")


def _hash(code):
    return hashlib.sha256(code.encode("ascii")).hexdigest()


def _con(path=None):
    return _db.connect(path or DB, row=True)


def default_role(name, con=None):
    for m in config.members():
        if (m.get("name") or "").strip().lower() == name.strip().lower():
            return "limited" if m.get("role") in ("child", "limited") else "adult"
    if con is not None:  # added with members.py, not in family.json: trust the stored role
        try:
            r = con.execute("SELECT role FROM members WHERE lower(name)=?", (name.strip().lower(),)).fetchone()
        except sqlite3.OperationalError:
            r = None
        if r and r[0] == "adult":
            return "adult"
    return "limited"  # unknown or not an adult: the safe side


def canonical_member(con, name):
    """The member's name as stored, or None when nobody by that name is in the household."""
    want = " ".join(str(name).split()).lower()
    try:
        for (n,) in con.execute("SELECT name FROM members WHERE role != 'pet'"):
            if n.lower() == want:
                return n
    except sqlite3.OperationalError as e:
        if not _db.missing(e):
            raise
    for m in config.members():
        if (m.get("name") or "").strip().lower() == want and m.get("role") != "pet":
            return m["name"].strip()
    return None


def invite(con, name, role=None, platform=None, minutes=15, now=None):
    """A one-time pairing code for `name`. Returns (code, member, role, expires_at). Only the hash is stored."""
    member = canonical_member(con, name)
    if not member:
        raise ValueError(f"'{name}' is not a household member (see `python data/members.py list`; "
                         f"add one with `python data/members.py add {name} --role adult`)")
    role = role or default_role(member, con)
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if platform is not None and platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    if not 1 <= int(minutes) <= 60:
        raise ValueError("minutes must be 1..60")
    now = now or _now()
    code = "".join(secrets.choice("0123456789") for _ in range(CODE_DIGITS))
    exp = now + dt.timedelta(minutes=int(minutes))
    # an older unused code for the same person stops working
    con.execute("UPDATE chat_invites SET used_at=? WHERE member=? AND used_at IS NULL", (_ts(now), member))
    con.execute("INSERT INTO chat_invites(code_hash, member, role, platform, created_at, expires_at) VALUES (?,?,?,?,?,?)",
                (_hash(code), member, role, platform, _ts(now), _ts(exp)))
    con.commit()
    return code, member, role, _ts(exp)


def identify(con, platform, user_id):
    r = con.execute("SELECT id, member, role, alerts FROM chat_links WHERE platform=? AND platform_user_id=? AND revoked_at IS NULL",
                    (platform, str(user_id))).fetchone()
    return dict(r) if r else None


def _log(con, platform, user_id, member, command, outcome, now):
    con.execute("INSERT INTO chat_log(at, platform, platform_user_id, member, command, outcome) VALUES (?,?,?,?,?,?)",
                (_ts(now), platform, str(user_id), member, command[:20] or "?", outcome))
    con.commit()


def _bad_codes(con, platform, user_id, now):
    since = _ts(now - dt.timedelta(hours=1))
    return con.execute("SELECT COUNT(*) FROM chat_log WHERE platform=? AND platform_user_id=? AND at>=? "
                       "AND outcome IN ('bad_code','throttled')", (platform, str(user_id), since)).fetchone()[0]


def redeem(con, platform, user_id, code, now=None):
    """Link this chat account with the code's member. Returns the link dict, or None (wrong, used or expired code)."""
    now = now or _now()
    code = (code or "").strip()
    if not (len(code) == CODE_DIGITS and code.isdigit()):
        return None
    r = con.execute("SELECT id, member, role, platform, expires_at FROM chat_invites WHERE code_hash=? AND used_at IS NULL",
                    (_hash(code),)).fetchone()
    if not r or r["expires_at"] < _ts(now) or (r["platform"] and r["platform"] != platform):
        return None
    con.execute("UPDATE chat_invites SET used_at=? WHERE id=?", (_ts(now), r["id"]))
    con.execute("UPDATE chat_links SET revoked_at=? WHERE platform=? AND platform_user_id=? AND revoked_at IS NULL",
                (_ts(now), platform, str(user_id)))
    con.execute("INSERT INTO chat_links(platform, platform_user_id, member, role, created_at) VALUES (?,?,?,?,?)",
                (platform, str(user_id), r["member"], r["role"], _ts(now)))
    con.commit()
    return {"member": r["member"], "role": r["role"]}


def revoke(con, who, now=None):
    """Unlink by link id or member name. Returns how many links were revoked."""
    now = now or _now()
    if str(who).isdigit():
        cur = con.execute("UPDATE chat_links SET revoked_at=? WHERE id=? AND revoked_at IS NULL", (_ts(now), int(who)))
    else:
        cur = con.execute("UPDATE chat_links SET revoked_at=? WHERE member=? COLLATE NOCASE AND revoked_at IS NULL",
                          (_ts(now), str(who).strip()))
    con.commit()
    return cur.rowcount


def set_alerts(con, who, on):
    """Turn daily alerts on/off by link id or member name (all their links). Returns how many links changed."""
    v = 1 if on else 0
    if str(who).isdigit():
        cur = con.execute("UPDATE chat_links SET alerts=? WHERE id=? AND revoked_at IS NULL", (v, int(who)))
    else:
        cur = con.execute("UPDATE chat_links SET alerts=? WHERE member=? COLLATE NOCASE AND revoked_at IS NULL",
                          (v, str(who).strip()))
    con.commit()
    return cur.rowcount


def alert_text(con, who, today, path=None):
    """The morning alert for one person, or None when nothing is due soon (no message at all then).

    Always for a private chat. Adults: overdue items and the next ALERT_DAYS days, with amounts. Limited: only their own
    items and family entries in the next ALERT_DAYS days; never money."""
    import action_items
    import money
    end = today + dt.timedelta(days=ALERT_DAYS)
    if who["role"] == "limited":
        import limited_view
        d = limited_view.data(who["member"], today, db=path or DB)
        lines = []
        for r in d["mine"]:
            due = r.get("due_date")
            if due and due <= end.isoformat():
                lines.append(f"- {due}: {r['title']}")
        for r in d["week"]:
            if r["due_date"] <= end.isoformat() and r.get("member") != who["member"]:
                lines.append(f"- {r['due_date']}: {r['title']}")
        if not lines:
            return None
        return f"Good morning {who['member']}! Coming up:\n" + "\n".join(sorted(set(lines))[:MAX_LINES])
    items = [i for i in sorted(action_items.collect_items(con, today, ALERT_DAYS), key=lambda i: i["date"]) if i["date"] <= end]
    if not items:
        return None
    lines = []
    for i in items:
        line = f"- {action_items.when_label(i['date'], today)}: {i['kind']}: {i['title']}"
        if i.get("amount"):
            line += f" ({money.fmt(i['amount'])})"
        lines.append(line)
    over = sum(1 for i in items if i["date"] < today)
    head = f"Good morning {who['member']}. " + (f"{over} overdue, " if over else "") + f"{len(items) - over} due in the next {ALERT_DAYS} days:"
    return _clip([head] + lines, "")


def _is_money(item):
    return item.get("amount") is not None or item.get("kind") in MONEY_KINDS


def _adult_lines(con, today, private):
    import action_items
    import money
    items = sorted(action_items.collect_items(con, today, HORIZON), key=lambda i: i["date"])
    hidden = 0
    out = []
    for i in items:
        if _is_money(i) and not private:
            hidden += 1
            continue
        line = f"- {action_items.when_label(i['date'], today)}: {i['kind']}: {i['title']}"
        if private and i.get("amount"):
            line += f" ({money.fmt(i['amount'])})"
        out.append(line)
    return out, hidden


def _limited_lines(name, today, path):
    import limited_view
    d = limited_view.data(name, today, db=path)
    out = []
    for r in d["mine"]:
        out.append(f"- Mine: {r['title']}" + (f" (due {r['due_date']})" if r.get("due_date") else ""))
    for r in d["week"]:
        if r.get("member") == name and any(m["title"] == r["title"] for m in d["mine"]):
            continue
        out.append(f"- {r['due_date']}: {r['title']}" + (f" ({r['member']})" if r.get("member") else ""))
    for b in d["birthdays"]:
        out.append(f"- {b['date']}: {b['title']}")
    return out


def _clip(lines, empty):
    if not lines:
        return empty
    more = len(lines) - MAX_LINES
    return "\n".join(lines[:MAX_LINES]) + (f"\n... and {more} more (see the dashboard)" if more > 0 else "")


def _due(con, who, today, private, path, family_only=False):
    if who["role"] == "limited":
        return _clip(_limited_lines(who["member"], today, path), "Nothing coming up for you in the next two weeks.")
    if family_only:
        private = False
    lines, hidden = _adult_lines(con, today, private)
    txt = _clip(lines, "Nothing overdue or due in the next 7 days.")
    if hidden:
        txt += f"\n({hidden} money item{'s' if hidden != 1 else ''} not shown here; ask me in a private chat.)"
    return txt


import inbox_upload as _iu  # noqa: E402
SNIFF, NEVER = _iu.SNIFF, _iu.NEVER  # kept here: tests and callers read them from chat_core


def ask_limit():
    try:
        return int((config.family().get("chat") or {}).get("ask_per_day", ASK_PER_DAY))
    except (TypeError, ValueError):
        return ASK_PER_DAY


def _ask(con, who, rest, private, now, answer=None):
    """/ask QUESTION: adults in a private chat; read-only through the assistant's fixed catalog; capped per day.
    The question goes to the family's AI provider with identifiers masked (data/assistant.py); it is never logged."""
    if who["role"] != "adult":
        return "Questions to the AI are for adults."
    if not private:
        return "Ask me in a private chat."
    q = (rest[0] if rest else "").strip()
    if not q:
        return "Send /ask and your question, e.g. /ask how much did we spend on groceries in September?"
    if len(q) > ASK_MAX_CHARS:
        return f"Please keep the question under {ASK_MAX_CHARS} characters."
    used = con.execute("SELECT COUNT(*) FROM chat_log WHERE member=? AND command='ask' AND outcome='ok' AND at>=?",
                       (who["member"], _ts(now.replace(hour=0, minute=0, second=0)))).fetchone()[0]
    if used >= ask_limit():
        return f"That's today's {ask_limit()} questions. Ask again tomorrow, or use the dashboard."
    if answer is None:
        import assistant
        answer = assistant.handle
    lines = []
    mem = _MEMORY.get(who["member"])
    if mem and (now - mem[0]).total_seconds() > MEMORY_IDLE:
        mem = None
    try:
        answer(q, assume_yes=False, confirm=lambda _q: False, out=lines.append, read_only=True, history=mem[1] if mem else None)
    except Exception as e:  # provider down, timeout: say so, never the details of the request
        return f"The AI could not answer right now ({type(e).__name__})."
    text = "\n".join(x for x in lines if x).strip() or "I have no answer for that."
    import assistant
    _MEMORY[who["member"]] = (now, assistant.remember(mem[1] if mem else None, q, text))
    return text[:1500] + "\n(AI-assisted answer from your records; not professional advice.)"


def _find(con, who, words, private):
    """/find WORDS: filed documents by title, date and type only, never the text. Adults, private chats only."""
    if who["role"] != "adult":
        return "Searching the family's papers is for adults."
    if not private:
        return "Ask me /find in a private chat."
    if not words:
        return "Send /find and some words, e.g. /find water bill march."
    import archive_search
    hits = archive_search.search(con, " ".join(words), limit=FIND_MAX)
    if not hits:
        return "No filed document matches. New files are searchable after the next inbox check."
    return "\n".join([f"{len(hits)} filed document(s), best match first:"] +
                      [f"- {h['date'] or '(no date)'}  {h['type'] or 'document'}: {h['title']}" for h in hits]
                      + ["Open them on the family PC (type the words in Chat)."])


def _inbox(con, who, private):
    """/inbox: open Inbox items with numbered choices. Adults, private chats only (summaries can carry amounts)."""
    if who["role"] != "adult":
        return "The Inbox is for adults."
    if not private:
        return "Ask me /inbox in a private chat."
    import proposals
    # holiday and festival dates stay off chat services: their summary names the family's tradition
    items = [it for it in proposals.items(con) if it["source"] not in PC_ONLY]
    if not items:
        return "Nothing is waiting in the Inbox."
    lines = [f"{len(items)} waiting. Reply /ok ID for the first choice, /ok ID N for choice N, /no ID for no."]
    for it in items[:INBOX_MAX]:
        lines.append(f"#{it['id']} {it['summary']}")
        lines.append("   " + "   ".join(f"{n}) {lab}" for n, lab in enumerate(it["options"].values(), 1)))
    if len(items) > INBOX_MAX:
        lines.append(f"...and {len(items) - INBOX_MAX} more on the family PC (Inbox).")
    return "\n".join(lines)


def _decide(con, who, args, private, yes=True):
    """/ok ID [N] [YYYY-MM-DD] and /no ID: decide an Inbox item through proposals.decide (the same checked, logged
    path as the dashboard). Adults, private chats only. Filing a document needs the PC (type, sender and date)."""
    if who["role"] != "adult":
        return "Only adults can decide Inbox items."
    if not private:
        return "Decide Inbox items in a private chat with me."
    import agent_profile
    if not agent_profile.may_approve(who["member"]):
        return "Inbox items are decided by " + ", ".join(agent_profile.get()["approvers"]) + " (Settings > Home Profile on the family PC)."
    import proposals
    import validators
    word = "ok" if yes else "no"
    if not args or not args[0].lstrip("#").isdigit():
        return f"Send /{word} and the number from /inbox, e.g. /{word} 12."
    pid = int(args[0].lstrip("#"))
    item = proposals.get(con, pid)
    if not item or item["status"] not in proposals.LIVE:
        return "That one is already handled."
    if item["source"] in PC_ONLY:
        return "Decide that one in the Inbox on the family PC."
    opts = list(item["options"])
    day = None
    for a in args[1:]:
        try:
            day = validators.iso_date(a)
        except ValueError:
            pass
    if yes:
        nums = [a for a in args[1:] if a.isdigit()]
        n = int(nums[0]) if nums else 1
        if not 1 <= n <= len(opts):
            return f"Choose 1 to {len(opts)}."
        opt = opts[n - 1]
    else:
        opt = NO_CHOICE.get(item["source"])
        if opt not in opts:
            return "There is no 'no' for that one; use /ok ID N."
    answer = {}
    if (item["source"], opt) in proposals.NEEDS:
        if proposals.NEEDS[(item["source"], opt)] == ("date",) and day:
            answer["date"] = day
        elif proposals.NEEDS[(item["source"], opt)] == ("date",):
            return f"Send the date too, e.g. /ok {pid} {opts.index(opt) + 1} 2026-03-01."
        else:
            return "Filing a document needs the type, sender and date: do that one in the Inbox on the family PC."
    ok, msg = proposals.decide({"name": who["member"], "role": "adult"}, pid, opt, **answer)
    return msg


content_ok = _iu.content_ok


def files_today(con, member, now):
    return con.execute("SELECT COUNT(*) FROM chat_log WHERE command='upload' AND outcome='ok' AND member=? AND at>=?",
                       (member, _ts(now)[:10])).fetchone()[0]


def accept_file(platform, user_id, filename, data=None, size=None, private=True, db=None, now=None, fetch=None):
    """A file sent to the bot -> inbox/ (the dashboard upload's checks, plus the content must match the name).

    Only linked adults, only in a private chat, at most MAX_FILES_PER_DAY a day per person. Pass the bytes as `data`,
    or `fetch()` that downloads them: it is called only after every check that does not need the content, so refused
    files are never downloaded. Returns the reply, or None for silence (strangers). Captions are never read."""
    import inbox_upload
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    now = now or _now()
    con = _con(pathlib.Path(db) if db else DB)
    try:
        who = identify(con, platform, user_id)
        if not who:
            _log(con, platform, user_id, None, "upload", "unknown_user", now)
            return None

        def no(msg, outcome="denied"):
            _log(con, platform, user_id, who["member"], "upload", outcome, now)
            return msg
        if who["role"] != "adult":
            return no(f"Only grown-ups can send documents to {brand.PRODUCT}. Ask a parent to send it.")
        if not private:
            return no("Please send documents to me in a private chat, not here.")
        if files_today(con, who["member"], now) >= MAX_FILES_PER_DAY:
            return no(f"That's {MAX_FILES_PER_DAY} files today. Drop the rest into the inbox on the PC.", "throttled")
        fname = inbox_upload.clean_name(filename or "document")
        if pathlib.Path(fname).suffix not in inbox_upload.ALLOWED:
            return no("I can only take PDFs, photos and spreadsheets (bills, statements, receipts).")
        if size and size > inbox_upload.MAX_BYTES:
            return no(f"That file is too large (limit {inbox_upload.MAX_BYTES // (1024 * 1024)} MB).")
        if data is None and fetch:
            data = fetch()
        if not data:
            return no("That file arrived empty. Please send it again.")
        if not content_ok(fname, data):
            return no("That file does not look like the document its name says. Not saved.")
        ok, msg = inbox_upload.save_upload(f"{now:%Y-%m-%d_%H%M%S}_{platform}_{fname}", data)
        if not ok:
            return no(f"Not saved: {msg}")
        _log(con, platform, user_id, who["member"], "upload", "ok", now)
        return f"Got it: saved to the inbox as {msg}. It gets filed at the next inbox check."
    except Exception:
        _log(con, platform, user_id, None, "upload", "error", now)
        raise
    finally:
        con.close()


def handle(platform, user_id, text, private=True, today=None, db=None, now=None):
    """The bot's reply to one message, or None for no reply at all (strangers, empty messages).

    platform: 'telegram' | 'discord'; user_id: the platform's stable numeric id (never a display name);
    private: True only for a one-to-one chat with the bot (Telegram private chat, Discord DM)."""
    if platform not in PLATFORMS:
        raise ValueError(f"platform must be one of {PLATFORMS}")
    now = now or _now()
    today = today or now.date()
    path = pathlib.Path(db) if db else DB
    words = (text or "").strip().split()
    if not words:
        return None
    cmd = words[0].lower().split("@")[0].lstrip("/!")  # Telegram adds @botname in groups
    con = _con(path)
    try:
        who = identify(con, platform, user_id)
        if cmd == "start" and len(words) > 1:
            if not private:
                _log(con, platform, user_id, who and who["member"], "start", "denied", now)
                return "Send the code to me in a private chat, not here."
            if _bad_codes(con, platform, user_id, now) >= MAX_BAD_CODES:
                _log(con, platform, user_id, None, "start", "throttled", now)
                return None
            link = redeem(con, platform, user_id, words[1], now)
            if not link:
                _log(con, platform, user_id, None, "start", "bad_code", now)
                return "That code did not work. Ask a parent for a new one."
            _log(con, platform, user_id, link["member"], "start", "linked", now)
            return f"Hi {link['member']}, you're linked. " + (HELP_LIMITED if link["role"] == "limited" else HELP_ADULT)
        if not who:
            _log(con, platform, user_id, None, cmd or "?", "unknown_user", now)
            return None  # strangers get silence: nothing to probe
        help_txt = HELP_LIMITED if who["role"] == "limited" else HELP_ADULT
        if cmd in ("start", "help"):
            reply = help_txt
        elif cmd == "whoami":
            reply = f"You are {who['member']} ({'adult' if who['role'] == 'adult' else 'family member, no money info'})."
        elif cmd == "due":
            reply = _due(con, who, today, private, path)
        elif cmd == "week":
            reply = _due(con, who, today, private, path, family_only=True)
        elif cmd == "alerts":
            arg = words[1].lower() if len(words) > 1 else ""
            if arg in ("on", "off"):
                if not private and arg == "on":
                    reply = "Turn alerts on in a private chat with me; they always come as a private message."
                else:
                    set_alerts(con, who["id"], arg == "on")
                    reply = ("Alerts on: I'll message you here each morning when something is due." if arg == "on"
                             else "Alerts off.")
            else:
                reply = f"Alerts are {'on' if who.get('alerts') else 'off'}. Send /alerts on or /alerts off."
        elif cmd == "ask":
            reply = _ask(con, who, (text or "").strip().split(None, 1)[1:], private, now)
        elif cmd == "find":
            reply = _find(con, who, words[1:], private)
        elif cmd == "inbox":
            reply = _inbox(con, who, private)
        elif cmd in ("ok", "no"):
            reply = _decide(con, who, words[1:], private, yes=(cmd == "ok"))
        elif cmd == "unlink":
            revoke(con, who["id"], now)
            reply = "Unlinked. Ask a parent for a new code to link again."
        else:
            _log(con, platform, user_id, who["member"], cmd or "?", "denied", now)
            return "I don't know that one. " + help_txt
        _log(con, platform, user_id, who["member"], cmd, "ok", now)
        return reply
    except Exception:
        _log(con, platform, user_id, None, cmd or "?", "error", now)
        raise
    finally:
        con.close()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("invite")
    p.add_argument("name")
    p.add_argument("--role", choices=ROLES)
    p.add_argument("--platform", choices=PLATFORMS)
    p.add_argument("--minutes", type=int, default=15)
    sub.add_parser("links")
    p = sub.add_parser("revoke")
    p.add_argument("who")
    p = sub.add_parser("alerts")
    p.add_argument("who")
    p.add_argument("state", choices=("on", "off"))
    p = sub.add_parser("log")
    p.add_argument("--days", type=int, default=7)
    p = sub.add_parser("try")
    p.add_argument("platform", choices=PLATFORMS)
    p.add_argument("user_id")
    p.add_argument("text", nargs="+")
    p.add_argument("--group", action="store_true", help="as if sent in a group/channel")
    a = ap.parse_args(argv)
    if a.cmd == "try":
        r = handle(a.platform, a.user_id, " ".join(a.text), private=not a.group)
        print("(no reply)" if r is None else r)
        return 0
    con = _con()
    try:
        if a.cmd == "invite":
            try:
                code, member, role, exp = invite(con, a.name, a.role, a.platform, a.minutes)
            except ValueError as e:
                print(e, file=sys.stderr)
                return 2
            print(f"Code for {member} ({role}): {code}")
            print(f"Send /start {code} to the bot in a private chat before {exp[11:16]}. Works once.")
        elif a.cmd == "links":
            for r in con.execute("SELECT id, platform, member, role, alerts, created_at FROM chat_links WHERE revoked_at IS NULL ORDER BY member"):
                print(f"{r['id']:>4}  {r['platform']:<9} {r['member']:<16} {r['role']:<8} "
                      f"alerts {'on ' if r['alerts'] else 'off'}  since {r['created_at'][:10]}")
        elif a.cmd == "revoke":
            print(f"{revoke(con, a.who)} link(s) revoked")
        elif a.cmd == "alerts":
            n = set_alerts(con, a.who, a.state == "on")
            print(f"alerts {a.state} for {n} link(s)" + ("" if n else ": nobody linked by that name or id"))
            if not n:
                return 1
        elif a.cmd == "log":
            since = _ts(_now() - dt.timedelta(days=a.days))
            for r in con.execute("SELECT at, platform, member, command, outcome FROM chat_log WHERE at>=? ORDER BY at", (since,)):
                print(f"{r['at']}  {r['platform']:<9} {r['member'] or '(stranger)':<16} {r['command']:<8} {r['outcome']}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
