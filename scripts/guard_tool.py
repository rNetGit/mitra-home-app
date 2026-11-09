"""PreToolUse guard for the Claude Code agents in this folder (wired in .claude/settings.json).

Documents and emails are untrusted data. If one of them carries instructions that an agent follows, the damage is
limited by this hook, not by prose: it decides, per tool call, whether the call stays inside the places an agent may
touch. It reads the hook JSON on stdin and exits 2 (blocked, reason on stderr) or 0 (allowed).

Allowed:
  * Read / Glob / Grep anywhere except config/secrets* and *.env* (and nothing under .git).
  * Write / Edit only under archive/, reports/, brief/, inbox/ and the family-owned config/category_rules.json,
    and never a program (.py, .bat, .ps1, .sh, ...): agents write documents, not code.
  * Bash: `python data/<script>.py ...` except the admin scripts in ADMIN_PY (purge, restore, PINs, phones, bots,
    Google, updates, migrations, and every script that reaches outside this PC: web look-ups, mail, the AI provider:
    those are for the family, from Settings or a terminal), `python
    scripts/verify_clean.py`, `mkdir` under archive/ or inbox/, `mv`/`cp`/`move`/`copy` of exactly one file from
    inbox/ into archive/ or inbox/needs_review/ (no third operand), and plain read-only listing (ls, dir).
Blocked: anything mentioning secrets, .env, .claude/, CLAUDE.md, tasks/, onboard.py; `python -c`; `-m`; shell
redirection, backticks and `$(...)`; curl/wget/Invoke-WebRequest; rm/del/erase/rmdir/Remove-Item; git; powershell;
pip. Chained commands (`&&`, `||`, `;`, `&`, newlines) are checked part by part.

Redacted read-through (opt-in): with "ai": {"agents_read_redacted": true} in config/family.json, agents may not open
inbox/ or archive/ files with Read, Grep, cat/head/tail/type or data/doc_text.py; they read documents through
`python data/pii.py read FILE`, which masks identifiers (last four digits kept) and the family's names first.

Families can relax this by editing .claude/settings.local.json (hooks there run in addition, they do not replace this
one); maintainers who develop inside this folder should work from the parent directory or temporarily remove the hook.
"""
import json
import os
import re
import sys

ROOT = os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _home():
    """The household folder named in mitrahome_home.txt (familyagent_home.txt before the rename; absolute, or relative
    to the app folder), else the app folder."""
    t = ""
    for name in ("mitrahome_home.txt", "familyagent_home.txt"):
        try:
            with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
                t = fh.read().strip()
            break
        except OSError:
            continue
    return os.path.realpath(os.path.join(ROOT, os.path.expanduser(t))) if t else ROOT


HOME = _home()
BASES = (HOME, ROOT) if HOME != ROOT else (ROOT,)
WRITE_OK = ("archive", "reports", "brief", "inbox")
WRITE_FILES = {os.path.join("config", "category_rules.json")}
SECRET = re.compile(r"secrets|\.env\b|\.git[/\\]", re.I)
# programs an agent must never write, wherever the folder allows documents (a script in inbox/ could be run next)
PROGRAM_EXT = {".py", ".pyw", ".pyc", ".pyd", ".pth", ".bat", ".cmd", ".ps1", ".psm1", ".sh", ".bash", ".zsh", ".command",
               ".exe", ".com", ".dll", ".so", ".vbs", ".js", ".jse", ".wsf", ".wsh", ".msi", ".scr", ".lnk", ".reg", ".jar"}
BASH_BLOCK = re.compile(
    r"secrets|\.env\b|\.claude[/\\]|CLAUDE\.md|\btasks[/\\]|onboard\.py|\bpython\d?(\.exe)?\s+-[cm]\b|\bpy\s+-[cm]\b|"
    r"[<>|`]|\$\(|\$\{|\brm\b|\bcurl\b|\bwget\b|Invoke-\w+|\bdel\b|\berase\b|\brmdir\b|Remove-Item|\bgit\b|powershell|pwsh|"
    r"\bpip\d?\b|\bsudo\b|\bchmod\b|\bstart\b|\bcmd\b|\bxargs\b|\beval\b", re.I)
PY_OK = re.compile(r"^\s*python\d?(\.exe)?\s+(data[/\\]([\w.-]+)\.py|scripts[/\\]verify_clean\.py)(\s|$)", re.I)
# data/ scripts that change who may get in, delete or replace the household's data, talk to outside services, or
# change the code: the family runs these from Settings or a terminal, never an agent acting on a document
ADMIN_PY = {"purge", "restore_backup", "auth", "devices", "lan_tls", "chat_core", "chat_telegram", "chat_discord",
            "autostart", "updater", "init_db", "seed_demo", "google_calendar", "google_gmail", "calendar_sync",
            "drive_setup", "export_data", "task_register", "admin_actions", "web_app", "first_run", "setup_interview",
            "setup_data", "release_keys", "sign_release", "backup", "crypto_box", "heartbeat", "bank_sync",
            "traditions",
            # these reach outside this PC (web pages, mail servers, the AI provider) or change the system: a document
            # steering an agent must not be able to send anything out through them
            "recipe_web", "lookups", "calendar_feeds", "calendar_find", "calendar_import", "mail_folder", "schools",
            "weather", "make_audio_brief", "llm", "assistant", "firewall", "sync_all"}
