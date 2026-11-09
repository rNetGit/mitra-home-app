"""Documents sent to the chat bots (chat_core.accept_file): adults only, private chats only, strangers silent, allowed
types, content must match the name (no programs or web pages), size checked before download, refused files never
fetched, daily cap, saved into inbox/ without overwriting, log without file names or text; Discord attachment helper."""
import datetime as D

import pytest

NOW = D.datetime(2026, 10, 9, 10, 0, 0)
PDF = b"%PDF-1.7\n" + b"x" * 100
JPG = b"\xff\xd8\xff\xe0" + b"j" * 100
PNG = b"\x89PNG\r\n\x1a\n" + b"p" * 50


@pytest.fixture(scope="module")
def C(root, modules):
    return modules("chat_core")


@pytest.fixture(scope="module")
def dbp(root):
    return root / "data" / "family.db"


@pytest.fixture(scope="module")
def linked(C, dbp):
    con = C._con(dbp)
    try:
        for name, uid, plat in (("Alex", "a1", "telegram"), ("Sam", "k1", "telegram"), ("Alex", "a2", "discord")):
            code, *_ = C.invite(con, name, now=NOW)
            assert "linked" in C.handle(plat, uid, f"/start {code}", db=dbp, now=NOW)
    finally:
        con.close()


def up(C, dbp, uid, name, data=None, platform="telegram", private=True, now=NOW, **kw):
    return C.accept_file(platform, uid, name, data=data, private=private, db=dbp, now=now, **kw)


def inbox(root):
    return sorted(p.name for p in (root / "inbox").iterdir() if p.is_file())


def test_adult_pdf_and_photo_saved(C, dbp, root, linked):
    r = up(C, dbp, "a1", "Electric bill Oct.pdf", PDF)
    assert "saved to the inbox" in r
    assert "2026-10-09_100000_telegram_Electric bill Oct.pdf" in inbox(root)
    assert "saved" in up(C, dbp, "a2", "photo.jpg", JPG, platform="discord")
    assert (root / "inbox" / "2026-10-09_100000_telegram_Electric bill Oct.pdf").read_bytes() == PDF


def test_same_name_never_overwrites(C, dbp, root, linked):
    up(C, dbp, "a1", "same.png", PNG)
    up(C, dbp, "a1", "same.png", PNG + b"2")
    names = [n for n in inbox(root) if "same" in n]
    assert len(names) == 2


def test_kid_refused_and_nothing_fetched(C, dbp, root, linked):
    before = inbox(root)
    called = []
    r = up(C, dbp, "k1", "report.pdf", fetch=lambda: called.append(1) or PDF)
    assert "grown-ups" in r and not called and inbox(root) == before


def test_group_refused_before_download(C, dbp, linked):
    called = []
    r = up(C, dbp, "a1", "bill.pdf", private=False, fetch=lambda: called.append(1) or PDF)
    assert "private chat" in r and not called


def test_stranger_silent(C, dbp):
    assert up(C, dbp, "zz", "bill.pdf", PDF) is None


@pytest.mark.parametrize("name,data", [
    ("tool.exe", b"MZ" + b"0" * 50),          # type not allowed
    ("bill.pdf", b"MZ\x90\x00" + b"0" * 50),  # program named .pdf
    ("bill.jpg", PDF),                         # PDF named .jpg
    ("notes.txt", b"<script>alert(1)</script>"),
    ("page.pdf", b"<!DOCTYPE html><html>"),
    ("run.csv", b"#!/bin/sh\nrm -rf /"),
    ("empty.pdf", b""),
])
def test_bad_files_refused(C, dbp, root, linked, name, data):
    before = inbox(root)
    r = up(C, dbp, "a1", name, data)
    assert "Not saved" in r or "only take" in r or "does not look" in r or "empty" in r
    assert inbox(root) == before


def test_size_checked_before_download(C, dbp, linked, modules):
    called = []
    big = modules("inbox_upload").MAX_BYTES + 1
    r = up(C, dbp, "a1", "huge.pdf", size=big, fetch=lambda: called.append(1) or PDF)
    assert "too large" in r and not called


def test_path_tricks_flattened(C, dbp, root, linked):
    r = up(C, dbp, "a1", "..\\..\\Windows\\evil.pdf", PDF)
    assert "saved" in r
    assert not (root.parent / "evil.pdf").exists()
    assert any(n.endswith("_telegram_evil.pdf") for n in inbox(root))


def test_daily_cap(C, dbp, root, linked, monkeypatch):
    monkeypatch.setattr(C, "MAX_FILES_PER_DAY", 3)
    day = NOW + D.timedelta(days=1)
    for i in range(3):
        assert "saved" in up(C, dbp, "a1", f"r{i}.jpg", JPG, now=day)
    assert "files today" in up(C, dbp, "a1", "r9.jpg", JPG, now=day)
    assert "saved" in up(C, dbp, "a1", "r9.jpg", JPG, now=day + D.timedelta(days=1))


def test_log_has_no_file_names(C, dbp, root, linked):
    from conftest import q
    up(C, dbp, "a1", "Secret Medical Letter.pdf", PDF)
    rows = q(root, "select * from chat_log where command='upload'")
    assert rows and "Secret" not in " ".join(str(c) for r in rows for c in r)


def test_discord_attachment_helper(root, modules, dbp, linked):
    Dm = modules("chat_discord")
    assert "saved" in Dm.accept_attachment("a2", "receipt.png", len(PNG), lambda: PNG, True, db=dbp, now=NOW)
    assert "private chat" in Dm.accept_attachment("a2", "receipt.png", 10, lambda: PNG, False, db=dbp, now=NOW)
    assert Dm.MAX_ATTACHMENTS == 5
