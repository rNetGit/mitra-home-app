# Your data: what is stored, where, what leaves this PC, how to export and delete it

Mitra Home keeps one household's records on one PC. There is no Mitra Home server, no account with us and no
telemetry. This page lists every place your data lives and every way it can leave the PC, so you can decide what to
switch on. Security details: `THREAT_MODEL.md`. AI provider terms: `COMPLIANCE.md`.

## 1. Where it lives

Everything below is in your household folder: `../Mitra-Home-Data` next to the app on a new install (the app folder names it in `mitrahome_home.txt`; an older install keeps `MitraHome_home` or `FamilyAgent_home` and `familyagent_home.txt`; the database is then `family.db` at its top), or the app folder itself on an older install. `python data/paths.py` prints every path; `python onboard.py home` moves an install to its own folder.

| Place | What is in it | Notes |
|---|---|---|
| `data/family.db` | The records (one SQLite file; tables below) | Account, card, policy, VIN, plate and ID numbers are stored as the **last four digits only**. No passwords, PINs, full card or ID numbers, or diagnoses (a title like "Dentist" is fine; the one exception is what an adult types into Records > People > Critical info, which stays on this PC and is never sent to an AI, phone or chat). Birthdays are stored as month-day with an optional year. |
| `inbox/` | Documents waiting to be filed (dropped by you, the dashboard upload or the Drive sweep) | Raw files, full detail. `inbox/needs_review/` holds files the pipeline would not guess about. |
| `archive/<year>/<category>/` | Your original documents after filing, renamed `YYYY-MM-DD_vendor_type.ext` | The only place full account numbers exist. Never deleted by Mitra Home. |
| `config/` | `family.json` (members, settings, dashboard logins as salted PIN hashes), `contacts.json`, `tax_prep.json`, `category_rules.json`, `expiries.json`, `recurring_bills.json`, `statement_formats.json`, `country/` | `config/secrets.env` holds API keys and the backup passphrase. It is never backed up, exported, shown or sent anywhere. |
| `brief/`, `reports/` | Generated summaries: daily brief, weekly digest, this week, family meeting, monthly report, emergency sheet, `mitrahome.ics`, `lists.md`, `saved.md` | Contain vendor names, amounts, due dates, names of family members. |
| `logs/` | What ran and when (see section 4) | No document text, no prompts, no list or saved-item text. |
| `exports/` | Only what you export (section 5) | Delete it when you are done. |
| `data/backups_pre_upgrade/` | A copy of the database before every update, migration and purge; copies of code files an update replaced | Same sensitivity as `family.db`. |
| `../Mitra-Home-Backup/` and any backup destination you added | Weekly backups (section 3) | Encrypted if you turned on `backup_encrypt`. |
| `CLAUDE.local.md`, `.claude/settings.local.json`, `.claude/agents/local-*.md` | Your own rules for the AI | Kept on every update. |

