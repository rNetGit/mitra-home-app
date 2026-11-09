"""What every table means, for the chat assistant: the data dictionary the AI reads before it writes a query.

  python data/schema_catalog.py                 the overview (one line per table, what the system prompt carries)
  python data/schema_catalog.py describe bills transactions     full entries: columns, relations, statuses, this
                                                household's own values in the vocabulary columns
  python data/schema_catalog.py check           tables in the database with no entry and no deny-list line (a
                                                migration added a table: write its entry here)
  python data/schema_catalog.py recipes [KEY]   the named questions with known-good SQL; one runs it

Two layers:
  * Generated from the database itself: columns (`PRAGMA table_info`), relations (`PRAGMA foreign_key_list`), the
    distinct values in the vocabulary columns (`VOCAB`, counts, top `VOCAB_TOP`, masked by `pii`). Cached per schema
    (the migration count) and refreshed once a day.
  * Written here, next to the migrations (`TABLES`): what a table means, which column names the person / date /
    money, what each status means, the relations in words, and the Records section (`records.SECTION`).

Tables that never go to an AI (`DENY`: the PC-only tables and the app's own bookkeeping) are not described, not
listed and not queried: `ask_sql` refuses them too. `check` fails when a migration adds a table that is neither
described nor denied, so the list cannot go stale without a test saying so.
"""
import datetime as dt
import json
import pathlib
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import db  # noqa: E402
import paths  # noqa: E402
import records  # noqa: E402

# Never described, never queried from chat: private (PC only), secrets-adjacent, or the app's own bookkeeping.
DENY = {
    "member_info", "home_contacts", "wallet_cards",                       # PC only (CLAUDE.md privacy rules)
    "chat_invites", "chat_links", "chat_log", "devices", "device_pairings", "device_uploads", "sync_log", "sync_ops",
    "audit_runs", "audit_findings", "audit_fixes", "review_queue", "proposals", "action_state", "category_rules",
    "schema_migrations", "meta", "doc_search_state", "statement_cycles", "home_office_profile",
    "walls", "wall_pairings", "wall_ops",                                 # Mitra Wall sign-in (token hashes), app wall tap receipts
}
VOCAB_TOP = 30          # distinct values listed per vocabulary column
# columns whose values ride in the one-line overview too (the ones a question names most: a category, a kind, a type),
# so the first query uses the household's own spelling without a describe round; at most INLINE_TOP each
INLINE = {("transactions", "category"), ("transactions", "txn_type"), ("life_items", "domain"), ("documents", "doc_type"),
          ("bills", "status"), ("accounts", "type"), ("recurring_items", "category"), ("policies", "kind"), ("subscriptions", "category")}
INLINE_TOP = 15
CACHE_HOURS = 24
MAX_DESCRIBE = 6        # tables per describe() call

