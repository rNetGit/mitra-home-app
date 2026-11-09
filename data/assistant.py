"""Mitra Home assistant for ANY provider (OpenAI, Gemini, Anthropic API, local Ollama): the `family` agent without Claude Code.

  python data/assistant.py                     chat (blank line or 'quit' to leave)
  python data/assistant.py "Sam's dentist is Oct 21 at 3pm"      one request
  python data/assistant.py --yes "done a1b2c3d4"                  skip the confirmation for changes

How it stays safe:
  * The model never writes commands. It picks named actions from the fixed CATALOG below with typed arguments; this
    code validates every argument and builds the command line itself (no shell, no free text as options).
  * Changes (WRITE actions) are shown and need your "y" unless you pass --yes. Reading (SELECT-only SQL, digests) runs directly.
  * It may look things up in up to MAX_STEPS rounds: read-only actions run at once and their results go back to the model
    as DATA (fenced, untrusted) until it can answer. Changes are accepted only from the FIRST round, before any data was
    seen, so text inside a record or document can never ask for a change. Changes from all of a request are shown once
    and run exactly as shown after the OK (`run` plans, `apply` writes; nothing is planned again).
  * Memory: the caller may pass the last few turns (`history`), so "and Sam's too" works. Kept by the caller only
    (dashboard session, phone bot process memory); never written to disk.
  * Every answer carries `refs`: the records it came from (data/records.py), shown as links into Records.
  * Only the adult running this program talks to it. It sends your message and, for questions, the query result
    to the provider you chose, with identifiers masked (SSN, account/card numbers, emails, phones: data/pii.py). Family
    names are NOT masked here, because you are talking about them on purpose. See COMPLIANCE.md. Answers are
    AI-assisted records, not advice.
Needs ai.provider = anthropic | openai | gemini | openrouter | ollama (or a signed-in CLI) in config/family.json.
"""
import brand
import argparse
import datetime as dt
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import dates  # noqa: E402
import llm  # noqa: E402
import records  # noqa: E402
import assistant_voice as voice  # noqa: E402
import members  # noqa: E402
import agent_profile  # noqa: E402
import db  # noqa: E402
import schema_catalog  # noqa: E402

PY = sys.executable
MAX_STEPS = 4      # planning rounds per request (each round = one AI call)
MEMORY_TURNS = 10  # earlier turns passed back as context
HEX8 = re.compile(r"^[0-9a-f]{8}$")
DOMAINS = ["school", "activity", "medical", "prescription", "vaccine", "pet", "legal", "travel", "gift", "chore", "other"]
HO_CATS = ["rent", "mortgage_interest", "property_tax", "insurance", "utilities", "repairs", "hoa", "depreciation",
           "internet", "phone", "supplies", "equipment", "other"]


# ---------- argument validators: shared with the dashboard forms (data/validators.py); each returns the cleaned value or raises ValueError
from validators import text, iso_date, iso_datetime, clock_time, month_day, num, integer, one_of, money as money_amount  # noqa: E402,F401


SAVED_KINDS = ["link", "note", "place", "deal", "video", "repo", "article", "social"]  # data/saved.py KINDS


def web_url(x):
    """http(s) only, tracking stripped, token-carrying links refused (data/saved.py clean_url)."""
    import saved
    return saved.clean_url(x)[0] or _bad("empty URL")


def _bad(msg):
    raise ValueError(msg)


def action_id(x):
    if not HEX8.match(str(x)):
        raise ValueError("id must be 8 hex characters")
    return str(x)


def select_sql(x):
    s = str(x).strip().rstrip(";")
    if ";" in s or not re.match(r"(?is)^(select|with)\b", s) or len(s) > 1500:
        raise ValueError("one SELECT only")
    if _DENIED.search(s):
        raise ValueError("a table the chat may not read")
    return s


_DENIED = re.compile(r"(?i)\b(" + "|".join(sorted(schema_catalog.DENY)) + r")\b")
TABLE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


def table_names(x):
    """'bills, transactions' -> ['bills', 'transactions']: plain names only, at most MAX_DESCRIBE."""
    names = [n for n in re.split(r"[\s,]+", str(x).strip().lower()) if n]
    if not names or len(names) > schema_catalog.MAX_DESCRIBE or not all(TABLE_NAME.match(n) for n in names):
        raise ValueError(f"1 to {schema_catalog.MAX_DESCRIBE} table names")
    return " ".join(names)


# ---------- the catalog: name -> (write?, description, params {name: (validator, required)}, argv builder)
def argv(script, *parts):
    return [PY, str(HERE / script), *[str(p) for p in parts if p is not None]]


def opt(flag, value):
    return [flag, str(value)] if value is not None else []


EDIT_ACTIONS = set()  # actions made through data/edit_cli.py -> edit_actions, as the signed-in person (`execute` adds --as / --role)
CLI_ACTOR = {"name": "this PC", "role": "adult"}  # the adult at the terminal (`python data/assistant.py`); the app passes the signed-in person


def event_day(x):
    """event_add's date: 'YYYY-MM-DD', or 'YYYY-MM-DD HH:MM' when the model put the time there (validate_action moves
    it to starts, so the confirm card and the change both show it as a time)."""
    try:
        return iso_date(x)
    except ValueError:
        try:
            return iso_datetime(x)
        except ValueError:
            raise ValueError("date must be YYYY-MM-DD") from None


