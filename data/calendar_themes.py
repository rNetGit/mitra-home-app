"""The look of a calendar day card (week and month views): which theme a day gets from what is on it.

A day takes the theme of its most important item. Named festivals and holidays (Diwali, Thanksgiving, Christmas,
the flag days) have their own illustrated card; birthdays and medical visits have one too; the other kinds only
tint the card. Colours come from CSS (`.th-<key>` in app.css), the drawings from /static/themes/<key>.svg, so a
theme is changed or added without touching this logic. Pure functions: nothing here reads the database.

Needs: a day's `things`, a list of (kind, title) as calendar_data.load_events makes them."""
import re

# (theme key, kinds it may come from, words in the title). Order = priority: the first theme any item of the day matches wins.
NAMED = (
    ("diwali", ("Festival", "Holiday"),
     r"diwali|deepavali|dhanteras|lakshmi|govardhan|bhai dooj|bhai duj|naraka chaturdashi|kali puja|annakut"),
    ("thanksgiving", ("Festival", "Holiday"), r"thanksgiving"),
    ("christmas", ("Festival", "Holiday"), r"christmas|xmas|noel"),
    ("patriot", ("Festival", "Holiday"),
     r"veterans day|memorial day|independence day|flag day|presidents'? day|fourth of july|july 4"),
)
MEDICAL_WORDS = (r"doctor|dr\.|dentist|dental|clinic|check-?up|physical|vaccin|flu shot|booster|therapy|orthodont|braces|"
                 r"pediatric|paediatric|eye exam|optometr|dermatolog|cardiolog|lab work|blood test|x-ray|mri|surgery|hospital")
MEDICAL_KINDS = ("Medical",)
# Kinds that only tint the card, in priority order (after the named themes, birthdays and medical visits).
TINTS = (("festival", ("Festival",)), ("holiday", ("Holiday", "Clocks change")),
         ("class", ("Class", "Activity", "School", "No school", "Early dismissal")),
         ("bill", ("Bill", "Subscription", "Loan", "Tax", "Insurance")))
# The themes that have a drawing in /static/themes/<key>.svg.
ART = ("diwali", "thanksgiving", "christmas", "patriot", "birthday", "medical")


def _medical(kind, title):
    if kind in MEDICAL_KINDS:
        return True
    return kind in ("Appointment", "Event") and re.search(MEDICAL_WORDS, title or "", re.I) is not None


def day_theme(things):
    """The theme key for a day's (kind, title) list: one of the NAMED / 'birthday' / 'medical' / TINTS keys, or ''."""
    things = list(things or [])
    if not things:
        return ""
    for key, kinds, words in NAMED:
        if any(k in kinds and re.search(words, t or "", re.I) for k, t in things):
            return key
    if any(k == "Birthday" for k, _ in things):
        return "birthday"
    if any(_medical(k, t) for k, t in things):
        return "medical"
    for key, kinds in TINTS:
        if any(k in kinds for k, _ in things):
            return key
    return ""


def has_art(key):
    return key in ART
