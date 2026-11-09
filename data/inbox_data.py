"""What the Inbox shows, with no web code: the open proposals as cards (plain choices, choices that need
answers), the files waiting to be read, and the two actions that are not a proposal choice (file them now, save an upload).
Used by the web app (webapp/app.py).

Every choice still goes through proposals.decide (adults only, fixed handler, logged); every upload goes through
inbox_upload.save_upload plus inbox_upload.content_ok, the same checks the phone bot uses.
"""
import pathlib
import subprocess
import sys

import ai_intake
import brand
import config
import db
import inbox_upload
import intake_progress
import paths
import proposals

# Categories a person works through, in page order: (key, title, one line, icon class, proposal sources). A source not
# named here lands in "other".
CATEGORIES = (
    ("files", "Files to look at", "Papers that could not be read or placed.", "i-file", ("review",)),
    ("money", "Money", "Repeating payments, price rises, statements, duplicates.", "i-coin",
     ("recurring", "price_rise", "statement", "amazon", "bank_dupe", "bank_sync", "audit")),
    ("renewals", "Renewals and documents", "Policies and papers that run out.", "i-shield", ("renewal", "info_review")),
    ("family", "Family and household", "Birthdays, dates and details to fill in.", "i-users", ("profile", "undated")),
    ("calendar", "Calendar", "Holidays and school days to add, changes made in Google.", "i-cal", ("days", "calendar_back")),
    ("app", brand.PRODUCT, "Updates for this app.", "i-app", ("update",)),
    ("other", "Other", "Everything else.", "i-dots", ()),
)
CAT_OF = {src: c[0] for c in CATEGORIES for src in c[4]}
VIEWS = ("all",) + tuple(c[0] for c in CATEGORIES)
PREVIEW = 3  # cards a category shows on the All view before "Show all"
MAX_FILES_IN_INBOX = 500  # refuse more uploads while this many files already wait: the folder must not grow without end
ROOT = paths.ROOT
# providers that can read and file what waits in the inbox right now (the rest wait for Claude Code or a person)
FILE_NOW = ("claude_cli", "codex_cli", "gemini_cli", "anthropic", "openai", "gemini", "openrouter", "ollama")
SKIP = {".gitkeep", "needs_review", "duplicates"}


def waiting_files():
    try:
        return [p for p in paths.INBOX.iterdir() if p.name not in SKIP and not p.name.startswith(".")]
    except OSError:
        return []


def provider():
    return ((config.family().get("ai") or {}).get("provider") or "claude_code").lower()


def waiting():
    return len(waiting_files())


def file_now_note():
    """(count waiting, can the button run, the sentence under it)."""
    n, prov = waiting(), provider()
    can = n > 0 and (prov in FILE_NOW or prov == "none")
    if not n:
        return 0, False, ""
    s = "s" if n != 1 else ""
    if prov in FILE_NOW:
        return n, can, f"{n} file{s} waiting to be read."
    if prov == "none":
        return n, can, (f"{n} file{s} waiting. School calendars, phone bills, PayPal and bank statements are read here; "
                        "choose an AI in Settings to have the rest filed for you.")
    if prov == "claude_code":
        return n, False, f"{n} file{s} waiting. They will be filed at the next inbox check."
    return n, False, f"{n} file{s} waiting. Choose an AI in Settings to have them filed for you."


def _intake_cmd():
    return [sys.executable, str(ROOT / "data" / "ai_intake.py")] + (["local"] if provider() == "none" else [])


RUN_LOG = "intake_web.log"  # logs/: what the background "File them now" run printed (names and outcomes, no contents)
RUN_LOG_MAX = 1024 * 1024
RUN_TIMEOUT_S = 900
STOPPED_UPDATE = "An update or restore is running. Press File them now again in a few minutes."
STOPPED_SLOW = "Reading took too long and was stopped. Press File them now to try again."
STOPPED_ERROR = "Filing stopped before this file. Press File them now to try again."


