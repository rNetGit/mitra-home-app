# Feature tiers: Standard and Advanced

How the app's features sort into tiers, so a family can take on what fits their comfort and skill, and so every
new feature lands in a tier on purpose. Written in October 2026 after the 0.127.0 release; the code named below is the
source of truth.

There is no paid tier. The owner decided on 2026-10-25 to drop the Pro plan: every feature is free, and bank sync
(the one feature that had been marked Pro) is an Advanced feature like any other. If that ever changes, it is a new
decision, written here first.

## 1. One axis: how much the screens show

| Axis | What it is | Where it lives | Rule |
|---|---|---|---|
| **Ability** (Standard / Advanced) | A display preference: how much the screens show | `data/view_mode.py` (`ui.mode` in `config/family.json`, today named `simple` / `advanced`), `SIMPLE_PAGES`, `SIMPLE_GROUPS` | Never blocks a page, route or code path. Both levels are free. |

## 2. Two questions that place a feature

1. **Does it need a step outside the app?** An app password, a Google client file, a Tailscale account, a bot token,
   a SimpleFIN setup token, Task Scheduler. Then it is Advanced.
2. **Can a wrong setting cause silent harm?** Data leaving the PC, money figures wrong, a child seeing adult content.
   Then Advanced, and the switch asks for a confirm.

A feature that passes neither is Standard: it works after the first-run interview with no further setup.

## 3. The first cut

| Tier | Features |
|---|---|
| **Standard** | Today, Calendar, Add (drop a paper, type it in, from a photo without AI), Family, Records, Wallet, lists, meals, routines and rewards, Notes, PIN sign-in, phone pairing by QR, the Mitra Wall, the daily brief, the weekly backup, the emergency sheet, holidays packs |
| **Advanced** | AI provider and key, Chat, receipt and card photos read by AI, Google Calendar and Gmail, the mail folder (IMAP), other calendars (.ics), bank sync (SimpleFIN), online look-ups and weather, school and college look-ups, away from home over Tailscale, Telegram / Discord bots and alerts, encrypted backups and the live restore, the Data check, Work contracts and invoices, the tax-preparer pack, home office, country and seasonal packs, expiry lead times, category rules, the audio brief, task times and the "runs on its own" card, Drive briefs |

Where the table and the code disagree, the code wins until the table is applied.

## 4. How to apply it without a rewrite

1. **Names.** Keep two ability levels. In the UI call them Standard and Advanced; the stored values `simple` /
   `advanced` stay as they are so no install changes mode.
2. **One registry.** Today the tier lives in two tuples (`SIMPLE_PAGES`, `SIMPLE_GROUPS`). Replace them with one
   table, one row per feature: `key`, `tier`, `needs` (what must be set up first, in words), `help_key`. `view_mode`,
   `settings_data`, `help_text` and the first-run interview read the same rows.
3. **Fold, do not hide.** In Standard the Settings home lists Advanced cards folded under "More you can switch on",
   each with its tier badge and its `needs` line. Hidden features are never found; folded ones are.
4. **Nudges through the Inbox.** The Inbox already carries profile gaps. An adoption nudge is a `proposals` row
   (source `upgrade`): "You file bank statements every month; bank sync can do that for you." At most one a month,
   dismissable, never for a feature already on.

## 5. Open decisions for the owner

- Whether Chat belongs in Standard once a family has set an AI provider (the provider step is Advanced; the page
  itself is simple to use).
- Whether a third level ("Expert": CLI scripts, agents, `CLAUDE.local.md`) is worth a mode of its own or stays as
  documentation.
