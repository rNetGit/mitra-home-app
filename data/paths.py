"""Where this household's files live, in one place (standard library only).

    import paths
    paths.ROOT      the app folder (code: data/, tasks/, scripts/, onboard.py)
    paths.HOME      the household folder: papers, settings, database, briefs, logs
    paths.INBOX, ARCHIVE, BRIEF, REPORTS, EXPORTS, LOGS, CONFIG, DB, PRE_UPGRADE, BACKUPS

Two layouts:
  * separate (the default for a new install): HOME is a folder of its own next to the app, `Mitra-Home-Data` by
    default. An update of the app never goes near it, a mistake inside the app folder cannot touch it, and the app
    folder can be deleted and unzipped again without losing anything. The app finds it through one line in
    `mitrahome_home.txt` in the app folder (an absolute path, or one relative to the app folder); an install made
    before the rename has `familyagent_home.txt` instead, which is still read.
  * inside the app (no marker file): everything under the app folder, as before 0.61: `inbox/`, `archive/`, ...,
    `config/`, `data/family.db`, `data/backups_pre_upgrade/`. Test copies of the template use this layout.

`python onboard.py home [PATH]` moves a household from inside the app to its own folder; `python data/paths.py`
prints every path.
"""
import os
import pathlib

import brand

ROOT = pathlib.Path(__file__).resolve().parent.parent
MARKER = ROOT / "mitrahome_home.txt"
LEGACY_MARKER = ROOT / "familyagent_home.txt"  # before the rename; read when MARKER is missing
DEFAULT_HOME_NAME = brand.HOME_DIR
FOLDERS = ("inbox", "archive", "brief", "reports", "exports", "logs", "config")


def env(name, default=""):
    """Environment variable `name` (written with the MITRAHOME_ prefix), or its FAMILYAGENT_ form from before the rename."""
    v = os.environ.get(name)
    if v is None and name.startswith(brand.ENV_PREFIX):
        v = os.environ.get(brand.LEGACY_ENV_PREFIX + name[len(brand.ENV_PREFIX):])
    return default if v is None else v


def marker_file():
    """The marker file in use: MARKER, or LEGACY_MARKER when only that one exists."""
    return LEGACY_MARKER if not MARKER.exists() and LEGACY_MARKER.exists() else MARKER


def read_marker():
    """The folder named in the marker file, or None when the household lives inside the app folder."""
    try:
        text = marker_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    p = pathlib.Path(text).expanduser()
    return (p if p.is_absolute() else ROOT / p).resolve()


HOME = read_marker() or ROOT
SEPARATE = HOME != ROOT
INBOX = HOME / "inbox"
ARCHIVE = HOME / "archive"
BRIEF = HOME / "brief"
REPORTS = HOME / "reports"
EXPORTS = HOME / "exports"
LOGS = HOME / "logs"
CONFIG = HOME / "config"
DB = HOME / "family.db" if SEPARATE else ROOT / "data" / "family.db"
PRE_UPGRADE = HOME / "backups_pre_upgrade" if SEPARATE else ROOT / "data" / "backups_pre_upgrade"
def backups_dir(parent):
    """The backup folder in `parent`. An install that has only an older one (brand.LEGACY_BACKUP_DIRS) keeps it."""
    new = parent / brand.BACKUP_DIR
    if new.exists():
        return new
    return next((parent / n for n in brand.LEGACY_BACKUP_DIRS if (parent / n).exists()), new)


def adopt_legacy_backups(parent=None):
    """Rename an older backup folder in `parent` (default: next to the household) to brand.BACKUP_DIR when the new one
    does not exist yet. -> the old name moved, or "" (nothing to do, or the rename failed: the old folder keeps working)."""
    parent = pathlib.Path(parent) if parent else HOME.parent
    new = parent / brand.BACKUP_DIR
    old = backups_dir(parent)
    if old == new or not old.is_dir():
        return ""
    try:
        old.rename(new)
    except OSError:
        return ""
    return old.name


BACKUPS = backups_dir(HOME.parent)  # same drive as the household
BY_NAME = {"inbox": INBOX, "archive": ARCHIVE, "brief": BRIEF, "reports": REPORTS, "exports": EXPORTS, "logs": LOGS,
           "config": CONFIG}


def folder(name):
    """Household folder by its short name ("inbox", "archive", ...)."""
    return BY_NAME[name]


def rel(p):
    """`p` relative to HOME as a posix string when it is inside it, else the absolute path (for messages and logs)."""
    p = pathlib.Path(p)
    try:
        return p.resolve().relative_to(HOME.resolve()).as_posix()
    except ValueError:
        return str(p)


def ensure():
    """Create the household folders that are missing (never removes anything)."""
    for d in (*BY_NAME.values(), DB.parent, PRE_UPGRADE.parent):
        d.mkdir(parents=True, exist_ok=True)


def describe():
    lines = [f"app folder:        {ROOT}", f"household folder:  {HOME}" + ("" if SEPARATE else "  (inside the app folder)")]
    for name, p in (("database", DB), *BY_NAME.items(), ("pre-upgrade copies", PRE_UPGRADE), ("backups", BACKUPS)):
        lines.append(f"  {name:<19}{p}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(describe())
