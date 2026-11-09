# Mitra Home

**Your family's paperwork, bills, dates and to-dos in one calm place, on your own computer.**

Drop in a bill, a bank statement or a school calendar; Mitra Home files it, tracks what is due and tells each person
what needs them today. Everything stays on your PC. An AI helper is optional, and you choose which one.

**Why it exists.** Family admin is invisible work: someone carries the due bills, the renewals, the school forms and
the expiring passports. Mitra Home takes that load off, without putting a family's papers on someone else's server,
so evenings and weekends go back to the family. Free, no account, no subscription, no paid plan.

Website, screenshots and a click-through demo of an invented family: https://rnetgit.github.io/mitra-home/

## How it fits together
```
 phones (Android / iPhone app)  ─┐
 Mitra Wall (an old tablet)     ─┼─ home Wi-Fi, HTTPS, paired by one-time code ─►  your PC: Mitra Home
 any browser on the Wi-Fi + PIN ─┘                                                  database, filed papers, backups
                                                                                    reads papers, keeps the calendar,
 optional, your own accounts, off until you turn them on:                           writes the daily brief
   AI helper (your key or plan, or a local model) · SimpleFIN bank sync · Google Calendar / Gmail / Drive
   · Telegram / Discord · online look-ups (ZIP code only) · daily update check (GitHub)
```
No telemetry, no analytics, no server of ours. The phone app's code: https://github.com/rNetGit/mitra-home-companion