### What the database holds
| Area | Tables |
|---|---|
| People | `members` (names, roles, birthdays), `life_items` (school, activities, medical visits by title, pets, chores, ...), `appointments`, `events`, `activity_schedules` (weekly classes: title, provider, days, times, season; no addresses), `calendar_days` (holidays, festivals, school closures, early dismissals; proposed until an adult accepts AI or school-calendar dates), `id_documents` (type, last four, expiry), `contracts` (work profile: rate, invoice and timesheet cycle, schedule), `work_hours` (date, hours, on / off site; no names), `work_calendar` (holidays, pay days), `work_invoices` |
| Money | `accounts`, `account_balances`, `transactions`, `receipts` (store, date, total, matched charge), `statement_cycles`, `bills`, `subscriptions`, `budget`, `loans`, `investments`, `interest_income`, `card_benefits`, `amazon_orders`, `category_rules` |
| Home and car | `home_assets` (inventory, warranties), `vehicles`, `vehicle_log`, `vehicle_service_rules`, `recurring_items` + `recurring_log`, `seasonal_tasks` + `seasonal_log`, `home_office_expenses`, `home_office_profile` |
| Insurance | `policies`, `policy_vehicles`, `policy_coverages`, `policy_discounts` |
| Everyday | `recipes`, `recipe_ingredients`, `meal_plan` (meals), `lists`, `list_items` (shared lists), `saved_items` (links, notes, places, deals), `shopping_items` (shopping pack) |
| Paperwork | `documents` (one row per filed original: path, type, date, vendor), `review_queue`, `doc_search` + `doc_search_state` (archive search index: each filed document's text with account and card numbers, SSNs, emails and phones masked; rebuilt from `archive/` by `python data/archive_search.py index --rebuild`, left out of exports) |
| Housekeeping | `action_state` (done / snoozed / hidden items), `proposals` (the Inbox queue: files to review, recurring payments to decide, statements due, price rises, checkups with no date; one line each in household words, the person's choice and who made it; filled from your own records with no AI by `python data/proposals.py sync`), `schema_migrations`, `meta` |

`python data/ask_sql.py --tables` lists every table and column of your own copy.

## 2. What leaves this PC, and only if you set it up

| Where to | What | When | How to stop it |
|---|---|---|---|
| **Your AI provider** (your Claude account, your OpenAI / Gemini / Anthropic API key, or nothing at all with Ollama on this PC) | The text of a document being filed, your question to the assistant and the last few turns of that conversation, the results of the assistant's look-ups (up to four rounds per question) | Only when you or a scheduled task asks the AI to do something | Choose `ollama` or no AI (`python onboard.py add ai`). Hard identifiers (SSN/ID, account and card numbers, email addresses, phone numbers) are masked before sending, and family names too in the inbox pipeline (`data/pii.py`; preview with `python data/llm.py redact-preview FILE`). The provider keeps what it receives under its own terms (`COMPLIANCE.md`). With Claude Code agents, set `ai.agents_read_redacted` so agents read documents only through the masking. **Receipt photos** (`.jpg` / `.png` / `.webp` in the inbox) are sent only if you set `ai.read_receipt_photos: true`: a photo cannot be masked first, so whatever is printed on the receipt reaches the provider (with `ollama` it stays on this PC). |
| **Google Drive** (`Brief/` in your MitraHome folder) | PDFs of the latest daily brief and weekly digest, `mitrahome.ics` (due dates), `lists.pdf` (open items on family lists); the newest spoken brief (`*_audio.wav`) only if you add `"audio"`; `saved.pdf` (pinned family saved items) only if you add `"saved"` | After each scheduled run, only if you ran `python onboard.py add drive` | Remove entries from `"drive": {"push": [...]}` in `config/family.json`, or remove the Drive setup. Adults-only lists and private saved items never go to Drive. |
| **Google Drive** (`Inbox/`) | Nothing goes up: phone photos you drop there are moved DOWN into `inbox/` and the Drive copy is removed once the local copy is verified | Every 15 minutes with the inbox sweep | Do not set up Drive, or turn off the sweep task. |
| **Google Calendar API** (`www.googleapis.com`, sign-in at `accounts.google.com`) | A request for your calendar events, with a sign-in token; nothing else | Only if you ran `python onboard.py add calendar`, when Calendar is opened or `google_calendar.py events` runs | `python data/google_calendar.py revoke`, delete `config/google_client.json`. Read-only; the token never leaves `config/secrets.env`. Guide: `docs/GOOGLE_CALENDAR.md` |
| **GitHub** | A request for the latest release (and your read-only token if the repository is private); the release download | `python onboard.py check` / `update`, and the update button in Settings > Data | Do not run them. No family data is sent. |
| **Email / calendar** | Nothing is sent or created without your clear yes in the chat (agents' rule) | Only when you approve | Do not connect Gmail / Calendar. |

Not sent anywhere: the database, `archive/`, `config/`, `secrets.env`, backups, logs. The app listens on
`127.0.0.1` only (this PC) unless you start it for phones, and it sends no usage statistics anywhere.

## 3. Backups

(The dashboard's Settings > Data > Health check shows the newest backup in each place and whether the passphrase is found.)

`python data/backup.py` (weekly task `weekly_backup`) writes to `../Mitra-Home-Backup/` (same drive: protects
against mistakes) and to each extra destination you named (a different device: protects against drive loss):
`db/` (newest 14 database copies), `archive/` (mirror of your originals, copy-only), `config/` (never `secrets.env`),
`code/` (a small snapshot of the scripts, no data).
With `"backup_encrypt": true` contents AND file names are encrypted with your passphrase; without the passphrase an
encrypted backup cannot be read. Restore: Settings > Data > Restore from backup (picks a snapshot, checks it, closes the dashboard, keeps a copy of today's database in `../Mitra-Home-Backup/before_restore/`, puts the snapshot in place, brings back filed papers and settings that went missing, then opens the dashboard again). To restore into a new folder without touching this install: `python data/restore_backup.py SRC OUT`.

## 4. Logs

| File | What it records |
|---|---|
| `logs/edits.log` | Every change made from the dashboard: when, who, which action, which row id. Never the text you typed. |
| `logs/mitrahome.log` | Updates, migrations, backups, AI calls (provider, model, counts), errors from scripts and scheduled tasks. |
| `logs/mitrahome-web.log`, `-telegram.log`, `-discord.log` | The same, from the web app and the phone bots (each long-running process has its own file). |
| `logs/ai_usage.log`, `logs/ai_calls_<date>.count` | One line per AI call: time, provider, model, purpose, token counts, ok/error; a daily call counter for the cap. Never the prompt or the answer. |
| `logs/<task>.log`, `logs/heartbeat.json` | What each scheduled task did and when it last ran. |
| `logs/login_throttle.json` | Failed PIN attempts per name (for the lock-out), cleared after a good login. |
| `logs/purge_<time>.json` | Row counts removed by a purge (no contents). |

## 5. Export everything

```
python data/export_data.py            # every table as CSV into exports/<date_time>/, plus manifest.json
python data/export_data.py --format both --zip
python data/export_data.py --tables bills,transactions
```
The export is exactly what the database holds (last-four identifiers, vendors, amounts, dates). Saved links also come
out as `bookmarks.html` for any browser. Your originals are already plain files under `archive/`; `documents.csv`
says which is which. `config/*.json` is readable as it is. Calendar: `brief/mitrahome.ics`.

## 6. Delete

| To remove | Do this |
|---|---|
| One person | `python data/purge.py person NAME` (dry run, lists what would go) then add `--yes`. Their life items, appointments, ID documents, contracts, checkups, home-office figures, seasonal tasks, private saved items and the member row are deleted; shared rows (transactions, accounts, vehicles, lists, saved items) keep their data but forget the name. Their login and settings entry go too. A database snapshot is kept in `data/backups_pre_upgrade/`; delete it when you are sure. |
| Everything | `python data/purge.py all` (dry run) then `--yes`; add `--archive` to delete `inbox/` and `archive/` originals too. Empties every table, removes `config/*.json`, briefs, reports, logs and pre-upgrade backups. |
| One document | Move it out of `archive/` yourself; its `documents` row stays until you purge (records only point at files). |
| A dashboard item | Hide / Done / Remove never erase history; only a purge deletes rows. |

A purge cannot reach copies outside this folder. After `purge.py all`, also delete, yourself:
backups in `../Mitra-Home-Backup/` and any extra backup destination, `exports/`, the `Mitra Home` folder in Google
Drive (if set up), `config/secrets.env` (API keys), scheduled tasks (`python onboard.py doctor` lists them), and
anything your AI provider kept under its own retention policy (see its settings). Briefs or reports you copied
elsewhere are not tracked.

## 7. Retention at a glance
- Nothing in the database is deleted automatically. Ticked list items fade from the screen after 7 days but stay;
  ended deals drop off lists but stay searchable; archived lists and saved items stay.
- Backups: newest 14 database copies per destination; the archive mirror never deletes.
- `data/backups_pre_upgrade/`: grows with each update; safe to clear old ones once an update has proven fine.
- Drive `Brief/`: only the latest of each brief; older ones are moved back to `archive/old_drive_briefs/` on this PC.