def edit(fn, **names):
    """A change made through data/edit_actions.py (role-checked, validated again, logged in logs/edits.log) like the app's
    forms, run as `python data/edit_cli.py FUNCTION '{json}'` so this module never imports the form layer (audit A9);
    `names` maps an action argument to the function's parameter when they differ."""
    EDIT_ACTIONS.add(fn)
    return lambda a: argv("edit_cli.py", fn, json.dumps({names.get(k, k): v for k, v in a.items()}, ensure_ascii=False))

CATALOG = {
    "members_birthday": (True, "set a member's birthday", {"name": (text(60), True), "md": (month_day, True), "year": (integer(1900, 2100), False)},
                         lambda a: argv("members.py", "birthday", a["name"], a["md"], *opt("--year", a.get("year")))),
    "action_done": (True, "mark a digest item (8-char Id) handled", {"id": (action_id, True)}, lambda a: argv("action_state.py", "done", a["id"])),
    "action_snooze": (True, "hide a digest item for N days", {"id": (action_id, True), "days": (integer(1, 365), True)},
                      lambda a: argv("action_state.py", "snooze", a["id"], a["days"])),
    "action_ignore": (True, "hide a digest item for good", {"id": (action_id, True)}, lambda a: argv("action_state.py", "ignore", a["id"])),
    "life_add": (True, "add a school/activity/medical/prescription/vaccine/pet/legal/travel/gift/chore item",
                 {"domain": (one_of(DOMAINS), True), "title": (text(), True), "who": (text(60), False), "due": (iso_date, False),
                  "every_months": (integer(1, 120), False), "provider": (text(), False), "amount": (money_amount(), False)},
                 lambda a: argv("life.py", "add", a["domain"], a["title"], *opt("--who", a.get("who")), *opt("--due", a.get("due")),
                                *opt("--every", a.get("every_months")), *opt("--provider", a.get("provider")), *opt("--amount", a.get("amount")))),
    "life_done": (True, "mark an item from the LIFE items list done (school, activity, appointment, a one-off task). NOT routine checkups: use recurring_done", {"title_fragment": (text(), True), "who": (text(60), False), "date": (iso_date, False)},
                  lambda a: argv("life.py", "done", a["title_fragment"], *([a["date"]] if a.get("date") else []), *opt("--who", a.get("who")))),
    "life_set_due": (True, "set the due date of a life item", {"title_fragment": (text(), True), "due": (iso_date, True), "who": (text(60), False)},
                     lambda a: argv("life.py", "set", a["title_fragment"], "--due", a["due"], *opt("--who", a.get("who")))),
    "activity_add": (True, "add a class, sport, lesson or club that repeats EVERY WEEK (swimming Mon and Wed 5pm at the YMCA, "
                     "piano on Saturdays): days like 'Mon Wed' or 'weekdays', times HH:MM, optional first/last day of the "
                     "season; school_days 1 = no class on days off school. A one-off school or activity date is life_add",
                     {"title": (text(80), True), "days": (text(60), True), "who": (text(60), False), "starts": (text(10), False),
                      "ends": (text(10), False), "where": (text(80), False), "first_day": (iso_date, False),
                      "last_day": (iso_date, False), "school_days": (integer(0, 1), False)},
                     lambda a: argv("activities.py", "add", a["title"], "--days", a["days"], *opt("--who", a.get("who")),
                                    *opt("--time", a.get("starts")), *opt("--until", a.get("ends")),
                                    *opt("--provider", a.get("where")), *opt("--from", a.get("first_day")),
                                    *opt("--to", a.get("last_day")), *(["--school-days"] if a.get("school_days") else []))),
    "day_off_add": (True, "add a holiday, festival, school closure (no school) or early dismissal day, or a break with a "
                    "last day; who = one child when it is only their school",
                    {"date": (iso_date, True), "name": (text(80), True), "kind": (one_of(["holiday", "festival", "closure", "early"]), False),
                     "last_day": (iso_date, False), "who": (text(60), False)},
                    lambda a: argv("calendar_days.py", "add", a["date"], a["name"], *opt("--kind", a.get("kind")),
                                   *opt("--end", a.get("last_day")), *opt("--who", a.get("who")))),
    "recurring_done": (True, "record that a routine checkup or home task was done on a date: dental cleaning, physical, eye exam, furnace filter, water heater flush, smoke detectors (the 'checkups that need a date' list)", {"name_fragment": (text(), True), "who": (text(60), False), "date": (iso_date, False)},
                       lambda a: argv("recurring.py", "done", a["name_fragment"], *([a["date"]] if a.get("date") else []), *opt("--who", a.get("who")))),
    "seasonal_done": (True, "log a seasonal task as done", {"name_fragment": (text(), True), "date": (iso_date, False)},
                      lambda a: argv("seasonal.py", "done", a["name_fragment"], *([a["date"]] if a.get("date") else []))),
    "budget_set": (True, "set a monthly budget limit", {"category": (text(60), True), "amount": (money_amount(), True)},
                   lambda a: argv("budget.py", "set", a["category"], a["amount"])),
    "subscription_decide": (True, "keep or cancel a subscription (records the decision only)", {"name": (text(80), True), "decision": (one_of(["keep", "cancel"]), True)},
                            lambda a: argv("subscriptions.py", "decide", a["name"], a["decision"])),
    "shopping_add": (True, "add an item to a shopping list", {"list": (text(60), True), "item": (text(80), True), "date": (iso_date, False)},
                     lambda a: argv("shopping.py", "add", a["list"], a["item"], *opt("--date", a.get("date")))),
    "shopping_bought": (True, "mark a shopping item bought (records only)", {"list": (text(60), True), "item": (text(80), True), "paid": (money_amount(), False)},
                        lambda a: argv("shopping.py", "bought", a["list"], a["item"], *opt("--paid", a.get("paid")))),
    "list_add": (True, "add an item to a shared family list (groceries, to-do, packing)",
                 {"list": (text(60), True), "item": (text(120), True), "qty": (text(20), False), "for": (text(60), False)},
                 lambda a: argv("lists.py", "add", a["list"], a["item"], *opt("--qty", a.get("qty")), *opt("--for", a.get("for")))),
    "list_done": (True, "tick an item off a shared list", {"list": (text(60), True), "item_fragment": (text(120), True)},
                  lambda a: argv("lists.py", "done", a["list"], a["item_fragment"])),
    "list_show": (False, "show the shared lists, or one list", {"list": (text(60), False)},
                  lambda a: argv("lists.py", "show", *([a["list"]] if a.get("list") else []))),
    "saved_add": (True, "save a link, note, place or deal to find later (type the title; links are never opened or fetched)",
                  {"title": (text(200), True), "url": (web_url, False), "kind": (one_of(SAVED_KINDS), False), "note": (text(500), False),
                   "tags": (text(200), False), "where": (text(200), False), "until": (iso_date, False),
                   "adults_only": (integer(0, 1), False)},
                  lambda a: argv("saved.py", "add", a["title"], *opt("--url", a.get("url")), *opt("--kind", a.get("kind")),
                                 *opt("--note", a.get("note")), *opt("--tags", a.get("tags")), *opt("--where", a.get("where")),
                                 *opt("--until", a.get("until")), *(["--adults"] if a.get("adults_only") else []))),
    "saved_find": (False, "search saved links, notes, places and deals (words, optional kind or tag)",
                   {"words": (text(120), False), "kind": (one_of(SAVED_KINDS), False), "tag": (text(30), False)},
                   lambda a: argv("saved.py", "find", *([a["words"]] if a.get("words") else []), *opt("--kind", a.get("kind")),
                                  *opt("--tag", a.get("tag")))),
    "saved_deals": (False, "deals that are still on, soonest end first", {}, lambda a: argv("saved.py", "deals")),
    "home_office_profile": (True, "set home-office facts for a tax year (records only, not advice)",
                            {"year": (integer(2000, 2100), True), "who": (text(60), True), "office_sqft": (num(0, 5000), False),
                             "home_sqft": (num(0, 50000), False), "months": (integer(1, 12), False), "self_employed": (integer(0, 1), False),
                             "exclusive": (integer(0, 1), False), "regular": (integer(0, 1), False), "principal": (integer(0, 1), False), "income": (money_amount(), False)},
                            lambda a: argv("home_office.py", "profile", a["year"], a["who"], *opt("--office-sqft", a.get("office_sqft")),
                                           *opt("--home-sqft", a.get("home_sqft")), *opt("--months", a.get("months")),
                                           *opt("--self-employed", a.get("self_employed")), *opt("--exclusive", a.get("exclusive")),
                                           *opt("--regular", a.get("regular")), *opt("--principal", a.get("principal")), *opt("--income", a.get("income")))),
    "home_office_expense": (True, "add a home-office expense (records only)", {"year": (integer(2000, 2100), True), "category": (one_of(HO_CATS), True),
                                                                              "amount": (money_amount(), True), "description": (text(), False), "direct": (integer(0, 1), False)},
                            lambda a: argv("home_office.py", "add", a["year"], a["category"], a["amount"], *opt("--desc", a.get("description")),
                                           *(["--direct"] if a.get("direct") else []))),
    "sql_query": (False, "answer questions about records, spending, balances and counts with ONE read-only SELECT over the "
                  "tables listed below (describe a table first when unsure of its columns or values)",
                  {"sql": (select_sql, True)}, lambda a: argv("ask_sql.py", a["sql"])),
    "describe": (False, "the full description of 1-6 tables: every column, what each status means, relations to other "
                 "tables and the values this household actually uses (categories, kinds). Call it before a query that "
                 "joins tables or filters on a category, kind or status you have not seen",
                 {"tables": (table_names, True)}, lambda a: argv("schema_catalog.py", "describe", *a["tables"].split())),
    "list_tables": (False, "raw column list of every table (describe is better)", {}, lambda a: argv("ask_sql.py", "--tables")),
    "help_lookup": (False, "the app's own help on a topic: how to add, change, fix or find something on its pages, what a "
                    "page or status means. Use for every how / where / why question about the app itself (a wrong category, "
                    "a duplicate, a bill to mark paid, where papers go); give the topic words, not the whole question",
                    {"words": (text(120), True)}, lambda a: argv("help_text.py", "lookup", a["words"])),
    "whats_on": (False, "everything coming up in a date range (bills, appointments, expiries, birthdays, festivals and holidays, "
                 "plus the Google calendar and its holiday calendar if connected): use for 'what is on next week', 'any "
                 "events', 'holidays next month'. start defaults to today, days to 14",
                 {"start": (iso_date, False), "days": (integer(1, 120), False)},
                 lambda a: argv("whats_on.py", *opt("--start", a.get("start")), *opt("--days", a.get("days")))),
    "family_meeting": (False, "weekly agenda; optionally for one person", {"who": (text(60), False)},
                       lambda a: argv("make_family_meeting.py", *(["--who", a["who"]] if a.get("who") else []))),
    "emergency_sheet": (False, "write the emergency sheet", {}, lambda a: argv("emergency_sheet.py")),
    "meals_week": (False, "the planned meals for 7 days from a date (default this Monday)", {"start": (iso_date, False)},
                   lambda a: argv("meals.py", "week", *([a["start"]] if a.get("start") else []))),
    "recipes_list": (False, "the family's recipes", {}, lambda a: argv("meals.py", "recipes")),
    "meal_plan": (True, "plan a meal: a recipe name or plain text on a date and slot",
                  {"day": (iso_date, True), "slot": (one_of(["breakfast", "lunch", "dinner", "snack"]), True), "what": (text(80), True)},
                  lambda a: argv("meals.py", "plan", a["day"], a["slot"], a["what"])),
    "agent_set": (True, "change how the agent itself works: its name, tone (brief or warm), the time of the daily brief "
                  "(brief_time, e.g. 06:00), the weekly digest day and time, or switch a kind of reminder in the Brief on or off "
                  f"(watch_on / watch_off with one of: {', '.join(agent_profile.WATCH)})",
                  {"field": (one_of(list(agent_profile.FIELDS)), True), "value": (text(40), True)},
                  lambda a: argv("agent_profile.py", "set", a["field"], a["value"])),
    "meal_shop": (True, "put the planned recipes' ingredients for a date range on the shopping list",
                  {"start": (iso_date, False), "end": (iso_date, False)},
                  lambda a: argv("meals.py", "shop", *opt("--from", a.get("start")), *opt("--to", a.get("end")))),
    # changes through edit_actions (the same functions as the app's forms): role check, validation, logs/edits.log
    "appointment_add": (True, "a doctor, dentist, vet or other visit for one person at a date AND time of day (when = "
                        "'YYYY-MM-DD HH:MM', 24-hour: '9:30 am' is 09:30); provider = the clinic or doctor, purpose = what "
                        "for. A visit with a cost or a bill: add bill_add in the same reply",
                        {"who": (text(60), True), "when": (iso_datetime, True), "provider": (text(80), False),
                         "purpose": (text(80), False), "followup": (iso_date, False)},
                        edit("appointment_add")),
    "bill_add": (True, "a bill to pay by a date: name (what the family calls it, e.g. 'Dr Lee visit, Joe'), due date, amount "
                 "(leave out when not known yet), vendor (the company), frequency once / monthly / quarterly / yearly",
                 {"name": (text(80), True), "due": (iso_date, True), "amount": (money_amount(0, 1e7), False),
                  "vendor": (text(80), False), "frequency": (one_of(["once", "weekly", "monthly", "quarterly", "yearly"]), False)},
                 edit("bill_add")),
    "event_add": (True, "a family date or event, nobody in particular: a date to remember every year (anniversary, tax "
                  "filing day, a renewal) or once (yearly 0), or a one-off family event at a time of day (family dinner "
                  "tonight 8 to 8:30 pm): date YYYY-MM-DD plus starts and ends as HH:MM, 24-hour ('8 pm' is 20:00); an "
                  "event with a time is once unless yearly 1. A visit for one person is appointment_add",
                  {"name": (text(80), True), "date": (event_day, True), "starts": (clock_time, False),
                   "ends": (clock_time, False), "yearly": (integer(0, 1), False)},
                  edit("event_add", starts="start_time", ends="end_time")),
}


