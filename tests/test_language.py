"""Household language (0.55): no command, file path or framework word reaches the family outside Settings > Data >
Advanced. Every string in the app's page modules and templates and in the text that ends up on the Brief, in the
briefing documents, in the phone calendar file or in a connection error is checked; docstrings, terminal output (print,
argparse help, SystemExit) and code comparisons are not shown to anyone and are skipped."""
import ast
import re

import pytest

from conftest import SRC

BANNED = re.compile(r"python (data|tasks)/|python onboard|onboard\.py (add|check|doctor|upgrade|update)|config/|"
                    r"data/family\.db|\bTerminal:|\barchive/|[a-z_]+\.py (log|set|add|done|show|list|leads)\b")
DASHBOARD = [SRC / "data" / n for n in (
    "limited_view.py", "kid_data.py", "setup_data.py", "settings_data.py", "connections_data.py", "maintenance_data.py",
    "work_data.py", "records_edit.py", "records_data.py", "finance_data.py", "inbox_data.py", "chat_data.py",
    "notes_data.py", "brief_data.py", "calendar_data.py")] + [SRC / "data" / "webapp" / "app.py"]
TEMPLATES = sorted((SRC / "data" / "webapp" / "templates").glob("*.html"))
ADVANCED_BLOCK = re.compile(r'<details class="card more-form"><summary><h2>Advanced</h2>.*?</details>', re.S)
SHOWN = [SRC / "data" / n for n in (
    "vehicle_log.py", "id_docs.py", "export_ics.py", "make_digest.py", "make_report.py", "tax_prep.py", "emergency_sheet.py",
    "calendar_sync.py", "google_calendar.py", "chat_telegram.py", "assistant_voice.py", "proposals.py", "profile_gaps.py",
    "brief_narrative.py", "whats_on.py", "records.py", "edit_actions.py")]
ALLOWED = {("settings_data.py", "advanced")}  # the one place that shows commands (Settings > Data > Advanced)
TERMINAL = {"print", "add_argument", "ArgumentParser", "add_parser", "exit", "SystemExit", "_warn", "warn"}
CODE = {"startswith", "endswith", "split", "glob", "joinpath"}


def _shown_strings(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    skip = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
            skip.add(id(n.body[0].value))
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and (path.name, n.name) in ALLOWED:
            skip.update(id(s) for s in ast.walk(n))
        if isinstance(n, ast.Call):
            fn = n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
            if fn in TERMINAL or fn in CODE:
                skip.update(id(s) for s in ast.walk(n))
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div):  # ROOT / "data" / "family.db"
            skip.update(id(s) for s in ast.walk(n))
    return [(n.lineno, n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


@pytest.mark.parametrize("path", DASHBOARD + SHOWN, ids=lambda p: p.name)
def test_no_commands_or_paths_in_household_text(path):
    bad = [f"{path.name}:{ln}: {s[:100]!r}" for ln, s in _shown_strings(path) if BANNED.search(s)]
    assert not bad, "household language: move these under Settings > Data > Advanced or reword them\n" + "\n".join(bad)


def test_the_scan_sees_a_command_when_there_is_one(tmp_path):
    f = tmp_path / "settings_data.py"
    f.write_text('"""Doc: python data/x.py is fine here."""\n'
                 'def page(st):\n    st.caption("Run python data/members.py sync")\n'
                 'def advanced(st):\n    st.caption("python onboard.py doctor")\n', encoding="utf-8")
    found = [s for _, s in _shown_strings(f) if BANNED.search(s)]
    assert found == ["Run python data/members.py sync"], found


def test_health_rows_say_where_to_fix_in_household_words(modules):
    health = modules("health")
    rows = health.checks()
    assert rows and all("here" in r for r in rows)
    bad = [r for r in rows if BANNED.search(r["here"] or "")]
    assert not bad, bad


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_no_commands_or_paths_in_the_pages(path):
    text = ADVANCED_BLOCK.sub("", path.read_text(encoding="utf-8"))
    bad = [m.group(0) for m in BANNED.finditer(text)]
    assert not bad, f"{path.name}: household language: move these under Settings > Data > Advanced or reword them: {bad}"


def test_no_classic_view_left():
    for p in DASHBOARD + TEMPLATES:
        t = p.read_text(encoding="utf-8")
        assert "classic" not in t.lower(), p.name
    assert not (SRC / "data" / "dashboard").exists() and not (SRC / "data" / "dashboard_app.py").exists()