# table -> entry. `means` is one or two sentences; `person` / `date` / `money` name the columns a person would ask by;
# `status` maps each value to its meaning; `links` explains the relations in words; `vocab` lists the columns whose
# distinct values are worth showing (categories, kinds); `notes` are query rules the model needs for THIS table.
TABLES = {
    "members": dict(
        means="The household: people and pets. Other tables name a person by this name (member, person, who, owner).",
        person="name", date="birth_month_day (MM-DD) + birth_year",
        status=None, vocab=["role"],
        notes="role is adult, child or pet. Birthdays repeat every year: compare birth_month_day, not a full date."),
    "life_items": dict(
        means="One-off and repeating things to do for a person or the house: school forms, activities, medical visits, "
              "prescriptions, vaccines, pet care, legal, travel, gifts, chores.",
        person="member", date="due_date", money="amount (a fee or cost, if any)",
        status={"open": "still to do", "done": "finished (last_done = when)", "dropped": "removed"},
        vocab=["domain"],
        notes="recur_months set = repeats; NULL = one-off. 'What is due for Sam' = status open AND member = 'Sam'."),
    "appointments": dict(
        means="Doctor, dentist, vet and other visits with a date and time, and an optional follow-up date.",
        person="person", date="appt_datetime (YYYY-MM-DD HH:MM) and followup_due",
        notes="Upcoming = appt_datetime >= today. purpose is free text ('cleaning', 'physical')."),
    "recurring_items": dict(
        means="Routine checkups and home tasks that repeat every N months: dental cleaning, physical, eye exam, "
              "furnace filter, smoke detectors. One row per routine; each time it is done goes to recurring_log.",
        person="who (NULL or 'home' = the house)", date="last_done; next due = last_done + interval_months",
        status=None, vocab=["category"],
        links={"recurring_log.item_id": "the dates it was done, newest first"},
        notes="active = 1 only. Overdue = date(last_done, '+' || interval_months || ' months') < today, or last_done NULL."),
    "vaccinations": dict(
        means="Vaccinations given to a person or pet: the vaccine, the day it was given, and the next one due if there is one.",
        person="member", date="given_on and next_due",
        status={"active": "on file", "dropped": "removed"},
        links={"life_item_id": "life_items.id, the open reminder for next_due (domain vaccine)"},
        notes="Records only, no medical advice. 'When is Sam's next flu shot' = next_due of the newest active row for that "
              "member and vaccine; the reminder itself is the open life_items row."),
    "recurring_log": dict(
        means="Each time a routine checkup or home task was done, with the provider.",
        date="done_date", links={"item_id": "recurring_items.id"}),
    "events": dict(
        means="Family dates and events with nobody in particular: anniversaries, tax filing, passport renewal (every "
              "year) and one-off family events, some at a time of day (family dinner 20:00-20:30).",
        date="event_date (the next or first occurrence; recurs_yearly = 1 means every year on that month and day); "
             "start_time / end_time HH:MM 24-hour, NULL start_time = all day",
        notes="A visit for one person is in appointments, a class every week in activity_schedules."),
    "activity_schedules": dict(
        means="Classes, sports, lessons and clubs that repeat every week for one person.",
        person="member", date="term_start / term_end; weekdays like 'MO,WE'; start_time / end_time HH:MM",
        status={"active": "running", "ended": "over"},
        notes="'Which days does Sam have swimming' = weekdays of the active row; skip_dates are days off."),
    "calendar_days": dict(
        means="Holidays, festivals, school closures and early dismissals the family keeps.",
        person="member (NULL = everyone)", date="day and end_day",
        status={"active": "on the calendar", "proposed": "waiting for a yes in the Inbox", "dropped": "declined"},
        vocab=["kind", "source"],
        notes="Public holidays of the country are computed, not stored here: use the whats_on action for 'is Monday a holiday'."),
    "orgs": dict(
        means="The school, college or employer a person is linked to (members.org_id), with where its year calendar "
              "was read from.", vocab=["kind"],
        notes="calendar_days.org_id = the days imported from that org's calendar; members.school shows the name."),
    "lists": dict(
        means="Shared family lists: shopping, to-do, packing.", vocab=["kind", "audience"],
        status={"active": "in use", "archived": "put away"},
        links={"list_items.list_id": "the lines on the list"}),
    "list_items": dict(
        means="Lines on a shared list.", person="assigned_to", date="added_at / done_at",
        status={"open": "to do / to buy", "done": "ticked", "dropped": "removed"},
        links={"list_id": "lists.id (join for the list's name)"}),
    "recipes": dict(means="The family's recipes; ingredients in recipe_ingredients.", status={"active": "", "archived": ""},
                    links={"recipe_ingredients.recipe_id": "one line per ingredient"}),
    "recipe_ingredients": dict(means="Ingredient lines of a recipe (qty parsed; pantry = 1 is a staple).",
                               links={"recipe_id": "recipes.id"}),
    "meal_plan": dict(means="What is planned for each day and slot: a recipe or plain text.",
                      date="day", vocab=["slot"], links={"recipe_id": "recipes.id (NULL when title is plain text)"}),
    "routines": dict(
        means="Children's jobs on the Mitra Wall, by part of the day, each worth 1 to 5 stars. Each day a job was done is "
              "a row in routine_done.",
        person="member (the child)", date="created_at", status={"active": "on the wall", "dropped": "removed"},
        vocab=["part", "icon"], links={"routine_done.routine_id": "the days it was done"},
        notes="part is morning, afternoon (shown as After school) or evening. weekdays is like 'MO,WE'; empty = every day."),
    "routine_done": dict(
        means="One row per job a child did on a day, with the stars it earned that day.",
        person="routines.member (the child); done_by = who tapped it (the child, an adult or the wall's name)",
        date="day", links={"routine_id": "routines.id"},
        notes="Stars of a week: SUM(stars) for day between Monday and Sunday. The allowance is that times wall.star_cents "
              "in config (default 25 cents); nothing is paid automatically."),
    "rewards": dict(
        means="What a child can ask for with their stars (for example 30 minutes of screen time = 10 stars).",
        person="member (one child; NULL = any child)", date="created_at",
        status={"active": "offered", "dropped": "removed"}, links={"reward_claims.reward_id": "the times it was asked for"}),
    "reward_claims": dict(
        means="A child asking for a reward and an adult's answer; given requests spend the stars.",
        person="member (the child); asked_by = who tapped it; decided_by = the adult", date="asked_at, decided_at",
        status={"asked": "waiting for an adult", "given": "the stars are spent", "declined": "the stars come back"},
        links={"reward_id": "rewards.id"},
        notes="Stars to spend = SUM(routine_done.stars) of the child's jobs minus stars of their asked and given requests."),
    "savings_goals": dict(
        means="What the family is saving for: the target, by when, and how much is set aside so far.",
        date="due_date, created_at", money="target, saved", links={"account_id": "accounts.id (the account kept for it)"},
        status={"active": "", "done": "reached", "dropped": "given up"},
        notes="With account_id set, the amount set aside is that account's latest balance (v_balance_latest), not saved."),
    "saved_items": dict(
        means="Links, notes, places, deals, videos and articles the family saved to find later.",
        person="owner (who saved it)", date="added_at; expires_on for deals",
        status={"active": "", "archived": ""}, vocab=["kind", "audience"],
        notes="audience private = only the owner may see it; the chat's SQL never returns private items."),
    "seasonal_tasks": dict(
        means="Jobs that come round once a year in a season: gutters, sprinklers, winter prep. Each time done goes to seasonal_log.",
        person="who", date="start_md / end_md (MM-DD window)", vocab=["category"],
        links={"seasonal_log.task_id": "when it was done"}),
    "seasonal_log": dict(means="Each time a seasonal job was done.", date="done_date", links={"task_id": "seasonal_tasks.id"}),
    "home_assets": dict(
        means="Household inventory: appliances, electronics, furniture, with price, warranty and where it is.",
        date="purchase_date, warranty_end", money="price",
        status={"in_use": "in the house (NULL counts as in_use)", "sold": "", "disposed": "", "lost": ""}, vocab=["category"],
        links={"receipt_document_id / manual_document_id": "documents.id (the filed receipt / manual)",
               "vehicle_id": "vehicles.id when it belongs to a car"}),
    "shopping_items": dict(
        means="Planned purchases with a target date and price (not the grocery list: that is lists).",
        date="target_date / bought_date", money="est_price, paid",
        status={"todo": "still to buy", "bought": "", "dropped": ""}),
    "vehicles": dict(
        means="The family's cars: make, model, year, owner, plate, registration and inspection dates.",
        person="owner, primary_driver", date="registration_expires, inspection_expires",
        status={"active": "", "sold": ""},
        links={"vehicle_log.vehicle_id": "services and repairs", "policy_vehicles.vehicle_id": "the car on an insurance term"},
        notes="vin_last4 and plate only; never ask for the full VIN."),
    "vehicle_log": dict(means="Services, repairs, inspections and mileage readings per car.",
                        date="log_date", money="cost", vocab=["kind"],
                        links={"vehicle_id": "vehicles.id", "document_id": "documents.id (the filed invoice)"}),
    "vehicle_service_rules": dict(means="How often a kind of service is due per car (months or miles).",
                                  links={"vehicle_id": "vehicles.id"}),
    "accounts": dict(
        means="Bank, card, loan and investment accounts, by name and last four digits.",
        person="owner", vocab=["type"],
        links={"transactions.account_id": "its lines", "account_balances.account_id": "balance snapshots"},
        notes="type: checking, savings, credit, loan, investment. Latest balance: v_balance_latest."),
    "account_balances": dict(means="Balance snapshots of an account on a date (from statements or bank sync).",
                             date="as_of", money="balance", links={"account_id": "accounts.id"},
                             notes="Latest per account = MAX(as_of); v_balance_latest does it for you."),
    "transactions": dict(
        means="Every line from bank and card statements: date, description, amount, category.",
        person="cardholder (card lines)", date="txn_date", money="amount (NEGATIVE = money out, positive = money in)",
        vocab=["category", "txn_type"],
        links={"account_id": "accounts.id", "document_id": "documents.id (the statement)"},
        notes="Spend on a category = SUM(-amount) WHERE amount < 0. card_payment and transfer lines move money between "
              "own accounts: leave them out of 'spending'. A month = substr(txn_date, 1, 7) = 'YYYY-MM'. "
              "Monthly totals are ready in v_monthly_cashflow and v_card_category_monthly."),
    "bills": dict(
        means="Bills to pay, one row per due date (a monthly bill gets a new row each month).",
        date="due_date, paid_date", money="amount (positive = owed)", vocab=["frequency"],
        status={"due": "not paid yet", "overdue": "past the due date, not paid", "paid": "paid on paid_date"},
        links={"document_id": "documents.id (the bill itself)", "account_id": "accounts.id (paid from)"},
        notes="'What do we owe' = status IN ('due', 'overdue'). Vendor is the company; name is what the family calls it."),
    "subscriptions": dict(
        means="Streaming, memberships and other repeat charges found on statements or added by hand.",
        date="next_renewal, reviewed_on", money="amount per frequency", vocab=["frequency", "category", "decision"],
        notes="active = 1 is current. decision keep / cancel is the family's choice, recorded only."),
    "loans": dict(means="Mortgage, car and other loans: balance, rate, payment.", date="balance_date, payoff_date",
                  money="balance, payment", vocab=["kind"], status={"active": "", "paid_off": ""}),
    "investments": dict(means="Investments and deposits with their value and maturity.", date="as_of, maturity_date",
                        money="invested, current_value", vocab=["kind"]),
    "interest_income": dict(means="Interest earned per account and period.", date="period_end", money="amount",
                            links={"account_id": "accounts.id"}),
    "budget": dict(means="Monthly spending limit per category (the key is category).", money="monthly_limit",
                   notes="Compare with transactions of the month by category; a line 'allowance:<name>' is one person's allowance."),
    "receipts": dict(
        means="Receipts from shops and PayPal, matched to the card or bank line they paid.",
        date="receipt_date", money="total", vocab=["match_confidence"],
        status={"open": "no charge matched yet", "matched": "linked to a transaction", "ignored": "no charge expected"},
        links={"transaction_id": "transactions.id", "document_id": "documents.id"}),
    "card_benefits": dict(means="Credits a card gives (dining, travel) and whether they were used.",
                          money="amount", links={"account_id": "accounts.id"}),
    "amazon_orders": dict(means="Amazon orders read from order reports, matched to card charges.",
                          date="order_date", money="total", status={"delivered": "", "returned": "", "refunded": "",
                                                                   "cancelled": "", "digital": "", "gift_card": "", "other": ""},
                          links={"transaction_id": "transactions.id"}),
    "mobile_bills": dict(means="Phone bills, one per month, with the account total.", date="bill_date, due_date",
                         money="total_due, bill_total", links={"mobile_bill_lines.bill_id": "each person's line"}),
    "mobile_bill_lines": dict(means="Each person's line on a phone bill: plan, devices, perks, taxes, their net cost.",
                              person="person (as printed) / member (the family name)", money="line_total, net",
                              links={"bill_id": "mobile_bills.id"}),
    "mobile_bill_items": dict(means="The itemised charges of a phone bill line.", money="amount",
                              links={"line_id": "mobile_bill_lines.id", "bill_id": "mobile_bills.id"}),
    "home_office_expenses": dict(means="Home-office costs recorded for a tax year (records, not advice).",
                                 person="who", date="expense_date", money="amount", vocab=["category"],
                                 notes="direct = 1 is a cost of the office only; tax_year groups them."),
    "contracts": dict(means="Work contracts of adults who bill their time: client, rate, dates.",
                      person="person", date="start_date, end_date", money="hourly_rate",
                      status={"active": "", "renewed": "a newer contract replaced it", "ended": ""},
                      links={"work_hours.contract_id": "hours worked", "work_invoices.contract_id": "invoices"}),
    "work_hours": dict(means="Hours worked per day per contract.", date="work_date", vocab=["location"],
                       links={"contract_id": "contracts.id"}),
    "work_invoices": dict(means="Invoices made from work hours.", date="period_start, period_end, sent_on, paid_on",
                          money="amount", status={"draft": "", "sent": "", "paid": ""},
                          links={"contract_id": "contracts.id"}),
    "work_calendar": dict(means="Holidays, floating days and pay days of a work calendar.", date="day", vocab=["kind"]),
    "work_papers": dict(means="Filed papers kept with a job: offer letter, contract, W-2, 1099, timesheet, benefits.",
                        vocab=["kind"], links={"contract_id": "contracts.id", "document_id": "documents.id"}),
    "work_match_rules": dict(means="Words printed on a job's timesheets that point a new timesheet to that job.",
                             links={"contract_id": "contracts.id"}),
    "documents": dict(
        means="Every filed paper: bills, statements, receipts, policies, IDs, medical, tax, with its vendor and date. "
              "The text of a paper is not here: it stays on the PC.",
        date="doc_date", vocab=["doc_type"],
        notes="Other tables point here through document_id. Never show filed_path to the person."),
    "id_documents": dict(means="Passports, licences and other IDs: who, type, last four, when they expire.",
                         person="person", date="issued, expires", vocab=["doc_type"],
                         links={"document_id": "documents.id (the scan)"},
                         notes="active = 1 is current. number_last4 only; never ask for the full number."),
    "policies": dict(
        means="Insurance policies, one row per TERM (a renewal is a new row linked by prior_policy_id).",
        date="term_start, term_end (the renewal date)", money="premium_total", vocab=["kind", "payment_plan"],
        status={"active": "current term", "expired": "", "replaced": "a newer term exists (prior_policy_id points here)"},
        links={"prior_policy_id": "policies.id (the term before)", "document_id": "documents.id (the declarations page)",
               "policy_vehicles.policy_id": "the cars on an auto term", "policy_coverages.policy_id": "coverages and deductibles",
               "policy_drivers.policy_id": "listed drivers", "policy_discounts.policy_id": "discounts"},
        notes="Newest term of a kind: WHERE id = (SELECT id FROM policies WHERE kind = 'auto' ORDER BY term_end DESC LIMIT 1). "
              "Premium history: v_policy_premium_history."),
    "policy_vehicles": dict(means="Each car on an auto policy term, with that car's premium.", money="premium",
                            links={"policy_id": "policies.id", "vehicle_id": "vehicles.id"},
                            notes="'Per car' means every row of the term: never LIMIT 1."),
    "policy_coverages": dict(means="Coverages of a policy term: limit, deductible, premium; vehicle_id NULL = the whole policy.",
                             money="deductible, premium", links={"policy_id": "policies.id", "vehicle_id": "policy_vehicles.id"}),
    "policy_drivers": dict(means="Drivers listed on a policy term (excluded = 1 is not covered).",
                           links={"policy_id": "policies.id"}),
    "policy_discounts": dict(means="Discounts on a policy term.", money="amount", links={"policy_id": "policies.id"}),
    # views
    "v_balance_latest": dict(means="VIEW: the latest balance of every account (signed_balance: a card's balance is money owed).",
                             money="balance, signed_balance"),
    "v_monthly_cashflow": dict(means="VIEW: per month, income, card payments, loans, insurance, utilities, other spend, "
                                     "invested and what was left (operating_net).", date="month 'YYYY-MM'"),
    "v_card_category_monthly": dict(means="VIEW: card spend per month and category.", date="month"),
    "v_card_spend_monthly": dict(means="VIEW: each card's charges, credits and net spend per month.", date="month"),
    "v_card_payments": dict(means="VIEW: card payments made from bank accounts per month.", date="month"),
    "v_investment_flows": dict(means="VIEW: money moved to investments per month, with running totals.", date="month"),
    "v_policy_premium_history": dict(means="VIEW: each policy term against the term before: premium, change, change %.",
                                     date="term_end"),
}

