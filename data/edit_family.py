"""Validated edits for the web app: people, life items, weekly activities, school days off and critical information (split from edit_actions.py, audit A9).

See edit_core.py for the rules every edit follows; edit_actions.py re-exports everything, callers keep using it.
"""
import datetime as dt
import re
import sqlite3
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import config  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import health_records  # noqa: E402
import life  # noqa: E402
import members as mem  # noqa: E402
import validators as v  # noqa: E402
from edit_core import (  # noqa: E402
    EditError,
    ROLES,
    _adult,
    _clean,
    _con,
    _item,
    _log,
    _member_name,
    _opt,
    edits,
)


# ---------------------------------------------------------------- life items
@edits
def life_add(actor, domain, title, who=None, due=None, every=None, amount=None, provider=None, notes=None):
    _adult(actor)
    domain = _clean(v.one_of(life.DOMAINS), domain, "type")
    title = _clean(v.text(120), title, "what")
    due = _opt(v.iso_date, due, "due date")
    every = _opt(v.integer(1, 600), every, "repeat months")
    amount = _opt(v.money(0, 1e7), amount, "cost")
    provider = _opt(v.text(80), provider, "where / who")
    notes = _opt(v.text(300), notes, "notes")
    with _con() as con:
        who = _member_name(con, who)
        cur = con.execute("INSERT INTO life_items(domain, member, title, due_date, recur_months, lead_days, amount, provider, notes) "
                          "VALUES (?,?,?,?,?,14,?,?,?)", (domain, who, title, due, every, amount, provider, notes))
        _log(actor, "life_add", f"id={cur.lastrowid} domain={domain}")
    return f"Added '{title}'."


@edits
def appointment_add(actor, who, when, provider=None, purpose=None, followup=None):
    """A doctor, dentist, vet or other visit at a date and time (`when` = 'YYYY-MM-DD HH:MM'), for a family member."""
    _adult(actor)
    when = _clean(v.iso_datetime, when, "when")
    provider = _opt(v.text(80), provider, "with")
    purpose = _opt(v.text(80), purpose, "what for")
    followup = _opt(v.iso_date, followup, "follow-up")
    with _con() as con:
        name = _member_name(con, who)
        if not name:
            raise EditError("for: say who the appointment is for")
        dup = con.execute("SELECT id FROM appointments WHERE person=? AND appt_datetime=?", (name, when)).fetchone()
        if dup:
            raise EditError("already recorded: an appointment at that time")
        cur = con.execute("INSERT INTO appointments(person, provider, purpose, appt_datetime, followup_due) VALUES (?,?,?,?,?)",
                          (name, provider, purpose, when, followup))
        _log(actor, "appointment_add", f"id={cur.lastrowid}")
    return f"Added the appointment for {name} on {when}."


@edits
def event_add(actor, name, date, yearly=None, start_time=None, end_time=None):
    """A date to remember (anniversary, tax filing, renewal) or a family event at a time of day (family dinner 8 to
    8:30 PM; nobody in particular: a visit for one person is appointment_add). yearly = it comes round every year on
    that day; left out = every year for a date, once for an event with a time. A date sent as 'YYYY-MM-DD HH:MM' gives
    the start time when start_time is not given."""
    _adult(actor)
    name = _clean(v.text(80), name, "what")
    date = str(date if date is not None else "").strip()
    if len(date) > 10 and start_time in (None, ""):
        date, start_time = date[:10], date[10:].strip(" T")
    date = _clean(v.iso_date, date, "date")
    start = _opt(v.clock_time, start_time, "starts")
    end = _opt(v.clock_time, end_time, "ends")
    if end and not start:
        raise EditError("ends: say when it starts too")
    if end and end <= start:
        raise EditError("ends: must be after it starts")
    yearly = not start if yearly is None else bool(yearly)
    with _con() as con:
        dup = con.execute("SELECT id FROM events WHERE lower(name)=lower(?) AND event_date=? AND COALESCE(start_time, '')=?",
                          (name, date, start or "")).fetchone()
        if dup:
            raise EditError("already recorded: that date" + (" and time" if start else ""))
        cur = con.execute("INSERT INTO events(name, event_date, recurs_yearly, start_time, end_time) VALUES (?,?,?,?,?)",
                          (name, date, 1 if yearly else 0, start, end))
        _log(actor, "event_add", f"id={cur.lastrowid}")
    return f"Added {name} on {date}" + (f", {dates.time_span(start, end)}" if start else "") + "."