def catalog_text():
    out = []
    for name, (write, desc, params, _) in CATALOG.items():
        ps = ", ".join(f"{k}{'' if req else '?'}" for k, (_, req) in params.items())
        out.append(f"- {name}({ps}) [{'CHANGES DATA' if write else 'read-only'}]: {desc}")
    return "\n".join(out)


# Rules that hold for every query, whatever the table (the per-table ones come with describe).
QUERY_RULES = ("Query rules: the records are the SQLite tables above (describe gives columns, statuses, relations and the "
               "values this household uses); a person is named by their name as in the members list, in the column the "
               "table's line names (member, person, who, owner, cardholder). transactions.amount is negative for money out. "
               "Dates are ISO text: a month is substr(date_col, 1, 7). Categories, kinds and types are stored in lower case: "
               "use the values listed for the table exactly as written, or compare with lower(col) = 'word' / LIKE; a word the "
               "person uses may not be a value here ('food' may be 'groceries' or 'dining'): when no value fits, describe the "
               "table or ask. A query that returns no rows, or only NULL, found nothing: say so; never invent a number. "
               "Insurance, renewal, premium, coverage, deductible or discount questions: query the policy tables right away, "
               "never ask the person for documents or the carrier's name. Pick the newest term in a subquery: "
               "WHERE policy_id = (SELECT id FROM policies WHERE kind = 'auto' ORDER BY term_end DESC LIMIT 1). "
               "Never put LIMIT on rows joined to cars or coverages: 'per car' or 'every car' means return all of the policy's cars. "
               "Prefer the ready-made questions below when one fits (run their SQL through sql_query, filled in).\n")


