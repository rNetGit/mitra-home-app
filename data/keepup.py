"""Keep up: the small card on Today (adults) that says what the house needs to stay current, with one action each.

  python data/keepup.py            print the rows for today

Families on a laptop open the PC now and then; nothing tells them the numbers are behind. The card gathers what was
only in Settings or in logs:
  * bank sync (SimpleFIN): the last good pull, the last error or a bank's "needs attention" note, and Sync now
  * accounts that went quiet: lines in 2 of the 3 months before this one, then none for SYNC_QUIET_DAYS (a synced
    account) or STATEMENT_QUIET_DAYS (one missed monthly statement): "Add statement" / "Check sync"
  * scheduled jobs: never set up, last run failed, or long ago (heartbeat.stale); jobs that evidently run (a
    heartbeat within EVIDENCE_DAYS) count as set up even when the flag in config/family.json was never written
  * Inbox cards waiting for an answer (open proposals; files still to be read are the Add badge's business)

Every row: {"key", "tone": ok | warn, "text", "action", "href", "op"}; op "sync" is the Sync now button (POST
/today/act op=sync -> admin_actions.bank_pull_now). Nothing here writes; a failing part is left out, never the page.
"""
import datetime as dt
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402
import db  # noqa: E402

SYNC_QUIET_DAYS = 10        # a bank-synced account with no new line for this long: the connection is likely broken
STATEMENT_QUIET_DAYS = 40   # a statement-fed account: one monthly statement not dropped in yet
ACTIVE_MONTHS = 2           # of the 3 calendar months before this one
EVIDENCE_DAYS = 9           # a heartbeat this recent = the jobs run, flag or no flag
SLOW_TYPES = ("savings", "investment", "loan")   # accounts with few lines a month: listed after checking and cards
SETTINGS_DATA = "/settings?group=data"
SETTINGS_BANK = "/settings?group=connections#conn-bank"


def _row(key, tone, text, action="", href="", op=""):
    return {"key": key, "tone": tone, "text": text, "action": action, "href": href, "op": op}


def _day(iso, today):
    d = dt.date.fromisoformat(iso[:10])
    days = (today - d).days
    return "today" if days == 0 else "yesterday" if days == 1 else f"{d:%b} {d.day}"


def bank_row(today):
    """The bank-sync row, or None when the family has no bank sync."""
    import bank_sync
    if not bank_sync.configured():
        return None
    st = bank_sync.status(today)
    if st["stale_days"] is None:
        text = "Bank sync: no pull has worked yet" + (f" ({st['error']})" if st["error"] else "")
        return _row("bank", "warn", text, "Settings", SETTINGS_BANK, op="syncall")
    last = st.get("last") or {}
    notes = [w for w in (last.get("warnings") or []) if w]
    if st["error"]:
        return _row("bank", "warn", f"Bank sync: the last pull failed ({st['error']}); last good one {_day(st['last_ok'], today)}",
                    "Settings", SETTINGS_BANK, op="syncall")
    if st["stale_days"] > bank_sync.STALE_DAYS:
        return _row("bank", "warn", f"Bank sync: last good pull {st['stale_days']} days ago", "Settings", SETTINGS_BANK, op="syncall")
    n = last.get("inserted")
    text = f"Bank sync: pulled {_day(st['last_ok'], today)}" + (f", {n} new" if n is not None else "")
    if notes:
        return _row("bank", "warn", text + ". " + notes[0].rstrip(".") + ": sign in again at SimpleFIN Bridge",
                    "Settings", SETTINGS_BANK, op="syncall")
    return _row("bank", "ok", text, "", "", op="syncall")


def sync_row(today, has_bank_row):
    """While a Sync runs: its step. For RECENT_MINUTES after: what it did. With no bank row, a Sync now button when the
    Drive inbox or a mail folder is set up. None otherwise."""
    import sync_all
    s = sync_all.recent()
    if s and s.get("running"):
        return _row("sync", "ok", f"Syncing: {s.get('step') or 'starting'}...")
    if s:
        text = "Sync " + ("done" if s.get("ok") else "finished with problems") + ": " + "; ".join(s.get("lines") or [])
        return _row("sync", "ok" if s.get("ok") else "warn", text[:300], op="" if has_bank_row else "syncall")
    if not has_bank_row and sync_all.steps():
        return _row("sync", "ok", "Pull the Drive inbox and the mail folder now", op="syncall")
    return None


def _synced_ids():
    """accounts.id of the accounts the family ticked for bank sync (config/bank_sync.json), or an empty set."""
    try:
        import bank_sync
        accts = (bank_sync.state() or {}).get("accounts") or {}
        return {a.get("account_id") for a in accts.values() if a.get("chosen") and a.get("account_id") is not None}
    except Exception:  # noqa: BLE001
        return set()


