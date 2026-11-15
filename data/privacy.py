"""Privacy mode: stars instead of money totals and dates of birth while someone else may be looking at the screen.

One place for every mask. The flag lives in the signed-in session (`sessions` key "private"; in memory, so a restart
or a new sign-in starts again from the household default `privacy.on_signin` in family.json, on unless switched off in
Settings > Household profile). An adult flips it from the user menu (`POST /privacy`); a limited person (child, guest) is
always private. The web app's guard middleware puts the answer for the current request in a context variable, so the
masks work in templates (`|money`, `|money2`, `|mask`) and in the data modules that build display text (`fmt`, `hide`)
without every function being handed the session. Masking happens when the page is built: the real figure is never in
the HTML while private, so view-source and copy / paste show stars too.

Masked: net worth and the "what you have / owe" figures, account balances and group totals, investment and loan
values, home and car equity, the Money Overview / This month / Statement / Trends / Home costs figures, budget and goal
bars, the Today money card, and dates of birth (Family, Records). Not masked: the amount on one transaction line (the
Ledger, an account's lines, a month's charges), the wall's own PIN-gated Money screen, and the phone API (a phone has
its own scopes). Chat answers about money, the Ledger / tax / year-end downloads and the Money > Look back files
wait until privacy is off.

Never use the masks for text that is stored or sent anywhere: they are for pages only. Outside a web request the flag
is off, so the briefs, reports, bots and the command line are unchanged.
"""
import contextvars
import re

import config
import money

STARS = "*****"
_flag = contextvars.ContextVar("mitra_privacy", default=False)

# Record fields (the words a record shows) whose value is hidden while private: dates of birth and balances.
HIDDEN_FIELDS = {"birth month day", "birth year", "birthday", "born", "balance", "current value", "invested", "opening balance",
                 "credit limit", "balance as of", "principal", "original amount", "monthly limit"}


DOWNLOAD_REFUSED = "Privacy mode is on, and this document lists real figures. Turn on Easy access in your user menu first."
CHAT_REFUSED = ("Privacy mode is on, so I will not answer questions about money or birthdays. Turn on Easy access in your "
                "user menu (your name, bottom left on a PC or top right on a phone), then ask again.")
MONEY_DOCS = ("this_week", "weekly_digest", "family_meeting")  # the emergency sheet has no figures


def default_on():
    """New sign-ins start private unless the household switched that off (Settings > Household profile)."""
    try:
        return bool((config.family().get("privacy") or {}).get("on_signin", True))
    except Exception:  # noqa: BLE001  - an unreadable family.json must never open the vault
        return True


def effective(session, user):
    """Is this person private right now? A limited person always is; the open-on-this-PC session (nobody has a PIN) never."""
    if not session or not user:
        return False
    if session.get("open"):
        return False
    if user.get("role") != "adult":
        return True
    flag = session.get("private")
    return default_on() if flag is None else bool(flag)


def set_current(on):
    """Called by the guard middleware once per request; returns the token for reset()."""
    return _flag.set(bool(on))


def reset(token):
    _flag.reset(token)


def active():
    return _flag.get()


# ---- masks -----------------------------------------------------------------------------------------------------
def hide(text="", stars=STARS):
    """`text` as it is, or stars while private."""
    return stars if _flag.get() else text


def fmt(value, decimals=2):
    """money.fmt for a figure that must be hidden while private (a total, a balance, a limit)."""
    return STARS if _flag.get() else money.fmt(value, decimals)


def money_filter(decimals):
    """The Jinja filters `|money` (no cents) and `|money2` (cents): stars while private, else money.fmt as before."""
    return lambda v: STARS if _flag.get() else money.fmt(v, decimals)


def raw_filter(decimals):
    """`|amt` and `|amt2`: the amount of one transaction line, which stays visible (the owner's decision)."""
    return lambda v: money.fmt(v, decimals)


def mask_filter(v, stars=STARS):
    """`|mask`: any text (a date of birth, an age) as it is, or stars while private. Empty stays empty."""
    return stars if _flag.get() and v not in (None, "") else v


def mask_text(text):
    """A sentence that carries figures (a note built by a data module): every money-looking figure becomes stars."""
    if not _flag.get() or not text:
        return text
    return _FIGURE.sub(STARS, str(text))


def mask_tree(obj):
    """mask_text over every string of a nested dict / list / tuple built by a data module (display text only)."""
    if not _flag.get():
        return obj
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {k: mask_tree(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [mask_tree(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(mask_tree(v) for v in obj)
    return obj


_FIGURE = re.compile(r"-?(?:[$€£₹¥]|C\$|A\$|NZ\$|S\$|CHF |kr )\d[\d,]*(?:\.\d+)?")


def hidden_col(col):
    """Is this column (a database column name) one whose value hides while private? A date of birth or a balance."""
    return _flag.get() and str(col).lower().replace("_", " ") in HIDDEN_FIELDS


def field(key, value):
    """A record field (lower-case words, as records.detail gives them): hidden while private when it is a date of birth
    or a balance."""
    if hidden_col(key) and value not in (None, ""):
        return STARS
    return value