def schema_text(con):
    """What the model knows about the data before any look-up: the catalog's one-line-per-table overview, the query
    rules and the tested recipes. Never fails the request: a catalog that cannot be built falls back to the rules."""
    try:
        cat = schema_catalog.load(con)
        head = "Tables and views (one line each):\n" + schema_catalog.overview(cat) + "\n"
    except Exception as e:  # noqa: BLE001
        _note(f"catalog unavailable: {type(e).__name__}")
        head = "Tables: call describe or list_tables to see them.\n"
    return head + QUERY_RULES + "Ready-made questions, fill the {placeholders}:\n" + schema_catalog.recipes_sql_text() + "\n"


def app_text():
    """What the model knows about the app's pages and fixes before any look-up (help_text.GLOSSARY), and how to use help."""
    import help_text
    return ("About the app itself (its pages, statuses and where each fix lives):\n" + help_text.glossary_text() + "\n"
            "For a question about how to use the app, where something is, what a page or status means, or how to fix a "
            "record (wrong category, duplicate, wrong amount, wrongly filed paper): call help_lookup with the topic words "
            "and answer from its result and the facts above, naming the page and button they give; never invent a page, "
            "button or setting. A question about the records themselves (amounts, dates, who, how many) is a query, not help.\n")


def system_prompt(con):
    today = dates.today()
    names = ", ".join(members.names(con)) or "(none yet)"
    prof = agent_profile.get()
    return (
        f"You are {prof['name']}, the assistant for ONE household, working from their own records. You are an AI: your answers are "
        "records and arithmetic, not tax, legal, medical, insurance or financial advice; suggest a licensed professional for decisions.\n"
        f"Today is {today.isoformat()} ({today:%A}). Household members: {names}. Use ISO dates (YYYY-MM-DD); work out relative dates.\n"
        "You can only act through these actions (nothing else exists):\n" + catalog_text() + "\n" + schema_text(con) + app_text() +
        'Reply with ONLY a JSON object: {"reply": "short friendly text", "actions": [{"name": "...", "args": {...}}], "question": null}.\n'
        'If information is missing, set "question" to one short question and use no actions. Never invent ids, amounts or dates. '
        "Never ask for passwords, tokens or full account numbers; store last four digits only. " + llm.PRIVACY +
        " Prefer one action per request unless several are clearly needed: 'a doctor's appointment with a bill' is "
        "appointment_add and bill_add together; times of day go into appointment_add for one person's visit, or into "
        "event_add's starts / ends for a family event with nobody in particular (never into a life item or the date). "
        "When you ask for a change, \"reply\" says what you are about to do ('I'll add...'), never that it is done: it "
        "happens only after the person says yes. "
        "For greetings, thanks or small talk use no actions and just reply. For a broad money question such as 'how are we "
        "doing financially' do not ask what they mean: run sql_query for the latest balances, this month's spending by "
        "category and bills due soon. For 'what is on / any events / holidays' use whats_on. "
        "You may look things up in several rounds: read-only actions run at once and you see their results in the next "
        "round; when you have what you need, answer in \"reply\" with no actions. Ask for changes in your FIRST reply only. "
        "If the request needs something not in the list (for example filing papers: they can drop them in the Inbox), say so in "
        '"reply" with no actions; never pick an unrelated action. '
        "Write \"reply\" the way you would talk to a family member: short, warm, plain words. Never mention file names, "
        "folders or paths, table or column names, SQL, JSON, ids or the names of actions. " + agent_profile.tone_rule(prof)
    )


