"""Plain-language wording for the assistant (chat in the dashboard, `python data/assistant.py`, phone bots).

Everything a family member sees goes through here: what the assistant is about to change ("Set Sam's birthday to
February 2"), what it did, why something did not work, and the content of a briefing instead of its file path.
No action names, argument dictionaries, JSON, table or column names, SQL, ids or file paths reach the person; the
technical detail stays in logs/assistant.log.
"""
import datetime as dt
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
import dates  # noqa: E402
DOC_SUFFIXES = (".md", ".txt")


def nice_date(iso, today=None):
    try:
        d = dt.date.fromisoformat(str(iso))
    except ValueError:
        return str(iso)
    today = today or dates.today()
    return f"{d:%B} {d.day}" + ("" if d.year == today.year else f", {d.year}")


def nice_when(iso, today=None):
    """'2026-12-10 09:30' -> 'December 10 at 9:30 am'."""
    try:
        d = dt.datetime.strptime(str(iso), "%Y-%m-%d %H:%M")
    except ValueError:
        return str(iso)
    hour = d.hour % 12 or 12
    return f"{nice_date(d.date().isoformat(), today)} at {hour}:{d.minute:02d} {'am' if d.hour < 12 else 'pm'}"


def _md(md):
    try:
        m, d = str(md).split("-")
        return f"{dt.date(2000, int(m), int(d)):%B} {int(d)}"
    except ValueError:
        return str(md)


def _money(x):
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return str(x)


def _on(a, key="date"):
    return f" on {nice_date(a[key])}" if a.get(key) else ""


def _for(a, key="who"):
    return f" for {a[key]}" if a.get(key) else ""


TEMPLATES = {
    "members_birthday": lambda a: f"Set {a['name']}'s birthday to {_md(a['md'])}" + (f", {a['year']}" if a.get("year") else ""),
    "action_done": lambda a: "Mark that item as handled",
    "action_snooze": lambda a: f"Hide that item for {a['days']} days",
    "action_ignore": lambda a: "Hide that item for good",
    "life_add": lambda a: f"Add {a['title']}" + _for(a) + (f", due {nice_date(a['due'])}" if a.get("due") else ""),
    "life_done": lambda a: f"Mark {a['title_fragment']} as done" + _for(a) + _on(a),
    "life_set_due": lambda a: f"Move the due date of {a['title_fragment']} to {nice_date(a['due'])}" + _for(a),
    "activity_add": lambda a: f"Add {a['title']} every {a['days']}" + (f" at {a['starts']}" if a.get("starts") else "") + _for(a),
    "day_off_add": lambda a: f"Add {a['name']} on {nice_date(a['date'])}" + (f" to {nice_date(a['last_day'])}" if a.get("last_day") else "") + _for(a),
    "recurring_done": lambda a: f"Record that {a['name_fragment']} was done" + _for(a) + _on(a),
    "seasonal_done": lambda a: f"Log {a['name_fragment']} as done" + _on(a),
    "budget_set": lambda a: f"Set the {a['category']} budget to {_money(a['amount'])} a month",
    "subscription_decide": lambda a: f"Record that you decided to {a['decision']} {a['name']}",
    "shopping_add": lambda a: f"Add {a['item']} to {a['list']}",
    "shopping_bought": lambda a: f"Mark {a['item']} as bought" + (f" ({_money(a['paid'])})" if a.get("paid") is not None else ""),
    "list_add": lambda a: f"Add {a['item']} to the {a['list']} list",
    "list_done": lambda a: f"Tick off {a['item_fragment']} on the {a['list']} list",
    "saved_add": lambda a: f"Save “{a['title']}” for later",
    "home_office_profile": lambda a: f"Record home-office details for {a['who']} ({a['year']})",
    "home_office_expense": lambda a: f"Add a {a['category'].replace('_', ' ')} home-office expense of {_money(a['amount'])} ({a['year']})",
    "meal_plan": lambda a: f"Plan {a['what']} for {a['slot']} on {nice_date(a['day'])}",
    "meal_shop": lambda a: "Put the ingredients for the planned meals on the shopping list",
    "appointment_add": lambda a: f"Add an appointment for {a['who']} on {nice_when(a['when'])}"
                                 + (f" with {a['provider']}" if a.get("provider") else "") + (f" ({a['purpose']})" if a.get("purpose") else ""),
    "bill_add": lambda a: f"Add the bill {a['name']}" + (f" from {a['vendor']}" if a.get("vendor") else "")
                          + (f", {_money(a['amount'])}" if a.get("amount") is not None else ", amount not known yet")
                          + f", due {nice_date(a['due'])}" + (f", {a['frequency']}" if a.get("frequency") and a["frequency"] != "once" else ""),
    "event_add": lambda a: f"Add {a['name']} on {nice_date(a['date'])}"
                           + (f", {dates.time_span(a['starts'], a.get('ends'))}" if a.get("starts") else "")
                           + (" (every year)" if a.get("yearly", 0 if a.get("starts") else 1) else " (once)"),
    "agent_set": lambda a: _agent(a),
}


