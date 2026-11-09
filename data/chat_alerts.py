"""Daily chat alerts: a private message from the bot to each person who turned alerts on, when something is due.

  python data/chat_alerts.py send            send today's alerts (the daily task runs this after the brief)
  python data/chat_alerts.py send --dry-run  print what would be sent, send nothing
  python data/chat_alerts.py preview NAME    the message NAME would get today

Who: live chat links with alerts on (`/alerts on` in a private chat, or `python data/chat_core.py alerts NAME on`).
What: chat_core.alert_text: adults get overdue items and the next 3 days with amounts; children only their own items
and family entries, never money. Nothing due -> no message. At most one alert per chat account per day, so a re-run
of the daily task does not repeat it. Always a private message (Telegram private chat, Discord direct message),
never a group or server channel. No AI.
"""
import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import chat_core  # noqa: E402
import dates  # noqa: E402
import log as _log  # noqa: E402

log = _log.get("chat_alerts")


def _telegram_sender():
    import chat_telegram as T
    tok = T.token()
    if not tok:
        return None
    return lambda uid, text: T.call("sendMessage", tok, http_timeout=20, chat_id=int(uid), text=text[:T.MAX_REPLY],
                                    disable_web_page_preview=True)


def _discord_sender():
    import chat_discord as Dc
    tok = Dc.token()
    if not tok:
        return None
    return lambda uid, text: Dc.send_dm(tok, uid, text)


def default_senders():
    return {"telegram": _telegram_sender(), "discord": _discord_sender()}


def _sent_today(con, platform, uid, today):
    return con.execute("SELECT 1 FROM chat_log WHERE command='alert' AND outcome='ok' AND platform=? AND platform_user_id=? "
                       "AND substr(at,1,10)=?", (platform, str(uid), today.isoformat())).fetchone() is not None


def send(today=None, dry_run=False, senders=None, db=None, now=None):
    """Returns a list of (platform, member, result) with result in sent | nothing_due | already_sent | no_bot | failed | dry_run."""
    now = now or chat_core._now()
    today = today or now.date()
    path = pathlib.Path(db) if db else chat_core.DB
    senders = default_senders() if senders is None else senders
    out = []
    con = chat_core._con(path)
    try:
        links = [dict(r) for r in con.execute("SELECT id, platform, platform_user_id, member, role, alerts FROM chat_links "
                                              "WHERE revoked_at IS NULL AND alerts=1 ORDER BY id")]
        for ln in links:
            plat, uid = ln["platform"], ln["platform_user_id"]
            if _sent_today(con, plat, uid, today):
                out.append((plat, ln["member"], "already_sent"))
                continue
            text = chat_core.alert_text(con, ln, today, path)
            if not text:
                out.append((plat, ln["member"], "nothing_due"))
                continue
            if dry_run:
                print(f"--- {plat} -> {ln['member']} ---\n{text}\n")
                out.append((plat, ln["member"], "dry_run"))
                continue
            fn = senders.get(plat)
            if not fn:
                out.append((plat, ln["member"], "no_bot"))
                continue
            try:
                fn(uid, text)
            except Exception as e:  # one failed send must not stop the others; the reason, never the text
                log.warning("chat alert to %s on %s failed: %s", ln["member"], plat, type(e).__name__)
                chat_core._log(con, plat, uid, ln["member"], "alert", "error", now)
                out.append((plat, ln["member"], "failed"))
                continue
            chat_core._log(con, plat, uid, ln["member"], "alert", "ok", now)
            out.append((plat, ln["member"], "sent"))
    finally:
        con.close()
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("send")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("preview")
    p.add_argument("name")
    a = ap.parse_args(argv)
    if a.cmd == "preview":
        con = chat_core._con()
        try:
            member = chat_core.canonical_member(con, a.name)
            if not member:
                print(f"'{a.name}' is not a household member", file=sys.stderr)
                return 2
            r = con.execute("SELECT role FROM chat_links WHERE member=? AND revoked_at IS NULL LIMIT 1", (member,)).fetchone()
            who = {"member": member, "role": r["role"] if r else chat_core.default_role(member)}
            print(chat_core.alert_text(con, who, dates.today()) or "(nothing due: no message today)")
        finally:
            con.close()
        return 0
    res = send(dry_run=a.dry_run)
    for plat, member, result in res:
        print(f"{plat:<9} {member:<16} {result}")
    if not res:
        print("nobody has alerts on (python data/chat_core.py alerts NAME on)")
    return 1 if any(r[2] == "failed" for r in res) else 0


if __name__ == "__main__":
    sys.exit(main())