# column -> the values worth sampling even when the entry does not list them (every table with such a column)
VOCAB = {"status", "kind", "category", "domain", "doc_type", "txn_type", "frequency", "role", "type", "slot",
         "audience", "source", "decision", "payment_plan", "location", "match_confidence"}

# named questions with SQL that is tested: the model prefers one when it fits
RECIPES = {
    "spend_by_category_month": (
        "spending by category in a month (YYYY-MM); card payments and transfers left out",
        "SELECT category, ROUND(SUM(-amount), 2) AS spent, COUNT(*) AS lines FROM transactions "
        "WHERE substr(txn_date, 1, 7) = '{month}' AND amount < 0 AND COALESCE(txn_type, '') NOT IN ('card_payment', 'transfer', 'investment_transfer') "
        "GROUP BY category ORDER BY spent DESC"),
    "spend_at_payee": (
        "what was paid to one payee or description word over a date range",
        "SELECT txn_date, description, -amount AS paid, category FROM transactions "
        "WHERE amount < 0 AND (UPPER(description) LIKE UPPER('%{word}%') OR UPPER(payee) LIKE UPPER('%{word}%')) "
        "AND txn_date BETWEEN '{start}' AND '{end}' ORDER BY txn_date DESC"),
    "balances_latest": ("the latest balance of every account",
                        "SELECT name, type, last4, as_of, balance FROM v_balance_latest ORDER BY type, name"),
    "bills_open": ("bills not paid yet, soonest first",
                   "SELECT name, vendor, amount, due_date, status FROM bills WHERE status IN ('due', 'overdue') ORDER BY due_date"),
    "bills_paid_to_vendor": ("what a vendor was paid, by bill, newest first",
                             "SELECT due_date, paid_date, amount, status FROM bills WHERE UPPER(COALESCE(vendor, name)) LIKE UPPER('%{word}%') "
                             "ORDER BY due_date DESC"),
    "open_for_person": ("everything still open for one person: life items, appointments, routine checkups",
                        "SELECT 'item' AS what, title AS name, due_date AS on_date FROM life_items WHERE member = '{name}' AND status = 'open' "
                        "UNION ALL SELECT 'appointment', COALESCE(purpose, provider), substr(appt_datetime, 1, 16) FROM appointments "
                        "WHERE person = '{name}' AND appt_datetime >= date('now') "
                        "UNION ALL SELECT 'checkup', name, date(last_done, '+' || interval_months || ' months') FROM recurring_items "
                        "WHERE who = '{name}' AND active = 1 ORDER BY on_date"),
    "cashflow_months": ("income, spending and what was left per month, newest first",
                        "SELECT month, income, other_spend + utilities + insurance + loans AS spent, operating_net AS left_over "
                        "FROM v_monthly_cashflow ORDER BY month DESC LIMIT 12"),
    "premium_history": ("every insurance term with its premium and the change from the term before",
                        "SELECT kind, carrier, term_start, term_end, premium_total, prior_premium, change_pct FROM v_policy_premium_history "
                        "ORDER BY kind, term_end DESC"),
    "subscriptions_active": ("current subscriptions and what they cost",
                             "SELECT name, amount, frequency, next_renewal, decision FROM subscriptions WHERE active = 1 ORDER BY name"),
    "expiring": ("IDs, registrations and inspections that run out within N days",
                 "SELECT person || ' ' || doc_type AS what, expires AS on_date FROM id_documents WHERE active = 1 AND expires <= date('now', '+{days} days') "
                 "UNION ALL SELECT make || ' ' || model || ' registration', registration_expires FROM vehicles "
                 "WHERE status = 'active' AND registration_expires <= date('now', '+{days} days') "
                 "UNION ALL SELECT make || ' ' || model || ' inspection', inspection_expires FROM vehicles "
                 "WHERE status = 'active' AND inspection_expires <= date('now', '+{days} days') ORDER BY on_date"),
}
RECIPE_SAMPLE = {"month": "2026-09", "word": "water", "start": "2026-01-01", "end": "2026-12-31", "name": "Alex", "days": "90"}


