"""Add from a photo: a flyer, invitation or school letter becomes dates to add, a recipe card becomes a recipe. No web code
(webapp/routes_photo.py draws the pages).

The photo waits as a draft (wallet.save_draft: the same content checks as the Inbox, removed after a day). Only when the
family turned photo reading on (ai.read_receipt_photos) and ticked "Let the AI read it" does the family's own AI read it
(llm.extract_image_json); the answer is checked here and only proposes: nothing is saved until an adult has checked each
line and pressed Add. Without the AI the same form is filled in by hand.

  read_dates(path, today, names)   -> (rows, message)   rows: date, title, who, kind, time, area
  read_recipe(path)                -> (fields, message)  name, servings, ingredients (one a line), notes
  save_dates(actor, rows)          -> (added, [what failed]) through edit_actions (adults; validated and logged there)
"""
import datetime as dt
import re

DATE_KINDS = {"event": "On the calendar", "no_school": "No school (day off)", "early": "Early dismissal",
              "deadline": "To do by this date"}
AREAS = ("school", "activity", "other")
MAX_ROWS = 20
PAST_DAYS, AHEAD_DAYS = 30, 400  # a date further away than this is a misreading (or last year's flyer)
DATES_SCHEMA = {
    "has_dates": (bool, True, None),
    "items": (list, False, {"date": (str, True, None), "title": (str, True, None), "who": (str, False, None),
                            "kind": (str, False, None), "time": (str, False, None), "end_date": (str, False, None),
                            "area": (str, False, None)}),
    "confidence": ((int, float), False, None),
}
DATES_INSTRUCTION = (
    "This is a photo of a flyer, invitation, school letter or notice. List every dated item a family would put on its "
    "calendar: has_dates (true/false); items: date (YYYY-MM-DD; when no year is printed use the next such date after "
    "{today}), end_date (YYYY-MM-DD, only for a span of days), time (HH:MM 24-hour, only when printed), title (short, "
    "as a family would say it, at most 60 characters, no links), who (the child or person it is for, only when named: "
    "one of {names}, else empty), kind (event = something to go to; no_school = a day off school; early = early "
    "dismissal; deadline = something to bring, pay or return by that date), area (school, activity or other); "
    "confidence 0 to 1. Never copy a phone number, email address, account number or link.")
RECIPE_SCHEMA = {
    "is_recipe": (bool, True, None),
    "name": (str, False, None),
    "servings": ((int, float), False, None),
    "ingredients": (list, False, {"text": (str, True, None)}),
    "notes": (str, False, None),
    "confidence": ((int, float), False, None),
}
RECIPE_INSTRUCTION = (
    "This is a photo of a recipe (a card, a cookbook page or a screen). Return: is_recipe (true/false); name (at most 80 "
    "characters); servings (a number, only when printed); ingredients: one item each, text = quantity and ingredient as "
    "printed (for example '2 cups flour'), at most 60; notes = the method in short plain sentences, at most 400 "
    "characters; confidence 0 to 1. No links.")
_LINK = re.compile(r"https?://|www\.|@", re.I)


def _text(value, n):
    t = " ".join(str(value or "").split())[:n]
    return "" if not t or t.startswith(("-", "=", "+")) or _LINK.search(t) else t


def _day(value, today):
    try:
        d = dt.date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None
    return d if today - dt.timedelta(days=PAST_DAYS) <= d <= today + dt.timedelta(days=AHEAD_DAYS) else None


def clean_dates(obj, today, names):
    """The AI's answer -> rows the check form shows (bad dates and empty titles left out, at most MAX_ROWS)."""
    rows, seen = [], set()
    for it in (obj or {}).get("items") or []:
        d = _day(it.get("date"), today)
        title = _text(it.get("title"), 80)
        if not d or not title:
            continue
        end = _day(it.get("end_date"), today)
        kind = str(it.get("kind") or "event").lower()
        kind = kind if kind in DATE_KINDS else "event"
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(it.get("time") or "").strip())
        time = f"{int(m.group(1)):02d}:{m.group(2)}" if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 else ""
        who = next((n for n in names if n.lower() == str(it.get("who") or "").strip().lower()), "")
        area = str(it.get("area") or "other").lower()
        key = (d, title.lower())
        if key in seen:
            continue
        seen.add(key)
        rows.append({"date": d.isoformat(), "end": end.isoformat() if end and end > d else "", "title": title, "who": who,
                     "kind": kind, "time": time if kind in ("event", "early") else "", "area": area if area in AREAS else "other"})
        if len(rows) >= MAX_ROWS:
            break
    return sorted(rows, key=lambda r: (r["date"], r["time"], r["title"]))


