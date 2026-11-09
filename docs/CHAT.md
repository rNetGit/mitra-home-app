# Chat with Mitra Home from your phone

Family members can message Mitra Home from their phones and get quick answers: what is due this week, their own
school and chore items, birthdays. The answers come from the database on your PC. No AI writes them.

Choose one app, or set up both:

| App | Good for | Setup |
|---|---|---|
| **Telegram** | Adults, and anyone who already uses it | `python onboard.py add telegram` (below) |
| **Discord** | Kids and teens who already have Discord | `python onboard.py add discord` (below) |

## Before you start: what to know

- **Your PC has to be on and signed in** for the bot to answer. Telegram messages sent while it is off get answered
  when it comes back (Telegram keeps them for 24 hours). On Discord the bot shows as offline and commands fail until
  the PC is back.
- **Nothing on your PC is opened to the internet.** Your PC connects out to Telegram or Discord. No router changes,
  no webhooks, no port forwarding.
- **Bot chats are not end-to-end encrypted** on Telegram or Discord. Their servers see the messages and the replies. So:
  - Children and teens (role `limited`) **never** get money information: no bills, amounts or accounts.
  - Adults get bills and amounts **only in a private chat** (Telegram) or **direct message** (Discord) with the bot,
    never in a group or server channel.
  - Account numbers, ID numbers and documents are never sent.
- **Strangers get no reply.** Only people you link with a code on this PC can use the bot.
- The bot keeps a log of who used which command and whether it worked. It **never** stores the message text
  (`python data/chat_core.py log`).

## Telegram setup (about 5 minutes)

### 1. Create the bot (on your phone)

1. Install Telegram and sign in.
2. Search for **@BotFather**. Pick the one with the blue tick.
3. Send `/newbot`.
4. Give it a display name, for example `Our Mitra Home`.
5. Give it a username that ends in `bot`, for example `smith_family_agent_bot`.
6. BotFather replies with a **token** that looks like `123456789:AAH...`. Treat it like a password: anyone who has it
   can act as your bot. Don't paste it anywhere except the next step.
7. Recommended: send `/setjoingroups` to BotFather, pick your bot, choose **Disable**. Then nobody can add your bot
   to other groups.

### 2. Connect it (on your PC)

```
python onboard.py add telegram
```

The setup:
- asks you to paste the token. Typing is hidden, and the token is saved only in `config/secrets.env` on this PC.
- checks the token with Telegram and shows the bot's @name.
- offers to start the bot every time you sign in to Windows (a task named `Mitra Home Telegram Bot`). You can turn this on or off later with **Start with this PC** in Settings > Connections > Phone bot.

On macOS or Linux it prints one `@reboot` line to add to your crontab.

### 3. Link each family member

For each person, make a one-time code **on this PC**:

```
python data/chat_core.py invite Sam
```

It prints an 8-digit code. The code works once and expires in 15 minutes. Then that person:
1. opens your bot in Telegram (search its @name) and presses **Start**,
2. sends `/start 12345678` with their code.

The bot answers "Hi Sam, you're linked". Members marked as children in your family settings are linked as
`limited` automatically. To override, add `--role adult` or `--role limited`.

If someone sends five wrong codes within an hour, the bot stops listening to that account for the rest of the hour.

### 4. Use it