# ---------------------------------------------------------------------------------------------- generated layer
def _ro(path=None):
    return db.connect(path or paths.DB, readonly=True)


def tables_in(con):
    """Every table and view the chat may see: in the database, not denied, not an FTS shadow table."""
    rows = con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                       "AND name NOT LIKE 'doc_search%' ORDER BY type, name").fetchall()
    return [(n, t) for n, t in rows if n not in DENY]


def undescribed(con):
    """Tables in the database with neither an entry nor a deny line (a migration added one: describe it)."""
    return [n for n, _ in tables_in(con) if n not in TABLES]


def _columns(con, table):
    return [(r[1], (r[2] or "").upper()) for r in con.execute(f"PRAGMA table_info({table})")]


def _foreign_keys(con, table):
    return [(r[3], r[2], r[4]) for r in con.execute(f"PRAGMA foreign_key_list({table})")]  # (column, table, to)


def _vocab(con, table, cols):
    """Distinct values of the vocabulary columns as this household uses them: value (count), top VOCAB_TOP, masked."""
    import pii
    red = pii.redactor()
    out = {}
    wanted = set(TABLES.get(table, {}).get("vocab") or []) | {c for c, _ in cols if c in VOCAB}
    for c, _ in cols:
        if c not in wanted:
            continue
        try:
            rows = con.execute(f"SELECT {c}, COUNT(*) FROM {table} WHERE {c} IS NOT NULL AND {c} != '' "
                               f"GROUP BY {c} ORDER BY 2 DESC, 1 LIMIT {VOCAB_TOP + 1}").fetchall()
        except sqlite3.Error:
            continue
        vals = [(red.redact(str(v))[:40], n) for v, n in rows[:VOCAB_TOP]]
        if vals:
            out[c] = {"values": vals, "more": len(rows) > VOCAB_TOP}
    return out