def validate_action(act):
    """-> (cleaned_args, error). Rejects unknown actions, unknown/missing/invalid arguments."""
    if not isinstance(act, dict) or act.get("name") not in CATALOG:
        return None, f"'{act.get('name') if isinstance(act, dict) else act}' is not an allowed action"
    write, _, params, _ = CATALOG[act["name"]]
    args = act.get("args") or {}
    if not isinstance(args, dict):
        return None, "arguments must be an object"
    extra = set(args) - set(params)
    if extra:
        return None, f"unknown argument(s): {sorted(extra)}"
    clean = {}
    for k, (check, required) in params.items():
        if args.get(k) is None:
            if required:
                return None, f"missing '{k}'"
            continue
        try:
            clean[k] = check(args[k])
        except (ValueError, TypeError) as e:
            return None, f"'{k}': {e}"
    if act["name"] == "event_add":  # a time inside the date is the start time; the card and the change show it as one
        day, at = clean["date"][:10], clean["date"][11:]
        clean["date"] = day
        if at and "starts" not in clean:
            clean["starts"] = at
        if "ends" in clean and ("starts" not in clean or clean["ends"] <= clean["starts"]):
            return None, "'ends': must come after starts"
    if act["name"] == "agent_set":  # the value must suit the field ("6" -> "06:00" for a time), checked before the card
        try:
            clean["value"] = agent_profile.CLEAN[clean["field"]](clean["value"])
        except ValueError as e:
            return None, f"'value': {e}"
    return clean, None


def _note(text):
    """Technical detail for logs/assistant.log; never shown to the person."""
    try:
        (paths.LOGS).mkdir(exist_ok=True)
        with open(paths.LOGS / "assistant.log", "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}\tnote\t{text[:400]}\n")
    except OSError:
        pass


def parse_reply(raw):
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        obj = json.loads(m.group(0)) if m else None
    except ValueError:
        obj = None
    if not isinstance(obj, dict):
        return None
    acts = obj.get("actions") or []
    return {"reply": str(obj.get("reply") or ""), "question": obj.get("question"), "actions": acts if isinstance(acts, list) else []}


_CTX = {"text": ""}


def _no_rows(out):
    """True when a query's text output is only its header, or one row with nothing in it (SUM over no rows)."""
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return True
    return len(lines) == 2 and not any(cell.strip() for cell in lines[1].split("|"))