def quiet_accounts(con, today, synced=None):
    """[{"id", "name", "last4", "newest", "days", "synced"}] accounts active in ACTIVE_MONTHS of the 3 months before
    this one whose newest line is older than the threshold for their kind, oldest gap first."""
    synced = _synced_ids() if synced is None else synced
    m0 = today.replace(day=1)
    m3 = m0
    for _ in range(3):
        m3 = (m3 - dt.timedelta(days=1)).replace(day=1)
    rows = con.execute(
        "SELECT a.id, a.name, a.last4, a.simplefin_id, a.type, MAX(t.txn_date), "
        "COUNT(DISTINCT CASE WHEN t.txn_date >= ? AND t.txn_date < ? THEN substr(t.txn_date, 1, 7) END) "
        "FROM accounts a JOIN transactions t ON t.account_id = a.id GROUP BY a.id",
        (m3.isoformat(), m0.isoformat())).fetchall()
    out = []
    for aid, name, last4, sfin, kind, newest, months in rows:
        if months < ACTIVE_MONTHS or not newest:
            continue
        is_synced = bool(sfin) and aid in synced
        days = (today - dt.date.fromisoformat(newest[:10])).days
        if days > (SYNC_QUIET_DAYS if is_synced else STATEMENT_QUIET_DAYS):
            out.append({"id": aid, "name": name, "last4": last4 or "", "newest": newest[:10], "days": days, "synced": is_synced,
                        "type": (kind or "").lower()})
    # a broken sync first (the salary account matters more than a CD's monthly interest), then the accounts money moves
    # through (checking, credit), then by the age of the gap
    out.sort(key=lambda r: (not r["synced"], r["type"] in SLOW_TYPES, -r["days"]))
    return out


def account_rows(con, today, limit=4, synced=None):
    out = []
    for a in quiet_accounts(con, today, synced)[:limit]:
        label = a["name"] + (f" x{a['last4']}" if a["last4"] and a["last4"] not in a["name"] else "")
        text = f"{label}: no new lines since {_day(a['newest'], today)} ({a['days']} days)"
        if a["synced"]:
            out.append(_row(f"acct:{a['id']}", "warn", text, "Check sync", SETTINGS_BANK))
        else:
            out.append(_row(f"acct:{a['id']}", "warn", text, "Add statement", "/add"))
    return out


def data_as_of(con, today, synced=None):
    """Money > Overview line: {"text", "behind"} or None. "Cards and checking as of Oct 21 · savings and investments as
    of Sep 30 · 1 account behind": the newest line per kind of account, plus how many accounts quiet_accounts lists."""
    groups = {"fast": None, "slow": None}
    for kind, newest in con.execute("SELECT a.type, MAX(t.txn_date) FROM accounts a JOIN transactions t ON t.account_id = a.id "
                                    "GROUP BY a.id").fetchall():
        if not newest:
            continue
        g = "slow" if (kind or "").lower() in SLOW_TYPES else "fast"
        groups[g] = max(groups[g] or "", newest[:10])
    parts = []
    for g, label in (("fast", "Cards and checking"), ("slow", "savings and loans")):
        if groups[g]:
            parts.append(f"{label} as of {dt.date.fromisoformat(groups[g]):%b} {dt.date.fromisoformat(groups[g]).day}")
    if not parts:
        return None
    behind = len(quiet_accounts(con, today, synced))
    if behind:
        parts.append(f"{behind} account{'s' if behind != 1 else ''} behind")
    return {"text": " · ".join(parts), "behind": behind}


def age_note(days):
    """Age pill text for the Keep accounts table: '' while fresh (under a week), 'quiet 23 days' once past a month."""
    return "" if days is None or days < 35 else f"no lines for {days} days"


def task_rows(today):
    import heartbeat
    import task_register
    cfg = config.family()
    beats = heartbeat._load()
    recent = False
    for r in beats.values():
        try:
            recent = recent or (today - dt.datetime.fromisoformat(r["at"]).date()).days <= EVIDENCE_DAYS
        except (KeyError, ValueError, TypeError):
            pass
    if not cfg.get("tasks_registered") and not recent:
        return [_row("tasks", "warn", "Nothing runs by itself yet: the daily brief, the inbox check and the weekly backup are off",
                     "Turn on", SETTINGS_DATA)]
    out = []
    for task, msg in heartbeat.stale(today, assume_registered=True):
        label = task_register.LABELS.get(task, task)
        out.append(_row(f"task:{task}", "warn", f"{label}: {msg}", "Settings", SETTINGS_DATA))
    return out


def inbox_row(con):
    n = con.execute("SELECT COUNT(*) FROM proposals WHERE status='open'").fetchone()[0]
    if not n:
        return None
    return _row("inbox", "warn" if n >= 10 else "ok", f"{n} Inbox card{'s' if n != 1 else ''} wait{'s' if n == 1 else ''} for an answer",
                "Open", "/add")


def rows(user, today=None, con=None):
    """The card for `user` (adults only): [] when nothing needs saying. Each part is independent; one that fails is
    left out."""
    if not user or user.get("role") != "adult":
        return []
    today = today or dates.today()
    out = []
    bank = None
    for part in (lambda: bank_row(today), lambda: task_rows(today)):
        try:
            got = part()
            if got is not None and not isinstance(got, list):
                bank = got
            out.extend(got if isinstance(got, list) else [got] if got else [])
        except Exception:  # noqa: BLE001
            pass
    try:
        r = sync_row(today, bank is not None)
        if r:
            out.append(r)
    except Exception:  # noqa: BLE001
        pass
    try:
        own = con is None
        con = con or db.connect(paths.DB, readonly=True)
        try:
            out.extend(account_rows(con, today))
            r = inbox_row(con)
            if r:
                out.append(r)
        finally:
            if own:
                con.close()
    except Exception:  # noqa: BLE001
        pass
    out.sort(key=lambda r: 0 if r["tone"] == "warn" else 1)
    return out


def main(argv=None):
    for r in rows({"name": "", "role": "adult"}):
        print(f"{r['tone']:4} {r['text']}" + (f"  -> {r['action']} {r['href']}" if r["href"] else "") + ("  [Sync now]" if r["op"] else ""))


if __name__ == "__main__":
    main()
