# Making Chat the front door: review and plan, October 2026

Goal: a family member asks Chat anything about their own records, how the app works, or how to fix something, and
gets an answer with links, without browsing. Next, they add and change records from Chat ("Dr appointment with a
bill, Dec 10 at 9:30 for Joe"). This document reviews what Chat does today and proposes how to get there without
loosening the safety rules the app already has.

## 1. What Chat is today (from the code)

The web Chat (`webapp/app.py` -> `chat_data.py` -> `admin_actions.ask` -> `assistant.py`) is already an agent loop,
and a careful one:

| Piece | Where | What it does |
|---|---|---|
| Action catalog | `assistant.CATALOG` | 36 named actions. The model picks names and typed arguments; Python validates each and builds the command line itself (never a shell). |
| Planning loop | `assistant.run` | Up to 4 rounds. Read-only actions run at once, results go back as fenced untrusted data; changes are accepted only from round 1 (before any data was seen), shown on a confirm card and run exactly as shown after "Yes, save it" (`apply`). |
| SQL questions | `sql_query` -> `ask_sql.py` | One SELECT, read-only connection, 200 rows, three private tables refused. One automatic repair when a column/table name is wrong. |
| Schema knowledge | `assistant.SCHEMA_HINT` | A hand-written paragraph: about 20 of the 70+ tables, mostly money and insurance. The rest only through `list_tables`, which prints raw `PRAGMA table_info` with no meaning, vocabularies or relations. |
| Citations | `records.refs_for_sql` | The rows a query read become "From:" links into Records. |
| "How do I ...?" | `help_text.howto`, run first in `chat_data.message` | No AI. A regex gate (`is_howto`) + word scoring over the help entries. The AI never sees the help text. |
| No-AI fallbacks | `chat_data` chips | What is due, what we owe, trends, log a checkup, record / paper / list word search. |
| Memory | `assistant.memory_text` | Last 10 turns, kept in the server session, masked. |
| Phone bots | `chat_core` `/ask` | Same assistant, read-only, 20 a day. |

What is good and must stay: the fixed catalog, validation of every argument, the confirm card with a one-time nonce,
"changes only before data was read" (prompt-injection defence), `pii` masking, PC-only tables refused, adults only,
rate caps, citations.

## 2. Where it falls short of "ask instead of browse"

1. **The model does not know the data.** `SCHEMA_HINT` is partial and hand-maintained. For anything outside it the
   model gets column names only. It does not know: what `status` values mean (`due|paid|overdue`, `open|done|dropped`,
   `active|proposed|dropped`), which column holds the person (`member`, `person`, `who`, `owner`, `cardholder` differ
   by table), that `transactions.amount` is negative for spend, that `policies` are one row per term, how
   `recurring_items` / `recurring_log` relate, that `v_monthly_cashflow` exists, or which tables it may not touch.
   Complex questions ("what did we pay the dentist for Joe this year, and is a follow-up due?") need
   `life_items` + `recurring_items` + `appointments` + `transactions` + `receipts`; today the model guesses.
2. **Questions about the app go nowhere.** Only text matching the `is_howto` regex reaches the help. "My bill shows
   the wrong category" or "why is this under Needs a look" goes to the AI, which knows nothing about the pages,
   buttons, the Inbox, Records sections, statuses or the fix for each. It answers from general knowledge or says it
   cannot.
3. **Adding records is narrow.** No action adds an appointment with a time (`life_add` has a date only; the
   `appointments` table has `appt_datetime` but no add action), no action adds a bill, an event, a vehicle service,
   a subscription, a note; no action changes or removes an existing row (`life_update`, `bill_paid` by name,
   `subscription_set_active` exist in `edit_actions` but not in the catalog). "Dr appointment with a bill" needs
   two writes in one request; the catalog has neither.
4. **Changes cannot follow a lookup.** Because changes are taken only from round 1, "mark the water bill paid" works
   only if the model names it without looking; "mark the bill that was due last Tuesday paid" cannot be done,
   because finding it is a read, and after a read no change is accepted.
5. **Two code paths to the same tables.** Chat writes go through `data/<script>.py` subprocesses; the dashboard writes
   go through `edit_actions` (validated, role-checked, logged in `logs/edits.log`). Chat changes therefore miss the
   edit log and the sync triggers' actor, and every new chat action needs CLI plumbing.

## 3. Design

Five pieces, each shippable on its own. Order by value: A, C, D, B, E.

### A. A data dictionary the model can read (`data/schema_catalog.py`)

One module that is the single source of what each table means, built from two layers:

- **Generated**: `PRAGMA table_info` / `foreign_key_list` for every table and view, less the PC-only ones
  (`member_info`, `home_contacts`, `wallet_cards`, `chat_*`, `device*`, `sync_*`, `audit_*`, `doc_search*`).
  Cached per schema version (`PRAGMA user_version` or the migration count); rebuilt on `migrate.py`.
- **Written**: a `TABLES` dict in the module, one entry per table, kept next to the migrations:

  ```python
  "bills": dict(
      means="A bill to pay, one row per due date. Recurring bills get a new row when rolled forward.",
      person=None, date="due_date", money="amount (positive = owed)",
      status={"due": "not paid yet", "overdue": "past due_date, not paid", "paid": "paid on paid_date"},
      links={"document_id": "documents.id = the filed paper", "account_id": "accounts.id = paid from"},
      ask_like=["what do we owe", "bills due next week", "did we pay the electric bill"],
      see="money/bills"),
  ```

  `records.SECTION` / `LABEL` / `SEARCH` already hold a third of this (which section, what a row is called,
  searchable columns); the catalog imports them rather than repeating them.
- **Vocabulary samples**: for columns such as `transactions.category`, `life_items.domain`, `documents.doc_type`,
  the catalog lists the distinct values actually in this household's database (counts, top 30, masked by `pii`),
  refreshed daily. This is what lets "how much on groceries" map to the family's own category names.

How the model gets it: a two-tier prompt. The **overview** (one line per table: name, meaning, person/date/money
columns, section) replaces `SCHEMA_HINT` in the system prompt; roughly 60 lines. A new read-only action
`describe(tables)` returns the full entry for up to six tables, with relations and vocabularies, as data. `list_tables`
goes. Query rules that are true for every table (amount sign, newest term, "per car" = every car, ISO dates, never
`LIMIT` a join) stay in the prompt as today.

Also in the catalog: a short list of **named questions with known-good SQL** (`RECIPES`): spend by category for a
month, latest balance per account, what is open for a person, premium history. The model is told to prefer a recipe
when one fits; recipes are tested, so the common questions never regress.

### B. A better query tool (`ask_sql` in-process)

- Run the SELECT in the web app's process on a read-only connection (`db.connect(readonly=True)` +
  `PRAGMA query_only`) instead of a subprocess; keep `ask_sql.py` as the CLI for the Claude Code agents.