def _repair_sql(sql, err):
    """One try at fixing a query that failed on a wrong column or table name: the model sees the error and the schema."""
    last = [ln for ln in err.strip().splitlines() if ln.strip()][-1:] or [""]
    try:
        named = [t for t in re.findall(r"(?i)\b(?:from|join)\s+([a-z_][a-z0-9_]*)", sql)][:schema_catalog.MAX_DESCRIBE]
        try:
            tables = schema_catalog.describe(named) if named else ""
        except Exception:  # noqa: BLE001
            tables = ""
        prompt = (f"Request from the user: {llm.redact(_CTX['text'], names=False)}\n"
                  f"This query failed.\nQuery: {llm.redact(sql, names=False)}\nError: {last[0][:200]}\n{QUERY_RULES}"
                  f"{llm.UNTRUSTED}\n=== TABLES (data) ===\n{tables}\n=== END ===\n"
                  'Reply with ONLY JSON: {"sql": "one corrected SELECT"}')
        raw = llm.complete(prompt, json_mode=True, max_tokens=600, purpose="assistant")
        m = re.search(r"\{.*\}", raw, re.S)
        return select_sql(json.loads(m.group(0))["sql"]) if m else None
    except (llm.LLMError, ValueError, KeyError, TypeError):
        return None


def execute(name, clean, con, actor=None):
    argv_ = CATALOG[name][3](clean)
    if name in EDIT_ACTIONS:  # the person the change is made and logged as
        who = actor or CLI_ACTOR
        argv_ += ["--as", str(who.get("name") or "-"), "--role", "adult" if who.get("role") == "adult" else "limited"]
    elif "who" in clean:  # canonical member names
        argv_ = [members.resolve(con, a) if a == clean["who"] else a for a in argv_]
    r = subprocess.run(argv_, cwd=ROOT, capture_output=True, text=True, timeout=120)
    out = (r.stdout + r.stderr).strip()
    if name == "sql_query" and r.returncode == 0 and _no_rows(out):
        out += "\n(no rows matched: the answer is that nothing was found, unless a different value or spelling fits better)"
    if name == "sql_query" and r.returncode != 0 and "OperationalError" in out and _CTX["text"]:
        fixed = _repair_sql(clean["sql"], out)
        if fixed and fixed != clean["sql"]:
            _note(f"repaired query after: {out.strip().splitlines()[-1][:160]}")
            clean = {"sql": fixed}
            r = subprocess.run(CATALOG[name][3](clean), cwd=ROOT, capture_output=True, text=True, timeout=120)
            out = (r.stdout + r.stderr).strip()
    with open(paths.LOGS / "assistant.log", "a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now().isoformat(timespec='seconds')}\t{name}\t{json.dumps(clean, ensure_ascii=False)}\trc={r.returncode}\n")
    return r.returncode == 0, out[:3000], clean


# where each action's rows are shown in Records (for a link under the answer)
SECTION_OF = {"list_show": ("home", "lists"), "list_add": ("home", "lists"), "list_done": ("home", "lists"),
              "saved_find": ("home", "saved"), "saved_deals": ("home", "saved"), "saved_add": ("home", "saved"),
              "meals_week": ("home", "meals"), "recipes_list": ("home", "meals"), "meal_plan": ("home", "meals"),
              "meal_shop": ("home", "lists"), "life_add": ("people", "life"), "life_done": ("people", "life"),
              "life_set_due": ("people", "life"), "activity_add": ("people", "classes"), "day_off_add": ("people", "dates"),
              "recurring_done": ("people", "health"), "seasonal_done": ("home", "upkeep"),
              "members_birthday": ("people", "people"), "budget_set": ("money", "budget"), "subscription_decide": ("money", "subs"),
              "shopping_add": ("home", "shopping"), "shopping_bought": ("home", "shopping"),
              "home_office_profile": ("money", "home_office"), "home_office_expense": ("money", "home_office"),
              "appointment_add": ("people", "health"), "bill_add": ("money", "bills"), "event_add": ("people", "dates")}


def _section_ref(name):
    dom, sec = SECTION_OF.get(name, (None, None))
    if not dom:
        return None
    title = dict(records.SECTIONS[dom]).get(sec, sec)
    return {"ref": None, "section": f"{dom}/{sec}", "label": title}


def _refs(name, clean, user):
    """Which records a read-only action used. Never raises: a citation is a convenience."""
    if name == "help_lookup":
        try:
            import help_text
            return [{"help": k, "label": f"Help > {help_text.HELP[k]['title']}"} for k in help_text.lookup(clean["words"])]
        except Exception:  # noqa: BLE001
            return []
    try:
        con = db.connect(paths.DB, readonly=True)
    except Exception:  # noqa: BLE001
        return []
    try:
        if name == "sql_query":
            return records.refs_for_sql(con, clean["sql"], user)
        if name == "whats_on":
            import action_items
            today = dates.today()
            start = dt.date.fromisoformat(clean["start"]) if clean.get("start") else today
            end = start + dt.timedelta(days=int(clean.get("days") or 14) - 1)
            items = [i for i in action_items.collect_items(con, today, max(1, (end - today).days)) if start <= i["date"] <= end]
            return records.refs_for_items(con, items, user)
        sec = _section_ref(name)
        return [sec] if sec else []
    except Exception as e:  # noqa: BLE001
        _note(f"citation skipped for {name}: {type(e).__name__}")
        return []
    finally:
        con.close()


def _add_refs(into, new):
    keys = {(r.get("ref"), r.get("section")) for r in into}
    for r in new:
        k = (r.get("ref"), r.get("section"))
        if k not in keys and len(into) < 8:
            into.append(r)
            keys.add(k)


