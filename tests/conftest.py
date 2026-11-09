"""Shared fixtures: every test module gets its own throwaway copy of the template (never your real data).

`root` is a migrated, seeded copy: the template is migrated and seeded once per test session (`golden`) and each test
module gets its own copy of that (no copy stores its own path, so a copied copy works the same). `modules` imports data/
modules bound to THAT copy (and forgets modules bound to an earlier copy, so modules never see each other's database).
`run` executes a script in a copy.
"""
import contextlib
import datetime as dt
import http.server
import importlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns("__pycache__", "*.db", "family.json", "onboard_state.json", "heartbeat.json", ".git",
                                "private_terms.txt", "backups_pre_upgrade", ".pytest_cache", ".ruff_cache", "mitrahome_home.txt", "familyagent_home.txt",
                                "dist")
FAMILY = {
    "family_name": "Test", "agent_email": "agent@example.com", "currency": "USD", "climate": "mild",
    "region": {"place": "Austin", "state": "TX", "county": "", "zip": ""},
    "members": [{"name": "Alex", "role": "adult", "birth_month_day": "03-14", "birth_year": 1985},
                {"name": "Sam", "role": "child", "birth_month_day": "09-02"},
                {"name": "Biscuit", "role": "pet"}],
    "packs": {}, "tasks_registered": False,
}
DRY = {"AIFA_DRY_RUN": "1"}  # onboard.py: never touch Task Scheduler / cron, never ping Claude
# The real Task Scheduler / crontab of the PC running the tests is never touched, in this process or a child one
# (task_register.live_runner). Tests that check scheduling pass their own fake runner.
os.environ["MITRAHOME_NO_SCHEDULER"] = "1"
# Backstop for code that ignores that switch (an older release's code, a new call that forgets it): every Python the
# suite starts loads scheduler_guard/sitecustomize.py, which never lets schtasks / crontab / launchctl run, and a command
# that would have changed a task fails the test that caused it (_scheduler_tripwire).
GUARD = Path(__file__).resolve().parent / "scheduler_guard"
_paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p and Path(p) != GUARD]
os.environ["PYTHONPATH"] = os.pathsep.join([str(GUARD), *_paths])
TRIPWIRE = Path(tempfile.gettempdir()) / f"mitrahome_scheduler_tripwire_{os.getpid()}.jsonl"
TRIPWIRE.unlink(missing_ok=True)
os.environ["MITRAHOME_SCHEDULER_TRIPWIRE"] = str(TRIPWIRE)
_spec = importlib.util.spec_from_file_location("mitrahome_scheduler_guard", GUARD / "sitecustomize.py")
_spec.loader.exec_module(importlib.util.module_from_spec(_spec))  # installs the guard in this process
_tripped = [0]  # tripwire lines already reported
_BOUND = []  # copies whose data/ dir has been on sys.path


def _tripwire_lines():
    try:
        return TRIPWIRE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


@pytest.fixture(autouse=True)
def _scheduler_tripwire():
    """Fail the test (or the fixture before it) that tried to register, change, run or remove a real scheduled task."""
    yield
    lines = _tripwire_lines()
    new, _tripped[0] = lines[_tripped[0]:], len(lines)
    if new:
        pytest.fail("tried to change this PC's real scheduled tasks (blocked by tests/scheduler_guard):\n  " + "\n  ".join(new))


def pytest_configure(config):
    """Parallel runs keep each test module on one worker: a module's tests share one copied install and build on each
    other's state, so plain `pytest -n auto` (xdist's default "load" spreads one file over several workers) would fail
    them. scripts/smoke_test.py already passes --dist loadfile; this makes it the default for any -n run."""
    if getattr(config.option, "dist", "no") == "load":
        config.option.dist = "loadfile"


def pytest_sessionfinish(session, exitstatus):
    new = _tripwire_lines()[_tripped[0]:]
    if new:
        print("\nTried to change this PC's real scheduled tasks (blocked):\n  " + "\n  ".join(new))
        session.exitstatus = 1
    TRIPWIRE.unlink(missing_ok=True)


def run(args, cwd, env=None, timeout=300, input=None):
    """python <args> inside a copy; stdin closed unless `input` is given."""
    return subprocess.run([sys.executable, *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          stdin=subprocess.DEVNULL if input is None else None, input=input,
                          env={**os.environ, **(env or {})})


def _ignore(folder, names):
    """IGNORE, plus a family's own settings: only the shipped config/*.example.json files go into a test copy, so tests
    run inside a real install neither see that family's config (recurring bills, leads, formats) nor copy secrets.env."""
    out = set(IGNORE(folder, names))
    if Path(folder).resolve() == (SRC / "config").resolve():
        out |= {n for n in names if not n.endswith(".example.json")}
    if Path(folder).resolve() == SRC.resolve():
        out.add("mobile")  # the phone app's source (export-ignored): not part of an install
        out.add("installer")  # maintainer build scripts and their downloads (export-ignored, hundreds of MB)
    return out


def copy_template(dst, family=True):
    shutil.copytree(SRC, dst, ignore=_ignore)
    (dst / "config").mkdir(exist_ok=True)
    (dst / "inbox").mkdir(exist_ok=True)
    if family:
        write_family(dst, FAMILY)
    return dst



def read_family(root):
    return json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))


