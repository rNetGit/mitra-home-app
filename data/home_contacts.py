"""House maintenance contacts: the plumber, furnace company, garage, electrician or handyman the household has used.

Table home_contacts (migration 052). Adults add, change and remove them in Family > Home > Service contacts
(edit_actions.home_contact_*). "Last job" is the later of the row's own last_used and the upkeep log
(recurring_log.provider = the contact's name), so marking an upkeep job done with that name keeps it current.
PC only: no sync trigger, not in the phone API, refused by ask_sql; printed on the emergency sheet.
"""
import re
import sqlite3

TRADES = (("plumbing", "Plumbing"), ("electrical", "Electrical"), ("heating_cooling", "Heating and cooling (furnace, AC)"),
          ("garage_door", "Garage door"), ("auto", "Car repair"), ("appliance", "Appliance repair"), ("roofing", "Roofing"),
          ("handyman", "Handyman"), ("landscaping", "Lawn and garden"), ("pest", "Pest control"), ("cleaning", "Cleaning"),
          ("painting", "Painting"), ("locksmith", "Locksmith"), ("pool", "Pool and spa"), ("other", "Other"))
HIDDEN_TABLE = "home_contacts"

_PHONE = re.compile(r"^\+?[\d ().-]{7,24}(?:\s*(?:x|ext\.?)\s*\d{1,6})?$", re.I)
_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(?:\.[\w-]+)+$")
_WEB = re.compile(r"^https?://[^\s<>\"']{3,190}$", re.I)


def phone(x):
    s = " ".join(str(x).split())
    if not _PHONE.match(s) or not 7 <= sum(ch.isdigit() for ch in s) <= 20:
        raise ValueError("use digits, spaces, + ( ) - and an optional 'ext 12'")
    return s


def email(x):
    s = str(x).strip()
    if len(s) > 120 or not _EMAIL.match(s):
        raise ValueError("not an email address")
    return s


def website(x):
    s = str(x).strip()
    if s and "://" not in s and ":" not in s.split("/")[0]:
        s = "https://" + s  # "acme.example" -> https://; "javascript:..." stays as typed and fails below
    if not _WEB.match(s):
        raise ValueError("a web address starting with http:// or https://")
    return s


LAST_JOB = ("MAX(COALESCE(c.last_used, ''), COALESCE((SELECT MAX(l.done_date) FROM recurring_log l "
            "WHERE lower(trim(l.provider)) = lower(c.name)), ''))")


def names():
    """Active contact names, for the upkeep "Where / who" suggestions."""
    import db
    import paths
    try:
        con = db.connect(paths.DB, readonly=True)
    except sqlite3.Error:
        return []
    try:
        return [n for (n,) in con.execute("SELECT DISTINCT name FROM home_contacts WHERE status='active' ORDER BY name")]
    except sqlite3.Error:
        return []
    finally:
        con.close()


def for_sheet(con):
    """[(trade title, name, phone, notes)] for the printed emergency sheet."""
    title = dict(TRADES)
    try:
        return [(title.get(t, t), n, p or "", no or "") for t, n, p, no in con.execute(
            "SELECT trade, name, phone, notes FROM home_contacts WHERE status='active' AND COALESCE(again, 1) = 1 "
            "ORDER BY trade, name")]
    except sqlite3.OperationalError:
        return []
