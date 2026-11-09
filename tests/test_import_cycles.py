"""Audit A9: modules in data/ do not import each other in circles.

Top-level imports must form no cycle at all (a cycle there breaks at import time depending on who loads first).
Imports inside a function are how the older cycles were broken; those groups are listed below and may only shrink:
a new module joining one, or a new group, fails here. Remove a name from KNOWN when its last cycle is gone."""
import ast
import pathlib

DATA = pathlib.Path(__file__).resolve().parent.parent / "data"

KNOWN = [  # groups that import each other only from inside functions (2026-10-18; edit_family and edit_money joined when edit_actions was split: same cycle, spread over more files)
    {"assets", "expiries", "saved"},
    {"action_items", "action_state"},
    {"ai_intake", "work"},
    {"agent_profile", "autostart", "task_register"},
    {"activities", "admin_actions", "bank_sync", "calendar_days", "chat_core", "chat_telegram", "edit_actions",
     "edit_family", "edit_money", "google_gmail", "limited_view", "maintenance_data", "migrate", "migrate_025_constraints", "profile_gaps",
     "proposals", "restore_backup", "sync_data"},
]


def _graph():
    names = {p.stem for p in DATA.glob("*.py")}
    top, anywhere = {}, {}
    for name in names:
        tree = ast.parse((DATA / f"{name}.py").read_text(encoding="utf-8"))
        t, a = set(), set()

        def walk(node, in_func):
            for ch in ast.iter_child_nodes(node):
                inner = in_func or isinstance(ch, (ast.FunctionDef, ast.AsyncFunctionDef))
                found = ()
                if isinstance(ch, ast.Import):
                    found = [x.name.split(".")[0] for x in ch.names]
                elif isinstance(ch, ast.ImportFrom) and ch.module and ch.level == 0:
                    found = [ch.module.split(".")[0]]
                for n in found:
                    if n in names and n != name:
                        a.add(n)
                        if not inner:
                            t.add(n)
                walk(ch, inner)

        walk(tree, False)
        top[name], anywhere[name] = t, a
    return top, anywhere


def _cycles(graph):
    """Strongly connected groups of more than one module (Tarjan)."""
    index, low, stack, on, out = {}, {}, [], set(), []

    def visit(v):
        index[v] = low[v] = len(index)
        stack.append(v)
        on.add(v)
        for w in graph[v]:
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = set()
            while True:
                w = stack.pop()
                on.discard(w)
                comp.add(w)
                if w == v:
                    break
            if len(comp) > 1:
                out.append(comp)

    for v in sorted(graph):
        if v not in index:
            visit(v)
    return out


def test_top_level_imports_have_no_cycle():
    top, _ = _graph()
    assert _cycles(top) == [], f"import cycle at module level: {_cycles(top)}"


def test_function_level_cycles_do_not_grow():
    _, anywhere = _graph()
    for group in _cycles(anywhere):
        assert any(group <= known for known in KNOWN), (
            f"new import cycle (or a module joined one): {sorted(group)}; break it, do not add it to KNOWN")
