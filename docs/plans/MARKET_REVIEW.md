# Where Mitra Home stands, and what to build next: review and plan, October 2026

A look at Mitra Home (0.125.0) next to the apps families use for the same jobs, the gaps that matter, and a grouped
plan to close most of them, easiest first. The market picture is from general knowledge of these products as of
mid-2026, not a fresh survey: prices and features change, so check a competitor before quoting it.

## 1. The market in four groups

No single product does what Mitra Home does. Families usually combine apps from these groups:

| Group | Typical products | What they do well | Mitra Home today |
|---|---|---|---|
| Family organizer | Cozi, FamilyWall, OurHome, Picniic | Shared calendar with two-way sync, lists, meals, chores, phone alerts | Even on calendar, lists, meals, chores. Behind on two-way calendar sync and phone alerts. |
| Wall display | Skylight, Hearth Display | A dedicated screen in the kitchen: calendar, chores with rewards, photos, meals | The Mitra Wall covers the core on an old tablet, with no hardware to buy and no subscription. Money stays behind an adult's PIN. Behind on a rewards store and photo proof of chores. |
| Money | Monarch, YNAB, Copilot, Rocket Money, Quicken Simplifi | Bank connections, budgets, goals, net worth, investments | Statements, bank downloads, ledger, budget, bills, subscriptions, trends, optional read-only bank sync. Behind on goals, net worth over time, debt payoff planning. Never pays or cancels anything (on purpose). |
| Papers and family vault | Trustworthy, Everplans, Paperless-ngx | Store documents, share essentials with a trusted person | Ahead on reading and filing papers automatically and tying them to reminders. Behind on emergency access for a trusted person. |
| AI family assistant | Ollie, Maple, Ohai and similar | Forward an email or say it in plain words; the AI files it | Chat with a confirm card, citations and "How do I" answers from help. Behind on email forwarding for non-Gmail families. |

## 2. Where Mitra Home is strong

- Local-first: the database, papers and backups stay on the family's PC; no account, no company server.
- Works without AI: common bank statements, CSV and OFX / QFX downloads and phone bills are read on the PC.
- Paperwork, money and the family calendar in one app, so a filed bill becomes a reminder by itself.
- The Mitra Wall on hardware families already own; competitors sell a screen and a subscription.
- The weekly Data check of its own records.
- Children get their own page and the wall, never money and never the AI.

## 3. Where it is weak

The biggest gap is reach, not features: it needs an always-on PC, and away from home the phone app shows only its
last copy. App-store competitors install in minutes and work anywhere. Families judge this first.

## 4. The gaps, and what we will do about them

| # | Gap | Decision |
|---|---|---|
| 1 | Phone notifications. Correction: the phone app already has an opt-in **daily** reminder (overdue and today, from its own copy, private on the lock screen) on Android and iPhone. Missing: an alert for each timed item ("Dentist in an hour") | Build: per-item alerts from the phone's copy, no server. |
| 2 | Two-way calendar sync; no Outlook / iCloud | Build: read iCloud / Outlook calendar feeds first; two-way later, for Mitra's own events only. |
| 3 | Getting started (always-on PC, setup) | Installers exist (`installer/MitraHome.iss`: Windows with its own Python; `installer/build_mac.py --dmg`). Finish: signing / notarizing, publishing them, the website's install steps (they still ask Mac users for Python), a shorter first run. |
| 4 | Forward an email to be filed (Gmail label only today) | Build: read one mail folder over IMAP (any provider), same checks as Gmail. |
| 5 | Using it away from home | Build: a guided private-network setup (Tailscale), the certificate names that address, the phone app learns it. |
| 6 | Emergency access for a trusted person | Build: an emergency pack (the sheet plus "where things are"), printable and as a passphrase-sealed file. |
| 7 | Rewards for stars, photo proof of a job | Build: rewards a child spends stars on, approved by an adult. Photo proof later. |
| 8 | Meals: recipe from a web address, grocery hand-off | Build: share or print a list now; recipe from a web address through the online look-ups switch later. |
| 9 | Money: goals, net worth over time, debt payoff, tax-preparer export | Build all four, in two steps. |
| 10 | Other languages | Build: a translation layer, then Spanish. Largest item; last. |

Not planned (by design): location sharing, paying or cancelling bills, in-app family chat. Voice assistants maybe
later, read-only. Co-parenting across two households only if families ask.

## 5. The plan, in groups, easiest first