def _agent(a):
    import agent_profile as ap
    f, v = a["field"], a["value"]
    if f == "watch_on":
        return f"Show {ap.WATCH[v].lower()} on Today again"
    if f == "watch_off":
        return f"Leave {ap.WATCH[v].lower()} out of the Brief"
    if f == "tone":
        return f"Set the tone to: {ap.TONES[v].lower()}"
    if f == "weekly_day":
        return f"Send the weekly digest on {ap.DAY_NAMES[v]}"
    return {"name": f"Call the agent {v}", "brief_time": f"Make the daily brief at {v}",
            "weekly_time": f"Send the weekly digest at {v}"}[f]


def describe(name, clean, fallback=""):
    """One plain sentence for an action and its arguments."""
    try:
        return TEMPLATES[name](clean)
    except (KeyError, TypeError):
        return (fallback or "Make that change").capitalize()


def failure(name, text, write=True):
    """Why it did not work, without internals. A lookup that failed never claims anything was changed."""
    low = (text or "").lower()
    if not write:
        return "I couldn't look that up just now. Try asking in a different way, or ask for something more specific."
    if "0 matches" in low or "no match" in low or "not found" in low:
        return "I couldn't find that one. Check the name and try again."
    if "already" in low:
        return "That looks like it is already recorded."
    return "I couldn't do that one, so nothing was changed."


def document_from(text):
    """If an action's output is the path of a briefing file inside this household's folder, return its text, else None."""
    lines = (text or "").strip().splitlines()
    if not lines:
        return None
    try:
        p = pathlib.Path(lines[-1].strip()).resolve()
        p.relative_to(paths.HOME.resolve())
        if p.suffix.lower() in DOC_SUFFIXES and p.is_file():
            return p.read_text(encoding="utf-8")[:6000]
    except (OSError, ValueError):
        pass
    return None


def ai_trouble(err):
    e = str(err).lower()
    if "no api key" in e or "key" in e and "missing" in e:
        return "I don't have an AI key yet. Add one in Settings > Connections > AI provider."
    if "daily" in e and ("cap" in e or "limit" in e):
        return "I've reached today's limit for AI questions. Try again tomorrow, or raise the limit in Settings."
    if "free tier" in e or "paid" in e:
        return "The chosen AI plan isn't allowed for family documents. Check Settings > Connections > AI provider."
    return "The AI service isn't answering right now. Check Settings > Connections > AI provider, or try again in a minute."


def plain(text, limit=1500):
    """Strip folder paths from free text so a briefing or error never shows where files live."""
    t = re.sub(r"[A-Za-z]:\\[^\s]+|(?:/[\w.\-]+){2,}", "", text or "")
    return t[:limit].strip()