def _schema_stamp(con):
    try:
        return con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    except sqlite3.Error:
        return 0


def build(con):
    """The whole catalog as plain data: {"stamp", "built", "tables": {name: {...}}}."""
    out = {}
    for name, typ in tables_in(con):
        cols = _columns(con, name)
        e = dict(TABLES.get(name) or {})
        dom, sec = records.SECTION.get(name, (None, None))
        out[name] = {
            "view": typ == "view", "means": e.get("means", ""), "person": e.get("person"), "date": e.get("date"),
            "money": e.get("money"), "status": e.get("status"), "notes": e.get("notes"),
            "columns": [c for c, _ in cols if c not in records.HIDDEN_COLS or c == "id"],
            "links": {**{f"{c}": f"{t}.{to}" for c, t, to in _foreign_keys(con, name)}, **(e.get("links") or {})},
            "section": f"{dom}/{sec}" if dom else None,
            "vocab": _vocab(con, name, cols),
        }
    return {"stamp": _schema_stamp(con), "built": dt.datetime.now().isoformat(timespec="seconds"), "tables": out}


def _cache_file():
    return paths.LOGS / "schema_catalog.json"


def load(con=None, fresh=False):
    """The catalog, from logs/schema_catalog.json when it is for this schema and under CACHE_HOURS old."""
    f = _cache_file()
    if not fresh:
        try:
            c = json.loads(f.read_text(encoding="utf-8"))
            built = dt.datetime.fromisoformat(c["built"])
            own = con is None
            con = con or _ro()
            try:
                stamp = _schema_stamp(con)
            finally:
                if own:
                    con.close()
            if c.get("stamp") == stamp and dt.datetime.now() - built < dt.timedelta(hours=CACHE_HOURS):
                return c
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            pass
    own = con is None
    con = con or _ro()
    try:
        c = build(con)
    finally:
        if own:
            con.close()
    try:
        paths.LOGS.mkdir(exist_ok=True)
        f.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return c


