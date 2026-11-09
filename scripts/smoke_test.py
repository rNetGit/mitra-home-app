"""The release gate: every test in tests/, on throwaway copies of the template (never touches your real data).

  python scripts/smoke_test.py            run the whole suite (in parallel when pytest-xdist is installed)
  python scripts/smoke_test.py --quick    the core scenarios plus the tests of what changed since main (a few minutes;
                                          for work in progress; the whole suite still runs before a release or build)
  python scripts/smoke_test.py --keep     keep the temp copies and print where they are
  python scripts/smoke_test.py --serial   one process (slower; for chasing an order-dependent failure)
  python scripts/smoke_test.py -k llm     any extra arguments go to pytest

Parallel runs keep each test module on one worker (`--dist loadfile`): a module's tests share one copy of the template.
At most 4 workers: more made Windows fail to start test processes (0xC0000142) on a busy PC.
Needs `pip install -r requirements-dev.txt`. Exit code 1 on any failure.
"""
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAGS = ("--keep", "--serial", "--quick")
# Always in --quick: the database and its updates, Today and the five tabs, help naming real buttons, the agent fence.
CORE = ("test_db_dates.py", "test_migrations.py", "test_today.py", "test_help.py", "test_guard.py")
# Modules nearly every test loads: a change to one runs its own scenarios instead of most of the suite.
SHARED = {"db": ("test_db_dates.py", "test_migrations.py", "test_backup.py", "test_restore_live.py", "test_job_safety.py",
                 "test_maintenance_lock.py"),
          "onboard": ("test_onboard_help.py", "test_paths.py", "test_modules.py", "test_maintenance_lock.py"),
          "paths": ("test_paths.py",), "config": ("test_job_safety.py", "test_paths.py"), "log": (), "brand": ("test_brand.py",),
          "dates": ("test_db_dates.py",), "money": ("test_money.py",), "joblock": ("test_job_safety.py", "test_maintenance_lock.py")}
# A change to any web page (template, CSS, JS, app.py) also runs these.
WEB = ("test_webapp.py", "test_today.py", "test_help.py", "test_ui_polish.py")


def changed(base="main"):
    """Files changed since `base` (committed on this branch, staged or not), relative to the template."""
    out = set()
    for cmd in (["git", "diff", "--name-only", f"{base}...HEAD"], ["git", "diff", "--name-only", "HEAD"],
                ["git", "ls-files", "--others", "--exclude-standard"]):
        try:
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return set()
        out |= {ln.strip() for ln in r.stdout.splitlines() if ln.strip()}
    return out


def quick_files(files):
    """Test files for --quick: CORE, the changed tests themselves, the tests that load a changed module, WEB when a page
    changed. -> (sorted names, {name: why})."""
    tests = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in (ROOT / "tests").glob("test_*.py")}
    why = {t: "core" for t in CORE if t in tests}
    for f in files:
        p = Path(f)
        if p.parent.name == "tests" and p.name in tests:
            why.setdefault(p.name, "changed")
        elif "webapp" in p.parts:
            for t in WEB:
                why.setdefault(t, f"page {p.name}")
        if p.suffix == ".py" and p.stem in SHARED:
            for t in SHARED[p.stem]:
                if t in tests:
                    why.setdefault(t, f"uses {p.stem}")
        elif p.suffix == ".py" and p.parent.name in ("data", "scripts", "tasks", ""):
            mod = p.stem
            pat = re.compile(rf"""(modules\(["']{re.escape(mod)}["']\)|\bimport {re.escape(mod)}\b|["']{re.escape(mod)}\.py["']|test_{re.escape(mod)}\.py)""")
            for name, text in tests.items():
                if name == f"test_{mod}.py" or pat.search(text):
                    why.setdefault(name, f"uses {mod}")
    return sorted(why), why


def main():
    args = [a for a in sys.argv[1:] if a not in FLAGS]
    cmd = [sys.executable, "-m", "pytest", "-q", *args]
    if "--quick" in sys.argv:
        names, why = quick_files(changed())
        print(f"quick: {len(names)} of {len(list((ROOT / 'tests').glob('test_*.py')))} test files")
        for n in names:
            print(f"  {n:34} {why[n]}")
        cmd += [str(Path("tests") / n) for n in names]
    if "--serial" not in sys.argv and importlib.util.find_spec("xdist"):
        cmd += ["-n", str(min(4, max(2, (os.cpu_count() or 2) - 1))), "--dist", "loadfile"]
    if "--keep" in sys.argv:
        keep = Path(tempfile.mkdtemp(prefix="mitrahome_smoke_"))
        cmd += ["--basetemp", str(keep)]
        print(f"copies kept under {keep}")
    try:
        return subprocess.call(cmd, cwd=ROOT)
    except FileNotFoundError:
        print("pytest is not installed: python -m pip install -r requirements-dev.txt")
        return 1


if __name__ == "__main__":
    sys.exit(main())