- Before running: `EXPLAIN` it (catches a missing table cheaply), refuse the PC-only tables and `sqlite_*` as now,
  add `LIMIT 200` when none is given, 5-second `con.set_progress_handler` timeout.
- Two repair rounds instead of one, each fed the exact SQLite error plus the `describe` entries of the tables named
  in the query.
- Results go back as a compact table plus `row_count` and `truncated`, so the model says "the first 200 of 1,340".
- Citations stay (`records.refs_for_sql`); extend `rows_used` to the first table of a simple two-table join.

### C. Answer questions about the app from its own help (`help_lookup`)

- New read-only action `help_lookup(words)` returning the top three `help_text` entries as data (title, purpose,
  sections, links). Rank with the existing `howto` scorer; it already has `SYNONYMS` and stemming.
- A written **glossary** in `help_text` (or the catalog) the model always sees, 20-30 lines: what Today / Late /
  Needs a look / Inbox / Records / Wallet are; what the statuses mean; where to fix a wrong category (Money > Ledger
  or Cards > Remember), a wrong bill amount (Open record > Change it), a duplicate (Data check), a wrongly filed
  paper (Inbox > Why?); that papers are added by dropping them in Add.
- Keep the no-AI path first (`chat_data.howto`) for the plain "How do I add a birthday?" case, but drop the regex gate
  for the AI: when an AI is set, every question can call `help_lookup`, so "my bill shows the wrong category" gets
  the Ledger answer with a link. The answer carries a `help` ref (already supported by the chat template).
- The AI is told: for "how / where / why" questions, answer from `help_lookup` and the glossary only; never invent a
  button name. The existing test that every `[Name]` in help exists in a template keeps the names true.

### D. Adding and changing records from Chat, through `edit_actions`

Route chat writes through the same functions as the dashboard forms, so each change is role-checked, validated,
logged to `logs/edits.log` with the actor, and visible in a record's history. Concretely, a second catalog
`WRITES` where the runner is a Python callable instead of an argv builder:

```python
"appointment_add": (True, "a doctor, dentist, vet or other visit on a date and time",
    {"who": text(60), "when": iso_datetime, "provider": text(80)?, "purpose": text(80)?, "amount": money?},
    lambda u, a: ea.appointment_add(u, **a)),
"bill_add": (True, "a bill to pay: name, amount, due date, how often",
    {"name": text(80), "amount": money, "due": iso_date, "vendor": text(80)?, "frequency": one_of(FREQS)?},
    lambda u, a: ea.bill_add(u, **a)),
```

`execute` dispatches on which catalog the name is in; `validate_action`, the confirm card, `voice.describe` and
`apply` do not change. New `edit_actions` functions needed: `appointment_add`, `bill_add`, `event_add`,
`note_add` (exists for phones), plus catalog entries for the existing `life_update`, `life_drop`, `bill_paid`,
`bill_unpaid`, `subscription_add`, `subscription_set_active`, `vehicle_service`, `recurring_done` by id.
`iso_datetime` is a new validator (`YYYY-MM-DD HH:MM`, 24-hour); the prompt gets "work out times from '9:30 am'".

"Dr appointment with bill for Joe, Dec 10 at 9:30" then becomes two actions in one round, `appointment_add` and
`bill_add`, shown together on one card:

> Before I change anything, please check:
> - Add an appointment for Joe on December 10 at 9:30 am (doctor)
> - Add a bill "Doctor visit, Joe", $0 (amount not known), due December 10

The card is the place to catch a missing amount: the model is told to ask one question when a required field is
missing (it does today), and to put unknown optional ones as "not known" rather than invent them.

### E. Changes after a lookup, without reopening the injection hole

The round-1-only rule exists so text inside a record or paper can never ask for a change. Keep that goal, loosen the
mechanism with two checks that Python can make, not the model:

1. **Metadata reads do not close the window.** `describe`, `help_lookup` and `list_show`-style reads return the
   app's own text, not a family's documents. Rounds that ran only those still accept changes.
2. **Provenance for everything else.** After a data-returning read (`sql_query`, `find_record`, `whats_on`,
   archive search), a change is accepted only if every text argument of the write appears, word for word (after
   normalising case and whitespace), in the user's own message or the earlier turns of this conversation, and every
   id argument is one the reads of this request returned. Dates and amounts may come from either. So "mark the bill
   due last Tuesday paid" works: the read finds the bill's id, the write is `bill_paid(id=<that id>)` with an id the
   read returned and no free text; "add a note saying <text from a document>" is refused with the same log line as today.

A new read-only `find_record(words, table?)` wraps `records.search` and returns `table:id` plus the label, so the
model has a cheap way to resolve "the water bill" to an id before writing.

### F. Small things that make it feel like a front door

- "From:" links already exist; add a **"Change it"** link on the card after a successful write (`/records?ref=`).
- Chips become context-aware: after an answer that cited bills, offer "Mark one paid"; after a how-to answer, offer
  "Open that page".
- The system prompt gets the person's name and role from `user`, so "my" resolves ("my dentist" = the signed-in
  adult).
- Tone and length rules stay (`agent_profile.tone_rule`).

## 4. Out of scope, on purpose

- Free SQL writes, or any new shell path: every change still goes through a named, validated action.
- Sending the PC-only tables (`member_info`, `home_contacts`, `wallet_cards`) or any document text to the AI from
  Chat. The catalog never lists them; `ask_sql` keeps refusing them.
- Children: Chat stays adults only.
- The phone bots' `/ask`: it inherits A, B and C (read-only) for free; D and E stay off there (`read_only=True`).

## 5. Phases and tests

**Phase 1 landed, October 2026**: `data/schema_catalog.py` (written `TABLES` for 53 tables and views, `DENY` for 22,
generated columns / relations / vocabulary samples cached in `logs/schema_catalog.json`, `RECIPES` with 10 tested
queries), `assistant.schema_text` replaces `SCHEMA_HINT` (overview + `QUERY_RULES` + recipes with their SQL; about
4.5K tokens per planning call), the `describe` action, `select_sql` refuses the denied tables, SQL repair sees the
failing query's tables, `ask_sql.run` in-process; `tests/test_schema_catalog.py`. Not done from the phase-1 column:
nothing. Noted for phase 4: the prompt grew from ~1K to ~4.5K tokens; if that shows in cost, the recipes' SQL can move
behind a `recipe(key, fills)` action.

