"""Build the Mac app (Mitra Home.app, zipped) from any computer: no Mac needed. Maintainer only.

  python installer/build_mac.py                 build from the committed HEAD, Apple silicon and Intel
  python installer/build_mac.py --ref v0.111.0  build from a tag
  python installer/build_mac.py --arch arm64    one architecture only (arm64 | x86_64)
  python installer/build_mac.py --dmg           also a .dmg next to each zip (macOS only: ditto + hdiutil)

Out: dist/installer/MitraHome-<version>-mac-arm64.zip and -mac-intel.zip. Each holds one `Mitra Home.app`:
  Contents/MacOS/mitra-home      the starter (sh): copies the code to ~/Library/Application Support/MitraHome/app
                                 when that copy is missing or older, then runs launch.py with the bundled Python
  Contents/Resources/app/        the code exactly as `git archive` gives it (never family data)
  Contents/Resources/runtime/    standalone CPython for macOS (python-build-standalone, checked against SHA256SUMS)
                                 plus runtime/mitrahome-wheels/ (requirements.txt for that Mac), so the first start is
                                 offline
The zip is written straight from the downloaded archives, so file modes and symlinks survive a build on Windows.
With --dmg (on a Mac) the zip is unpacked with `ditto` and packed again as MitraHome-<version>-mac-<arch>.dmg: the app
plus an Applications shortcut to drag it onto.
Unsigned: the family opens it once with System Settings > Privacy & Security > Open Anyway (see installer/README.md).
"""
import argparse
import io
import json
import os
import plistlib
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_installer as win  # noqa: E402  (shared: fetch, sha256, the python-build-standalone release)

ROOT = win.ROOT
CACHE = win.CACHE
OUT = win.OUT
APP = "Mitra Home.app"
BUNDLE_ID = "ai.mitrahome.app"
MIN_MACOS = "11.0"
ARCHES = {  # our name -> (python-build-standalone triple, pip platform tags, file label)
    "arm64": ("aarch64-apple-darwin", [f"macosx_{v}_0_arm64" for v in (11, 12, 13, 14)] + ["macosx_11_0_universal2", "macosx_10_9_universal2"], "arm64"),
    "x86_64": ("x86_64-apple-darwin", [f"macosx_10_{v}_x86_64" for v in (9, 12, 13, 15)] + [f"macosx_{v}_0_x86_64" for v in (11, 12)]
               + ["macosx_10_9_universal2"], "intel"),
}

STARTER = r'''#!/bin/sh
# Mitra Home starter for the Mac app. The code runs from a writable copy (so updates work); the Python ships inside.
B="$(cd "$(dirname "$0")/../.." && pwd)"
R="$B/Contents/Resources"
S="$HOME/Library/Application Support/MitraHome"
A="$S/app"
L="$HOME/Library/Logs/MitraHome"
mkdir -p "$S" "$L"
exec >>"$L/start.log" 2>&1
echo "---- $(date)"
xattr -dr com.apple.quarantine "$B" 2>/dev/null
PY="$R/runtime/bin/python3.12"
newer() { "$PY" -c 'import sys; v=lambda p: tuple(int(x) for x in open(p).read().strip().split(".")); sys.exit(0 if v(sys.argv[1]) > v(sys.argv[2]) else 1)' "$R/app/VERSION" "$A/VERSION"; }
if [ ! -f "$A/VERSION" ] || newer; then
  echo "copying the code $(cat "$R/app/VERSION") to $A"
  mkdir -p "$A" && ditto "$R/app" "$A"
fi
cd "$A" || exit 1
if [ ! -f mitrahome_home.txt ] && [ ! -f familyagent_home.txt ]; then
  set -- --home "$HOME/Documents/Mitra-Home-Data" "$@"
fi
exec "$PY" launch.py "$@"
'''