@edits
def appointment_move(actor, appt_id, date):
    """Move an appointment to another day, keeping its time (the Inbox: a change made in Google Calendar)."""
    _adult(actor)
    day = _clean(v.iso_date, date, "date")
    with _con() as con:
        r = con.execute("SELECT person, purpose, appt_datetime FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not r:
            raise EditError("that appointment is no longer on record")
        when = f"{day}{str(r[2] or '')[10:16]}"
        con.execute("UPDATE appointments SET appt_datetime=? WHERE id=?", (when, appt_id))
        _log(actor, "appointment_move", f"id={appt_id}")
    return f"Moved {r[1] or 'the appointment'} ({r[0]}) to {dates.day_text(day)}."


@edits
def event_move(actor, event_id, date):
    """Move a family event (a yearly one: from that year on) to another day, keeping its time."""
    _adult(actor)
    day = _clean(v.iso_date, date, "date")
    with _con() as con:
        r = con.execute("SELECT name FROM events WHERE id=?", (event_id,)).fetchone()
        if not r:
            raise EditError("that event is no longer on record")
        con.execute("UPDATE events SET event_date=? WHERE id=?", (day, event_id))
        _log(actor, "event_move", f"id={event_id}")
    return f"Moved {r[0]} to {dates.day_text(day)}."


@edits
def appointment_update(actor, appt_id, who, when, provider=None, purpose=None, followup=None):
    """Correct an appointment (who, 'YYYY-MM-DD HH:MM', with, what for, follow-up). Blank with / what for / follow-up clears it."""
    _adult(actor)
    when = _clean(v.iso_datetime, when, "when")
    provider = _opt(v.text(80), provider, "with")
    purpose = _opt(v.text(80), purpose, "what for")
    followup = _opt(v.iso_date, followup, "follow-up")
    with _con() as con:
        if not con.execute("SELECT 1 FROM appointments WHERE id=?", (appt_id,)).fetchone():
            raise EditError("that appointment is no longer on record")
        name = _member_name(con, who)
        if not name:
            raise EditError("for: say who the appointment is for")
        if con.execute("SELECT 1 FROM appointments WHERE person=? AND appt_datetime=? AND id!=?", (name, when, appt_id)).fetchone():
            raise EditError("already recorded: an appointment at that time")
        con.execute("UPDATE appointments SET person=?, provider=?, purpose=?, appt_datetime=?, followup_due=? WHERE id=?",
                    (name, provider, purpose, when, followup, appt_id))
        _log(actor, "appointment_update", f"id={appt_id}")
    return f"Saved the appointment for {name} on {when}."


@edits
def appointment_drop(actor, appt_id):
    """Remove an appointment that was added by mistake."""
    _adult(actor)
    with _con() as con:
        r = con.execute("SELECT person, purpose, appt_datetime FROM appointments WHERE id=?", (appt_id,)).fetchone()
        if not r:
            raise EditError("that appointment is no longer on record")
        con.execute("DELETE FROM appointments WHERE id=?", (appt_id,))
        _log(actor, "appointment_drop", f"id={appt_id}")
    return f"Removed {r[1] or 'the appointment'} ({r[0]}) on {str(r[2])[:10]}."


@edits
def event_update(actor, event_id, name, date, yearly=None, start_time=None, end_time=None):
    """Correct a family event or yearly date: same checks as event_add. yearly left out = every year for a date, once for
    an event with a time."""
    _adult(actor)
    name = _clean(v.text(80), name, "what")
    date = _clean(v.iso_date, date, "date")
    start = _opt(v.clock_time, start_time, "starts")
    end = _opt(v.clock_time, end_time, "ends")
    if end and not start:
        raise EditError("ends: say when it starts too")
    if end and end <= start:
        raise EditError("ends: must be after it starts")
    yearly = not start if yearly is None else bool(yearly)
    with _con() as con:
        if not con.execute("SELECT 1 FROM events WHERE id=?", (event_id,)).fetchone():
            raise EditError("that event is no longer on record")
        if con.execute("SELECT 1 FROM events WHERE lower(name)=lower(?) AND event_date=? AND COALESCE(start_time, '')=? AND id!=?",
                       (name, date, start or "", event_id)).fetchone():
            raise EditError("already recorded: that date" + (" and time" if start else ""))
        con.execute("UPDATE events SET name=?, event_date=?, recurs_yearly=?, start_time=?, end_time=? WHERE id=?",
                    (name, date, 1 if yearly else 0, start, end, event_id))
        _log(actor, "event_update", f"id={event_id}")
    return f"Saved {name} on {date}" + (f", {dates.time_span(start, end)}" if start else "") + "."


@edits
def event_drop(actor, event_id):
    """Remove a family event or yearly date that was added by mistake."""
    _adult(actor)
    with _con() as con:
        r = con.execute("SELECT name, event_date FROM events WHERE id=?", (event_id,)).fetchone()
        if not r:
            raise EditError("that event is no longer on record")
        con.execute("DELETE FROM events WHERE id=?", (event_id,))
        _log(actor, "event_drop", f"id={event_id}")
    return f"Removed {r[0]} ({r[1]})."


@edits
def life_update(actor, item_id, **fields):
    """fields: title, who, due, every, amount, provider, notes. Omitted = unchanged; "" = clear (not for title)."""
    _adult(actor)
    unknown = set(fields) - {"title", "who", "due", "every", "amount", "provider", "notes"}
    if unknown:
        raise EditError(f"cannot change: {', '.join(sorted(unknown))}")
    with _con() as con:
        old = _item(con, item_id)
        sets = {}
        if "title" in fields:
            sets["title"] = _clean(v.text(120), fields["title"], "what")
        if "who" in fields:
            sets["member"] = _member_name(con, fields["who"] or None)
        if "due" in fields:
            sets["due_date"] = _opt(v.iso_date, fields["due"], "due date")
        if "every" in fields:
            sets["recur_months"] = _opt(v.integer(1, 600), fields["every"], "repeat months")
        if "amount" in fields:
            sets["amount"] = _opt(v.money(0, 1e7), fields["amount"], "cost")
        if "provider" in fields:
            sets["provider"] = _opt(v.text(80), fields["provider"], "where / who")
        if "notes" in fields:
            sets["notes"] = _opt(v.text(300), fields["notes"], "notes")
        changed = {k: x for k, x in sets.items() if old[k] != x}
        if not changed:
            return "Nothing changed."
        con.execute(f"UPDATE life_items SET {', '.join(k + '=?' for k in changed)} WHERE id=?", (*changed.values(), item_id))
        _log(actor, "life_update", f"id={item_id} fields={','.join(changed)}")
    return f"Saved changes to '{sets.get('title', old['title'])}'."


def _finish(con, row, when):
    if row["recur_months"]:
        nxt = life._add_months(when, row["recur_months"]).isoformat()
        con.execute("UPDATE life_items SET last_done=?, due_date=? WHERE id=?", (when.isoformat(), nxt, row["id"]))
        health_records.log_done(con, row, when, nxt)
        return f"Done. Next one: {nxt}."
    con.execute("UPDATE life_items SET last_done=?, status='done' WHERE id=?", (when.isoformat(), row["id"]))
    health_records.log_done(con, row, when)
    return "Done."


@edits
def life_done(actor, item_id, when=None):
    _adult(actor)
    day = dt.date.fromisoformat(_clean(v.iso_date, when, "date")) if when else dates.today()
    with _con() as con:
        row = _item(con, item_id)
        msg = _finish(con, row, day)
        _log(actor, "life_done", f"id={item_id}")
    return f"'{row['title']}': {msg}"


@edits
def life_done_own(actor, item_id):
    """A child or guest finishes one of THEIR OWN items in the non-financial domains the limited view shows."""
    import limited_view
    name = (actor or {}).get("name")
    if not name:
        raise EditError("sign in first")
    with _con() as con:
        row = _item(con, item_id)
        if row["member"] != name or row["domain"] not in limited_view.SAFE_DOMAINS:
            raise EditError("you can only finish your own items")
        msg = _finish(con, row, dates.today())
        _log(actor, "life_done_own", f"id={item_id}")
    return f"'{row['title']}': {msg}"


@edits
def life_drop(actor, item_id):
    _adult(actor)
    with _con() as con:
        row = _item(con, item_id)
        con.execute("UPDATE life_items SET status='dropped' WHERE id=?", (item_id,))
        _log(actor, "life_drop", f"id={item_id}")
    return f"Removed '{row['title']}'."


# ---------------------------------------------------------------- vaccinations (health_records.py)
@edits
def vaccination_add(actor, who, vaccine, given, next_due=None, provider=None, notes=None):
    """A shot given to a person or pet. A next due date keeps one reminder in life_items (Today, Calendar, digest)."""
    _adult(actor)
    vaccine = _clean(v.text(60), vaccine, "vaccine")
    given = _clean(v.iso_date, given, "given on")
    next_due = _opt(v.iso_date, next_due, "next due")
    provider = _opt(v.text(80), provider, "clinic or vet")
    notes = _opt(v.text(200), notes, "notes")
    if next_due and next_due <= given:
        raise EditError("next due: must be after the day it was given")
    with _con() as con:
        who = _member_name(con, who)
        if not who:
            raise EditError("for: pick a family member")
        if con.execute("SELECT 1 FROM vaccinations WHERE status='active' AND member=? AND lower(vaccine)=lower(?) AND given_on=?",
                       (who, vaccine, given)).fetchone():
            raise EditError(f"{who} already has {vaccine} on {given}")
        # an older shot (an old vaccine card typed in later) is history only: it never closes or moves today's reminder
        newest = con.execute("SELECT MAX(given_on) FROM vaccinations WHERE status='active' AND member=? AND lower(vaccine)=lower(?)",
                             (who, vaccine)).fetchone()[0]
        item = health_records.sync_reminder(con, who, vaccine, next_due, provider) if not newest or given >= newest else None
        rid = con.execute("INSERT INTO vaccinations(member, vaccine, given_on, next_due, provider, notes, life_item_id) "
                          "VALUES (?,?,?,?,?,?,?)", (who, vaccine, given, next_due, provider, notes, item)).lastrowid
        _log(actor, "vaccination_add", f"id={rid}")
    return f"Saved {vaccine} for {who}." + (f" Next one: {next_due}." if next_due else "")


@edits
def vaccination_drop(actor, rid):
    _adult(actor)
    with _con() as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM vaccinations WHERE id=? AND status='active'", (rid,)).fetchone()
        if not row:
            raise EditError("that record is not on file")
        con.execute("UPDATE vaccinations SET status='dropped' WHERE id=?", (row["id"],))
        # the reminder follows the newest shot still on file: its next due date, or closed when it has none (or none is left)
        if row["life_item_id"]:
            newest = con.execute("SELECT id, next_due FROM vaccinations WHERE status='active' AND member=? AND lower(vaccine)=lower(?) "
                                 "ORDER BY given_on DESC, id DESC LIMIT 1", (row["member"], row["vaccine"])).fetchone()
            if newest and newest["next_due"]:
                con.execute("UPDATE life_items SET due_date=? WHERE id=? AND status='open'", (newest["next_due"], row["life_item_id"]))
                con.execute("UPDATE vaccinations SET life_item_id=? WHERE id=?", (row["life_item_id"], newest["id"]))
            else:
                con.execute("UPDATE life_items SET status='dropped' WHERE id=? AND status='open'", (row["life_item_id"],))
        _log(actor, "vaccination_drop", f"id={row['id']}")
    return f"Removed {row['vaccine']} for {row['member']}."


# ---------------------------------------------------------------- weekly activities (activities.py)
def _days(x):
    import activities
    return activities.parse_days(x)


def _time(x):
    import activities
    return activities.parse_time(x)


def _activity(con, sid):
    con.row_factory = sqlite3.Row
    try:
        sid = int(sid)
    except (TypeError, ValueError):
        raise EditError("that class no longer exists") from None
    r = con.execute("SELECT * FROM activity_schedules WHERE id=? AND status='active'", (sid,)).fetchone()
    if not r:
        raise EditError("that class no longer exists (or its season has ended)")
    return r


def _activity_fields(con, fields):
    """Validated columns from the activity form fields that were given."""
    sets = {}
    if "title" in fields:
        sets["title"] = _clean(v.text(80), fields["title"], "what")
    if "who" in fields:
        sets["member"] = _member_name(con, fields["who"] or None)
    if "weekdays" in fields:
        sets["weekdays"] = _clean(_days, fields["weekdays"], "days")
    if "start_time" in fields:
        sets["start_time"] = _opt(_time, fields["start_time"], "starts")
    if "end_time" in fields:
        sets["end_time"] = _opt(_time, fields["end_time"], "ends")
    if "provider" in fields:
        sets["provider"] = _opt(v.text(80), fields["provider"], "where")
    if "term_start" in fields:
        sets["term_start"] = _opt(v.iso_date, fields["term_start"], "first day")
    if "term_end" in fields:
        sets["term_end"] = _opt(v.iso_date, fields["term_end"], "last day")
    if "school_days" in fields:
        sets["school_days"] = 1 if str(fields["school_days"]).lower() in ("1", "on", "yes", "true") else 0
    return sets


def _activity_check(row):
    if row.get("start_time") and row.get("end_time") and row["end_time"] <= row["start_time"]:
        raise EditError("ends: must be after it starts")
    if row.get("term_start") and row.get("term_end") and row["term_end"] < row["term_start"]:
        raise EditError("last day: must be on or after the first day")


@edits
def activity_add(actor, title, weekdays, who=None, start_time=None, end_time=None, provider=None, term_start=None,
                 term_end=None, school_days=False):
    """A class, sport, lesson or club that repeats every week."""
    _adult(actor)
    with _con() as con:
        sets = _activity_fields(con, {"title": title, "who": who, "weekdays": weekdays, "start_time": start_time,
                                      "end_time": end_time, "provider": provider, "term_start": term_start,
                                      "term_end": term_end, "school_days": school_days})
        _activity_check(sets)
        cur = con.execute(f"INSERT INTO activity_schedules({', '.join(sets)}) VALUES ({', '.join('?' * len(sets))})",
                          tuple(sets.values()))
        _log(actor, "activity_add", f"id={cur.lastrowid}")
    import activities
    return f"Added {activities.summary(sets)}."


@edits
def activity_update(actor, sched_id, **fields):
    """fields: title, who, weekdays, start_time, end_time, provider, term_start, term_end, school_days.
    Omitted = unchanged; "" = clear (not for title or weekdays)."""
    _adult(actor)
    unknown = set(fields) - {"title", "who", "weekdays", "start_time", "end_time", "provider", "term_start", "term_end",
                             "school_days"}
    if unknown:
        raise EditError(f"cannot change: {', '.join(sorted(unknown))}")
    with _con() as con:
        old = _activity(con, sched_id)
        sets = _activity_fields(con, fields)
        _activity_check({**dict(old), **sets})
        changed = {k: x for k, x in sets.items() if old[k] != x}
        if not changed:
            return "Nothing changed."
        con.execute(f"UPDATE activity_schedules SET {', '.join(k + '=?' for k in changed)} WHERE id=?",
                    (*changed.values(), old["id"]))
        _log(actor, "activity_update", f"id={old['id']} fields={','.join(changed)}")
    return f"Saved changes to '{sets.get('title', old['title'])}'."


@edits
def activity_skip(actor, sched_id, day):
    """One cancelled lesson: the class is left out on that date."""
    _adult(actor)
    day = _clean(v.iso_date, day, "date")
    with _con() as con:
        old = _activity(con, sched_id)
        have = [s for s in (old["skip_dates"] or "").split(",") if s]
        if day in have:
            return f"'{old['title']}' is already off on {day}."
        keep = sorted(set(have + [day]))[-60:]  # the newest 60 are plenty
        con.execute("UPDATE activity_schedules SET skip_dates=? WHERE id=?", (",".join(keep), old["id"]))
        _log(actor, "activity_skip", f"id={old['id']}")
    return f"'{old['title']}' is off on {day}."


@edits
def activity_end(actor, sched_id):
    """The season is over: the schedule stays in the records, marked ended."""
    _adult(actor)
    with _con() as con:
        old = _activity(con, sched_id)
        con.execute("UPDATE activity_schedules SET status='ended' WHERE id=?", (old["id"],))
        _log(actor, "activity_end", f"id={old['id']}")
    return f"'{old['title']}' has ended."


# ---------------------------------------------------------------- holidays, festivals, school days off (calendar_days.py)
CALENDAR_KINDS = ("holiday", "festival", "closure", "early")


@edits
def calendar_day_add(actor, day, name, kind="holiday", end=None, who=None):
    """A holiday, festival, school closure or early dismissal (end = last day of a span, e.g. a school break)."""
    _adult(actor)
    day = _clean(v.iso_date, day, "date")
    name = _clean(v.text(80), name, "name")
    kind = _clean(v.one_of(CALENDAR_KINDS), kind or "holiday", "kind")
    end = _opt(v.iso_date, end, "last day")
    if end and end < day:
        raise EditError("last day: must be on or after the first day")
    if end and (dt.date.fromisoformat(end) - dt.date.fromisoformat(day)).days > 120:
        raise EditError("last day: a span of more than 120 days is not a break")
    end = None if end == day else end
    with _con() as con:
        who = _member_name(con, who)
        old = con.execute("SELECT id, status FROM calendar_days WHERE day=? AND kind=? AND name=? "
                          "AND IFNULL(member, '')=IFNULL(?, '')", (day, kind, name, who)).fetchone()
        if old and old[1] == "active":
            return f"'{name}' on {day} is already on the calendar."
        if old:
            con.execute("UPDATE calendar_days SET status='active', end_day=?, source='manual' WHERE id=?", (end, old[0]))
            rid = old[0]
        else:
            rid = con.execute("INSERT INTO calendar_days(day, end_day, kind, name, member, source) VALUES (?,?,?,?,?,'manual')",
                              (day, end, kind, name, who)).lastrowid
        _log(actor, "calendar_day_add", f"id={rid} kind={kind}")
    return f"Added '{name}' on {day}" + (f" to {end}" if end else "") + "."


@edits
def calendar_day_update(actor, day_id, day, name, kind="holiday", end=None, who=None):
    """Change a calendar day (holiday, festival, school closure, early dismissal): same checks as calendar_day_add."""
    _adult(actor)
    try:
        day_id = int(day_id)
    except (TypeError, ValueError):
        raise EditError("that day is not on the calendar") from None
    day = _clean(v.iso_date, day, "date")
    name = _clean(v.text(80), name, "name")
    kind = _clean(v.one_of(CALENDAR_KINDS), kind or "holiday", "kind")
    end = _opt(v.iso_date, end, "last day")
    if end and end < day:
        raise EditError("last day: must be on or after the first day")
    if end and (dt.date.fromisoformat(end) - dt.date.fromisoformat(day)).days > 120:
        raise EditError("last day: a span of more than 120 days is not a break")
    end = None if end == day else end
    with _con() as con:
        if not con.execute("SELECT 1 FROM calendar_days WHERE id=? AND status='active'", (day_id,)).fetchone():
            raise EditError("that day is not on the calendar")
        who = _member_name(con, who)
        if con.execute("SELECT 1 FROM calendar_days WHERE day=? AND kind=? AND name=? AND IFNULL(member, '')=IFNULL(?, '') "
                       "AND status='active' AND id!=?", (day, kind, name, who, day_id)).fetchone():
            raise EditError(f"'{name}' on {day} is already on the calendar")
        con.execute("UPDATE calendar_days SET day=?, end_day=?, kind=?, name=?, member=?, source='manual' WHERE id=?",
                    (day, end, kind, name, who, day_id))
        _log(actor, "calendar_day_update", f"id={day_id} kind={kind}")
    return f"Saved '{name}' on {day}" + (f" to {end}" if end else "") + "."


@edits
def calendar_day_drop(actor, day_id):
    _adult(actor)
    try:
        day_id = int(day_id)
    except (TypeError, ValueError):
        raise EditError("that day is not on the calendar") from None
    with _con() as con:
        r = con.execute("SELECT name FROM calendar_days WHERE id=? AND status!='dropped'", (day_id,)).fetchone()
        if not r:
            raise EditError("that day is not on the calendar")
        con.execute("UPDATE calendar_days SET status='dropped' WHERE id=?", (day_id,))
        _log(actor, "calendar_day_drop", f"id={day_id}")
    return f"Removed '{r[0]}'."


@edits
def calendar_days_decide(actor, ids, accept):
    """Accept (active) or turn down (dropped) proposed days, e.g. one tradition's dates for a year or one school
    calendar. Only rows still 'proposed' change."""
    _adult(actor)
    try:
        ids = sorted({int(i) for i in ids})[:400]
    except (TypeError, ValueError):
        raise EditError("those days are not waiting for review") from None
    if not ids:
        raise EditError("those days are not waiting for review")
    with _con() as con:
        marks = ",".join("?" * len(ids))
        n = con.execute(f"UPDATE calendar_days SET status=? WHERE status='proposed' AND id IN ({marks})",
                        ("active" if accept else "dropped", *ids)).rowcount
        _log(actor, "calendar_days_accept" if accept else "calendar_days_dismiss", f"n={n}")
    if not n:
        return "Those days were already decided."
    return f"Added {n} day{'s' if n != 1 else ''} to the calendar." if accept else f"Left out {n} day{'s' if n != 1 else ''}."


# ---------------------------------------------------------------- people
def _write_member_config(name, updates, create=False):
    """Mirror a member change into config/family.json (atomic replace); members.py sync copies from there."""
    with config.family_edit() as data:  # a family.json that does not parse is refused (it used to become {})
        ms = data.setdefault("members", [])
        entry = next((m for m in ms if (m.get("name") or "").strip().lower() == name.lower()), None)
        if entry is None:
            if not create:
                return
            entry = {"name": name}
            ms.append(entry)
        entry.update(updates)


# every (table, column) that holds a member's name as the key of a row: a rename follows them (data/purge.py lists the same)
RENAME_COLUMNS = (("saved_items", "owner"), ("life_items", "member"), ("appointments", "person"), ("id_documents", "person"),
                  ("contracts", "person"), ("home_office_expenses", "who"), ("home_office_profile", "who"),
                  ("recurring_items", "who"), ("seasonal_tasks", "who"), ("chat_links", "member"), ("chat_invites", "member"),
                  ("device_pairings", "member"), ("devices", "member"), ("policy_drivers", "name"),
                  ("mobile_bill_lines", "person"), ("mobile_bill_lines", "member"), ("activity_schedules", "member"),
                  ("calendar_days", "member"), ("member_info", "member"), ("transactions", "cardholder"),
                  ("accounts", "owner"), ("vehicles", "owner"), ("vehicles", "primary_driver"),
                  ("policy_vehicles", "assigned_driver"), ("lists", "created_by"), ("list_items", "assigned_to"),
                  ("list_items", "added_by"), ("list_items", "done_by"), ("chat_log", "member"), ("recipes", "added_by"),
                  ("meal_plan", "added_by"), ("proposals", "decided_by"), ("devices", "created_by"),
                  ("device_pairings", "created_by"), ("wallet_cards", "member"), ("vaccinations", "member"), ("audit_runs", "actor"),
                  ("audit_fixes", "done_by"), ("audit_fixes", "undone_by"), ("routines", "member"),
                  ("routine_done", "done_by"), ("walls", "created_by"), ("wall_pairings", "created_by"),
                  ("rewards", "member"), ("reward_claims", "member"), ("reward_claims", "asked_by"),
                  ("reward_claims", "decided_by"))
MEMBER_TEXT = {"school": (80, "school"), "grade": (40, "grade or year"), "relation": (40, "relation")}


def _rename_member(con, old, new):
    """members row, every table that keys rows by the name, and config/family.json (members + sign-in users)."""
    for table, col in RENAME_COLUMNS:  # case-insensitive, as purge.py matches the name
        try:
            con.execute(f"UPDATE {table} SET {col}=? WHERE {col}=? COLLATE NOCASE", (new, old))
        except sqlite3.OperationalError as e:
            if not db.missing(e):
                raise
    try:  # the person's allowance line (data/budget.py "allowance:<name>")
        con.execute("UPDATE OR IGNORE budget SET category=? WHERE lower(category)=lower(?)",
                    ("allowance:" + new, "allowance:" + old))
    except sqlite3.OperationalError as e:
        if not db.missing(e):
            raise
    if not (config.CONFIG_DIR / "family.json").exists():
        return
    with config.family_edit() as data:
        for m in data.get("members", []):
            if (m.get("name") or "").strip() == old:
                m["name"] = new
        for u in data.get("dashboard_users", []):
            if u.get("name") == old:
                u["name"] = new
        goals = (data.get("wall") or {}).get("goals") or {}  # a child's Mitra Wall goal (wall.goals)
        if old in goals:
            goals[new] = goals.pop(old)


@edits
def member_update(actor, name, role=None, birthday=None, year=None, new_name=None, school=None, grade=None,
                  grad_year=None, relation=None):
    """birthday: MM-DD ("" clears); year: 1900..this year ("" clears); role: adult|child|pet; new_name corrects the name
    (a rename follows the person through every record); school, grade, grad_year, relation: "" clears."""
    _adult(actor)
    with _con() as con:
        canon = mem.resolve(con, name)
        if canon not in mem.names(con):
            raise EditError(f"'{name}' is not a family member")
        upd, extra = {}, {}
        if role is not None:
            upd["role"] = _clean(v.one_of(ROLES), role, "role")
        if birthday is not None:
            upd["birth_month_day"] = _opt(v.month_day, birthday, "birthday") or ""
        if year is not None:
            upd["birth_year"] = _opt(v.integer(1900, dates.today().year), year, "birth year")
        for key, val in (("school", school), ("grade", grade), ("relation", relation)):
            if val is not None:
                extra[key] = _opt(v.text(MEMBER_TEXT[key][0]), val, MEMBER_TEXT[key][1])
        if grad_year is not None:
            extra["grad_year"] = _opt(v.integer(1950, dates.today().year + 15), grad_year, "graduation year")
        renamed = None
        if new_name is not None and str(new_name).strip() and str(new_name).strip() != canon:
            renamed = _clean(v.text(40), new_name, "name")
            if renamed.lower() != canon.lower() and renamed.lower() in [n.lower() for n in mem.names(con)]:
                raise EditError(f"{renamed} is already in the family")
        if not upd and not extra and not renamed:
            return "Nothing changed."
        if upd or extra:
            both = {**upd, **extra}
            con.execute(f"UPDATE members SET {', '.join(k + '=?' for k in both)} WHERE name=?", (*both.values(), canon))
        if upd:
            _write_member_config(canon, upd)
        if renamed:
            con.execute("UPDATE members SET name=? WHERE name=?", (renamed, canon))
            _rename_member(con, canon, renamed)
        _log(actor, "member_update", f"name={renamed or canon} fields={','.join([*upd, *extra, *(['name'] if renamed else [])])}")
    if renamed:
        return (f"Saved. {canon} is now {renamed} everywhere. Papers already filed keep the old spelling; "
                f"{renamed} signs in with the new name.")
    return f"Saved {canon}."


HOUSEHOLD = {"tenure": ("own", "rent")}


@edits
def household_set(actor, field, value):
    """Household facts asked by the profile questions (config/family.json "household"): tenure own|rent."""
    _adult(actor)
    if field not in HOUSEHOLD:
        raise EditError("that is not a household fact")
    value = _clean(v.one_of(list(HOUSEHOLD[field])), value, field)
    with config.family_edit() as data:
        data["household"] = {**(data.get("household") or {}), field: value}
    _log(actor, "household_set", f"field={field}")
    return {"own": "Saved: you own your home.", "rent": "Saved: you rent your home."}.get(value, "Saved.")


_NOT_SECRET = re.compile(r"\b(password|passcode|pin)\s*(is|=|:)|\d{8,}", re.I)


@edits
def emergency_where_set(actor, values):
    """The emergency sheet's "Where things are" (config/family.json emergency.where): places and names only. Blank
    clears a line; text that looks like a password or a long number is refused. Logged by field name."""
    import emergency_sheet as es
    _adult(actor)
    out = {}
    for k, label in es.WHERE:
        text = " ".join(str((values or {}).get(k) or "").split())
        if len(text) > es.WHERE_MAX:
            raise EditError(f"{label}: at most {es.WHERE_MAX} characters")
        if _NOT_SECRET.search(text):
            raise EditError(f"{label}: write where it is or who has it, never a password, PIN or full number")
        if text:
            out[k] = text
    with config.family_edit() as data:
        data["emergency"] = {**(data.get("emergency") or {}), "where": out}
    _log(actor, "emergency_where_set", "fields=" + (",".join(out) or "none"))
    return "Saved. The emergency sheet shows it now."


@edits
def vehicle_add(actor, make, model, year=None):
    """A car or other vehicle from the first-run questions. The same year, make and model is not added twice."""
    _adult(actor)
    make = _clean(v.text(40), make, "make")
    model = _clean(v.text(60), model, "model")
    year = _opt(v.integer(1950, dates.today().year + 1), year, "year")
    with _con() as con:
        same = con.execute("SELECT id FROM vehicles WHERE LOWER(make)=LOWER(?) AND LOWER(model)=LOWER(?) "
                           "AND COALESCE(year,0)=COALESCE(?,0) AND COALESCE(status,'active')='active'", (make, model, year)).fetchone()
        if same:
            return f"{make} {model} is already listed."
        cur = con.execute("INSERT INTO vehicles(year, make, model, status) VALUES (?,?,?, 'active')", (year, make, model))
        _log(actor, "vehicle_add", f"id={cur.lastrowid}")
    return f"Added {' '.join(str(x) for x in (year, make, model) if x)}."


VEHICLE_KINDS = ["oil_change", "tires", "rotation", "brakes", "battery", "cabin_filter", "brake_fluid", "inspection",
                 "registration", "repair", "car_wash", "other"]


@edits
def vehicle_service(actor, vehicle_id, kind, when=None, odometer=None, cost=None, vendor=None):
    """Log a service on a car (the same row as `data/vehicle_log.py log`); the next due date follows from it."""
    _adult(actor)
    kind = _clean(v.one_of(VEHICLE_KINDS), kind, "service")
    when = _opt(v.iso_date, when, "date") or dates.today().isoformat()
    if when > dates.today().isoformat():
        raise EditError("date: a service that is done, so today or earlier")
    odometer = _opt(v.integer(0, 2_000_000), odometer, "odometer")
    cost = _opt(v.money(0, 100_000), cost, "cost")
    vendor = _opt(v.text(80), vendor, "shop")
    with _con() as con:
        if not con.execute("SELECT 1 FROM vehicles WHERE id=?", (vehicle_id,)).fetchone():
            raise EditError("that vehicle is not there any more")
        cur = con.execute("INSERT INTO vehicle_log(vehicle_id, log_date, kind, odometer, cost, vendor) VALUES (?,?,?,?,?,?)",
                          (vehicle_id, when, kind, odometer, cost, vendor))
        _log(actor, "vehicle_service", f"id={cur.lastrowid}")
    return f"Saved: {kind.replace('_', ' ')} on {when}."


@edits
def member_add(actor, name, role="adult", birthday=None, year=None):
    _adult(actor)
    name = _clean(v.text(40), name, "name")
    role = _clean(v.one_of(ROLES), role, "role")
    bd = _opt(v.month_day, birthday, "birthday") or ""
    by = _opt(v.integer(1900, dates.today().year), year, "birth year")
    with _con() as con:
        if name.lower() in [n.lower() for n in mem.names(con)]:
            raise EditError(f"{name} is already in the family")
        con.execute("INSERT INTO members(name, role, birth_month_day, birth_year) VALUES (?,?,?,?)", (name, role, bd, by))
        _write_member_config(name, {"role": role, "birth_month_day": bd, "birth_year": by}, create=True)
        _log(actor, "member_add", f"name={name} role={role}")
    return f"Added {name}."


# ---------------------------------------------------------------- critical information (member_info.py)
INFO_CATEGORIES = ("emergency", "medical", "school", "other")


def _info(con, rid):
    try:
        rid = int(rid)
    except (TypeError, ValueError):
        raise EditError("that fact is not on file") from None
    r = con.execute("SELECT id, member, category, label, value FROM member_info WHERE id=? AND status='active'",
                    (rid,)).fetchone()
    if not r:
        raise EditError("that fact is not on file")
    return r


@edits
def member_info_add(actor, who, category, label, value):
    """One fact about a person (a pet too): emergency contact, allergy, doctor, school. Counts as confirmed today."""
    _adult(actor)
    category = _clean(v.one_of(INFO_CATEGORIES), category or "other", "category")
    label = _clean(v.text(60), label, "what it is")
    value = _clean(v.text(200), value, "the fact")
    today = dates.today().isoformat()
    with _con() as con:
        who = _member_name(con, who)
        if not who:
            raise EditError("for: pick a family member")
        old = con.execute("SELECT id FROM member_info WHERE member=? AND category=? AND label=? AND status='active'",
                          (who, category, label)).fetchone()
        if old:
            raise EditError(f"{who} already has '{label}': change that one")
        rid = con.execute("INSERT INTO member_info(member, category, label, value, verified_on, created_at) VALUES (?,?,?,?,?,strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))",
                          (who, category, label, value, today)).lastrowid
        _log(actor, "member_info_add", f"id={rid} category={category}")
    return f"Saved '{label}' for {who}."


@edits
def member_info_update(actor, rid, label=None, value=None, category=None):
    """Change a fact; it counts as confirmed today."""
    _adult(actor)
    with _con() as con:
        old = _info(con, rid)
        new = {"label": old[3] if label is None else _clean(v.text(60), label, "what it is"),
               "value": old[4] if value is None else _clean(v.text(200), value, "the fact"),
               "category": old[2] if not category else _clean(v.one_of(INFO_CATEGORIES), category, "category")}
        if (new["label"], new["category"]) != (old[3], old[2]) and con.execute(
                "SELECT 1 FROM member_info WHERE member=? AND category=? AND label=? AND status='active' AND id!=?",
                (old[1], new["category"], new["label"], old[0])).fetchone():
            raise EditError(f"{old[1]} already has '{new['label']}'")
        changed = [k for k, i in (("label", 3), ("value", 4), ("category", 2)) if new[k] != old[i]]
        con.execute("UPDATE member_info SET label=?, value=?, category=?, verified_on=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id=?",
                    (new["label"], new["value"], new["category"], dates.today().isoformat(), old[0]))
        _log(actor, "member_info_update", f"id={old[0]} fields={','.join(changed) or 'none'}")
    return f"Saved. '{new['label']}' for {old[1]} is confirmed today."


@edits
def member_info_verify(actor, rids=None, who=None):
    """'Still correct': confirm facts by id, or every active fact of one person (who)."""
    _adult(actor)
    today = dates.today().isoformat()
    with _con() as con:
        if who:
            who = _member_name(con, who)
            ids = [r[0] for r in con.execute("SELECT id FROM member_info WHERE member=? AND status='active'", (who,))]
        else:
            ids = []
            for rid in rids or []:
                try:
                    ids.append(int(rid))
                except (TypeError, ValueError):
                    raise EditError("that fact is not on file") from None
        if not ids:
            raise EditError("nothing to confirm")
        marks = ",".join("?" * len(ids))
        n = con.execute(f"UPDATE member_info SET verified_on=? WHERE status='active' AND id IN ({marks})",
                        [today, *ids]).rowcount
        if not n:
            raise EditError("that fact is not on file")
        _log(actor, "member_info_verify", f"n={n}")
    return f"Confirmed {n} fact{'s' if n != 1 else ''} as still correct."


@edits
def member_info_drop(actor, rid):
    _adult(actor)
    with _con() as con:
        old = _info(con, rid)
        con.execute("UPDATE member_info SET status='dropped', updated_at=strftime('%Y-%m-%dT%H:%M:%S','now','localtime') WHERE id=?", (old[0],))
        _log(actor, "member_info_drop", f"id={old[0]}")
    return f"Removed '{old[3]}' for {old[1]}."


# ---------------------------------------------------------------- home area, online look-ups, schools and employers
US_STATES = {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY",
             "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH",
             "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"}
STATE_NAMES = {"ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA", "COLORADO": "CO",
               "CONNECTICUT": "CT", "DELAWARE": "DE", "DISTRICT OF COLUMBIA": "DC", "FLORIDA": "FL", "GEORGIA": "GA",
               "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
               "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
               "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
               "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
               "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
               "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC", "SOUTH DAKOTA": "SD",
               "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT", "VIRGINIA": "VA", "WASHINGTON": "WA",
               "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY"}
ORG_KINDS = ("school", "college", "employer")


def us_state_code(text):
    """'nj', 'New Jersey' -> 'NJ'; '' when it is not a US state."""
    t = " ".join(str(text or "").split()).upper().replace(".", "")
    return t if t in US_STATES else STATE_NAMES.get(t, "")


@edits
def home_area_set(actor, place, state, zip_code):
    """City, state and ZIP of the home (config/family.json region; no street address is kept). The state picks the
    state holidays; the ZIP finds schools near home when online look-ups are on."""
    _adult(actor)
    place = _opt(v.text(80), place, "city or town") or ""
    state = " ".join(str(state or "").split())
    zip_code = str(zip_code or "").strip()
    with config.family_edit() as data:
        us = (data.get("country") or "US").upper() == "US"
        if us:
            state = us_state_code(state) or state.upper()
            if state and state not in US_STATES:
                raise EditError("state: use the two-letter code (NJ, TX, CA ...)")
            if zip_code and not (len(zip_code) == 5 and zip_code.isdigit()):
                raise EditError("ZIP code: five digits")
        else:
            state = _opt(v.text(60), state, "state or region") or ""
            zip_code = _opt(v.text(12), zip_code, "postal code") or ""
        reg = dict(data.get("region") or {})
        reg.update(place=place, state=state, zip=zip_code)
        data["region"] = reg
    _log(actor, "home_area_set", "fields=place,state,zip")
    return "Saved the home's city, state and ZIP code."


@edits
def lookups_set(actor, on):
    """Online look-ups for schools, colleges and calendars (lookups.py) on or off."""
    _adult(actor)
    with config.family_edit() as data:
        data["lookups"] = {**(data.get("lookups") or {}), "online": bool(on)}
    _log(actor, "lookups_set", f"online={int(bool(on))}")
    return ("Online look-ups are on. Only public names, the ZIP code and the state go out."
            if on else "Online look-ups are off. Nothing is looked up on the internet.")


def _org_fields(kind, name, ext_id=None, district=None, city=None, state=None):
    kind = _clean(v.one_of(list(ORG_KINDS)), kind, "kind")
    name = _clean(v.text(100), name, "name")
    import lookups
    why = lookups.problem(name)
    if why:
        raise EditError(f"name: {why}; type the public name of the {kind}")
    ext = str(ext_id or "").strip()[:20] or None
    if ext and not all(c.isalnum() for c in ext):
        raise EditError("that directory id is not valid")
    return {"kind": kind, "name": name, "ext_id": ext, "district": _opt(v.text(100), district, "district"),
            "city": _opt(v.text(60), city, "city"), "state": _opt(v.text(20), state, "state")}


@edits
def member_org_set(actor, member, kind, name, ext_id=None, district=None, city=None, state=None):
    """Link a person to their school, college or employer (one at a time); the name also fills the person's
    'School, college or employer'."""
    _adult(actor)
    f = _org_fields(kind, name, ext_id, district, city, state)
    with _con() as con:
        who = _member_name(con, member)
        if not who:
            raise EditError("choose a person")
        row = con.execute("SELECT id FROM orgs WHERE kind=? AND name=? AND IFNULL(city,'')=IFNULL(?,'') "
                          "AND IFNULL(state,'')=IFNULL(?,'')", (f["kind"], f["name"], f["city"], f["state"])).fetchone()
        if row:
            oid = row[0]
            con.execute("UPDATE orgs SET ext_id=COALESCE(?, ext_id), district=COALESCE(?, district) WHERE id=?",
                        (f["ext_id"], f["district"], oid))
        else:
            oid = con.execute("INSERT INTO orgs(kind, name, ext_id, district, city, state) VALUES (?,?,?,?,?,?)",
                              (f["kind"], f["name"], f["ext_id"], f["district"], f["city"], f["state"])).lastrowid
        con.execute("UPDATE members SET org_id=?, school=? WHERE name=?", (oid, f["name"][:80], who))
        _log(actor, "member_org_set", f"org={oid} kind={f['kind']}")
    return f"{who}: {f['name']} saved."


@edits
def member_org_clear(actor, member):
    _adult(actor)
    with _con() as con:
        who = _member_name(con, member)
        if not who:
            raise EditError("choose a person")
        con.execute("UPDATE members SET org_id=NULL WHERE name=?", (who,))
        _log(actor, "member_org_clear", "")
    return f"{who} is no longer linked to a school, college or employer (days already on the calendar stay)."


def _org(con, org_id):
    con.row_factory = sqlite3.Row
    r = con.execute("SELECT * FROM orgs WHERE id=?", (int(org_id),)).fetchone()
    if not r:
        raise EditError("that school, college or employer is not on record")
    return dict(r)


def _calendar_behind(raw, base, kind):
    """The best three calendar files a page links to (.ics, a PDF named for the year), tried in turn. -> (details, url)."""
    import calendar_find as cf
    import calendar_import as ci
    import lookups
    labels = cf.years()
    links = sorted(((cf.score(u, t, labels), u) for u, t in cf.links_in(raw.decode("utf-8", "replace"), base)
                    if cf.kind_of(u) != "page"), reverse=True)
    last = ci.ImportError_("the page does not show the days off itself and links to no calendar file")
    for s, u in links[:3]:
        if s < 5:
            break
        try:
            ctype, body, final = lookups.get(u)
            return ci.read(body, ctype, final, kind), final
        except (ci.ImportError_, lookups.Refused) as e:
            last = e if isinstance(e, ci.ImportError_) else ci.ImportError_(str(e))
    raise last


@edits
def org_calendar_import(actor, org_id, url=None, filename=None, body=None):
    """Read a year calendar from a public link (needs online look-ups) or a file and propose its days off for every
    person linked to the org (Inbox). -> plain words with the count."""
    _adult(actor)
    import calendar_import as ci
    import lookups
    with _con() as con:
        org = _org(con, org_id)
    try:
        if url:
            ctype, raw, final = lookups.get(str(url).strip())
            try:
                details = ci.read(raw, ctype, final, org["kind"])
            except ci.ImportError_:
                if "html" not in ctype:
                    raise
                details, final = _calendar_behind(raw, final, org["kind"])  # a page that only links to the calendar
        elif body:
            final = None
            details = ci.read(body, "", str(filename or ""), org["kind"])
        else:
            raise EditError("give the calendar's link or a file")
    except lookups.Refused as e:
        raise EditError(str(e)) from None
    except ci.ImportError_ as e:
        raise EditError(f"Nothing was added: {e}.") from None
    with _con() as con:
        org = _org(con, org_id)
        who = [r[0] for r in con.execute("SELECT name FROM members WHERE org_id=? ORDER BY name", (org["id"],))]
        n = ci.store(con, org, who, details, final if url else None)
        _log(actor, "org_calendar_import", f"org={org['id']} n={n} how={details['how']}")
    try:
        import proposals
        proposals.sync()  # the days show in the Inbox now, not at the next scheduled check
    except Exception:  # noqa: BLE001 (the days are stored; the Inbox catches up on its next sync)
        pass
    if not n:
        return "Those days are already on the calendar or waiting in the Inbox."
    return (f"{n} day{'s' if n != 1 else ''} from {org['name']} {details.get('school_year') or ''} "
            f"(read from {ci.SHOWN[details['how']]}) wait in the Inbox: check them, then Add.").replace("  ", " ")