**Phase 2 landed, October 2026**: `help_text.GLOSSARY` (20 facts about the pages, statuses and fixes, about 3.5K
characters, in every planning prompt through `assistant.app_text`), `help_text.lookup` (any wording, how-to scorer
then word search, new synonyms for charge / transaction / category / ledger / duplicate / overdue / late / snooze /
wallet / plate), `as_data`, the `help_text.py lookup | glossary` CLI, the read-only `help_lookup` action with
`Help > Title` links under the answer, and a Ledger help entry that says how to fix a category. The no-AI path in
`chat_data` is unchanged: a plain "How do I ...?" is still answered from help without an AI call, and with an AI set
every other app question reaches the model, which now has the glossary and `help_lookup`. Tests:
`tests/test_chat_help.py`.

**Phase 3 landed, October 2026**: `edit_actions.appointment_add` (person, date and time, provider, purpose,
follow-up; the same time twice refused), `bill_add` (name, due date, amount optional, vendor, frequency; same name and
due date refused), `event_add` (yearly or once), `validators.iso_datetime`; in `assistant.CATALOG` a builder made by
`edit(fn)` runs the change as `python data/edit_cli.py FUNCTION '{json}' --as NAME --role adult` (a new small script
that calls `edit_actions`, allow-listed functions only) as the signed-in person (`CLI_ACTOR`, "this PC", at the
terminal), so it is role-checked, validated twice and logged in `logs/edits.log` like a form. A subprocess rather than
an import because `edit_money -> bank_sync -> proposals -> maintenance_data -> admin_actions -> assistant` is an
existing function-level import cycle (audit A9, `tests/test_import_cycles.py`) that `assistant -> edit_actions` would
have joined; `assistant_voice.nice_when` and three
confirm sentences; the prompt says an appointment with a cost is `appointment_add` + `bill_add` in one reply. The "Dr
appointment with bill for Joe, Dec 10 at 9:30 am" example now shows two lines on one card and runs both after the
yes. Not done from the phase-3 column: exposing the existing `life_update`, `life_drop`, `bill_paid`, `bill_unpaid`,
`subscription_add`, `subscription_set_active`, `vehicle_service` by id (they need `find_record` from phase 5 to be
useful). Tests: `tests/test_chat_writes.py`.

| Phase | Work | Tests |
|---|---|---|
| 1 | `schema_catalog.py` (generated + written layers, vocabulary samples, `describe`), new overview in the system prompt, `RECIPES` | every table in the database has an entry or is on the deny list (a test that fails when a migration adds a table); each recipe runs on the demo household and returns rows; `describe` never names a PC-only table |
| 2 | `help_lookup`, glossary, regex gate lifted for the AI path | the glossary's `[Name]`s exist in templates (reuse `test_help`); fake-provider tests in `test_chat_ask.py`: "wrong category" answer cites `finance:ledger` |
| 3 | `WRITES` catalog through `edit_actions`, `appointment_add`, `bill_add`, `event_add`, `iso_datetime`; existing edit functions exposed | one test per action: validation, confirm text (`assistant_voice.describe`), `edits.log` line, the row; the two-action card for the appointment + bill example |
| 4 | In-process `ask_sql`, two repairs, LIMIT and timeout, join citations | refusal cases unchanged; a 2-table join cites the first table |
| 5 | Provenance rule for post-lookup changes, `find_record` | a change whose text comes only from a read result is refused; "mark the bill due last Tuesday paid" is accepted with the id from the read; the existing "ignored a change asked for after reading data" test flips to the provenance message |

Phases 1-3 are independent of each other and could run in parallel. Phase 5 depends on 3.

## 6. Coordination

Another developer is adding agentic features in the Family section. The pieces that overlap are `edit_actions`
(phase 3 adds functions there) and `help_text` (phase 2 adds the glossary). The catalog in `schema_catalog.py` would
serve their work too: if their feature calls the AI about family records, it should read the same table entries
rather than a second hand-written hint. Worth agreeing before either side starts: who owns `assistant.CATALOG`
changes, and that both use `edit_actions` for every write.

## 7. Open questions for the owner

1. Should Chat be allowed to **change** records after looking them up (section E), or is "add only, change on the
   page" enough for the first release? E is the only part that touches the injection defence.
2. A `bill_add` from Chat with no amount: save it with no amount (the bill shows "amount not known" on Today), or ask
   and refuse to save until the amount is given?
3. Vocabulary samples (the family's own category names) go to the AI provider as part of the prompt. They already go
   there today inside query results; is listing them up front acceptable under COMPLIANCE.md as written?