Each group is one or more PRs. Every change keeps the existing rules: adults only for money, validated edits through
`edit_actions`, nothing sent anywhere unless the family switched it on, `pii` masking, help entries and tests updated.

### Group 1: quick wins (PC app, no new tables)
1. **Share or print a list** (#8): Share (the phone's share sheet, else copy as text) and Print on a list.
2. **Away from home with Tailscale** (#5, first half): `lan_tls` also names this PC's Tailscale address in the
   certificate; a guide (`docs/REMOTE_ACCESS.md`) for a browser on a phone away from home; the FAQ links it.
3. **Emergency pack for a trusted person** (#6): "Where things are" notes (will, password manager holder, backup
   drive, safe) kept in family.json and edited in Settings; printed on the emergency sheet; **Download a sealed copy**
   encrypts the sheet with a passphrase the family gives the trusted person.
4. **Pack for the tax preparer** (#9): one zip per tax year: the year-end summary, the tax-paper checklist, the
   home-office figures and copies of that year's filed tax papers.
5. **Net worth over time** (#9): month by month from the reported balances (cash, investments, minus cards and loans),
   on Money > Keep > Accounts.

### Group 2: family and money depth (new tables)
1. **Rewards** (#7): an adult lists rewards (for example 30 minutes of screen time = 10 stars); a child asks for one on
   the wall or their page; an adult approves; the stars are spent. The allowance stays as it is.
2. **Savings goals** (#9): a goal with an amount and a date, money set aside per month, progress from a chosen account.
3. **Debt payoff** (#9): for the loans and cards on file, what each extra amount a month does to the payoff date
   (arithmetic only, not advice).

### Group 3: connections
1. **Calendar feeds** (#2): subscribe to an iCloud, Outlook or other .ics address (read-only), shown with the Google copy.
2. **Mail folder over IMAP** (#4): one folder of any mailbox, read-only, attachments to the inbox with the Gmail checks.
3. **Two-way for Mitra's own events** (#2): an event moved in Google / iCloud comes back to Mitra Home (later).
4. **Recipe from a web address** (#8): only with online look-ups on, through `lookups.get` (public hosts, size cap).

### Group 4: the phone app (mitra-home-companion)
1. **Alerts for each timed item** (#1): next to the existing daily reminder (`Remind.java`, the iOS reminder), an alert
   before each timed appointment and event from the synced copy (for example an hour before), a switch, quiet hours;
   no server, nothing new leaves the PC. Native code on both platforms: build and try it on real phones.
2. **Away from home** (#5, second half): the pairing code also carries the Tailscale address; the app tries it when the
   home address does not answer.

### Group 5: getting started (#3)
Sign the Windows installer, notarize the Mac app, make the website's install page match (no Python step on a Mac),
and cut the first run to the questions needed for a useful Today.

### Group 6: languages (#10)
A translation layer for templates and messages (English text stays the key), dates and numbers by locale, then Spanish.

## 6. Progress

PRs are stacked: merge #28, then #29, then #30 (each later one is based on the one before).

| Group | Item | State |
|---|---|---|
| 1 | Share or print a list | done, PR #28 |
| 1 | Away from home with Tailscale (certificate, Settings, docs/REMOTE_ACCESS.md) | done, PR #28 |
| 1 | Emergency pack (Where things are, sealed copy, Print) | done, PR #28 |
| 1 | Pack for the tax preparer | done, PR #28 |
| 1 | Net worth by month | done, PR #28 |
| 2 | Paying loans off sooner | done, PR #29 |
| 2 | Savings goals | done, PR #29 |
| 2 | Rewards for stars | done, PR #29 (decision asked: should spending stars also lower the allowance?) |
| 3 | Other calendars (iCloud, Outlook, .ics), read-only | done, PR #30 (decision asked: should feeds need the look-ups switch?) |
| 3 | Recipe from a web address | done, PR #30 |
| 3 | Mail folder over IMAP (a Mitra-only mailbox, app password, read-only) | done, PR #32 (the owner allowed the app password) |
| 3 | Changes made in Google come back as Inbox cards (Mitra's own calendar only) | done, PR #33 |
| 4 | Alerts before each timed item on the phone | done in the phone app, companion PR #11: test on real phones before merging |
| 4 | Phone app away from home (Tailscale address in the pairing code) | not started: PC and both phone apps, needs real phones |
| 5 | Signed installers, website install steps, shorter first run | waiting: signing needs the Apple and Windows certificates |
| 6 | Languages (translation layer, Spanish) | not started: large; which languages and who checks translations is the owner's call |
