"""Audit A11: one clock. Every module reads today's date from dates.today(), so a test or a demo can fix it
(MITRAHOME_TODAY) and no two modules disagree about the day."""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
BARE = re.compile(r"\b(?:dt|datetime)\.date\.today\(\)|\bdatetime\.now\(\)\.date\(\)|__import__\(\"datetime\"\)\.date\.today\(\)")
SKIP = {"data/dates.py"}


def test_no_module_reads_the_system_date_itself():
    files = [*ROOT.glob("data/**/*.py"), *ROOT.glob("tasks/*.py"), ROOT / "onboard.py", ROOT / "launch.py"]
    bad = []
    for f in files:
        rel = f.relative_to(ROOT).as_posix()
        if rel in SKIP or not f.exists() or f.name.startswith("migrate_0"):  # applied migrations are frozen history
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if BARE.search(line) and not line.lstrip().startswith("#"):
                bad.append(f"{rel}:{n}: {line.strip()}")
    assert not bad, "use dates.today():\n" + "\n".join(bad)


def test_today_can_be_fixed_and_ignores_junk(monkeypatch, modules):
    dates = modules("dates")
    monkeypatch.setenv("MITRAHOME_TODAY", "2027-03-14")
    assert dates.today().isoformat() == "2027-03-14"
    monkeypatch.setenv("MITRAHOME_TODAY", "not a date")
    assert dates.today() == dates.dt.date.today()
    monkeypatch.delenv("MITRAHOME_TODAY")
    assert dates.today() == dates.dt.date.today()


def test_day_text_uses_the_same_clock(monkeypatch, modules):
    dates = modules("dates")
    monkeypatch.setenv("MITRAHOME_TODAY", "2027-03-14")
    assert dates.day_text("2027-03-15") == "Mon, Mar 15"
    assert dates.day_text("2026-03-15").endswith(", 2026")
