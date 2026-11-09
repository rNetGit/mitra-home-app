"""The daily "is there a new version?" look (Settings > Data > Updates > "Check for new versions every day").

  python data/update_notice.py daily     ask GitHub once a day (the daily scheduled task calls this), quiet
  python data/update_notice.py status    print what the last look found

When this PC cannot read the private app repository, the same look falls back to the PUBLIC releases of the
Mitra Home site (updater.site_release: only a release that has an installer for this system); such a notice says a
new version exists and links to the install page, it cannot install by itself.

At most once a day, and only when the setting is on (config updates.daily_check, on by default; off = no network call),
updater.check(quiet=True) asks api.github.com for the latest release. Nothing about the family is sent: it is one
read of the public release list (with the read-only MITRAHOME_TOKEN while the project is private). The answer goes to
logs/update_check.json: {checked_at, current, latest, newer, notes, last_error, last_ok, failing_since}.

What it feeds, all without AI: one Inbox item "Mitra Home X is available" (proposals.py source "update": Update now
runs the same signed update as Settings > Data > Updates, through admin_actions, adults only; Later snoozes a week),
a short line on Today and the Brief for adults, and a health row after 7 days of failed looks (a missing or expired
update token is the usual cause). A failed look is otherwise silent. The update itself is never started from here.
"""
import datetime as dt
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import config  # noqa: E402

STATE = "update_check.json"
FAIL_DAYS = 7
NOTES_MAX = 300
HOST = "api.github.com"


def _file():
    return paths.LOGS / STATE


def enabled(cfg=None):
    """Settings > Data > Updates: "Check for new versions every day" (on unless switched off)."""
    cfg = config.family() if cfg is None else cfg
    return (cfg.get("updates") or {}).get("daily_check", True) is not False


def state():
    try:
        d = json.loads(_file().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(d):
    paths.LOGS.mkdir(parents=True, exist_ok=True)
    tmp = _file().with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2), encoding="utf-8")
    tmp.replace(_file())


def summary(notes, limit=NOTES_MAX):
    """Release notes (markdown) -> one plain line of at most `limit` characters."""
    lines = []
    for ln in str(notes or "").splitlines():
        ln = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", ln)  # links and images -> their text
        ln = re.sub(r"[#*_`>]+", "", ln).strip(" -\t")
        if ln:
            lines.append(ln)
    text = " · ".join(lines)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def daily(today=None, check=None, force=False, site=None):
    """Look once a day. -> 'off' | 'done today' | 'newer' | 'up to date' | 'failed'. Never raises."""
    if not enabled():
        return "off"
    now = dt.datetime.now() if today is None else dt.datetime.combine(today, dt.time(7, 0))
    d = state()
    if not force and str(d.get("checked_at", ""))[:10] == now.date().isoformat():
        return "done today"
    import updater
    check = check or updater.check
    site = site or updater.site_release
    src, url = "app", ""
    try:
        cur, rel, newer = check(quiet=True)
        err = "" if rel else (getattr(updater, "LAST_ERROR", "") or "Could not reach GitHub.")
    except Exception as e:  # noqa: BLE001 (a look must never fail the daily task)
        cur, rel, newer, err = updater.current_version(), None, False, f"{type(e).__name__}"
    if not rel:  # not open to this PC (a private repository): the public releases on the Mitra Home site
        try:
            pub = site()
        except Exception:  # noqa: BLE001
            pub = None
        if pub:
            rel, src, url, err = pub, "site", pub.get("url", ""), ""
            newer = updater.parse(pub["version"]) > updater.parse(cur)
    stamp = now.isoformat(timespec="seconds")
    d.update(checked_at=stamp, current=cur, last_error=err[:300])
    if rel:
        d.update(latest=rel.get("version", ""), newer=bool(newer), notes=summary(rel.get("notes")), last_ok=stamp,
                 failing_since="", source=src, url=url)
    elif not d.get("failing_since"):
        d["failing_since"] = stamp
    _write(d)
    return "failed" if not rel else ("newer" if newer else "up to date")


def available(cfg=None):
    """{'version', 'notes'} when the last good look found a release newer than THIS install, else None (also when off)."""
    if not enabled(cfg):
        return None
    d = state()
    v = str(d.get("latest") or "")
    if not v:
        return None
    import updater
    if updater.parse(v) <= updater.parse(updater.current_version()):
        return None  # already updated (or the look is older than the update)
    return {"version": v, "notes": str(d.get("notes") or ""), "source": str(d.get("source") or "app"), "url": str(d.get("url") or "")}


def failing_days(today=None):
    """Whole days the daily look has failed in a row (0 when the last look worked or it is off)."""
    if not enabled():
        return 0
    since = str(state().get("failing_since") or "")
    if not since:
        return 0
    try:
        start = dt.date.fromisoformat(since[:10])
    except ValueError:
        return 0
    return max(0, ((today or dates.today()) - start).days)


def health_row(today=None):
    """(note) for the health check after FAIL_DAYS days of failed looks, else None."""
    n = failing_days(today)
    if n < FAIL_DAYS:
        return None
    err = str(state().get("last_error") or "")
    return f"could not look for new versions for {n} days" + (f": {err[:160]}" if err else "")


def notice(user, con=None):
    """The one line for Today and the Brief: adults only, and only while the Inbox item is not snoozed or dismissed."""
    if (user or {}).get("role") != "adult":
        return None
    a = available()
    if not a:
        return None
    if con is not None:
        try:
            r = con.execute("SELECT status FROM proposals WHERE dedupe_key=?", (f"update:{a['version']}",)).fetchone()
            if r and r[0] != "open":
                return None
        except Exception:  # noqa: BLE001 (an older database without the Inbox)
            pass
    import brand
    return {"version": a["version"], "text": f"{brand.PRODUCT} {a['version']} is available.",
            "href": a["url"] if a["source"] == "site" else ""}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd == "daily":
        print(daily())
        return 0
    if cmd == "status":
        d = state()
        print(json.dumps({**d, "enabled": enabled()}, indent=2) if d else ("No look yet." if enabled() else "Off."))
        return 0
    print("usage: update_notice.py daily|status")
    return 2


if __name__ == "__main__":
    sys.exit(main())
