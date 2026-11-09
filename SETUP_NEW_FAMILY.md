# Setting up Mitra Home for a new family

One family = one folder = one database, on that family's own PC. Nothing is shared between families; only the code is.

## Start here (about 15 minutes, laptop only)
You need: a PC or Mac that is usually on, Python 3.12 or newer, and one AI choice (an API key, a local model, or a Claude / ChatGPT / Gemini plan you already pay for; see "Which AI login should we use?" below). No Google account is needed to start.

1. **Get the code.** Download the release from GitHub Releases and unzip it (or `git clone https://github.com/rNetGit/mitra-home-app.git`) into a folder of your own, for example `D:\MitraHome` on Windows or `~/MitraHome` on a Mac. Your household data will live in a second folder next to it (`Mitra-Home-Data`), so updates never touch it.
2. **Double-click the starter.**
   - Windows: `Start Mitra Home.bat`.
   - Mac: `Start Mitra Home.command`. The first time, right-click it and choose Open > Open (macOS asks once).
   - Linux: `sh "Start Mitra Home.command"`.

   The first time it prepares Python for you (a private environment, nothing installed system-wide; about a minute, then the packages, a few minutes) and, on a brand-new install, makes your household folder next to the app. Then it opens the browser on the setup. If this PC has no Python 3.12 or newer, the starter opens the download page and tells you what to do; install it (Windows: tick "Add python.exe to PATH") and double-click again. Keep the black window open while you use Mitra Home: closing it stops it. Starting it again opens the same one instead of a second one.

3. **Answer the chat.** It asks a few questions (family, AI choice, people, home, cars, PINs), then asks you to drop a few papers. You can stop any time and come back; it resumes. At the end, Settings > Data > "Runs on its own" sets up the daily brief, the weekly digest and the weekly backup (each with its own on / off switch, time and last run); optional features and tax names are under Settings > Household profile.
4. **Check health** whenever you like: `python onboard.py doctor` (Mac: `python3`).

Prefer a terminal? `python launch.py` starts the dashboard the same way, and `python onboard.py` runs the setup as a checklist (13 steps below). Everything else (phone drop box, Gmail, calendar, backups to a second drive) can be added later with `python onboard.py add NAME`.

### Mac notes
- Everything above is the same on a Mac; the starter needs Python 3.12 or newer (`brew install python@3.12`, or the installer from python.org).
- Terminal instead of double-click: `python3 launch.py` from the app folder does the same thing.
- Scheduled tasks use `cron`: the wizard shows the lines and installs them into your crontab if you say yes. If they never run, macOS may be blocking cron from your folders: allow `cron` (Terminal) under System Settings > Privacy & Security > Full Disk Access.
- Starting with the Mac, restoring a backup from the dashboard, and Google Drive for Desktop paths are only lightly tested on macOS. Report anything odd with sanitized text only.
- Drive for Desktop on a Mac mounts under `~/Library/CloudStorage/GoogleDrive-...`; `python onboard.py add drive` asks for the folder.

