"""What Chat says and does, with no web code: the answers that need no AI (what is due, what we owe,
spending trends, word search, "Log ..."), the assistant's ask and confirm, and one conversation kept as a plain dict.
Used by the web app (webapp/app.py).

Safety rules the web app relies on:
  * The conversation (lines shown, memory, the change waiting for a yes) lives on the server, in the person's session.
    The browser never sends a change to make: "Yes, save it" sends only the one-time `nonce` of the waiting card, and
    then exactly the changes the card showed run (admin_actions.confirm), once.
  * Adults only (the callers check; admin_actions and edit_actions check again).
  * At most ASK_PER_HOUR questions to the AI per conversation, so a stuck key or a script cannot run up the bill.
"""
import datetime as dt
import secrets
import sqlite3
import threading
import time

import admin_actions as aa
import db
import edit_actions as ea
import help_text
import llm
import money
import paths

HIST_MAX = 30          # lines kept per conversation (older ones drop off)
TEXT_MAX = 1000        # characters of one message
ASK_PER_HOUR = 40
_lock = threading.Lock()


def as_text(lines):
    """Chat lines as markdown: bullet lines stay together, everything else is its own paragraph."""
    out = []
    for line in lines:
        if out and line.startswith("- ") and out[-1].startswith("- "):
            out[-1] += "\n" + line
        else:
            out.append(line)
    return "\n\n".join(out)


def ai_ready():
    """True when typed questions can go to an AI that runs by itself (not Claude Code, not none)."""
    return llm.settings()["provider"] not in ("none", "claude_code", "")


def greeting(now=None):
    h = (now or dt.datetime.now()).hour
    return "Good morning" if h < 12 else "Good afternoon" if h < 18 else "Good evening"


def _ro():
    return db.connect(paths.DB, readonly=True)


# ------------------------------------------------------------------ answers that need no AI
def due_week_refs(user, today, items, days=7):
    import records
    end = today + dt.timedelta(days=days)
    con = _ro()
    try:
        return records.refs_for_items(con, [i for i in items if today <= i["date"] <= end], user)
    finally:
        con.close()


def due_week(today, days=7):
    import whats_on
    start, end, rows, _ = whats_on.build(today, days, google=False)
    if not rows:
        return f"Nothing is due in the next {days} days."
    lines = [f"Coming up, {start:%B %d} to {end:%B %d}:"]
    for d, kind, title, amt in rows[:15]:
        lines.append(f"- {d:%a %b %d}: {title}" + (f", {amt}" if amt else ""))
    if len(rows) > 15:
        lines.append(f"- and {len(rows) - 15} more on Today.")
    return as_text(lines)


def owe(today, days=30):
    end = today + dt.timedelta(days=days)
    con = _ro()
    try:
        rows = con.execute("SELECT name, amount, due_date FROM bills WHERE status IN ('due','overdue') AND due_date <= ? "
                           "ORDER BY due_date", (end.isoformat(),)).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        con.close()
    if not rows:
        return f"No bills are open for the next {days} days."
    total = sum(float(r[1] or 0) for r in rows)
    late = sum(1 for r in rows if str(r[2])[:10] < today.isoformat())
    lines = [f"{len(rows)} bill{'s' if len(rows) != 1 else ''} to pay by {end:%B %d}, {money.fmt(total)} in all"
             + (f" ({late} already late)." if late else ".")]
    for name, amount, due in rows[:10]:
        lines.append(f"- {name}: {money.fmt(amount) if amount else 'amount not known'}, "
                     f"due {dt.date.fromisoformat(str(due)[:10]):%B %d}")
    return as_text(lines)


def trend():
    """Month over month and against last year, from the statements, no AI (data/trends.py)."""
    import trends as T
    con = _ro()
    try:
        lines = T.lines(con)
    finally:
        con.close()
    if not lines:
        return "No statements are filed yet, so there is nothing to compare. Drop a bank or card statement in the Inbox."
    return as_text([T.for_markdown(ln) for ln in lines] + ["More in Money > Trends."])


def has_transactions():
    con = _ro()
    try:
        return con.execute("SELECT 1 FROM transactions LIMIT 1").fetchone() is not None
    except sqlite3.OperationalError:
        return False
    finally:
        con.close()