## Get started in 3 steps
1. **Download** from [Releases](https://github.com/rNetGit/mitra-home-app/releases/latest):
   `MitraHome-Setup-X.Y.Z.exe` (Windows) or `MitraHome-X.Y.Z-mac-arm64.dmg` (Mac with Apple silicon; `-mac-intel` for older Macs).
2. **Install**: run the setup on Windows; on a Mac open the `.dmg` and drag Mitra Home onto Applications. No Python, no admin rights.
3. **Open it** and answer five short screens (Welcome, Your family, Your home, Sign-in, All set). That's it: your browser shows Today.

Phones and walls on the home Wi-Fi: once an adult has a PIN, pair them in Settings > Phones (Connection there checks
Windows Firewall and restarts the app for phones if needed).

| What it keeps | |
|---|---|
| Money | bills and due dates, statements, cards, receipts, subscriptions, budget, trends, tax papers |
| Family | birthdays, school, classes, checkups, pets, a page for each child |
| Home | upkeep, service contacts, inventory, lists, meals, a wallet of IDs, cars and memberships |
| Calendar | one calendar of everything, holidays and school days off, optional Google Calendar |

Private by design: one household, one PC, per-person PINs, encrypted backups, account numbers kept as the last four
digits. No account with us, no cloud of ours. Licence: AGPL-3.0.

<details><summary>For developers: run from source</summary>

```bash
git clone https://github.com/rNetGit/mitra-home-app.git MitraHome
cd MitraHome
python launch.py          # Python 3.12+; prepares its own environment and opens the setup
```
Tests: `python -m pytest`. How releases are built and signed: `RELEASING.md`. Rules for AI agents working here: `CLAUDE.md`, `AGENTS.md`.
</details>

---

_Formerly FamilyAgent. An install made before the rename keeps working as it is: its household folder, scheduled
tasks, Drive folder, Gmail label and saved keys are still recognised, and `python onboard.py update` moves the
scheduled tasks to the new names._

## Project status
Public beta, built by a small independent team (CLOUDWARE EDGE LLC). Windows is tested most, Mac less, Linux not yet.
The United States country profile is the most complete; amounts work in any currency. Questions and ideas: GitHub
Issues and Discussions. Security problems: `SECURITY.md` (privately, please).

## No Claude account?
Choose an OpenAI / Gemini / Anthropic / OpenRouter API key or a local Ollama model in the wizard (AI step) or Settings. The Python inbox
pipeline files every document and reads policies (vehicles, drivers, coverages, premium, dates), IDs, vehicle papers, medical letters,
investment and tax papers and statements into the database; the dashboard Chat (or `python data/assistant.py`) handles everyday requests
("Sam's dentist is Oct 21", "how much did we spend on groceries?"). Only the Gmail morning brief and the insurance year-over-year review
still need Claude Code. Cursor, Codex or Gemini CLI can also be used
interactively under your own account: `AGENTS.md` tells them the rules.

## Levels: start small, add what you want
1. **Basic (laptop only):** quick start, no Google. Pick one AI (any option below), drop documents in the dashboard's *Add documents* box.
2. **Add Google Drive later:** `python onboard.py add drive` (phone drop box `Inbox` + daily/weekly `Brief` PDFs; needs Google Drive for Desktop, no Claude). **Gmail without Claude:** `python onboard.py add calendar` then `python onboard.py add gmail` (mail you label `MitraHome` is filed into the inbox, read-only; `docs/GOOGLE_GMAIL.md`). The Gmail/Calendar morning brief by Claude connector: `python onboard.py add google` (needs Claude Code).
3. **Claude Pro:** `claude_code` (everything) or `claude_cli` (cheap text-only).
4. **Codex / Gemini CLI:** `codex_cli`, `gemini_cli`, from the wizard only (Codex can read files on this PC; avoid Gemini free tier for family papers; COMPLIANCE.md).
5. **Cheap API keys or Ollama:** about $0.20 to $1 a month for a family.

## Cheaper: use the plan you already pay for
In the wizard's AI step pick `claude_cli` (Claude Pro, Haiku), `codex_cli` (ChatGPT plan) or `gemini_cli` to file the inbox and chat using
your own signed-in CLI, or an API key / local Ollama. `python data/llm.py matrix` shows who pays and what works. Full Claude Code agents
(Gmail brief, insurance review) can use `ai.claude_model: haiku` to save quota.

## Install
```bash
git clone https://github.com/rNetGit/mitra-home-app.git MitraHome     # or download the zip from Releases
cd MitraHome
python onboard.py                                                         # guided checklist (Python 3.12+, Claude Code)
```
Or, without git or Python: the Releases page has `MitraHome-Setup-X.Y.Z.exe` (Windows, installs for the user only and
brings its own Python; code-signed) and `MitraHome-X.Y.Z-mac-arm64.dmg` / `-mac-intel.dmg` (Mac).

Plain-language steps for Windows and Mac (packages, starting the app, the setup): `SETUP_NEW_FAMILY.md`, "Start here". Easiest: double-click `Start Mitra Home.bat` (Windows) or `Start Mitra Home.command` (Mac); it prepares Python and opens the setup in the browser. Agent rules: `CLAUDE.md`.

**The app** (port 8601 up), for adults: Today, Family, Calendar, Wallet, Inbox, To do, This month, Finance, Records, Notes, Chat,
Work and Settings; children and guests get a page of their own. Everyday pages are swipeable cards; Finance, Records
and Settings open on a summary (one card per area with the figure that matters, and **Needs a look**), and inside an area
a back link and one row of chips switch parts. Lists are compact rows on a phone and full tables on a PC. The **?**
button on every page opens its help. **Wallet** keeps IDs, cars with their plates, insurance, memberships and home facts
as cards, each saying where its number is printed and showing your own scan on its back (reference copies, not official
IDs); search them, open **Parking** for the plate at a meter, or add a card from a photo that the AI fills in for you to check. Since 0.99.0 it is the only app: the older Streamlit dashboard is gone.

## Update
```bash
python onboard.py check      # is a newer release out?
python onboard.py update     # updates the code, backs up and migrates your database
```
Your data (`config/`, the database, `inbox/`, `archive/`, `reports/`, `brief/`, `logs/`) is never overwritten: it lives in a folder of
its own next to the app (`../Mitra-Home-Data`, see `python data/paths.py`), or inside the app folder on an older install. Put your own tweaks in
`CLAUDE.local.md`, `.claude/settings.local.json` or `.claude/agents/local-*.md`. See `CHANGELOG.md`.

## Privacy, plainly
- The database, archive, reports and backups live on this PC. The app listens on this PC only (127.0.0.1); started
  for phones, it also answers paired phones over HTTPS on the home Wi-Fi, never plain http, and only once a PIN exists.
- When an AI agent reads a statement, bill or email, that content is sent to the AI provider the family chose: its own Claude account, its own OpenAI / Gemini / Anthropic API key, or a local Ollama model (nothing leaves the PC). Do not use agents on documents you are not comfortable sending there.
- Leaving is easy: `python data/export_data.py` writes every table as CSV (or JSON) into `exports/`; `python data/purge.py person NAME` or `python data/purge.py all` removes data (dry run first, `--yes` to do it).
- Every due date as a calendar file: `python data/export_ics.py` writes `brief/mitrahome.ics` (also from Settings in the dashboard, and copied to Drive `Brief/` weekly). Import it on any phone; no Google account needed.
- Bank and card CSV exports load with no AI at all: `python data/import_statement.py FILE.csv --account NAME` (column mapping guessed from the header, day-first dates with `--dates dmy`, card charges inverted, duplicates skipped, mapping saved with `--save-format`).
- Before the Python pipeline or the assistant sends anything, identifiers are masked (SSN, account and card numbers to their last four, emails, phones, dates of birth, ID numbers, addresses) and, for documents, your family's names are replaced by placeholders (the Chat assistant keeps names in your own
questions so it can answer "what is due for Sam"); amounts, dates and vendors stay so filing still works. `python data/llm.py redact-preview FILE` shows exactly what would go out. Free-tier Gemini is refused. The Claude Code agents read files directly unless you turn on `ai.agents_read_redacted` (the wizard asks), which makes them read documents through the same masking; scanned images then stay for a person.
- Documents are treated as untrusted data: agents are told never to follow instructions found inside a file, and a permission file plus a hook (`.claude/settings.json`, `scripts/guard_tool.py`) limit what an agent can touch to `archive/`, `reports/`, `brief/`, `inbox/` and the `data/` scripts.
- Phone briefs copied to Google Drive contain vendor names and amounts.
- Backups hold the full financial database: put them on an encrypted drive (BitLocker, FileVault, VeraCrypt).
- Agents never log in to banks or tax sites and never handle passwords. Account, policy and ID numbers are stored as last four digits only.

## Compliance
Read `COMPLIANCE.md`: sign in to Claude yourself, one account per person (no sharing, 18+), API keys (not subscription logins) for any other tool, and opt out of model training if you prefer. Mitra Home is not affiliated with or endorsed by Anthropic, OpenAI or Google.

## Not advice
Records and checklists only. Nothing here is financial, tax, legal, insurance or medical advice. Confirm with a licensed professional.

GNU AGPL-3.0-or-later (see `LICENSE`, `NOTICE`; the name and logo: `TRADEMARK.md`). Free to use, no account, no subscription. Contributing: `CONTRIBUTING.md` and `CODE_OF_CONDUCT.md`. Security reports: `SECURITY.md`. What is protected from whom: `THREAT_MODEL.md`. What is stored where, what leaves the PC, export and delete: `docs/DATA.md`. Maintainers: `RELEASING.md`.