## Phones on the home Wi-Fi (optional)
1. Finish the first-run chat on the PC (or the web app's setup) and give each adult a PIN (the setup asks; also Settings > Home Profile). Phone access is refused until at least one PIN exists.
2. Start Mitra Home as usual. Phones and walls on the home Wi-Fi may connect by default (Settings > Phones > Connection switches it off or on); if it was running before the first PIN existed, press **Restart for phones** there. The window prints an address such as `https://192.168.1.20:8701` (the app's port + 100) and the certificate fingerprint. The PC itself keeps using `http://127.0.0.1:8601`. `Start Mitra Home for phones.bat` / `.command` still force it on; the Start menu's "Mitra Home (this PC only)" keeps it off.
3. On the phone, on the same Wi-Fi, open that address in the browser. The browser warns about the certificate the first time (it is this PC's own): continue only when the fingerprint it shows matches the one in Settings > Phones. Sign in with your PIN. "Add to Home Screen" makes it an icon.
4. If the phone cannot connect: Settings > Phones > Connection checks Windows Firewall and the network type. **Allow phones through Windows Firewall** adds one inbound rule (the phone port only, Private networks only) after Windows asks you to confirm; a network marked Public blocks phones even then, and the page opens Windows' Wi-Fi settings to make it Private. The window also prints the same `netsh` line for PowerShell as administrator.
- The phone app (later release) pairs from Settings > Phones on this PC: a one-time QR code, 5 minutes. Remove a lost phone there.
- It works only while that window is open and the PC is on. Encrypted with this PC's own certificate; still home Wi-Fi only, never a guest or public network.
- Away from home, use a private network such as Tailscale on the PC and the phones, and open `https://` + the PC's Tailscale address + `:8701` (same certificate check). Settings > Phones shows that address; step by step in docs/REMOTE_ACCESS.md.
- Give the PC a fixed address in your router (a DHCP reservation) so the link does not change.

## The checklist (what the wizard walks through)
1. Prerequisites: Python, packages (`requirements.txt`), Claude Code CLI.
2. Folders: your household folder (`../Mitra-Home-Data` next to the app, recommended; or inside the app folder) with
   `inbox/ archive/ brief/ reports/ exports/ logs/ config/` and the database. `python onboard.py home [PATH]` moves an
   existing install there; `python data/paths.py` prints where everything is.
3. Family profile: name, members (adult/child/pet, birthdays), country and climate (picks your seasonal task pack), agent Gmail, optional Drive folder -> `config/family.json`.
4. Database: schema + versioned migrations on an EMPTY database; seasonal pack applied; health reminders per member.
5. Agent account: create a NEW Gmail for the household agent; connect Gmail, Calendar, Drive in Claude Code (`/mcp`); create labels `Mitra Home`, `MitraHome/Processed`, `MitraHome/Needs review`.
6. AI provider: Claude Code under your own login (default), or an API key for Anthropic / OpenAI / Gemini, or a local Ollama model, for the Python inbox pipeline. Plain consent text; keys go to `config/secrets.env` only. Identifiers and family names are masked before anything is sent (`python data/llm.py redact-preview FILE` shows what goes out); free-tier Gemini is refused.
7. Safety rules and compliance summary (see `COMPLIANCE.md`).
8. Optional packs: festivals, contracts, Amazon, shopping.
9. Tax-prep payers (optional): banks/brokers that send 1099-INT, the state tax agency's name, your tuition payee -> `config/tax_prep.json`.
10. Family life: starter items, emergency contacts file, home-office tax prep, optional per-person dashboard logins.
11. Scheduled tasks and backups: daily digest, weekly digest + family-meeting agenda, weekly backup (**encrypted** if you choose; keep the passphrase somewhere safe that is not this PC). Windows Task Scheduler or cron on Mac/Linux.
12. First data drop: download statements yourself, drop in `inbox/`, then tell Claude "process inbox".
13. Doctor: integrity, digest builds, permissions file, Claude and AI provider answer, backups, no leftover original-family text.

## Troubleshooting
**`401 failed to authenticate API key` (loops "Retrying...") even after `/login` succeeds**
Some environment setting is redirecting Claude Code or overriding your own sign-in. Usual causes:
`ANTHROPIC_BASE_URL` (a leftover proxy/gateway), `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, or `apiKeyHelper` in `~/.claude/settings.json`.
`python onboard.py doctor` detects these (names only, never values). To fix by hand in PowerShell:
```powershell
Get-ChildItem Env: | Where-Object Name -match "ANTHROPIC|CLAUDE" | Select-Object Name
Remove-Item Env:ANTHROPIC_BASE_URL -ErrorAction SilentlyContinue
[Environment]::SetEnvironmentVariable("ANTHROPIC_BASE_URL",$null,"User")
```
(repeat for `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` if listed). Close the terminal, open a new one, run `claude`, then `/status` — it should show YOUR account (Pro/Max), not "API key".
Each family signs in with its own Claude account; do not share keys or logins between families.

## Getting and updating the code while the repository is private
No GitHub account or git login is needed on the family's PC.
1. First install: the maintainer sends the release zip (downloaded from the repo's Releases page) together with `SHA256SUMS` and `SHA256SUMS.sig`. Unzip it to the family's folder and follow "Start here" above.
2. Updates: the maintainer gives the family a read-only token (a GitHub fine-grained token for this one repository, Contents: read-only, with an expiry date). The family stores it once as a user environment variable named `MITRAHOME_TOKEN` (Windows: Settings > System > About > Advanced system settings > Environment Variables; Mac/Linux: add `export MITRAHOME_TOKEN=...` to the shell profile). Then `python onboard.py check` and `python onboard.py update` work as usual.
3. The token is only sent to GitHub, never stored by Mitra Home, and can be revoked or rotated by the maintainer at any time. Share it privately (not in a public chat or email thread).
4. No token? The maintainer can send a newer zip and the family runs `python onboard.py update --from MitraHome.zip`.

## Updating
`python onboard.py check` then `python onboard.py update` (or `update --from MitraHome.zip` if you were sent a zip). Code is replaced, your data is not; the database is backed up and migrated automatically. Customise only via `config/`, `CLAUDE.local.md`, `.claude/settings.local.json`, `.claude/agents/local-*.md`. Release notes: `CHANGELOG.md`.

## Support boundary
The maintainer never gets access to the family's database or archive. Share sanitized error text only.

## Optional packs (step 7)
Off by default; switched in `config/family.json` under `packs`. Enabling one with example data copies it to `config/` (edit it afterward).
- `festivals` -> `config/festivals.json` (list of start/end/name; the example is an Indian festival list, replace with your own).
- `contracts`, `amazon`, `shopping`: no data files; they just show their Planner tabs, digest lines and alerts.
Your own categorization rules: `config/category_rules.json` as `[["PATTERN%", "category", "txn_type", "Payee"], ...]` (see `data/apply_rules.py`).

## Adding things later
`python onboard.py add NAME`: `drive` (phone drop box + briefs), `calendar`, `gmail`, `google` (Claude connectors), `telegram`, `discord`, `backup` (second drive + weekly schedule), `tax`, `family`, `ai`.
Documents: drop them in the Inbox page of the dashboard, or copy them into the household folder's `inbox/`.
Phone bills: drop the Verizon PDF in the Inbox; each line's cost per person appears under Finance > Phone bills (read on this PC, no AI).

## Google Drive: phone drop box and briefs (optional, `python onboard.py add drive`)
Install **Google Drive for Desktop** on the family PC and sign in with the head of the family's Google account, then run `add drive`.
- **Inbox (phone -> PC):** on the phone open Drive > MitraHome > Inbox > + > Scan or Upload. Every 15 minutes the PC moves settled files into its own `inbox/` (the Drive copy is removed after the PC copy is verified), then they are filed as usual.
- **Brief (PC -> phone):** only the daily brief and weekly digest, as PDFs. They show vendor names and amounts.
- In Drive for Desktop set the MitraHome folder to *Mirror files* so the PC always has the files. The PC must be on and signed in for the sweep to run.
- Do **not** share `Inbox` with anyone you would not trust to put files into your records; share `Brief` only with people who may see your bills.
- Raw documents, the database and backups never go to Drive. Change which briefs are sent with `"drive": {"push": [...]}` in `config/family.json`.
- Not working? `python data/drive_setup.py check` and `python onboard.py doctor`.

## Which AI login should we use?
| You have | Pick | Cost | Limits |
|---|---|---|---|
| Claude Pro | `claude_code` (all features, `ai.claude_model: haiku` to save quota) or `claude_cli` (inbox + chat, cheapest) | Your plan | Plan quota; scheduled runs are ordinary-use only |
| ChatGPT plan | `codex_cli` | Your plan | Text only; run it yourself |
| Google account | `gemini_cli` | Free/plan | Free tier trains on prompts: avoid |
| Any API key | `openai` / `gemini` / `anthropic` / `openrouter` (one key, many models) | Cents per month | Good for scheduled runs |
| Nothing | `ollama` | Free | Lower accuracy |
Details and terms: COMPLIANCE.md. Run `python data/llm.py matrix` any time.

## What works without a Claude account
| Works (API key or local model) | Needs Claude Code |
|---|---|
| Inbox: every document is typed and filed by `data/ai_intake.py`; policies (vehicles, drivers, coverages, premium, dates), IDs, vehicle papers, medical letters, investment and tax papers are read into their tables (`data/doc_extract.py`); statements are imported when the lines add up to the printed balances (no-AI reader first, then the AI); uncertain files wait in the Inbox | Insurance year-over-year review and coverage-gap checklist (`insurance` agent) |
| Everyday requests and questions: Chat in the dashboard or `python data/assistant.py` | The `family` agent chat inside Claude Code, `email-intake` (Gmail) |
| Dashboard, digests, family meeting, taxes + home office numbers, life items, loans, budget, seasonal packs, emergency sheet, backups, updates, per-person logins | Gmail / Calendar morning brief (uses the Claude connectors) |
Cursor, Codex or Gemini CLI used by a person under their own account can follow `AGENTS.md`. Cursor subscriptions cannot be called from code.

## Known gaps
- Statements: the no-AI reader knows common PDF layouts; others are read by the AI and imported only when the lines add up. Very long statements (over ~60,000 characters) need a CSV export.
- Seasonal packs are general guidance for broad regions (windows vary by city): edit `packs/seasonal/*.json` or copy one into `config/seasonal/`.
- The festival example is Indian (Hindu/Telugu); other cultures need a new festivals JSON.
- Encrypted backups need the passphrase to restore; there is no recovery if it is lost. Plain (unencrypted) backups are possible but not recommended.
- Dashboard logins keep people out of the screen on a shared PC; they are not strong security (anyone with file access can read the database).
- Mac/Linux: scheduling uses cron; a Mac install has been run by hand and worked, but `sync_drive.py`, Drive for Desktop paths, "Start with this PC" and restore-from-backup are only tested on Windows. Linux is untested.
- Phone bills: only Verizon bills are read per person; other carriers are filed as one bill.
- The Python inbox pipeline (OpenAI / Gemini / Anthropic API / OpenRouter / Ollama / signed-in CLIs) is tested against mock servers, not live services: press Settings > Connections > AI provider > Test, or run `python onboard.py doctor` with your key.
- Gmail/Calendar morning briefs still need the Claude connectors (MCP). Without Claude, Calendar (`add calendar`) and Gmail filing (`add gmail`, read-only, one label) go straight to Google's API; there is no direct-API morning brief or mail summary.
- Not yet tested on a second real PC; Task Scheduler / cron registration only tested by hand.
- Run `python -m pytest` (needs `pip install -r requirements-dev.txt`) after any change: it builds throwaway families in a temp folder and exercises every module. `python scripts/smoke_test.py` runs the release subset.

## Leaving, or removing one person
Full list of what is stored where and what to delete outside this folder: `docs/DATA.md`.

- `python data/export_data.py` writes every table as CSV files into `exports/<date_time>/` (add `--format json` or
  `--zip`). Open them in any spreadsheet. The archived originals are already plain files under `archive/`.
- `python data/purge.py person NAME` shows what belongs to that person; add `--yes` to delete it (a database snapshot is
  kept in `data/backups_pre_upgrade/` and a receipt with counts in `logs/`). Shared money rows keep their numbers and
  forget the name.
- `python data/purge.py all` shows what a full wipe removes; `--yes` empties every table and removes `config/*.json`,
  briefs, reports and logs; add `--archive` to delete `inbox/` and `archive/` originals too. Backups outside the folder
  (`../Mitra-Home-Backup`, your second backup location, the Drive folder) are listed for you to delete by hand.