def write_family(root, fam):
    (root / "config" / "family.json").write_text(json.dumps(fam), encoding="utf-8")


def set_ai(root, provider, **kw):
    fam = read_family(root)
    fam["ai"] = {"provider": provider, **kw}
    write_family(root, fam)


def seed(root):
    for args in (["data/migrate.py"], ["data/members.py", "sync"], ["data/life.py", "seed"], ["data/seed_demo.py"]):
        r = run(args, root)
        assert r.returncode == 0, f"{' '.join(args)} failed: {r.stderr[-500:]}"


def db(root):
    return sqlite3.connect(root / "data" / "family.db")


def q(root, sql, *params):
    con = db(root)
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def bind(root):
    """Make `import llm`, `import auth`... resolve to this copy's data/ (and tasks/) modules."""
    for old in _BOUND:
        for p in (str(old / "data"), str(old / "tasks")):
            while p in sys.path:
                sys.path.remove(p)
    old_roots = [str(r) for r in _BOUND]
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None) or ""
        if any(f.startswith(r) for r in old_roots):
            del sys.modules[name]
    _BOUND.append(root)
    sys.path.insert(0, str(root / "tasks"))
    sys.path.insert(0, str(root / "data"))


@contextlib.contextmanager
def imported_from(folder, name):
    """Import module `name` fresh from `folder` for one block; afterwards the folder leaves sys.path and every module
    loaded from it is forgotten, so later test modules (or xdist neighbours) never see it."""
    folder = str(folder)
    sys.path.insert(0, folder)
    try:
        sys.modules.pop(name, None)
        yield importlib.import_module(name)
    finally:
        while folder in sys.path:
            sys.path.remove(folder)
        for k, m in list(sys.modules.items()):
            if (getattr(m, "__file__", None) or "").startswith(folder):
                del sys.modules[k]


@pytest.fixture(scope="session")
def golden(tmp_path_factory):
    """The migrated and demo-seeded copy every `root` starts from; built once per session (per worker under xdist).
    Never change it: copy it (`clone`)."""
    r = copy_template(tmp_path_factory.mktemp("golden") / "t")
    seed(r)
    return r


def clone(golden, dst):
    shutil.copytree(golden, dst)
    return dst


@pytest.fixture(scope="module")
def root(golden, tmp_path_factory):
    """A migrated and demo-seeded copy, private to the test module."""
    return clone(golden, tmp_path_factory.mktemp("fam") / "t")


@pytest.fixture(scope="module")
def modules(root):
    """modules('llm') -> the llm module of THIS copy."""
    bind(root)

    def load(name):
        return importlib.import_module(name)
    return load


@pytest.fixture(scope="module")
def chdir_root(root):
    old = os.getcwd()
    os.chdir(root)
    yield root
    os.chdir(old)


class MockProvider:
    """One HTTP server that speaks every provider's response format; records what it was sent."""

    def __init__(self):
        self.reply = ""
        self.queue = []
        self.seen = []
        state = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
                state.seen.append({"path": self.path, "headers": dict(self.headers), "body": body})
                txt = state.queue.pop(0) if state.queue else state.reply
                if self.path.startswith("/v1/messages"):
                    out = {"content": [{"type": "text", "text": txt}], "usage": {"input_tokens": 5, "output_tokens": 7}}
                elif self.path.startswith("/v1/chat/completions"):
                    out = {"choices": [{"message": {"content": txt}}], "usage": {"prompt_tokens": 5, "completion_tokens": 7}}
                elif ":generateContent" in self.path:
                    out = {"candidates": [{"content": {"parts": [{"text": txt}]}}],
                           "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 7}}
                elif self.path.startswith("/api/chat"):
                    out = {"message": {"content": txt}, "prompt_eval_count": 5, "eval_count": 7}
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                data = json.dumps(out).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_port}"

    def set(self, reply):
        self.reply = reply if isinstance(reply, str) else json.dumps(reply)
        self.seen = []

    def close(self):
        self.srv.shutdown()


KEYS = {"MITRAHOME_ANTHROPIC_API_KEY": "sk-ant-api03-test", "MITRAHOME_OPENAI_API_KEY": "sk-openai-test",
        "MITRAHOME_GEMINI_API_KEY": "gem-test-key", "MITRAHOME_OPENROUTER_API_KEY": "sk-or-v1-test"}


@pytest.fixture(scope="module")
def mock_llm(root):
    """Mock provider server + test API keys in the environment; family.json points at the mock."""
    m = MockProvider()
    saved = {k: os.environ.get(k) for k in KEYS}
    os.environ.update(KEYS)

    def use(provider, **kw):
        set_ai(root, provider, **{"base_url": m.base, "max_calls_per_day": 500, **kw})
        for x in (root / "logs").glob("ai_calls_*.count"):
            x.unlink()
    m.use = use
    yield m
    m.close()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    set_ai(root, "none")


def today():
    return dt.date.today()