def info_plist(version):
    return plistlib.dumps({
        "CFBundleName": "Mitra Home", "CFBundleDisplayName": "Mitra Home", "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "mitra-home", "CFBundleIconFile": "MitraHome", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": version, "CFBundleVersion": version, "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": MIN_MACOS, "LSUIElement": True, "NSHighResolutionCapable": True,
    }, sort_keys=True)


def icns():
    """The app icon from the logo (Pillow writes .icns), or None when Pillow or the logo is missing."""
    src = ROOT / "data" / "webapp" / "static" / "icon-512.png"  # the app's own icon
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.open(src).convert("RGBA").resize((1024, 1024)).save(buf, format="ICNS")
        return buf.getvalue()
    except Exception as e:  # noqa: BLE001
        win.say(f"no icon ({e}); the app gets the default one")
        return None


class Zip:
    """A zip with Unix modes and symlinks (what Finder's Archive Utility and `ditto -x -k` restore)."""
    def __init__(self, path):
        self.z = zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6)
        self.names = set()

    def _info(self, name, mode):
        zi = zipfile.ZipInfo(name, time.localtime()[:6])
        zi.create_system = 3
        zi.external_attr = mode << 16
        zi.compress_type = zipfile.ZIP_DEFLATED
        return zi

    def file(self, name, data, mode=0o644):
        self.names.add(name)
        self.z.writestr(self._info(name, stat.S_IFREG | mode), data)

    def link(self, name, target):
        self.names.add(name)
        zi = self._info(name, stat.S_IFLNK | 0o755)
        zi.compress_type = zipfile.ZIP_STORED
        self.z.writestr(zi, target)

    def tar(self, tf, prefix, strip=""):
        """Copy a tar into the zip under `prefix`, dropping `strip` from the front of each member name."""
        for m in tf.getmembers():
            rel = m.name[len(strip):] if strip and m.name.startswith(strip) else m.name
            rel = rel.lstrip("/")
            if not rel or m.isdir():
                continue
            if m.issym():
                self.link(prefix + rel, m.linkname)
            elif m.isfile():
                self.file(prefix + rel, tf.extractfile(m).read(), (m.mode & 0o777) or 0o644)

    def close(self):
        self.z.close()


def app_tar(ref):
    r = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"no commit or tag named {ref!r}: {r.stderr.decode(errors='replace').strip()}")
    tf = tarfile.open(fileobj=io.BytesIO(r.stdout))
    names = tf.getnames()
    if "launch.py" not in names or "VERSION" not in names:
        raise SystemExit(f"{ref} has no launch.py / VERSION")
    if "def home_arg" not in tf.extractfile("launch.py").read().decode("utf-8"):
        raise SystemExit(f"{ref} is older than the Mac app: its launch.py has no --home")
    return tf, tf.extractfile("VERSION").read().decode("utf-8").strip()


def python_archive(triple):
    name = f"cpython-{win.PBS_PYTHON}+{win.PBS_TAG}-{triple}-install_only.tar.gz"
    archive = win.fetch(f"{win.PBS_BASE}/{win.PBS_TAG}/{name}", CACHE / name)
    sums = win.fetch(f"{win.PBS_BASE}/{win.PBS_TAG}/SHA256SUMS", CACHE / f"SHA256SUMS-{win.PBS_TAG}")
    want = next((ln.split()[0] for ln in sums.read_text(encoding="utf-8").splitlines() if ln.strip().endswith(name)), None)
    got = win.sha256(archive)
    if want != got:
        archive.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch for {name}: expected {want}, got {got}")
    win.say(f"python {win.PBS_PYTHON} {triple} checksum ok")
    return archive


def pip_platform_args(tags):
    out = []
    for t in tags:
        out += ["--platform", t]
    return out


