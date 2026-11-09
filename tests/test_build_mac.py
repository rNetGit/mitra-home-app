"""The Mac app build (installer/build_mac.py, maintainers only): zip modes and symlinks, Info.plist, the starter, the .dmg.
installer/ is export-ignore, so a family install has no build scripts and these tests skip."""
import io
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parent.parent / "installer"
if not (INSTALLER / "build_mac.py").exists():
    pytest.skip("maintainer build scripts are not in this install", allow_module_level=True)
sys.path.insert(0, str(INSTALLER))
import build_mac  # noqa: E402


def _tar():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        for name, data, mode in [("python/bin/python3.12", b"\x7fELF", 0o755), ("python/lib/os.py", b"x = 1\n", 0o644)]:
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode = len(data), mode
            t.addfile(ti, io.BytesIO(data))
        ln = tarfile.TarInfo("python/bin/python3")
        ln.type, ln.linkname = tarfile.SYMTYPE, "python3.12"
        t.addfile(ln)
    buf.seek(0)
    return tarfile.open(fileobj=buf)


def test_zip_keeps_unix_modes_and_symlinks(tmp_path):
    z = build_mac.Zip(tmp_path / "a.zip")
    z.file("A.app/Contents/MacOS/mitra-home", b"#!/bin/sh\n", 0o755)
    z.tar(_tar(), "A.app/Contents/Resources/runtime/", strip="python/")
    z.close()
    zf = zipfile.ZipFile(tmp_path / "a.zip")
    mode = {i.filename: i.external_attr >> 16 for i in zf.infolist()}
    assert stat.S_IMODE(mode["A.app/Contents/MacOS/mitra-home"]) == 0o755
    assert stat.S_IMODE(mode["A.app/Contents/Resources/runtime/bin/python3.12"]) == 0o755
    assert stat.S_IMODE(mode["A.app/Contents/Resources/runtime/lib/os.py"]) == 0o644
    link = "A.app/Contents/Resources/runtime/bin/python3"
    assert stat.S_ISLNK(mode[link]) and zf.read(link) == b"python3.12"
    assert all(i.create_system == 3 for i in zf.infolist()), "Unix entries, so the Mac restores the modes"


def test_info_plist_and_starter():
    d = plistlib.loads(build_mac.info_plist("1.2.3"))
    assert d["CFBundleExecutable"] == "mitra-home" and d["CFBundleShortVersionString"] == "1.2.3"
    assert d["LSUIElement"] is True and d["CFBundleIdentifier"] == "ai.mitrahome.app"
    s = build_mac.STARTER
    assert s.startswith("#!/bin/sh\n") and "\r" not in s
    assert 'Library/Application Support/MitraHome' in s and "ditto" in s and "com.apple.quarantine" in s
    assert '--home "$HOME/Documents/Mitra-Home-Data"' in s, "a brand-new install keeps the family's files in Documents"
    assert "mitrahome_home.txt" in s and "familyagent_home.txt" in s, "an existing household is never re-pointed"
    assert build_mac.pip_platform_args(["a", "b"]) == ["--platform", "a", "--platform", "b"]
    assert set(build_mac.ARCHES) == {"arm64", "x86_64"}


def test_dmg_refused_off_a_mac_before_any_build(monkeypatch):
    monkeypatch.setattr(build_mac.sys, "platform", "win32")
    assert "needs a Mac" in build_mac.dmg_ready()
    monkeypatch.setattr(build_mac, "build", lambda *a: pytest.fail("nothing is downloaded or built when --dmg cannot finish"))
    with pytest.raises(SystemExit, match="needs a Mac"):
        build_mac.main(["--dmg", "--arch", "arm64"])


def test_notary_sign_in_prefers_this_macs_keychain_profile():
    """The maintainer's Mac (and its self-hosted runner) keeps the notary password in its keychain; GitHub's runner
    passes the three secrets."""
    assert build_mac.notary_auth({"MAC_NOTARY_PROFILE": "mitra", "APPLE_ID": "x"}) == ["--keychain-profile", "mitra"]
    assert build_mac.notary_auth({"APPLE_ID": "a@example.com", "APPLE_APP_PASSWORD": "p", "APPLE_TEAM_ID": "T"}) == [
        "--apple-id", "a@example.com", "--password", "p", "--team-id", "T"]
    with pytest.raises(SystemExit, match="MAC_NOTARY_PROFILE or APPLE_APP_PASSWORD"):
        build_mac.notary_auth({"APPLE_ID": "a", "APPLE_TEAM_ID": "T"})


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("hdiutil"), reason="a .dmg is made on a Mac only")
def test_dmg_holds_the_app_and_an_applications_shortcut(tmp_path):
    zp = tmp_path / "MitraHome-1.2.3-mac-arm64.zip"
    z = build_mac.Zip(zp)
    z.file(build_mac.APP + "/Contents/Info.plist", build_mac.info_plist("1.2.3"))
    z.file(build_mac.APP + "/Contents/MacOS/mitra-home", build_mac.STARTER.encode("utf-8"), 0o755)
    z.close()
    out = build_mac.dmg(zp)
    assert out == tmp_path / "MitraHome-1.2.3-mac-arm64.dmg" and out.stat().st_size > 0
    mnt = tmp_path / "mnt"
    mnt.mkdir()
    subprocess.run(["hdiutil", "attach", "-readonly", "-nobrowse", "-mountpoint", str(mnt), str(out)],
                   check=True, capture_output=True)
    try:
        assert os.readlink(mnt / "Applications") == "/Applications"
        starter = mnt / build_mac.APP / "Contents" / "MacOS" / "mitra-home"
        assert stat.S_IMODE(starter.stat().st_mode) & 0o111, "the starter stays executable inside the .dmg"
        assert plistlib.loads((mnt / build_mac.APP / "Contents" / "Info.plist").read_bytes())["CFBundleVersion"] == "1.2.3"
    finally:
        subprocess.run(["hdiutil", "detach", str(mnt), "-quiet"], check=False)


def test_dmg_refuses_a_zip_without_the_app(tmp_path):
    if build_mac.dmg_ready():
        pytest.skip("a .dmg is made on a Mac only")
    zp = tmp_path / "empty.zip"
    z = build_mac.Zip(zp)
    z.file("other/readme.txt", b"x")
    z.close()
    with pytest.raises(SystemExit, match="has no"):
        build_mac.dmg(zp)
    assert not (tmp_path / "empty.dmg").exists()
