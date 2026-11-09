"""The product's name, in one place.

Everything a person reads (page titles, Settings text, document headings, messages, the Google calendar's name) takes the
product name from here, so a rename touches this file only. The name of the agent itself is separate: each household
names its agent in Settings > Home Profile (data/agent_profile.py); this is only what that agent is called until they do.

The product was called FamilyAgent until 0.109. Names a family can see on their PC or in their accounts (folders,
scheduled tasks, the Drive folder, the Gmail label, secret names) now use SLUG / ENV_PREFIX; the old ones are still
recognised (LEGACY_*) so an install made before the rename keeps working without being touched.

Frozen on purpose, never renamed (changing one would break something already out there): the release manifest header
and the signing key ids (older installs check them before they update), the encrypted-backup check text (old backups
must still open), the calendar event and `.ics` ids (a change would duplicate every event on the family's phones), and
the update repository until it is renamed on GitHub.
"""
PRODUCT = "Mitra Home"
# What the agent is called until a household names it in Settings > Home Profile.
AGENT = "Mitra"
# Folder, task and label form of the name (no space) and the prefix of environment variables and secret names.
SLUG = "MitraHome"
ENV_PREFIX = "MITRAHOME_"
LEGACY_SLUG = "FamilyAgent"
LEGACY_ENV_PREFIX = "FAMILYAGENT_"
# The secondary Google calendar the app makes for itself (data/calendar_sync.py). A new calendar gets CALENDAR_NAME; one
# made earlier under any name in KNOWN_CALENDAR_NAMES is still recognised as ours and is renamed in place, so a rename
# never makes a second calendar or duplicates events.
CALENDAR_NAME = PRODUCT
KNOWN_CALENDAR_NAMES = ("FamilyAgent",)
# Folder next to the household that holds backups. Older names (newest first) are still found, and `onboard.py upgrade`
# renames the older folder to BACKUP_DIR (data/paths.py adopt_legacy_backups).
BACKUP_DIR = "Mitra-Home-Backup"
LEGACY_BACKUP_DIRS = ("MitraHome_backups", "FamilyAgent_backups")
# Default name of the household folder next to the app (data/paths.py). An existing household folder keeps its name:
# the marker file names it.
HOME_DIR = "Mitra-Home-Data"
# Scheduled task names start with this (Windows Task Scheduler) and cron lines end with "# " + SLUG.
TASK_PREFIX = PRODUCT
LEGACY_TASK_PREFIX = "FamilyAgent"