| Command | Adults (private chat) | Adults (group) | Children / teens |
|---|---|---|---|
| `/due` | Overdue items and the next 7 days, with amounts | The same without money items | Their own things, the family's next two weeks, birthdays |
| `/week` | Next 7 days without money items | Same | Same as `/due` |
| `/whoami` | Who the bot thinks you are | Same | Same |
| `/alerts on` / `off` | Morning alerts in this private chat | Turning off only | Their own items only |
| `/ask QUESTION` | A question about your records, answered by your AI (read-only, 20 a day; the last questions are remembered for 30 minutes so a follow-up works) | Refused (ask in private) | Refused |
| `/find WORDS` | Filed documents whose text has those words: date, type and file title only, never the text | Refused (ask in private) | Refused |
| `/inbox` | What is waiting for a decision (the dashboard's Inbox), each with numbered choices | Refused (ask in private) | Refused |
| `/ok ID [N] [DATE]` / `/no ID` | Take choice N of an Inbox item (default the first; a date for "Pick date"), or say no. Filing a document still needs the PC | Refused | Refused |
| `/unlink` | Unlink this phone | Same | Same |
| `/help` | The list of commands | Same | Same |

A family group works too. Add the bot to your Telegram family group, and in the group it answers only messages that
start with `/`.

## Discord setup (about 10 minutes, on a computer)

### 1. A family server

If the family has no server yet: in Discord press **+** (Add a Server) > **Create My Own** > **For me and my
friends**. Invite the family to it. Keep it invite-only.

### 2. Create the bot

1. Open https://discord.com/developers/applications and sign in. Press **New Application** and name it, for example
   `Our Mitra Home`.
2. **Installation**: set **Install Link** to **None**.
3. **Bot**: turn **Public Bot** OFF, so only you can add it to servers. Leave every **Privileged Gateway Intent** OFF.
   The bot doesn't need them because it never reads ordinary server messages.
4. **Bot > Reset Token > Copy.** Treat the token like a password.

### 3. Connect it (on your PC)

```
python onboard.py add discord
```

The setup:
- takes the token (hidden typing, saved only in `config/secrets.env`) and checks it with Discord.
- prints the **link that adds the bot to your server**. Open it, pick the family server, press **Authorise**. The
  bot asks only for permission to send messages.
- offers to install the `discord.py` package (about 2 MB, from PyPI). The Discord bot needs it; the Telegram bot doesn't.
- offers to start the bot every time you sign in to Windows (a task named `Mitra Home Discord Bot`).

### 4. Link each family member

Same as Telegram. Make a code on this PC:

```
python data/chat_core.py invite Sam
```

Sam opens a **direct message** with the bot (click the bot in the server's member list > Message) and sends
`/start 12345678`. Codes typed in the server are refused, so nobody else sees them.

### 5. Use it

- **In the server:** type `/` and pick `/due`, `/week`, `/whoami`, `/help`. Only the person who asked sees the
  reply. There are no money items in the server, even for adults.
- **In a direct message:** the same commands, or plain words like `due`. Adults see bills and amounts here.
  Children never do.

## Morning alerts

The bot can send each person a short private message in the morning when something is due. It's off until that
person turns it on.

- In a **private chat** (Telegram) or **direct message** (Discord) with the bot, send `/alerts on`. Send `/alerts off`
  to stop. `/alerts` shows whether they're on.
- Or on the PC: `python data/chat_core.py alerts Sam on`.
- **Adults** get overdue items and the next 3 days, with amounts.
- **Children** get only their own things (school forms, activities, chores) and family entries. Never money.
- **No message when nothing is due.** At most one alert per day per account.
- Alerts are always a private message, never posted in a group or server.
- They're sent by the daily task (7:00 by default) right after the morning brief. Preview someone's message with
  `python data/chat_alerts.py preview Sam`, or see what would go out today with `python data/chat_alerts.py send --dry-run`.
- On Discord the alert arrives even when the bot's own window isn't running, because it's sent directly.
  The person must share a server with the bot and allow direct messages from server members.

## Sending bills, statements and receipts

Adults can send the bot a photo or a file, and it lands in `inbox/` on the PC like a file you dropped there. The next
inbox check files it, and anything unclear waits in the dashboard review queue.

- **Telegram:** in your private chat with the bot, tap the paperclip and send a photo or a file (PDF, image,
  spreadsheet).
- **Discord:** attach the file in a **direct message** to the bot (up to 5 files in one message).

The rules:
- **Adults only, private chat only.** Children get a polite no, and files posted in a group or server are refused
  without being downloaded.
- Types accepted are the same as the dashboard upload: PDF, JPG/PNG/HEIC/WebP/TIFF photos, CSV, Excel, Word, OFX/QFX.
  Up to 25 MB. On Telegram, a photo is sent compressed; use **File** instead of **Photo** for small print.
- The content has to match the name. A program or web page renamed to `.pdf` is refused.
- At most 20 files a day per person. Drop bigger batches into `inbox/` on the PC.
- **Captions and message text are not read.** Writing "pay this" next to a photo does nothing. Documents are records,
  never instructions.
- The file goes to Telegram's or Discord's servers on its way to your PC, and they keep a copy in the chat. For
  statements with full account numbers, the Drive drop box or the dashboard upload keeps it off chat servers. You can
  delete the message in the chat after the bot says "saved".

## Looking after it

| Task | Command |
|---|---|
| Is the bot working? | `python data/chat_telegram.py check`, `python data/chat_discord.py check`, or `python onboard.py doctor` |
| Who is linked? | `python data/chat_core.py links` |
| Remove someone (lost phone, left the family) | `python data/chat_core.py revoke Sam` |
| What did the bot answer? | `python data/chat_core.py log --days 7` |
| Run the bot in a window instead of the task | `python data/chat_telegram.py run` or `python data/chat_discord.py run` (Ctrl+C stops it) |
| Bot output and errors | `logs/chat_telegram.out`, `logs/chat_discord.out`, `logs/mitrahome-telegram.log`, `logs/mitrahome-discord.log` |

**If the token leaks** (pasted somewhere, phone lost while BotFather was open):
1. Telegram: in @BotFather send `/revoke` and pick your bot. Discord: Developer Portal > your app > Bot > **Reset Token**.
   The old token stops working at once.
2. Run `python onboard.py add telegram` (or `add discord`) again and paste the new token.

**To turn a bot off:** stop its task. In Task Scheduler, disable `Mitra Home Telegram Bot` or `Mitra Home Discord
Bot`, or run `schtasks /delete /tn "Mitra Home Telegram Bot" /f`. To remove it for good, use `/deletebot` in
@BotFather, or delete the application in the Discord Developer Portal.

## Not yet

- Asking free-form questions. The bot only knows the commands above. AI chat stays on the PC.