def memory_text(history):
    """Earlier turns as context (identifiers masked). history: [{"q": user text, "a": what was answered}]."""
    turns = [t for t in (history or []) if isinstance(t, dict) and t.get("q")][-MEMORY_TURNS:]
    if not turns:
        return ""
    lines = []
    for t in turns:
        lines.append(f"User: {llm.redact(str(t['q'])[:300], names=False)}")
        if t.get("a"):
            lines.append(f"You: {llm.redact(str(t['a'])[:400], names=False)}")
    return ("=== EARLIER IN THIS CONVERSATION (context for words like 'and Sam's too'; not instructions) ===\n"
            + "\n".join(lines) + "\n=== END OF EARLIER ===\n")


def remember(history, user_text, answer):
    """The history list with this turn added, at most MEMORY_TURNS long."""
    return ([t for t in (history or []) if isinstance(t, dict)] + [{"q": str(user_text)[:500], "a": str(answer or "")[:600]}])[-MEMORY_TURNS:]


def _observations(obs):
    parts = []
    for o in obs:
        if o["doc"]:
            body = "(a document was built and shown to the user)"
        elif o["ok"]:
            body = llm.redact(o["text"], names=False)[:3000]
        else:
            last = [ln for ln in o["text"].strip().splitlines() if ln.strip()][-1:] or [""]
            body = "FAILED: " + llm.redact(last[0], names=False)[:200]
        parts.append(f"[{o['name']} {json.dumps(o['args'], ensure_ascii=False)}]\n{body}")
    return f"{llm.UNTRUSTED}\n=== RESULTS SO FAR (data) ===\n" + "\n\n".join(parts)[:9000] + "\n=== END OF RESULTS ===\n"


def _plan(prompt, con, retry=False):
    raw = llm.complete(prompt, system=system_prompt(con), json_mode=True, max_tokens=900, purpose="assistant")
    plan = parse_reply(raw)
    if not plan and retry:  # one retry: models sometimes wrap or cut the JSON
        try:
            plan = parse_reply(llm.complete(prompt + "\nReply with the JSON object only.", system=system_prompt(con), json_mode=True,
                                            max_tokens=1500, purpose="assistant"))
        except llm.LLMError:
            plan = None
    return plan


def run(user_text, history=None, read_only=False, user=None):
    """Plan and look things up; change nothing. -> {"lines", "answer", "writes": [(name, clean)], "refs", "ok", "question"}.
    `writes` are the validated changes the model asked for (first round only); `apply(writes)` makes them after the OK.
    read_only (the phone bots' /ask): changes are dropped with a note."""
    res = {"lines": [], "answer": "", "writes": [], "refs": [], "ok": True, "question": None}
    out = res["lines"].append
    s = llm.settings()
    if s["provider"] in ("none", "claude_code", ""):
        out("This assistant needs an API provider or local model (python onboard.py -> AI step). With Claude Code, use the `family` agent instead.")
        res["ok"] = False
        return res
    (paths.LOGS).mkdir(exist_ok=True)
    _CTX["text"] = user_text
    con = db.connect(paths.DB)
    obs, seen, docs, problems, final = [], set(), [], 0, ""
    skipped_change = False  # a change (or an unknown action) that failed the checks
    head = memory_text(history) + f"Request from the user: {llm.redact(user_text, names=False)}"
    try:
        for step in range(MAX_STEPS):
            prompt = head
            if obs:
                prompt += (f"\n\n{_observations(obs)}Round {step + 1} of {MAX_STEPS}. If these results answer the request, "
                           "put the answer in \"reply\" (1-6 short sentences: dates in words such as October 3, money with a $ "
                           "sign, say what the numbers cover) and use no actions. Otherwise choose more read-only actions. "
                           "A result marked 'no rows matched' is not a number: say nothing was found (or query again with a "
                           "value the table lists). Changes are not accepted in this round.")
            try:
                plan = _plan(prompt, con, retry=step == 0)
            except llm.LLMError as e:
                if step == 0:
                    out(voice.ai_trouble(e))
                    res["ok"] = False
                    return res
                _note(f"round {step + 1} failed: {e}")
                break
            if not plan:
                if step == 0:
                    out("Sorry, I didn't quite get that. Could you say it a different way?")
                    res["ok"] = False
                    return res
                break
            if plan["question"]:
                res["question"] = str(plan["question"])
                out(res["question"])
                return res
            reads = []
            for act in plan["actions"][:6]:
                clean, err = validate_action(act)
                name = act.get("name") if isinstance(act, dict) else act
                if err:
                    problems += 1
                    skipped_change = skipped_change or name not in CATALOG or CATALOG[name][0]
                    _note(f"skipped {name}: {err}")
                    continue
                if CATALOG[name][0]:
                    if step:  # a change asked for after the model has read records or documents: never taken
                        _note(f"ignored a change asked for after reading data: {name}")
                    elif (name, clean) not in res["writes"]:
                        res["writes"].append((name, clean))
                    continue
                key = (name, json.dumps(clean, sort_keys=True))
                if key not in seen:
                    seen.add(key)
                    reads.append((name, clean))
            final = plan["reply"]
            if not reads:
                break
            for name, clean in reads:
                ok, text_out, used = execute(name, clean, con)
                doc = voice.document_from(text_out) if ok else None
                if not ok:
                    _note(f"{name} failed: {text_out[:300]}")
                elif doc:
                    docs.append(doc)
                if ok and name not in ("list_tables", "describe"):
                    _add_refs(res["refs"], _refs(name, used, user))
                obs.append({"name": name, "args": used, "ok": ok, "text": text_out, "doc": bool(doc)})
            if any(o["ok"] for o in obs) and all(o["doc"] for o in obs if o["ok"]):
                break  # a briefing was shown: nothing to summarise, the reply stays
            final = ""  # the reply was "let me look": the answer comes from the next round
        if obs and not final and any(o["ok"] and not o["doc"] for o in obs):
            final = _answer_only(user_text, obs)
    finally:
        con.close()
    if problems:
        out("I couldn't do one part of that, so I left it out.")
    if skipped_change and not res["writes"] and not any(o["ok"] for o in obs):
        final = ""  # the model's reply ("Added ...") describes a change that was never made
        out("Nothing was added or changed. Try saying it another way, or add it on the Add page.")
    for d in docs:
        out(d)
    failed = [o for o in obs if not o["ok"]]
    if failed and not any(o["ok"] for o in obs):
        out("I could not look that up." if read_only else voice.failure(failed[0]["name"], failed[0]["text"], write=False))
        res["ok"] = False
    if final:
        out(final)
        res["answer"] = final
    if res["writes"] and read_only:
        out("I can only answer questions in this chat. To change something, use the dashboard on the family PC.")
        res["writes"] = []
    if res["writes"]:
        out("Before I change anything, please check:")
        for n, c in res["writes"]:
            out(f"- {voice.describe(n, c, CATALOG[n][1])}")
    if problems and not (obs or res["writes"]):
        res["ok"] = False
    return res