def mac_wheels(arch, requirements):
    """Wheels of requirements.txt for that Mac (binary only), downloaded with this computer's pip."""
    _triple, tags, _label = ARCHES[arch]
    dest = CACHE / f"wheels-mac-{arch}"
    dest.mkdir(parents=True, exist_ok=True)
    req = dest / "requirements.txt"
    req.write_bytes(requirements)
    py_ver = ".".join(win.PBS_PYTHON.split(".")[:2])
    subprocess.run([sys.executable, "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
                    *pip_platform_args(tags), "--python-version", py_ver, "--implementation", "cp",
                    "-r", str(req), "-d", str(dest)], check=True)
    wheels = sorted(dest.glob("*.whl"))
    win.say(f"{len(wheels)} wheels for {arch}")
    return wheels


def build(ref, arch):
    triple, _tags, label = ARCHES[arch]
    tf, version = app_tar(ref)
    out = OUT / f"MitraHome-{version}-mac-{label}.zip"
    OUT.mkdir(parents=True, exist_ok=True)
    wheels = mac_wheels(arch, tf.extractfile("requirements.txt").read())
    archive = python_archive(triple)
    c = f"{APP}/Contents/"
    z = Zip(out)
    z.file(c + "Info.plist", info_plist(version))
    z.file(c + "MacOS/mitra-home", STARTER.encode("utf-8"), 0o755)
    icon = icns()
    if icon:
        z.file(c + "Resources/MitraHome.icns", icon)
    z.tar(tf, c + "Resources/app/")
    with tarfile.open(archive) as pt:
        z.tar(pt, c + "Resources/runtime/", strip="python/")
    for w in wheels:
        z.file(c + "Resources/runtime/mitrahome-wheels/" + w.name, w.read_bytes())
    z.close()
    win.say(f"built {out.name} ({out.stat().st_size // (1 << 20)} MB) sha256 {win.sha256(out)}")
    return out


def dmg_ready():
    """Why a .dmg cannot be made here, or None: it needs macOS's own ditto and hdiutil."""
    if sys.platform != "darwin":
        return "--dmg needs a Mac (ditto and hdiutil); the zip builds anywhere"
    return None


ENTITLEMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>com.apple.security.cs.allow-unsigned-executable-memory</key><true/>
<key>com.apple.security.cs.disable-library-validation</key><true/>
</dict></plist>
"""
MACHO_MAGIC = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def is_macho(path):
    if path.is_symlink() or not path.is_file():
        return False
    with open(path, "rb") as f:
        return f.read(4) in MACHO_MAGIC


def codesign(identity, target, entitlements=None):
    cmd = ["codesign", "--force", "--timestamp", "--options", "runtime", "--sign", identity]
    if entitlements:
        cmd += ["--entitlements", str(entitlements)]
    subprocess.run(cmd + [str(target)], check=True)


def sign_wheel(whl, identity, ent, tmp):
    """Apple also scans inside zips: sign the Mach-O files in a wheel and repack it (pip installs it without hash checks)."""
    out = Path(tmp) / "wheel.tmp"
    n = 0
    with zipfile.ZipFile(whl) as zin, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = zin.read(info)
            if data[:4] in MACHO_MAGIC:
                f = Path(tmp) / "member.bin"
                f.write_bytes(data)
                codesign(identity, f, ent)
                data = f.read_bytes()
                n += 1
            zout.writestr(info, data, zipfile.ZIP_DEFLATED)
    out.replace(whl)
    return n


def sign_app(app, identity, tmp):
    """Developer ID signing, inside out: every Mach-O file first, then the bundle (hardened runtime, as notarization needs)."""
    ent = Path(tmp) / "entitlements.plist"
    ent.write_text(ENTITLEMENTS)
    wheels = sorted(app.rglob("*.whl"))
    inner = sum(sign_wheel(w, identity, ent, tmp) for w in wheels)
    files = [p for p in app.rglob("*") if is_macho(p)]
    for p in files:
        codesign(identity, p, ent)
    codesign(identity, app, ent)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    win.say(f"signed {len(files)} binaries + {inner} inside {len(wheels)} wheels + the app bundle")


def notary_auth(env=None):
    """notarytool's sign-in: a profile kept in this Mac's keychain (MAC_NOTARY_PROFILE, made once with `xcrun notarytool
    store-credentials NAME`; the maintainer's own Mac and its self-hosted runner), else APPLE_ID, APPLE_APP_PASSWORD
    and APPLE_TEAM_ID in the environment (GitHub's runner, from the repository secrets)."""
    env = os.environ if env is None else env
    if env.get("MAC_NOTARY_PROFILE"):
        return ["--keychain-profile", env["MAC_NOTARY_PROFILE"]]
    need = ["APPLE_ID", "APPLE_APP_PASSWORD", "APPLE_TEAM_ID"]
    if missing := [k for k in need if not env.get(k)]:
        raise SystemExit(f"notarizing needs MAC_NOTARY_PROFILE or {', '.join(missing)}")
    return ["--apple-id", env["APPLE_ID"], "--password", env["APPLE_APP_PASSWORD"], "--team-id", env["APPLE_TEAM_ID"]]


def notarize(dmg_path):
    """Apple's notary service (notary_auth), then staple the ticket."""
    auth = notary_auth()
    r = subprocess.run(["xcrun", "notarytool", "submit", str(dmg_path), "--wait", "--output-format", "json", *auth],
                       capture_output=True, text=True)
    print(r.stdout, r.stderr)
    try:
        res = json.loads(r.stdout)
    except ValueError:
        raise SystemExit("notarytool gave no result")
    if res.get("status") != "Accepted":
        subprocess.run(["xcrun", "notarytool", "log", res.get("id", ""), *auth])  # why Apple said no
        raise SystemExit(f"notarization {res.get('status')}")
    subprocess.run(["xcrun", "stapler", "staple", str(dmg_path)], check=True)
    win.say(f"notarized and stapled {dmg_path.name}")


def dmg(zip_path, identity=None):
    """The built zip as a compressed .dmg next to it: the app plus an Applications shortcut. With an identity: signed + notarized."""
    why = dmg_ready()
    if why:
        raise SystemExit(why)
    out = zip_path.with_suffix(".dmg")
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir()
        subprocess.run(["ditto", "-x", "-k", str(zip_path), str(stage)], check=True)
        if not (stage / APP).is_dir():
            raise SystemExit(f"{zip_path.name} has no {APP}")
        if identity:
            sign_app(stage / APP, identity, tmp)
        (stage / "Applications").symlink_to("/Applications")
        subprocess.run(["hdiutil", "create", "-volname", Path(APP).stem, "-srcfolder", str(stage), "-fs", "HFS+",
                        "-format", "UDZO", "-imagekey", "zlib-level=9", "-ov", "-quiet", str(out)], check=True)
    if identity:
        codesign(identity, out)
        notarize(out)
    win.say(f"built {out.name} ({out.stat().st_size // (1 << 20)} MB) sha256 {win.sha256(out)}")
    return out


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", default="HEAD", help="git ref to package (default HEAD; uncommitted changes are NOT included)")
    ap.add_argument("--arch", choices=sorted(ARCHES), action="append", help="arm64 and/or x86_64 (default both)")
    ap.add_argument("--dmg", action="store_true", help="also a .dmg next to each zip (macOS only)")
    ap.add_argument("--sign", metavar="IDENTITY", default=os.environ.get("MAC_SIGN_IDENTITY"),
                    help="Developer ID Application identity: sign the app and dmg and notarize (needs --dmg; default $MAC_SIGN_IDENTITY)")
    a = ap.parse_args(argv)
    if a.sign and not a.dmg:
        raise SystemExit("--sign needs --dmg")
    if a.dmg and (why := dmg_ready()):
        raise SystemExit(why)
    for arch in a.arch or ["arm64", "x86_64"]:
        out = build(a.ref, arch)
        if a.dmg:
            dmg(out, a.sign)
    win.say("signed and notarized" if a.sign else "unsigned: Mac users open it once via System Settings > Privacy & Security > Open Anyway")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