# ---------------------------------------------------------------------------------------------- text for the model
def overview(cat=None):
    """One line per table: what the system prompt carries. Views last."""
    cat = cat or load()
    lines = []
    for name, t in cat["tables"].items():
        bits = []
        if t.get("person"):
            bits.append(f"person: {t['person']}")
        if t.get("date"):
            bits.append(f"date: {t['date']}")
        if t.get("money"):
            bits.append(f"money: {t['money']}")
        if t.get("status"):
            bits.append("status " + "/".join(t["status"]))
        for col, v in (t.get("vocab") or {}).items():
            if (name, col) in INLINE and v["values"]:
                vals = ", ".join(val for val, _ in v["values"][:INLINE_TOP])
                bits.append(f"{col} values here: {vals}{', ...' if v['more'] or len(v['values']) > INLINE_TOP else ''}")
        lines.append(f"- {name}: {t['means'] or '(no description)'}" + (f" [{'; '.join(bits)}]" if bits else ""))
    return "\n".join(lines)


def describe(names, cat=None):
    """Full entries for up to MAX_DESCRIBE tables, as text the model reads as data. Unknown or denied names are
    named as such, never described."""
    cat = cat or load()
    out = []
    for raw in list(names)[:MAX_DESCRIBE]:
        name = str(raw).strip().lower()
        t = cat["tables"].get(name)
        if not t:
            out.append(f"{name}: not a table the chat can read.")
            continue
        s = [f"{name}{' (view)' if t['view'] else ''}: {t['means']}", "columns: " + ", ".join(t["columns"])]
        for k in ("person", "date", "money"):
            if t.get(k):
                s.append(f"{k}: {t[k]}")
        if t.get("status"):
            s.append("status: " + "; ".join(f"{v} = {m}" if m else v for v, m in t["status"].items()))
        if t.get("links"):
            s.append("relations: " + "; ".join(f"{c} -> {to}" for c, to in t["links"].items()))
        for c, v in (t.get("vocab") or {}).items():
            vals = ", ".join(f"{val} ({n})" for val, n in v["values"])
            s.append(f"values of {c} in this household: {vals}{', ...' if v['more'] else ''}")
        if t.get("notes"):
            s.append("rules: " + t["notes"])
        if t.get("section"):
            s.append(f"shown in Records: {t['section']}")
        out.append("\n".join(s))
    return "\n\n".join(out)