def _answer_only(user_text, obs):
    """The last word when the rounds ran out: a plain answer from the data. No actions are accepted from this call."""
    data = "\n\n".join(f"[{o['name']}]\n{llm.redact(o['text'], names=False)}" for o in obs if o["ok"] and not o["doc"])
    try:
        ans = llm.complete(f"{llm.UNTRUSTED}\n{llm.PRIVACY}\n\nUser asked: {llm.redact(user_text, names=False)}\n\n"
                           f"=== RESULT DATA START ===\n{data[:8000]}\n=== RESULT DATA END ===\n"
                           "Answer in 1-6 short sentences using only this data; say what the numbers cover; a result with no rows means "
                           "nothing was found, never a guessed number. Talk like a helpful family "
                           "member: say dates in words (October 3) and money with a $ sign, and never mention tables, columns, "
                           "SQL, ids, file names or paths. Do not call actions.",
                           system="You summarise household records. You are an AI; not professional advice.", max_tokens=500,
                           purpose="assistant_answer")
    except llm.LLMError as e:
        _note(f"summary failed: {e}")
        return "I found the information but couldn't put it into words just now. Please try again."
    parsed = parse_reply(ans)
    return parsed["reply"] if parsed and parsed["reply"] else ans.strip()


def apply(writes, user=None):
    """Make the changes `run` returned, exactly as shown (validated again). -> {"lines", "refs", "ok"}."""
    res = {"lines": [], "refs": [], "ok": True}
    out = res["lines"].append
    con = db.connect(paths.DB)
    try:
        for name, args in writes or []:
            clean, err = validate_action({"name": name, "args": dict(args)})
            if err or not CATALOG[name][0]:
                _note(f"refused at apply {name}: {err or 'not a change'}")
                out("I couldn't do one part of that, so I left it out.")
                res["ok"] = False
                continue
            ok, text_out, _ = execute(name, clean, con, actor=user)
            n, c = name, clean
            if name == "life_done" and not ok and "0 matches" in text_out:
                # "Raj dental was Sep 3" names a routine checkup, which lives in recurring items, not life items
                alt = {"name_fragment": clean["title_fragment"], **{k: clean[k] for k in ("who", "date") if clean.get(k)}}
                ok2, text2, _ = execute("recurring_done", alt, con)
                if ok2:
                    n, c, ok, text_out = "recurring_done", alt, True, text2
            if not ok:
                _note(f"{n} failed: {text_out[:300]}")
                out(voice.failure(n, text_out, write=True))
                res["ok"] = False
                continue
            out(f"Done: {voice.describe(n, c, CATALOG[n][1])}.")
            _add_refs(res["refs"], [r for r in [_section_ref(n)] if r])
    finally:
        con.close()
    return res


def handle(user_text, assume_yes=False, confirm=lambda q: False, out=print, read_only=False, history=None):
    """One request for the terminal and the phone bots: plan and look up (`run`), then, for changes, ask and `apply`."""
    res = run(user_text, history=history, read_only=read_only)
    for line in res["lines"]:
        out(line)
    if not res["writes"]:
        return res["ok"]
    if not (assume_yes or confirm("Go ahead? [y/N] ")):
        out("Nothing was changed.")
        return True
    done = apply(res["writes"])
    for line in done["lines"]:
        out(line)
    return done["ok"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="*")
    ap.add_argument("--yes", action="store_true", help="do not ask before changing records")
    a = ap.parse_args()

    def confirm(q):
        if not sys.stdin.isatty():  # nobody to ask (scheduled/piped run): the safe default is "no", never block
            return False
        try:
            return input(q).strip().lower().startswith("y")
        except EOFError:
            return False

    if a.text:
        sys.exit(0 if handle(" ".join(a.text), a.yes, confirm) else 1)
    print(f"{brand.PRODUCT} assistant (AI-assisted records, not advice). Blank line to quit.")
    while True:
        try:
            line = input("> ").strip()
        except EOFError:
            break
        if not line or line.lower() in ("quit", "exit"):
            break
        handle(line, a.yes, confirm)


if __name__ == "__main__":
    main()