def _ask(instruction, path, schema, purpose):
    import llm
    why = llm.photos_allowed()
    if why:
        return None, f"Not read by AI: {why}. Fill it in below."
    try:
        obj, errs = llm.extract_image_json(instruction, path, schema, purpose=purpose, max_tokens=1500)
    except llm.LLMError as e:
        return None, f"The AI could not read the photo ({str(e)[:120]}). Fill it in below."
    if errs or not obj:
        return None, "The AI's answer did not check out. Fill it in below."
    return obj, ""


def read_dates(path, today, names):
    obj, msg = _ask(DATES_INSTRUCTION.format(today=today.isoformat(), names=", ".join(names) or "none"), path,
                    DATES_SCHEMA, "dates_photo")
    if obj is None:
        return [], msg
    rows = clean_dates(obj, today, names) if obj.get("has_dates") else []
    if not rows:
        return [], "The AI found no dates it could use on this photo. Add them below, or try a sharper photo."
    sure = float(obj.get("confidence") or 0) >= 0.7
    return rows, (f"Read by AI: {len(rows)} date{'s' if len(rows) != 1 else ''} found. Check each one, untick what you do "
                  "not want, then add them." + ("" if sure else " It was not sure, so look closely."))


def clean_recipe(obj):
    lines = [_text(i.get("text"), 120) for i in (obj or {}).get("ingredients") or []]
    try:
        serv = int(float((obj or {}).get("servings") or 0))
    except (TypeError, ValueError):
        serv = 0
    return {"name": _text((obj or {}).get("name"), 80), "servings": str(serv) if 0 < serv <= 50 else "",
            "ingredients": "\n".join(x for x in lines if x)[:4000], "notes": _text((obj or {}).get("notes"), 400)}


def read_recipe(path):
    obj, msg = _ask(RECIPE_INSTRUCTION, path, RECIPE_SCHEMA, "recipe_photo")
    if obj is None:
        return {}, msg
    if not obj.get("is_recipe"):
        return {}, "The AI did not see a recipe in this photo. Type it in below, or try another photo."
    fields = clean_recipe(obj)
    sure = float(obj.get("confidence") or 0) >= 0.7
    return fields, "Read by AI: check the recipe, then save it." + ("" if sure else " It was not sure, so look closely.")


def save_dates(actor, rows):
    """Each checked row through edit_actions: a day off or early dismissal = a calendar day; an event with a time and a
    person = an appointment; another event = a family event on the calendar (at its time, when it has one); a deadline
    = a to-do for that day."""
    import edit_actions as ea
    added, failed = 0, []
    for r in rows:
        kind, title, who = r.get("kind"), r.get("title", ""), r.get("who") or None
        if kind in ("no_school", "early"):
            ok, msg = ea.calendar_day_add(actor, r.get("date"), title, kind="closure" if kind == "no_school" else "early",
                                          end=r.get("end") or None, who=who)
        elif kind == "deadline":
            ok, msg = ea.life_add(actor, "school" if r.get("area") == "school" else "activity" if r.get("area") == "activity"
                                  else "other", title, who=who, due=r.get("date"))
        elif r.get("time") and who:
            ok, msg = ea.appointment_add(actor, who, f"{r.get('date')} {r.get('time')}", purpose=title[:80])
        else:
            ok, msg = ea.event_add(actor, title[:80], r.get("date"), yearly=False, start_time=r.get("time") or None)
        if ok:
            added += 1
        else:
            failed.append(f"{title}: {msg}")
    return added, failed