def recipes_text():
    return "\n".join(f"- {k}: {d}" for k, (d, _) in RECIPES.items())


def recipes_sql_text():
    """Each recipe with its SQL, {placeholders} left for the model to fill (a month, a word, a name, a number of days)."""
    return "\n".join(f"- {k}: {d}\n  SQL: {sql}" for k, (d, sql) in RECIPES.items())


def recipe_sql(key, **fill):
    """The SQL of one recipe with its {placeholders} filled from plain values (quotes doubled)."""
    _, sql = RECIPES[key]
    safe = {k: str(v).replace("'", "''") for k, v in fill.items()}
    return sql.format(**{k: safe.get(k, RECIPE_SAMPLE[k]) for k in RECIPE_SAMPLE})


def main(argv=None):
    a = list(sys.argv[1:] if argv is None else argv)
    con = _ro()
    try:
        if not a:
            print(overview(load(con, fresh=True)))
        elif a[0] == "describe":
            print(describe(a[1:], load(con, fresh=True)))
        elif a[0] == "check":
            missing = undescribed(con)
            print("every table is described or denied" if not missing else "no entry: " + ", ".join(missing))
            return 1 if missing else 0
        elif a[0] == "recipes":
            if len(a) == 1:
                print(recipes_text())
            else:
                import ask_sql
                print(ask_sql.run(con, recipe_sql(a[1])))
        else:
            raise SystemExit(__doc__)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
