"""Discord bot for the family (adapter over data/chat_core.py).

  python data/chat_discord.py check      is the token set and valid? prints the bot's name and the invite link
  python data/chat_discord.py invite-url the link that adds the bot to your family server
  python data/chat_discord.py run        answer until stopped (Ctrl+C); the logon task runs this

Setup: `python onboard.py add discord` (see docs/CHAT.md). The token lives in config/secrets.env as
MITRAHOME_DISCORD_TOKEN and is never printed or logged. `check` and `invite-url` use the standard library; `run`
needs the optional package discord.py (`pip install "discord.py>=2.3"`, or `pip install -e .[chat]`), which keeps
the connection to Discord's gateway open.

How the family talks to it:
- slash commands in the family server or in a direct message: /due, /week, /whoami, /unlink, /help, /start CODE
- plain text in a direct message (`due`, `/start 12345678`)
- adults: a photo or PDF of a bill, statement or receipt attached in a direct message goes to inbox/
  (chat_core.accept_file; at most MAX_ATTACHMENTS per message; the message text is not read as instructions)
No privileged intents are needed: the bot never reads ordinary server messages. In a server, replies are ephemeral
(only the person who asked sees them) AND follow the group rules anyway: no money. Money only in a direct message,
and never for children (role `limited`). Discord does not end-to-end encrypt bot messages.
"""
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import chat_core  # noqa: E402
import log as _log  # noqa: E402

TOKEN_NAME = "MITRAHOME_DISCORD_TOKEN"
API_NAME = "MITRAHOME_DISCORD_API"  # tests only: a local stand-in for discord.com
OFFICIAL = "https://discord.com/api/v10"
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{18,40}\.[A-Za-z0-9_-]{4,10}\.[A-Za-z0-9_-]{25,60}$")
PERMISSIONS = 2048  # Send Messages, nothing else
MAX_REPLY = 1900  # Discord's limit is 2000 characters
MAX_ATTACHMENTS = 5
COMMANDS = {  # slash command -> (description, argument name or None)
    "due": ("What is due: overdue and the next days", None),
    "week": ("The family's next days (no money)", None),
    "whoami": ("Who the bot thinks you are", None),
    "unlink": ("Unlink this Discord account", None),
    "help": ("What I can do", None),
    "find": ("Find a filed document by its words (adults, direct message only)", "words"),
    "ask": ("Ask a question about your records (adults, direct message only)", "words"),
    "inbox": ("What is waiting for a decision (adults, direct message only)", None),
    "ok": ("Decide an Inbox item: its number, then a choice and a date if needed", "words"),
    "no": ("Say no to an Inbox item: its number", "words"),
    "start": ("Link your account with the code a parent made", "code"),
}
log = _log.get("chat_discord")


class DiscordError(Exception):
    pass


def _secret(name):
    import config
    return config.read_secret(name).strip()


def token():
    return _secret(TOKEN_NAME)


def valid_token_shape(t):
    return bool(TOKEN_RE.match(t or ""))


def api_base():
    """discord.com, or for tests a stand-in on this PC; anything else is refused so the token never goes elsewhere."""
    b = (_secret(API_NAME) or OFFICIAL).rstrip("/")
    if b == OFFICIAL or re.match(r"^http://127\.0\.0\.1:\d+$", b):
        return b
    raise DiscordError(f"{API_NAME} must be {OFFICIAL} (or http://127.0.0.1:PORT for tests)")


def _scrub(text, tok):
    return str(text).replace(tok, "***") if tok else str(text)


