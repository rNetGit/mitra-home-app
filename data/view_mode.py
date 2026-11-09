"""Simple / Advanced view of the web app: a display preference, nothing more.

`ui.mode` in config/family.json is "simple" or "advanced". Simple trims the More menu and Settings
to what an everyday family uses; Advanced shows everything. It never deletes data, never switches a feature off and
never blocks a page or a code path (every URL still opens in both modes). Both modes are free.

A brand-new install (the first-run interview) is saved as Advanced, like an install with no `ui.mode` (every install from
before this existed), so nothing a family uses is hidden; the switch is on the Settings home.
"""
import config

MODES = ("simple", "advanced")
DEFAULT = "advanced"  # no setting saved = an install that predates the switch
NEW_INSTALL = "advanced"
# What Simple keeps (keys of webapp.app.PAGES; Today is always there) and which Settings groups it lists.
SIMPLE_PAGES = ("family", "calendar", "wallet", "inbox", "records", "notes", "settings")
SIMPLE_GROUPS = ("household", "agent", "phones", "connections")


def get():
    m = str((config.family().get("ui") or {}).get("mode") or "").strip().lower()
    return m if m in MODES else DEFAULT


def is_simple():
    return get() == "simple"


def pages(all_pages):
    """The (key, label) pairs of the More menu for the current mode (the five tabs always show)."""
    return list(all_pages) if not is_simple() else [p for p in all_pages if p[0] in SIMPLE_PAGES]


def groups(all_groups):
    """The (key, label) pairs of the Settings pills."""
    return list(all_groups) if not is_simple() else [g for g in all_groups if g[0] in SIMPLE_GROUPS]