def _saved_hits(user, words, today, limit):
    try:
        import saved as S
        con = _ro()
    except (ImportError, sqlite3.Error):
        return []
    try:
        return S.search(con, viewer=user, words=words, today=today, limit=limit)
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def list_hits(user, words, today, limit=25):
    """Shared-list items (shopping, to-do, packing) whose text holds every word; adults also see adults-only lists."""
    ws = (words or "").lower().split()
    hits = []
    if not ws:
        return hits
    try:
        import lists as L
        con = _ro()
        try:
            for r in L.lists(con, (user or {}).get("role") == "adult"):
                for it in L.items(con, r["id"], today):
                    if all(w in it["text"].lower() for w in ws):
                        hits.append({"list": r["name"], "item": it["text"], "qty": it["qty"] or "",
                                     "status": "ticked" if it["status"] == "done" else "to do"})
        finally:
            con.close()
    except (ImportError, sqlite3.Error):
        pass
    return hits[:limit]


def archive_hits(user, words, limit=25):
    """Filed documents whose text matches (data/archive_search.py). Adults only; children never see the archive."""
    if (user or {}).get("role", "adult") != "adult":
        return []
    try:
        import archive_search as A
        con = _ro()
        try:
            return [{"date": h["date"], "type": h["type"], "vendor": h["vendor"], "document": h["title"],
                     "found": h["snippet"]} for h in A.search(con, words, limit, snippets=True)]
        finally:
            con.close()
    except (ImportError, sqlite3.Error):
        return []


def record_hits(user, words, limit=25):
    """Rows of the records (bills, payments, policies, people ...) whose words match, for this viewer (data/records.py);
    saved items and papers have their own lines in `search`."""
    if (user or {}).get("role", "adult") != "adult" or not (words or "").strip():
        return []
    try:
        import records
        con = _ro()
        try:
            rows = [h for h in records.search(con, words, user) if h["table"] not in ("saved_items", "documents")]  # own lines
            return rows[:limit]
        finally:
            con.close()
    except (ImportError, sqlite3.Error):
        return []


def search(user, today, words):
    words = (words or "").strip()
    lines = []
    for h in record_hits(user, words, limit=6):
        lines.append(f"- Record: {h['label']} ({h['kind']})")
    for r in _saved_hits(user, words, today, 6):
        lines.append(f"- Saved: {r.get('title') or ''}")
    for h in list_hits(user, words, today, limit=6):
        lines.append(f"- On {h['list']}: {h['item']} ({h['status']})")
    for h in archive_hits(user, words, limit=6):
        lines.append(f"- Paper: {h['document']} ({h['type']}, {h['date']})")
    return lines


def to_log(snap):
    """The one routine thing most worth logging today: an overdue checkup, else a seasonal task whose window is open."""
    for r in snap["rec"]:
        if r["status"] == "overdue":
            return {"type": "log", "source": "recurring", "id": r["id"], "name": r["name"], "who": r.get("who") or ""}
    for s in snap["seas"]:
        if s["state"] in ("now", "missed"):
            return {"type": "log", "source": "seasonal", "id": s["id"], "name": s["name"], "who": ""}
    return None


def chips(snap, ready, have_tx):
    """[(key, text)] (at most six) and the "Log ..." item behind the log chip, if any."""
    out = [("due", "What is due this week?"), ("owe", "What do we owe?")]
    lg = to_log(snap)
    if lg:
        out.append(("log", f"Log {lg['name'].lower()}"))
    if have_tx:
        out.append(("trend", "How is our spending going?"))
    out.append(("howto", "How do I ...?"))
    out.append(("ai", "How much did we spend last month?") if ready else ("connect", "Connect an AI"))
    return out[:6], lg


def describe_pending(pend, today):
    """The confirm card's lines for a waiting change."""
    if pend["type"] == "log":
        who = f" ({pend['who']})" if pend.get("who") and pend["who"].lower() not in ("home", "household") else ""
        return [f"{pend['name']}{who} done today, {today:%B %d}"]
    import assistant
    import assistant_voice as voice
    return [voice.describe(n, c, assistant.CATALOG[n][1]) for n, c in pend["writes"]]


# ------------------------------------------------------------------ one conversation (a plain dict in the session)
def new_state():
    return {"hist": [], "mem": [], "pend": None, "asks": []}


def say(state, who, text, refs=None):
    state["hist"].append({"who": who, "text": str(text), "refs": list(refs or [])[:6]})
    del state["hist"][:-HIST_MAX]


def _set_pending(state, pend):
    with _lock:
        state["pend"] = dict(pend, nonce=secrets.token_urlsafe(12)) if pend else None


def clear(state):
    with _lock:
        state.update(new_state())


def _ask_allowed(state, now=None):
    now = time.time() if now is None else now
    state["asks"] = [t for t in state["asks"] if now - t < 3600]
    if len(state["asks"]) >= ASK_PER_HOUR:
        return False
    state["asks"].append(now)
    return True


