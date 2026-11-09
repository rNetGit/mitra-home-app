"""Lint the Claude Code agent definitions in .claude/agents/*.md.

  python scripts/lint_agents.py          exit 1 on any problem

Checks: YAML-ish frontmatter with name (= file name), description, tools and model; every `data/*.py`,
`scripts/*.py` or `tasks/*.py` the prose refers to exists; no backslash paths (agents run on Mac/Linux too);
agents that can write or run commands state that documents/emails are untrusted data; CLAUDE.md is referenced.
Family-added `local-*.md` agents are not checked.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / ".claude" / "agents"
REQUIRED = ("name", "description", "tools", "model")
SCRIPT_REF = re.compile(r"\b((?:data|scripts|tasks)/[\w.-]+\.py)\b")
BACKSLASH = re.compile(r"\b(data|archive|inbox|config|scripts|reports|brief|tasks|logs)\\")
WRITE_TOOLS = ("Write", "Edit", "Bash")


def frontmatter(text):
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---", 4)
    if end < 0:
        return None, text
    head = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            head[k.strip()] = v.strip()
    return head, text[end + 4:]


def lint(path):
    errs = []
    text = path.read_text(encoding="utf-8")
    head, body = frontmatter(text)
    if head is None:
        return [f"{path.name}: no frontmatter block"]
    for k in REQUIRED:
        if not head.get(k):
            errs.append(f"{path.name}: frontmatter missing `{k}`")
    if head.get("name") and head["name"] != path.stem:
        errs.append(f"{path.name}: frontmatter name `{head['name']}` differs from the file name")
    for ref in sorted(set(SCRIPT_REF.findall(body))):
        if ref.startswith("data/<"):
            continue
        if not (ROOT / ref).exists():
            errs.append(f"{path.name}: refers to {ref}, which does not exist")
    for m in BACKSLASH.finditer(body):
        errs.append(f"{path.name}: backslash path near `{body[m.start():m.start() + 30]}` (use forward slashes)")
    tools = [t.strip() for t in head.get("tools", "").split(",")]
    if any(t.split("(")[0] in WRITE_TOOLS for t in tools) and "untrusted" not in body.lower():
        errs.append(f"{path.name}: can write or run commands but never says documents/emails are untrusted data")
    if "CLAUDE.md" not in body:
        errs.append(f"{path.name}: does not tell the agent to read CLAUDE.md")
    return errs


def main():
    files = sorted(p for p in AGENTS.glob("*.md") if not p.name.startswith("local-"))
    if not files:
        print("no agent definitions found")
        return 1
    errors = []
    for p in files:
        e = lint(p)
        errors += e
        print(f"  [{'!' if e else 'x'}] {p.name}")
    for e in errors:
        print("  " + e)
    print(f"{len(files)} agent(s), {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
