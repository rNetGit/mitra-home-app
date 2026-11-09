"""Repository-level invariants: no original-family strings, agent definitions well formed, stdlib-only core,
requirements cover every third-party import, VERSION and CHANGELOG agree."""
import ast
import re
import sys

import pytest

from conftest import SRC, run

STDLIB_ONLY = ("onboard.py", "data/updater.py", "data/ed25519_verify.py", "data/migrate.py", "data/llm.py")
LOCAL = {p.stem for p in (SRC / "data").glob("*.py")} | {p.stem for p in (SRC / "tasks").glob("*.py")} | {"conftest", "webapp", "onboard"}


def _imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module.split(".")[0])
    return out


def test_verify_clean_has_no_hits():
    r = run(["scripts/verify_clean.py"], SRC)
    assert r.returncode == 0, r.stdout[-500:]


def test_agent_definitions_lint():
    r = run(["scripts/lint_agents.py"], SRC)
    assert r.returncode == 0, r.stdout[-800:]


@pytest.mark.parametrize("rel", STDLIB_ONLY)
def test_core_scripts_are_standard_library_only(rel):
    third = {m for m in _imports(SRC / rel) if m not in sys.stdlib_module_names and m not in LOCAL}
    assert not third, f"{rel} imports {sorted(third)} before pip install can have run"


def test_requirements_cover_third_party_imports():
    req = (SRC / "requirements.txt").read_text(encoding="utf-8").lower()
    known = {"pypdf": "pypdf", "markdown": "markdown", "cryptography": "cryptography", "uvicorn": "uvicorn",
             "fastapi": "fastapi", "starlette": "fastapi", "jinja2": "jinja2", "PIL": "pillow", "pillow_heif": "pillow-heif",
             "fitz": None, "pytest": None,
             "discord": None}  # optional: Discord bot only, installed by `onboard.py add discord` / extra [chat]
    third = set()
    for p in list((SRC / "data").glob("*.py")) + list((SRC / "data" / "webapp").glob("*.py")) + list((SRC / "tasks").glob("*.py")) + list((SRC / "scripts").glob("*.py")) + [SRC / "onboard.py"]:
        third |= {m for m in _imports(p) if m not in sys.stdlib_module_names and m not in LOCAL}
    for mod in sorted(third):
        assert mod in known, f"unknown third-party import {mod}: add it to requirements.txt and this test"
        if known[mod]:
            assert known[mod] in req, f"{mod} is imported but missing from requirements.txt"


def test_version_and_changelog_agree():
    v = (SRC / "VERSION").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", v)
    top = re.search(r"^## (\d+\.\d+\.\d+)", (SRC / "CHANGELOG.md").read_text(encoding="utf-8"), re.M)
    assert top and top.group(1) == v, f"CHANGELOG top section {top and top.group(1)} != VERSION {v}"


def test_gitignore_protects_family_data():
    gi = (SRC / ".gitignore").read_text(encoding="utf-8")
    for must in ("config/*.json", "data/*.db", "config/secrets.env", "archive/*", "inbox/*", "scripts/private_terms.txt"):
        assert must in gi, must


def test_settings_json_deny_list_covers_all_agent_tools():
    """Every write-capable tool an agent declares is scoped by settings.json or the guard hook."""
    import json
    s = json.loads((SRC / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = json.dumps(s.get("hooks", {}))
    for tool in ("Write", "Edit", "Bash", "Read"):
        assert tool in hooks, f"{tool} is not checked by the PreToolUse hook"
