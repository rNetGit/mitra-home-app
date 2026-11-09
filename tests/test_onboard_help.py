"""`onboard.py <command> --help` prints usage and changes nothing; the Claude intake agent's duplicate pre-check is wired
to a command its permission file allows."""
import fnmatch
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("args", [["--help"], ["-h"], ["help"], ["update", "--help"], ["upgrade", "--help"], ["reset", "-h"],
                                  ["doctor", "--help"], ["check", "--help"], ["add", "--help"], ["easy", "--help"], ["--help", "x"]])
def test_help_prints_usage_and_changes_nothing(tmp_path, args):
    shutil.copy(SRC / "onboard.py", tmp_path / "onboard.py")  # alone in an empty folder: anything it creates shows up
    r = subprocess.run([sys.executable, str(tmp_path / "onboard.py"), *args], cwd=tmp_path, capture_output=True, text=True,
                       timeout=60, stdin=subprocess.DEVNULL)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "python onboard.py" in r.stdout and "doctor" in r.stdout, r.stdout
    assert [p.name for p in tmp_path.iterdir()] == ["onboard.py"], "help must not create files, backups or state"


def test_intake_agent_runs_the_duplicate_check_first_and_may_run_it():
    body = (SRC / ".claude" / "agents" / "intake.md").read_text(encoding="utf-8")
    cmd = "python data/ai_intake.py duplicates"
    steps = [ln for ln in body.splitlines() if ln[:3] in ("1. ", "2. ", "3. ")]
    assert steps and steps[0].startswith("1. ") and cmd in steps[0], "step 1 must run the duplicate check"
    assert "List `inbox/`" in steps[0].split(cmd)[0], "the check comes after listing the inbox and before any file is read"
    assert all("Read" not in ln.split(cmd)[0] for ln in steps[:1])
    perms = json.loads((SRC / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    assert any(fnmatch.fnmatchcase(cmd, p[5:-1]) for p in perms["allow"] if p.startswith("Bash(")), "allowed to run"
    assert not any(fnmatch.fnmatchcase(cmd, p[5:-1]) for p in perms["deny"] if p.startswith("Bash(")), "not denied"
    assert (SRC / "data" / "ai_intake.py").read_text(encoding="utf-8").count('"duplicates"') >= 1, "subcommand exists"