def rest(path, tok, timeout=15, body=None):
    """GET (or POST when `body` is given) on the Discord REST API."""
    headers = {"Authorization": f"Bot {tok}", "User-Agent": "MitraHome (local family bot, 1.0)"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{api_base()}{path}", data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (scheme checked in api_base)
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise DiscordError(f"{path}: HTTP {e.code}" + (" (token wrong or reset)" if e.code == 401 else "")) from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise DiscordError(_scrub(f"{path}: {getattr(e, 'reason', e)}", tok)) from None


def check(tok=None):
    """(ok, message, application_id or None)."""
    tok = tok if tok is not None else token()
    if not tok:
        return False, f"no token: run `python onboard.py add discord` (saves {TOKEN_NAME} in config/secrets.env)", None
    if not valid_token_shape(tok):
        return False, "that does not look like a Discord bot token (three parts separated by dots)", None
    try:
        me = rest("/users/@me", tok)
        app = rest("/oauth2/applications/@me", tok)
    except DiscordError as e:
        return False, str(e), None
    if not me.get("bot"):
        return False, "token does not belong to a bot", None
    if app.get("bot_public"):
        return True, f"{me.get('username')} (warning: 'Public Bot' is ON; turn it off so only you can add it)", app.get("id")
    return True, str(me.get("username")), app.get("id")


def send_dm(tok, user_id, text):
    """A direct message to one person (REST only, no gateway): open the DM channel, then post into it."""
    if not str(user_id).isdigit():
        raise DiscordError("not a Discord user id")
    ch = rest("/users/@me/channels", tok, body={"recipient_id": str(user_id)})
    if not str(ch.get("id", "")).isdigit():
        raise DiscordError("could not open a direct message")
    rest(f"/channels/{ch['id']}/messages", tok, body={"content": text[:MAX_REPLY], "allowed_mentions": {"parse": []}})


def invite_url(app_id):
    return (f"https://discord.com/oauth2/authorize?client_id={app_id}&scope=bot%20applications.commands"
            f"&permissions={PERMISSIONS}")


def as_text(command, code=None):
    """A slash command as the text chat_core understands."""
    if command not in COMMANDS:
        return ""
    return f"/{command} {code}".strip() if code else f"/{command}"


def reply_for(user_id, text, is_dm, is_bot=False, db=None, now=None):
    """The reply text for one message or slash command, or None for silence."""
    if is_bot or not isinstance(text, str) or not text.strip():
        return None
    words = text.strip().split()
    if is_dm and not words[0].startswith(("/", "!")):
        text = "/" + text.strip()  # in a DM plain `due` works too
    r = chat_core.handle("discord", str(user_id), text, private=bool(is_dm), db=db, now=now)
    return None if r is None else r[:MAX_REPLY]


def accept_attachment(user_id, filename, size, fetch, is_dm, db=None, now=None):
    """One attachment -> inbox/ via chat_core (fetch() downloads it, only after the cheap checks pass)."""
    return chat_core.accept_file("discord", str(user_id), filename, size=size, private=bool(is_dm), db=db, now=now,
                                 fetch=fetch)


def build_client(tok):  # pragma: no cover - needs discord.py and a live gateway
    try:
        import discord
        from discord import app_commands
    except ImportError:
        raise DiscordError('the Discord bot needs discord.py: pip install "discord.py>=2.3"') from None

    intents = discord.Intents.none()
    intents.guilds = True
    intents.dm_messages = True  # DM text arrives without the privileged message-content intent

    class Bot(discord.Client):
        def __init__(self):
            super().__init__(intents=intents)
            self.tree = app_commands.CommandTree(self)

        async def setup_hook(self):
            for name, (desc, takes_code) in COMMANDS.items():
                self.tree.add_command(_make(name, desc, takes_code))
            await self.tree.sync()

        async def on_ready(self):
            log.info("discord: bot %s connected to %d server(s)", self.user, len(self.guilds))
            print(f"Discord bot {self.user} running in {len(self.guilds)} server(s). Ctrl+C to stop.")

        async def on_message(self, message):
            if message.guild is not None or message.author.bot:
                return
            import asyncio
            loop = asyncio.get_running_loop()
            replies = []
            try:
                atts = list(getattr(message, "attachments", None) or [])
                for att in atts[:MAX_ATTACHMENTS]:
                    def fetch(a=att):
                        return asyncio.run_coroutine_threadsafe(a.read(), loop).result(90)
                    replies.append(await asyncio.to_thread(accept_attachment, message.author.id, att.filename,
                                                           att.size, fetch, True))
                if len(atts) > MAX_ATTACHMENTS:
                    replies.append(f"I took the first {MAX_ATTACHMENTS} files. Send the rest in another message.")
                if not atts:
                    replies.append(await asyncio.to_thread(reply_for, message.author.id, message.content, True))
            except Exception as e:  # one bad message must not stop the bot
                log.error("discord: handling DM failed: %s", type(e).__name__)
                return
            for r in replies:
                if r:
                    await message.channel.send(r[:MAX_REPLY])

    def _make(name, desc, takes_code):
        async def respond(interaction, code=None):
            is_dm = interaction.guild is None
            import asyncio
            slow = name == "ask"  # the AI can take longer than Discord's 3-second reply window
            if slow:
                await interaction.response.defer(ephemeral=not is_dm, thinking=True)
            try:
                r = await asyncio.to_thread(reply_for, interaction.user.id, as_text(name, code), is_dm)
            except Exception as e:
                log.error("discord: /%s failed: %s", name, type(e).__name__)
                r = "Something went wrong on the family PC."
            r = (r or "I can't help with that here.")[:MAX_REPLY]
            if slow:
                await interaction.followup.send(r, ephemeral=not is_dm)
            else:
                await interaction.response.send_message(r, ephemeral=not is_dm)

        if takes_code == "code":
            async def cb(interaction: discord.Interaction, code: str):
                await respond(interaction, code)
        elif takes_code == "words":
            async def cb(interaction: discord.Interaction, words: str):
                await respond(interaction, words)
        else:
            async def cb(interaction: discord.Interaction):
                await respond(interaction)
        return app_commands.Command(name=name, description=desc, callback=cb)

    return Bot()


def run():  # pragma: no cover - live gateway
    tok = token()
    ok, msg, _ = check(tok)
    if not ok:
        print(msg, file=sys.stderr)
        return 2
    try:
        client = build_client(tok)
    except DiscordError as e:
        print(e, file=sys.stderr)
        return 2
    client.run(tok, log_handler=None)
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else ""
    if cmd in ("check", "invite-url"):
        ok, msg, app_id = check()
        if not ok:
            print("Not working: " + msg)
            return 1
        if cmd == "check":
            print("OK " + msg)
            try:
                import discord  # noqa: F401
            except ImportError:
                print('Note: to run the bot, install discord.py: pip install "discord.py>=2.3"')
        print("Add to your family server: " + invite_url(app_id))
        return 0
    if cmd == "run":
        _log.use("discord")  # runs for days: a log file of its own (log.py)
        try:
            return run()
        except KeyboardInterrupt:
            return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