def ask(state, user, text):
    """Send the text to the assistant; its answer joins the conversation, and any change waits for a yes."""
    import assistant
    if not _ask_allowed(state):
        say(state, "assistant", f"That's {ASK_PER_HOUR} questions this hour. Please try again a little later.")
        return
    try:
        res = aa.ask(user, text, history=state["mem"])
    except Exception:  # noqa: BLE001 (provider down or a timeout: say so; the details go to the assistant's log)
        say(state, "assistant", "The AI could not answer right now. Please try again in a moment.")
        return
    shown = as_text(res["lines"]) or "I have nothing to add."
    say(state, "assistant", shown, res["refs"])
    state["mem"] = assistant.remember(state["mem"], text, res["answer"] or shown)
    _set_pending(state, {"type": "ask", "writes": [(n, dict(c)) for n, c in res["writes"]]} if res["needs_confirm"] else None)


HOWTO_EXAMPLES = ["How do I add a birthday?", "How do I mark a bill paid?", "How do I add a class?",
                  "How do I snooze a reminder?", "How do I connect an AI?"]


def help_ref(key):
    return {"help": key, "label": f"Help > {help_text.HELP[key]['title']}"}


def howto(state, text, ready):
    """"How do I ...?" answered from the app's help text, no AI. True when it answered (an AI gets the rest)."""
    if not help_text.is_howto(text):
        return False
    keys = help_text.howto(text)
    if keys:
        lines = help_text.as_chat(keys[0])
        if keys[1:]:
            lines.append("Also see: " + ", ".join(help_text.HELP[k]["title"] for k in keys[1:]) + ".")
        say(state, "assistant", as_text(lines), [help_ref(k) for k in keys])
        return True
    if ready:
        return False
    say(state, "assistant", "I have no help on that yet. Every help page is on the Help page; you can search it there.",
        [{"help": "", "label": "Help"}])
    return True


def message(state, user, today, text, ready):
    """One typed message: "How do I ..." from the help text, then the assistant when an AI is set, else a word
    search of the records."""
    text = (text or "").strip()[:TEXT_MAX]
    if not text:
        return
    say(state, "user", text)
    if howto(state, text, ready):
        return
    if ready:
        ask(state, user, text)
        return
    found = search(user, today, text)
    if found:
        say(state, "assistant", as_text(["Here is what I found in your records:"] + found),
            [{"ref": None, "section": None, "q": text[:80], "label": "search Records"}])
    else:
        say(state, "assistant", "I found nothing with those words. To ask in your own words, connect an AI in Settings.")


def chip(state, user, today, snap, key, ready):
    """A suggestion chip. Only the keys chips() offers right now are taken; the text comes from here, not the browser."""
    offered, lg = chips(snap, ready, has_transactions())
    text = dict(offered).get(key)
    if text is None or key == "connect":
        return False
    say(state, "user", text)
    if key == "due":
        say(state, "assistant", due_week(today), due_week_refs(user, today, snap["items"]))
    elif key == "owe":
        say(state, "assistant", owe(today))
    elif key == "trend":
        say(state, "assistant", trend())
    elif key == "howto":
        say(state, "assistant", as_text(["Ask me how to do something in the app and I answer from its help, for example:"]
                                         + [f"- {q}" for q in HOWTO_EXAMPLES]
                                         + ["Or press **?** at the bottom right of any page."]),
            [{"help": "", "label": "Help"}])
    elif key == "log":
        _set_pending(state, lg)
    elif key == "ai":
        ask(state, user, text)
    return True


def answer(state, user, nonce, yes):
    """Yes / No on the waiting card. Runs exactly the waiting change, once; a stale or wrong nonce changes nothing."""
    with _lock:
        pend = state.get("pend")
        if not pend or not secrets.compare_digest(str(pend.get("nonce", "")), str(nonce or "")):
            return False
        state["pend"] = None
    if not yes:
        say(state, "assistant", "Nothing was changed.")
        return True
    if pend["type"] == "log":
        fn = ea.recurring_done if pend["source"] == "recurring" else ea.seasonal_done
        ok, msg = fn(user, pend["id"])
        say(state, "assistant", msg if ok else f"I could not save that: {msg}")
        return True
    res = aa.confirm(user, pend["writes"])
    done = as_text(res["lines"]) or "Done."
    say(state, "assistant", done, res["refs"])
    if state["mem"]:
        state["mem"][-1]["a"] = (state["mem"][-1].get("a") or "") + " " + done
    return True
