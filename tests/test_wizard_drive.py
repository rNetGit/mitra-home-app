"""The quick-start wizard with scripted answers, add-ons added later, and the Google Drive phone drop box against a
fake Drive folder (the real Drive is never touched)."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import copy_template, q, read_family, write_family


def _env():
    env = {**os.environ, "AIFA_DRY_RUN": "1"}
    for k in list(env):
        if k.startswith("ANTHROPIC_"):
            env.pop(k)
    return env


def wiz(root, args, answers="", timeout=300):
    return subprocess.run([sys.executable, *args], cwd=root, input=answers, capture_output=True, text=True, timeout=timeout, env=_env())


@pytest.fixture(scope="module")
def easy(tmp_path_factory):
    root = copy_template(tmp_path_factory.mktemp("easy") / "e", family=False)
    r = wiz(root, ["onboard.py", "easy"], "Zed\nAnn\nadult\n\n\n")
    assert (root / "config" / "family.json").exists(), r.stdout[-400:] + r.stderr[-300:]
    return root


def test_quick_start_is_laptop_only(easy):
    cfg = read_family(easy)
    st = json.loads((easy / "config" / "onboard_state.json").read_text(encoding="utf-8"))
    assert cfg.get("family_name") == "Zed" and not cfg.get("agent_email")
    assert (easy / "data" / "family.db").exists()
    assert st["done"].get("database") and not st["done"].get("agent_account") and not st["done"].get("tax")
    assert q(easy, "select count(*) from life_items")[0][0] > 0, "starter family items seeded"
    assert cfg["members"][0]["name"] == "Ann" and cfg["members"][0]["role"] == "adult"


def test_doctor_is_quiet_about_optional_things(easy):
    r = wiz(easy, ["onboard.py", "doctor"])
    assert "not connected: fine" in r.stdout and "agent email" not in r.stdout.replace("Google", ""), r.stdout[-500:]


def test_help_prints_usage_and_never_starts_the_wizard(easy):
    before = (easy / "config" / "onboard_state.json").read_text(encoding="utf-8")
    for arg in ("--help", "-h", "help"):
        r = wiz(easy, ["onboard.py", arg], timeout=30)
        assert r.returncode == 0 and "python onboard.py doctor" in r.stdout and "Step " not in r.stdout, r.stdout[-300:]
    r = wiz(easy, ["onboard.py", "stauts"], timeout=30)
    assert r.returncode == 2 and "Unknown command: stauts" in r.stdout and "Step " not in r.stdout
    assert (easy / "config" / "onboard_state.json").read_text(encoding="utf-8") == before


def test_add_google_later(easy):
    r = wiz(easy, ["onboard.py", "add", "google"], "agent.zed@example.com\n\n\n\n\n\n", timeout=120)
    cfg = read_family(easy)
    assert cfg.get("agent_email") == "agent.zed@example.com" and cfg.get("family_name") == "Zed", r.stdout[-300:]
    r = wiz(easy, ["onboard.py", "add", "google"], "not-an-email\n", timeout=120)
    assert "not complete" in r.stdout and read_family(easy).get("agent_email") == "agent.zed@example.com"


@pytest.fixture(scope="module")
def drive(easy, tmp_path_factory):
    fake_my = tmp_path_factory.mktemp("FakeDrive") / "My Drive"
    fake_my.mkdir(parents=True)
    r = wiz(easy, ["onboard.py", "add", "drive"], f"{fake_my}\n", timeout=120)
    fa = fake_my / "MitraHome"
    assert (fa / "Inbox").is_dir() and (fa / "Brief").is_dir(), r.stdout[-400:]
    assert Path(read_family(easy).get("drive_path", "")) == fa
    assert "test file swept" in r.stdout and "removed from Drive" in r.stdout and not list((fa / "Inbox").iterdir())
    return fa


def _drop(fa, name, data=b"%PDF-1.4 data", age=900, sub=False):
    f = fa / "Inbox" / name
    if sub:
        f.mkdir()
        return f
    f.write_bytes(data)
    t0 = time.time() - age
    os.utime(f, (t0, t0))
    return f


def test_sweep_moves_only_settled_documents(easy, drive):
    fa = drive
    for name, data in (("good.pdf", None), ("photo.JPG", b"\xff\xd8\xff"), ("weird name!!.pdf", None), ("bad.exe", b"MZ"),
                       ("empty.pdf", b""), ("desktop.ini", b"[x]"), ("~$lock.docx", b"x"), ("shared.gdoc", b"{}")):
        _drop(fa, name, data if data is not None else b"%PDF-1.4 data")
    _drop(fa, "fresh.pdf", age=5)
    _drop(fa, "folder", sub=True)
    r = wiz(easy, ["data/sync_drive.py", "sweep"], timeout=120)
    inb = {f.name for f in (easy / "inbox").iterdir()}
    left = {f.name for f in (fa / "Inbox").iterdir()}
    assert {"good.pdf", "photo.jpg"} <= inb, str(inb) + r.stdout[-300:]
    assert any(n.startswith("weird name") for n in inb)
    assert "good.pdf" not in left and "photo.JPG" not in left and {"bad.exe", "fresh.pdf", "empty.pdf", "folder"} <= left
    assert not ({"bad.exe", "fresh.pdf", "empty.pdf", "desktop.ini", "~$lock.docx", "shared.gdoc"} & inb)
    assert "still syncing" in r.stdout and "not accepted" in r.stdout
    _drop(fa, "good.pdf", b"%PDF-1.4 second")
    wiz(easy, ["data/sync_drive.py", "sweep"], timeout=120)
    assert (easy / "inbox" / "good.pdf").read_bytes() == b"%PDF-1.4 data"
    assert (easy / "inbox" / "good_2.pdf").read_bytes() == b"%PDF-1.4 second"


def test_push_sends_only_daily_and_weekly_by_default(easy, drive):
    br = easy / "brief"
    br.mkdir(exist_ok=True)
    for n, body in (("2099-01-01.md", "# Morning Brief\n\nx\n"), ("2099-01-05_weekly_digest.md", "# Weekly\n\nx\n"),
                    ("2099-01-05_this_week.md", "# This week\n\nx\n")):
        (br / n).write_text(body, encoding="utf-8")
    wiz(easy, ["data/sync_drive.py", "push"])
    stems = {Path(f.name).stem for f in (drive / "Brief").iterdir()}
    assert stems == {"2099-01-01", "2099-01-05_weekly_digest"}, str(stems)
    fam = read_family(easy)
    fam["drive"] = {"push": ["daily", "weekly", "this_week"]}
    write_family(easy, fam)
    wiz(easy, ["data/sync_drive.py", "push"])
    assert "2099-01-05_this_week" in {Path(f.name).stem for f in (drive / "Brief").iterdir()}


EDGE = any(Path(x).exists() for x in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                                      r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"))  # = sync_drive.EDGE


@pytest.mark.skipif(not EDGE, reason="Drive briefs become PDFs through Microsoft Edge (Windows only)")
def test_push_sends_the_newest_monthly_report(easy, drive):
    rep = easy / "reports"
    rep.mkdir(exist_ok=True)
    for n in ("2098-11_monthly.md", "2098-12_monthly.md"):
        (rep / n).write_text(f"# Monthly {n}\n\nx\n", encoding="utf-8")
    fam = read_family(easy)
    fam.pop("drive", None)  # default list includes monthly
    write_family(easy, fam)
    wiz(easy, ["data/sync_drive.py", "push"])
    names = {f.name for f in (drive / "Brief").iterdir()}
    assert "2098-12_monthly.pdf" in names and "2098-11_monthly.pdf" not in names, str(names)
    fam["drive"] = {"push": ["daily", "weekly"]}
    write_family(easy, fam)
    wiz(easy, ["data/sync_drive.py", "push"])
    assert "2098-12_monthly.pdf" not in {f.name for f in (drive / "Brief").iterdir()}


def test_push_copies_the_calendar_file(easy, drive):
    (easy / "brief" / "mitrahome.ics").write_text("BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n", encoding="utf-8")
    fam = read_family(easy)
    fam.pop("drive", None)  # default list: daily, weekly, ics
    write_family(easy, fam)
    r = wiz(easy, ["data/sync_drive.py", "push"])
    assert r.returncode == 0, r.stdout + r.stderr
    assert (drive / "Brief" / "mitrahome.ics").read_text(encoding="utf-8").startswith("BEGIN:VCALENDAR")
    fam["drive"] = {"push": ["daily"]}
    write_family(easy, fam)
    wiz(easy, ["data/sync_drive.py", "push"])
    assert not (drive / "Brief" / "mitrahome.ics").exists(), "not in the push list: moved to archive/old_drive_briefs"


def test_inbox_sweep_task_and_heartbeat(easy, drive, tmp_path):
    wiz(easy, ["tasks/run_task.py", "inbox_sweep"], timeout=120)
    hb = json.loads((easy / "logs" / "heartbeat.json").read_text(encoding="utf-8"))
    assert hb.get("inbox_sweep", {}).get("ok") is True
    assert "pull:" in (easy / "logs" / "inbox_sweep.log").read_text(encoding="utf-8")
    nodrive = copy_template(tmp_path / "nodrive")
    assert subprocess.run([sys.executable, "data/migrate.py"], cwd=nodrive, capture_output=True).returncode == 0
    wiz(nodrive, ["tasks/run_task.py", "inbox_sweep"], timeout=120)
    assert "not set up" in (nodrive / "logs" / "inbox_sweep.log").read_text(encoding="utf-8")

    def stale_lines(**flags):
        fam = read_family(easy)
        fam.update(flags)
        write_family(easy, fam)
        (easy / "logs" / "heartbeat.json").unlink(missing_ok=True)
        return wiz(easy, ["data/heartbeat.py", "show"]).stdout
    assert "inbox_sweep" not in stale_lines(tasks_registered=True, sweep_registered=False)
    assert "STALE inbox_sweep" in stale_lines(tasks_registered=True, sweep_registered=True)


def test_doctor_sees_the_drive_folder_and_its_absence(easy, drive, tmp_path):
    r = wiz(easy, ["onboard.py", "doctor"])
    assert "[x] Google Drive folder reachable" in r.stdout, r.stdout[-600:]
    (drive / "Inbox").rename(drive / "Inbox_gone")
    try:
        r = wiz(easy, ["onboard.py", "doctor"])
        assert "[!] Google Drive folder reachable" in r.stdout
    finally:
        (drive / "Inbox_gone").rename(drive / "Inbox")
    assert wiz(easy, ["data/drive_setup.py", "check", str(tmp_path / "no_such_drive")]).returncode != 0


def test_drive_pdf_page_keeps_typed_text_as_text(modules):
    """audit 2026-10-28: a list item went into the HTML Edge prints unescaped, so `<script src=...>` ran on the PC"""
    S = modules("sync_drive")
    md = ("# Shopping\n\n- milk <script src=https://ev.il/x.js></script>\n- <img src=x onerror=alert(1)>\n\n"
          "| Item | Due | Amount |\n|---|---|---|\n| <b>x</b> [a](javascript:alert(1)) | today | $5.00 |\n"
          "| [site](https://example.com/a?b=1&c=\"2\") | soon | $1.00 |\n")
    page = S.pdf_html(md)
    body = page.split("</style>", 1)[1]
    assert "<script" not in body and "<img" not in body and "<b>" not in body
    assert "&lt;script src=https://ev.il/x.js&gt;" in body, "the text still prints, as text"
    assert 'href="javascript' not in body, "only http(s) and mailto links stay links"
    assert "default-src 'none'" in page, "no script, fetch or frame even if something slipped through"


def test_drive_pdf_fails_loudly_when_edge_writes_nothing(modules, monkeypatch, tmp_path):
    """28 Oct: an Edge flag made Edge exit 0 with no PDF, and the push skipped every brief without a word"""
    S = modules("sync_drive")
    calls = []
    monkeypatch.setattr(S.subprocess, "run", lambda argv, **kw: calls.append(argv))
    md, pdf = tmp_path / "b.md", tmp_path / "b.pdf"
    md.write_text("# Brief\n", encoding="utf-8")
    pdf.write_bytes(b"%PDF old copy")
    with pytest.raises(RuntimeError, match="no PDF"):
        S.md_to_pdf(md, pdf)
    assert not pdf.exists(), "the older copy is not left to pass for the new one"
    assert not any("blink-settings" in str(a) for a in calls[0]), "that flag stops Edge writing the PDF"
    monkeypatch.setattr(S.subprocess, "run", lambda argv, **kw: pdf.write_bytes(b"%PDF new"))
    S.md_to_pdf(md, pdf)
    assert pdf.read_bytes() == b"%PDF new"