def _run_log():
    """The background run's output file (started afresh past RUN_LOG_MAX), or DEVNULL when logs/ cannot be written."""
    p = paths.LOGS / RUN_LOG
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        big = p.exists() and p.stat().st_size > RUN_LOG_MAX
        return open(p, "wb" if big else "ab")
    except OSError:
        return subprocess.DEVNULL


def file_now(wait=True):
    """Read and file what waits in the inbox (the same script the scheduled inbox check runs). Returns (ok, message).
    wait=False starts it in the background (the Inbox page follows it through intake_progress) and returns at once.
    However the run ends (another run holds the inbox, an update is running, a crash, the time limit), the progress
    panel is closed with the reason, so it never keeps spinning."""
    import joblock
    local = provider() == "none"  # no AI: only the papers this PC reads itself (ai_intake.py local)
    if provider() not in FILE_NOW and not local:
        return False, "Choose an AI in Settings first."
    if not wait:
        p = intake_progress.read()
        if (p and p["running"]) or joblock.is_held("intake"):
            return True, "Already reading. You can watch it below."
        names = sorted(f.name for f in waiting_files() if f.is_file())
        if not names:
            return True, "Nothing waiting."
        intake_progress.starting(names)
        out = _run_log()
        try:
            subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()), "file"], cwd=ROOT,
                             stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
        except OSError:
            intake_progress.close_open("Filing did not start. Press File them now again.")
            return False, "Filing did not start. Try again in a moment."
        finally:
            if out is not subprocess.DEVNULL:
                out.close()
        return True, f"Reading {len(names)} file{'' if len(names) == 1 else 's'}."
    import log
    ok, msg, reason = True, "Done. Anything I was not sure about is below.", STOPPED_ERROR
    try:
        r = subprocess.run(_intake_cmd(), cwd=ROOT, capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
        said = (r.stdout or "") + (r.stderr or "")
        if "another filing run is reading the inbox" in said:
            # that run owns the progress panel and finishes it; nothing of this one to close
            return True, "Another filing run is reading the inbox. Its files show below when it is done."
        if "an update or restore is running" in said:
            ok, msg, reason = False, STOPPED_UPDATE, STOPPED_UPDATE
        elif r.returncode not in (0, 1):  # 1 = some file was skipped (AI unavailable): a normal end
            log.get("intake").warning("filing run ended with code %s: %s", r.returncode, (r.stderr or "")[-600:])
            ok, msg = False, "Filing stopped with an error. Try again in a moment."
    except subprocess.TimeoutExpired:
        ok, msg, reason = False, STOPPED_SLOW, STOPPED_SLOW
    except (OSError, subprocess.SubprocessError) as e:
        log.get("intake").warning("filing run did not run: %s", e)
        ok, msg = False, "Filing did not finish. Try again in a moment."
    intake_progress.close_open(reason)  # no-op when the run finished normally
    if not ok:
        return ok, msg
    try:
        proposals.sync()
    except Exception:  # noqa: BLE001 (a failed look-for-questions must not hide that the files were read)
        pass
    return ok, msg


STATUS_WORDS = {"filed": "Filed", "review": "Needs you", "duplicate": "Already filed", "waiting": "Waits for an AI",
                "skipped": "Try again later", "stopped": "Not read yet"}
STEP_WORDS = {"queued": "In line", "checking": "Checking", "reading": "Reading", "sorting": "Sorting"}


def _plain_info(status, info):
    """The outcome line for a person: the filed place without folders, reasons without jargon."""
    info = str(info or "")
    if status == "filed":
        if "/" in info or "\\" in info:
            return "Filed as " + info.replace("\\", "/").rsplit("/", 1)[-1]
        return (info[0].upper() + info[1:] + ".") if info else "Filed."  # "statement: 21 transactions added ..."
    if status == "review":
        return "Not sure what this is. It is under Files to look at."
    if status == "duplicate":
        return "The same file is already filed. Nothing was added twice."
    if status == "waiting" and info.startswith("Add the account"):
        return info
    if status == "waiting":
        return "Choose an AI in Settings to have this one read."
    if status == "skipped":
        if "HTTP 402" in info:
            return ("Your AI account is out of credit, or this file costs more than what is left. It waits in the inbox: "
                    "add credit with your AI provider, then press File them now.")
        if "cap reached" in info:
            return "Today's AI limit is used up, so this one waits in the inbox. It is read tomorrow at the first inbox check."
        if info.startswith("database error"):
            return "The database was busy. It waits in the inbox: press File them now, or it is read at the next inbox check."
        return ("The AI could not be reached. It waits in the inbox: press File them now, or it is read at the next "
                "inbox check.")
    if status == "stopped":
        return info or STOPPED_ERROR
    return ""


def progress(now=None):
    """The Inbox progress panel: {"state": running | done | waiting | "", "title", "rows", "done", "total", "poll"}.
    rows = [{"name", "step" (0-4), "label", "tone" (work | ok | need | wait), "line"}]. running = a run is writing
    intake_progress now; done = one finished in the last few minutes; waiting = files sit in inbox/ with no run."""
    p = intake_progress.read(now)
    in_box = sorted(f.name for f in waiting_files() if f.is_file())
    rows, steps = [], intake_progress.STEPS
    if p and (p["running"] or p["recent"]):
        for f in p["files"]:
            st = f.get("status") or ""
            step = steps.index(f["step"]) if f.get("step") in steps else 0
            if f.get("step") == "done":
                tone = {"filed": "ok", "duplicate": "ok", "review": "need"}.get(st, "wait")
                rows.append({"name": f["name"], "step": 4, "label": STATUS_WORDS.get(st, "Done"), "tone": tone,
                             "line": _plain_info(st, f.get("info"))})
            else:
                rows.append({"name": f["name"], "step": step, "label": STEP_WORDS.get(f["step"], "In line"),
                             "tone": "work" if step else "wait", "line": ""})
        seen = {r["name"] for r in rows}
        rows += [{"name": n, "step": 0, "label": "In line", "tone": "wait", "line": "Added after this run started."}
                 for n in in_box if n not in seen]
        done = sum(1 for r in rows if r["step"] == 4)
        if p["running"]:
            now_on = next((r["name"] for r in rows if 0 < r["step"] < 4), "")
            title = f"Reading {min(done + 1, len(rows))} of {len(rows)}" + (f": {now_on}" if now_on else "")
            return {"state": "running", "title": title, "rows": rows, "done": done, "total": len(rows), "poll": True}
        need = sum(1 for r in rows if r["tone"] == "need")
        filed = sum(1 for r in rows if r["label"] == "Filed")
        wait = sum(1 for r in rows if r["label"] == STATUS_WORDS["waiting"])
        later = sum(1 for r in rows if r["step"] == 4 and r["tone"] == "wait")  # waiting, skipped, stopped: still in inbox/
        title = (f"Done: {filed} filed" + (f", {need} need{'s' if need == 1 else ''} you" if need else "")
                 + (f", {later} not read yet" if later else ""))
        if not filed and not need and later:
            title = (f"Done: {wait} still wait{'s' if wait == 1 else ''} for an AI" if wait == later
                     else f"Done: {later} not read yet")
        return {"state": "done", "title": title, "rows": rows, "done": done, "total": len(rows), "poll": False,
                "left": len(in_box)}
    if in_box:
        last = intake_progress.outcomes()  # why each one is still here, from the run that left it
        rows = [{"name": n, "step": 0, "label": STATUS_WORDS.get(last[n]["status"], "Waiting") if n in last else "Waiting",
                 "tone": "wait", "line": _plain_info(last[n]["status"], last[n].get("info")) if n in last else ""}
                for n in in_box]
        return {"state": "waiting", "title": "Waiting to be read", "rows": rows,
                "done": 0, "total": len(rows), "poll": False}
    return {"state": "", "title": "", "rows": [], "done": 0, "total": 0, "poll": False}


def accounts():
    """[{"id", "label"}] of the household's accounts, for the Import as statement choice (last four only)."""
    with db.open(paths.DB, readonly=True) as con:
        rows = con.execute("SELECT id, name, type, last4 FROM accounts ORDER BY name COLLATE NOCASE").fetchall()
    kind = {"credit": "card"}
    return [{"id": i, "label": f"{n} ({kind.get(t, t)}{', ending ' + l4 if l4 else ''})"} for i, n, t, l4 in rows]


def category_of(source):
    return CAT_OF.get(source, "other")


def cards(view="all"):
    """(counts, items) for one view (all, or one category key). counts = {"all": n, <category>: n}. Each item gets
    `category`, `plain` and `needs` as [(option, label)] and `form` = the needs form kind ('file' | 'birthday' | 'date')
    for its first option that needs answers."""
    with db.open(paths.DB, readonly=True) as con:
        items = proposals.items(con)
    counts = {"all": len(items)}
    for it in items:
        it["category"] = category_of(it["source"])
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    if view != "all":
        items = [it for it in items if it["category"] == view]
    for it in items:
        opts = list(it["options"].items())
        it["needs"] = [(o, lab) for o, lab in opts if (it["source"], o) in proposals.NEEDS]
        it["plain"] = [(o, lab) for o, lab in opts if (it["source"], o) not in proposals.NEEDS]
        it["form"] = {"review": "file", "profile": "birthday"}.get(it["source"], "date") if it["needs"] else ""
        it["forms"] = [(o, lab, FORM_OF.get((it["source"], o)) or it["form"]) for o, lab in it["needs"]]
        it["forms"].sort(key=lambda x: {"job": 0, "account": 0, "statement": 1}.get(x[2], 2))  # the fixes before File it by hand
    return counts, items


FORM_OF = {("review", "account"): "account", ("review", "statement"): "statement", ("review", "job"): "job"}  # options whose form is not the source's usual one


GROUP_AT = 4  # a source with this many open cards folds into one heading (one wall of near-identical cards is no help)
GROUP_TITLES = {"recurring": "Payments that repeat: track as a bill?", "undated": "Things with no date yet",
                "review": "Files to look at", "profile": "Questions about your household", "statement": "Statements not seen",
                "price_rise": "Prices that went up", "renewal": "Renewals coming up", "amazon": "Amazon orders to check",
                "bank_dupe": "Possible duplicates from bank sync", "audit": "Found by the data check", "days": "Holidays and school days to add",
                "calendar_back": "Changed in Google Calendar"}


def groups(items):
    """[{"source", "title", "cards", "fold"}] in the order the sources first appear; fold = collapsed under a heading."""
    out, by = [], {}
    for it in items:
        g = by.get(it["source"])
        if g is None:
            g = by[it["source"]] = {"source": it["source"], "title": GROUP_TITLES.get(it["source"], it["source"].replace("_", " ").capitalize()),
                                    "cards": []}
            out.append(g)
        g["cards"].append(it)
    for g in out:
        g["fold"] = len(g["cards"]) >= GROUP_AT
    return out


def sections(items, view="all"):
    """[{"key", "title", "line", "icon", "n", "cards", "groups", "more"}] for the categories that have cards, in page
    order. On the All view each shows its first PREVIEW cards (more = how many are left for its own view); on a category
    view `groups` folds a crowd of one source as before."""
    out = []
    for key, title, line, icon, _ in CATEGORIES:
        mine = [it for it in items if it["category"] == key]
        if not mine:
            continue
        shown = mine[:PREVIEW] if view == "all" else mine
        out.append({"key": key, "title": title, "line": line, "icon": icon, "n": len(mine), "cards": shown,
                    "groups": groups(shown) if view != "all" else [{"source": "", "title": "", "cards": shown, "fold": False}],
                    "more": len(mine) - len(shown)})
    return out


def answer_for(item_source, option, data):
    """The fields a person may send for (source, option): only those proposals.NEEDS names, plus the optional extras."""
    keep = {("review", "file"): ("type", "vendor", "date", "amount", "due"), ("undated", "date"): ("date", "provider"),
            ("profile", "birthday"): ("date",), ("review", "account"): ("name", "type", "last4"),
            ("review", "statement"): ("account", "read_as", "force"), ("review", "job"): ("contract", "phrase")}.get((item_source, option), ())
    out = {k: str(data.get(k, ""))[:80].strip() for k in keep}
    if option == "file" and "type" in out and out["type"] not in ai_intake.CATEGORY:
        out["type"] = ""
    if "amount" in out:
        try:
            amt = float(out["amount"].replace(",", "")) if out["amount"] else 0.0
        except ValueError:
            amt = 0.0
        out["amount"] = amt if 0 < amt < 1e9 else None
    for k in ("due", "provider"):
        if k in out and not out[k]:
            out[k] = None
    return out


def decide(user, pid, option, data):
    """(ok, message) for one choice on one card."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False, "That item is no longer on the list."
    with db.open(paths.DB, readonly=True) as con:
        p = proposals.get(con, pid)
    if p is None:
        return False, "That item is no longer on the list."
    ok, msg = proposals.decide(user, pid, option, **answer_for(p["source"], option, data))
    if ok and p["source"] == "review" and option in READ_AGAIN:
        msg = f"{msg} {_read_again()}"
    return ok, msg


READ_AGAIN = ("retry", "account")  # choices that put a file back in the inbox: reading starts at once when it can


def _read_again():
    """Start a filing run for what is back in the inbox, or say when it will be read."""
    if provider() in FILE_NOW or provider() == "none":
        ok, msg = file_now(wait=False)
        return "Reading it now; watch it above." if ok and msg.startswith("Reading") else msg
    return file_now_note()[2]


def retry_all(user):
    """(ok, message): "Reprocess" on every file waiting for a person, then one filing run for all of them."""
    with db.open(paths.DB, readonly=True) as con:
        waiting_items = [it for it in proposals.items(con) if it["source"] == "review"]
    if not waiting_items:
        return True, "Nothing is waiting for you."
    back, trouble = 0, []
    for it in waiting_items:
        ok, msg = proposals.decide(user, it["id"], "retry")
        if ok:
            back += 1
        else:
            trouble.append(msg)
    if not back:
        return False, trouble[0] if trouble else "Nothing could go back to the inbox."
    s = "" if back == 1 else "s"
    tail = f" {len(trouble)} could not: {trouble[0]}" if trouble else ""
    return True, f"{back} file{s} back in the inbox. {_read_again()}{tail}"


def save_file(name, data):
    """(ok, message) for one uploaded file: type, size, content-matches-name, folder not full."""
    fname = inbox_upload.clean_name(name or "document")
    if waiting() >= MAX_FILES_IN_INBOX:
        return False, "The inbox is full. File what is waiting first."
    if not inbox_upload.content_ok(fname, data or b""):
        return False, "That file does not look like the document its name says. Not saved."
    return inbox_upload.save_upload(fname, data)


def main(argv=None):
    """`python data/inbox_data.py file`: what the Inbox's background "File them now" runs (intake, then the questions)."""
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] != ["file"]:
        print("usage: inbox_data.py file")
        return 2
    try:
        ok, msg = file_now(wait=True)
    except Exception:  # noqa: BLE001 (whatever broke, the page must not keep spinning; the traceback goes to the log)
        intake_progress.close_open(STOPPED_ERROR)
        raise
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
