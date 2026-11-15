"""Settings history: a copy of the settings files before every change made in Settings, and putting one back.

Before an adult's change under /settings/ (webapp/routes_settings.py) the top-level `config/*.json` files are copied
to `config/history/<YYYYmmdd-HHMMSS>/` with `meta.json` (when, who, what), but only when they differ from the newest
copy, so a button that changes nothing makes none. Left out: secrets.env (never copied), the Google client file and
the files that only keep where a sync stopped (`SKIP`, `*_state.json`), because putting an old one back would make a
sync repeat or lose its place. The newest `KEEP` copies stay.

`restore(name)` first copies the files as they are now, then writes the copy's files back (family.json through
config.write_json, so its lock and checks apply). Files that are not in the copy are left as they are.

    python data/settings_history.py list
    python data/settings_history.py snap [WHAT]
"""
import datetime as dt
import hashlib
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import config  # noqa: E402
import paths  # noqa: E402

KEEP = 40
SKIP = {"google_client.json", "setup_draft.json", "calendar_sync.json", "calendar_back.json"}
NAME_RE = re.compile(r"^\d{8}-\d{6}(-\d{1,2})?$")
META = "meta.json"
# What a change was, by its address under /settings/ (first part); anything else is shown as it is.
WHAT = {"agent": "Home Profile", "pin": "a PIN", "papers": "names on papers", "packs": "optional features",
        "traditions": "traditions", "tax": "tax papers", "lead": "reminders", "view": "Simple / Advanced",
        "ai": "AI helper", "telegram": "phone bot", "google": "Google", "mail": "mail folder", "feeds": "other calendars",
        "bank": "bank sync", "phones": "phones", "wall": "walls", "tasks": "runs on its own", "update": "updates",
        "restore": "hidden from Today"}


def home():
    return paths.CONFIG / "history"


def files():
    """The settings files copied: top-level config/*.json, minus SKIP and *_state.json. -> sorted [Path]."""
    d = paths.CONFIG
    if not d.is_dir():
        return []
    return sorted(p for p in d.glob("*.json")
                  if p.is_file() and p.name not in SKIP and not p.name.endswith("_state.json"))


def _digest(path_list):
    h = hashlib.sha256()
    for p in path_list:
        h.update(p.name.encode() + b"\0")
        try:
            h.update(p.read_bytes())
        except OSError:
            continue
        h.update(b"\0")
    return h.hexdigest()


def _copies():
    d = home()
    if not d.is_dir():
        return []
    return sorted((p for p in d.iterdir() if p.is_dir() and NAME_RE.match(p.name)), key=lambda p: p.name, reverse=True)


def _meta(d):
    try:
        m = json.loads((d / META).read_text(encoding="utf-8"))
        return m if isinstance(m, dict) else {}
    except (OSError, ValueError):
        return {}


def snapshot(who="", what=""):
    """Copy the settings files unless they equal the newest copy. -> the copy's name, or None (nothing to copy)."""
    src = files()
    if not src:
        return None
    digest = _digest(src)
    copies = _copies()
    if copies and _meta(copies[0]).get("digest") == digest:
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    name, n = stamp, 1
    while (home() / name).exists():
        name, n = f"{stamp}-{n}", n + 1
    d = home() / name
    d.mkdir(parents=True)
    for p in src:
        shutil.copy2(p, d / p.name)
    meta = {"when": dt.datetime.now().isoformat(timespec="seconds"), "who": str(who or "")[:60],
            "what": str(what or "")[:80], "digest": digest, "files": [p.name for p in src]}
    (d / META).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    for old in _copies()[KEEP:]:
        shutil.rmtree(old, ignore_errors=True)
    return name


def label(what):
    """'bank' / 'wall/screen' -> 'bank sync' / 'walls'; free text as it is."""
    head = str(what or "").split("/")[0]
    return WHAT.get(head, str(what or "").replace("/", " "))


def listing(limit=20):
    """[{name, when, who, what, n}] newest first."""
    out = []
    for d in _copies()[:limit]:
        m = _meta(d)
        out.append({"name": d.name, "when": (m.get("when") or "")[:16].replace("T", " "), "who": m.get("who") or "",
                    "what": label(m.get("what") or ""), "n": len(m.get("files") or [])})
    return out


def restore(name, who=""):
    """Put a copy back. -> (ok, message). The files as they are now are copied first."""
    if not NAME_RE.match(str(name or "")):
        return False, "That copy is not in the settings history."
    d = home() / name
    if not d.is_dir():
        return False, "That copy is not in the settings history."
    m = _meta(d)
    back = [p for p in sorted(d.glob("*.json")) if p.name != META and p.name not in SKIP
            and not p.name.endswith("_state.json")]
    if not back:
        return False, "That copy holds no settings files."
    parsed = []
    for p in back:
        try:
            parsed.append((p.name, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            return False, f"{p.name} in that copy cannot be read, so nothing was changed."
    snapshot(who, f"before putting back {m.get('when', name)[:16].replace('T', ' ')}")
    for fname, obj in parsed:
        config.write_json(paths.CONFIG / fname, obj, replace_broken=True)
    return True, f"Settings put back as they were at {m.get('when', name)[:16].replace('T', ' ')} ({len(parsed)} file(s)). " \
                 "The settings from just before are kept in the history too."


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["snap"]:
        print(snapshot("terminal", " ".join(argv[1:]) or "by hand") or "Nothing changed since the newest copy.")
        return 0
    for r in listing(KEEP):
        print(f"{r['name']}  {r['when']}  {r['who'] or '-'}  {r['what']}  ({r['n']} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