MKDIR_OK = re.compile(r"^\s*mkdir\s+(-p\s+)?[\"']?(archive|inbox)[/\\][^\s\"']*[\"']?\s*$", re.I)
# exactly one source under inbox/ and one destination under archive/ or inbox/needs_review/: a third operand would
# make the last one the destination folder (`cp inbox/x archive/ data/`)
_SRC = r"(?:\"inbox[/\\][^\"]+\"|'inbox[/\\][^']+'|inbox[/\\][^\s\"']+)"
_DST = r"(?:\"(?:archive|inbox[/\\]needs_review)[/\\][^\"]*\"|'(?:archive|inbox[/\\]needs_review)[/\\][^']*'|(?:archive|inbox[/\\]needs_review)[/\\][^\s\"']*)"
MOVE_OK = re.compile(r"^\s*(mv|cp|move|copy)\s+(-\w+\s+)*" + _SRC + r"\s+" + _DST + r"\s*$", re.I)
LIST_OK = re.compile(r"^\s*(ls|dir|pwd|cat|head|tail|wc|type)\b", re.I)
DOC_DIRS = ("inbox", "archive")
RAW_READ_CMD = re.compile(r"^\s*(cat|head|tail|type|more|less|strings|od|xxd)\b|python\d?(\.exe)?\s+data[/\\]doc_text\.py", re.I)
DOC_PATH = re.compile(r"(?:^|[\s\"'=])(?:\./)?(inbox|archive)[/\\]", re.I)
REDACT_MSG = ("this family reads documents through masking (ai.agents_read_redacted): use "
              "`python data/pii.py read <file>` instead; images and scans cannot be masked and go under Needs your input")


def redacted_mode():
    try:
        with open(os.path.join(HOME, "config", "family.json"), encoding="utf-8") as fh:
            return bool((json.load(fh).get("ai") or {}).get("agents_read_redacted"))
    except (OSError, ValueError):
        return False


def is_doc(path):
    r = rel(path) if path else None
    return bool(r) and r.split(os.sep)[0] in DOC_DIRS and os.path.splitext(r)[1] != ""


def rel(path):
    """Path relative to the household folder or the app folder, None when it is in neither."""
    p = os.path.realpath(os.path.join(ROOT, path)) if not os.path.isabs(path) else os.path.realpath(path)
    for base in BASES:
        if p != base and p.startswith(base + os.sep):
            return os.path.relpath(p, base)
    return None


def plain(cmd):
    """A shell line with the household folder's absolute path shortened away, so the relative-path rules apply to it."""
    if HOME == ROOT:
        return cmd
    for form in (HOME + os.sep, HOME.replace(os.sep, "/") + "/", HOME.replace(os.sep, "\\\\") + "\\\\"):
        cmd = cmd.replace(form, "")
    return cmd


def block(msg):
    sys.stderr.write(f"guard_tool: {msg}\n")
    sys.exit(2)


def main():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return  # not a hook payload; do nothing
    tool = d.get("tool_name") or ""
    inp = d.get("tool_input") or {}
    path = inp.get("file_path") or inp.get("path") or inp.get("notebook_path") or ""

    if tool in ("Read", "Glob", "Grep", "LS"):
        target = path or inp.get("pattern") or ""
        if SECRET.search(str(target)):
            block("reading secrets, .env files or .git is not allowed")
        if tool in ("Read", "Grep") and redacted_mode():
            if tool == "Read" and is_doc(path):
                block(REDACT_MSG)
            if tool == "Grep" and DOC_PATH.search(" " + str(inp.get("path") or inp.get("glob") or "")):
                block(REDACT_MSG)
        return

    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        r = rel(path) if path else None
        if r is None:
            block(f"writes outside the project are not allowed: {path}")
        if SECRET.search(r):
            block("writing secrets or .env files is not allowed")
        if os.path.splitext(r)[1].lower() in PROGRAM_EXT:
            block(f"agents write documents, never programs or scripts (asked for {r})")
        top = r.split(os.sep)[0]
        if top in WRITE_OK or r in WRITE_FILES:
            return
        block(f"agents may only write under {', '.join(WRITE_OK)}/ or config/category_rules.json (asked for {r})")

    if tool == "Bash":
        cmd = str(inp.get("command") or "")
        # split on command separators so one call cannot chain an allowed command with a blocked one
        parts = [plain(p) for p in re.split(r"&&|\|\||;|&|\n|\r", cmd) if p.strip()]
        redacted = redacted_mode()
        for part in parts:
            if BASH_BLOCK.search(part):
                block(f"not allowed for agents: {part.strip()[:80]}")
            if redacted and RAW_READ_CMD.search(part) and DOC_PATH.search(" " + part):
                block(REDACT_MSG)
            py = PY_OK.match(part)
            if py and py.group(3) and py.group(3).lower() in ADMIN_PY:
                block(f"data/{py.group(3)}.py is for the family (Settings or a terminal), not for agents")
            if not (py or MKDIR_OK.match(part) or MOVE_OK.match(part) or LIST_OK.match(part)):
                block(f"only `python data/<script>.py`, mkdir under archive/ or inbox/, and one-file moves from inbox/ "
                      f"to archive/ are allowed (asked for: {part.strip()[:80]})")
        return


if __name__ == "__main__":
    main()
