"""Family configuration (config/family.json), shared by every module.

Written by `python onboard.py`. Missing file or keys fall back to neutral defaults so the
code also runs on an unconfigured checkout. Optional packs are switched on in family.json:
  "packs": {"festivals": true, "contracts": false, "amazon": false, "shopping": false}
Pack data files live in config/ (see packs/ for examples).
"""
import contextlib
import copy
import json
import os
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import paths  # noqa: E402
CONFIG_DIR = paths.CONFIG
_CACHE = {}
_BROKEN = set()  # config files that exist but could not be read or parsed on the last load


def _load(name):
    """config/<name> as JSON, re-read whenever the file changes (long-running dashboards pick up edits).

    A missing file is an empty config. A file that exists but cannot be read or parsed (a hand edit gone wrong, a
    permission problem) also reads as empty so the scripts keep running, but `broken(name)` says so: the web app and
    the phone API must then fail closed instead of treating the household as "nobody has a PIN"."""
    try:  # config files are tiny: always re-read so edits (and tests) are never served stale
        data = json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))
        _BROKEN.discard(name)
    except FileNotFoundError:
        data = {}
        _BROKEN.discard(name)
    except (OSError, ValueError):
        data = {}
        _BROKEN.add(name)
    _CACHE[name] = data
    return data


def broken(name="family.json"):
    """True when config/<name> exists but could not be read or parsed on its last load (re-reads first)."""
    _load(name)
    return name in _BROKEN


class Broken(ValueError):
    """A config file exists but cannot be read: writing over it would throw away everything in it."""


class Busy(Broken):
    """Another part of the app kept family.json locked too long; nothing was saved (handled like Broken)."""


GUARDED = {"family.json"}  # never replaced while it does not parse (write_json), written under one lock
_LOCAL = threading.local()


@contextlib.contextmanager
def _family_lock():
    """logs/family_json.lock around a read-modify-write of family.json (web threads, scheduled tasks and terminal
    commands write it). Re-entrant in one thread, so write_json inside family_edit does not wait for itself."""
    if getattr(_LOCAL, "depth", 0):
        _LOCAL.depth += 1
        try:
            yield
        finally:
            _LOCAL.depth -= 1
        return
    import joblock
    try:
        hold = joblock.held("family_json", stale_after=120, wait=15)
        hold.__enter__()
    except joblock.Busy:
        raise Busy("Settings are being saved by another part of the app; nothing was changed. Try again.") from None
    _LOCAL.depth = 1
    try:
        yield
    finally:
        _LOCAL.depth = 0
        hold.__exit__(None, None, None)


@contextlib.contextmanager
def family_edit():
    """Change family.json safely: read it fresh under the lock, change the dict in the block, saved on leaving it.

        with config.family_edit() as cfg:
            cfg["ui"] = {**(cfg.get("ui") or {}), "mode": "simple"}

    Raises Broken (nothing saved) when the file exists but does not parse. An exception in the block saves nothing."""
    with _family_lock():
        if broken():
            raise Broken("family.json cannot be read (a hand edit with a typo?), so it was left as it is. "
                         "Fix the file or restore it from a backup, then try again.")
        data = copy.deepcopy(_load("family.json"))
        yield data
        write_json(CONFIG_DIR / "family.json", data)


def update_family(fn):
    """family_edit for a function: fn(cfg) changes cfg in place. -> what fn returned."""
    with family_edit() as cfg:
        return fn(cfg)


def write_json(path, obj, replace_broken=False):
    """Write JSON atomically (own temp file + rename) so a crash or a second writer never leaves a half-written file.

    Refuses (Broken) to replace a family.json that exists but does not parse: a writer that read it as {} would
    otherwise save a near-empty file over the members, PINs and settings. replace_broken=True is for a deliberate
    repair. Smaller preference files (expiries.json, dashboard_prefs.json...) are simply rewritten."""
    path = Path(path)
    if path.name in GUARDED:
        with _family_lock():
            _write_json(path, obj, replace_broken)
    else:
        _write_json(path, obj, replace_broken)


def _write_json(path, obj, replace_broken):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not replace_broken and path.name in GUARDED and path.exists():
        try:
            text = path.read_text(encoding="utf-8")
            if text.strip():
                json.loads(text)
        except (OSError, ValueError):
            raise Broken(f"{path.name} cannot be read (a hand edit with a typo?), so it was left as it is. "
                         "Fix the file or restore it from a backup, then try again.") from None
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, indent=2))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    _CACHE.pop(path.name, None)


def _legacy(name):
    """FAMILYAGENT_X for MITRAHOME_X (the name a secret had before the rename), else None."""
    import brand
    return brand.LEGACY_ENV_PREFIX + name[len(brand.ENV_PREFIX):] if name.startswith(brand.ENV_PREFIX) else None


def read_secret(name):
    """A secret from the environment or config/secrets.env ("" when missing). A MITRAHOME_ name also finds the value
    an install saved under its FAMILYAGENT_ name before the rename."""
    names = [n for n in (name, _legacy(name)) if n]
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    f = CONFIG_DIR / "secrets.env"
    if f.exists():
        lines = f.read_text(encoding="utf-8").splitlines()
        for n in names:
            for line in lines:
                if line.startswith(n + "="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def write_secret(name, value):
    """Set NAME=value in config/secrets.env: atomic, other lines kept (an older FAMILYAGENT_ line of the same secret is
    dropped), file readable by this user only (chmod 600; no-op on Windows, where the user profile folder already keeps
    other accounts out)."""
    f = CONFIG_DIR / "secrets.env"
    drop = tuple(n + "=" for n in (name, _legacy(name)) if n)
    keep = [l for l in (f.read_text(encoding="utf-8").splitlines() if f.exists() else []) if not l.startswith(drop)]
    f.parent.mkdir(exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(keep + [f"{name}={value}"]) + "\n")
    os.replace(tmp, f)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def family():
    return _load("family.json")


def phones_wanted(fam=None):
    """Settings > Phones > Connection: let phones and walls on the home Wi-Fi connect (family.json phones.lan). On unless
    the family switched it off; the app still opens to the Wi-Fi only once an adult has a PIN (launch.py, web_app.py).
    launch.py reads the same key with the standard library only."""
    ph = (family() if fam is None else fam).get("phones")
    return not (isinstance(ph, dict) and ph.get("lan") is False)


def data_file(name):
    """Contents of config/<name> (JSON), {} if absent."""
    return _load(name)


def members():
    return family().get("members", [])


def member_names(role=None):
    return [m["name"] for m in members() if role is None or m.get("role") == role]


def first_member(default="Family member"):
    n = member_names()
    return n[0] if n else default


def region():
    r = family().get("region", {})
    return {"state": r.get("state", ""), "county": r.get("county", ""), "zip": r.get("zip", ""),
            "place": r.get("place", "")}


def place_label():
    """'City, State' style label for headings; '' if not configured."""
    r = region()
    return ", ".join(x for x in (r["place"] or r["county"], r["state"]) if x)


def currency():
    return family().get("currency", "USD")


def agent_email():
    return family().get("agent_email", "")


def drive_path():
    p = family().get("drive_path", "")
    return Path(p) if p else None


def pack(name):
    return bool(family().get("packs", {}).get(name, False))
