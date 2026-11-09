"""Build the Windows installer (MitraHome-Setup-<version>.exe). Maintainer only; runs on a Windows PC with Inno Setup 6.

  python installer/build_installer.py                 build from the committed HEAD
  python installer/build_installer.py --ref v0.110.0  build from a tag
  python installer/build_installer.py --stage-only    prepare installer/build/ without running Inno Setup
  python installer/build_installer.py --sign          also Authenticode-sign the installer and uninstaller with Azure
                                                      Artifact Signing (setup in installer/README.md)

What goes in (installer/build/stage/):
  app/      the code exactly as `git archive` gives it (same files as the release zip; never family data)
  runtime/  a standalone CPython for Windows (python-build-standalone, checked against its SHA256SUMS)
            plus runtime/mitrahome-wheels/: every package of requirements.txt, so the first start needs no download
The family's PC gets the code in %LOCALAPPDATA%/Programs/MitraHome, the Python in %LOCALAPPDATA%/MitraHome/runtime
(where `Start Mitra Home.bat` and launch.py look for it) and nothing system-wide. See installer/README.md.
"""
import argparse
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BUILD = HERE / "build"
STAGE = BUILD / "stage"
CACHE = BUILD / "cache"
OUT = ROOT / "dist" / "installer"

# python-build-standalone release used for the bundled Python. Change both together; the build checks the download
# against that release's SHA256SUMS.
PBS_TAG = "20241016"
PBS_PYTHON = "3.12.7"
PBS_BASE = "https://github.com/astral-sh/python-build-standalone/releases/download"
PBS_FILE = f"cpython-{PBS_PYTHON}+{PBS_TAG}-x86_64-pc-windows-msvc-install_only.tar.gz"

ISCC_PLACES = [
    Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
    Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    Path.home() / "AppData" / "Local" / "Programs" / "Inno Setup 6" / "ISCC.exe",
]


# Azure Artifact Signing (formerly Trusted Signing): signtool plus the Azure.CodeSigning.Dlib.dll from the Artifact Signing
# client package. Paths come from the environment so nothing machine-specific or secret is committed:
#   MITRA_SIGN_DLIB      full path to Azure.CodeSigning.Dlib.dll (required with --sign)
#   MITRA_SIGN_METADATA  full path to the metadata .json (Endpoint, CodeSigningAccountName, CertificateProfileName)
#   MITRA_SIGNTOOL       signtool.exe (optional; else the newest Windows SDK x64 one)
# Azure credentials come from `az login` (or the AZURE_* variables); none are read or stored here.
SIGN_TIMESTAMP = "http://timestamp.acs.microsoft.com"


def signtool_path():
    env = os.environ.get("MITRA_SIGNTOOL")
    if env and Path(env).exists():
        return env
    found = shutil.which("signtool")
    if found:
        return found
    kits = sorted(Path(r"C:\Program Files (x86)\Windows Kits\10\bin").glob("10.*/x64/signtool.exe"), reverse=True)
    if kits:
        return str(kits[0])
    raise SystemExit("signtool.exe not found. Install the Windows SDK (winget install Microsoft.WindowsSDK.10.0.26100) "
                     "or set MITRA_SIGNTOOL.")


def sign_setup():
    """(signtool path, ISCC /S definition) for Inno Setup to sign the installer and the uninstaller."""
    dlib, meta = os.environ.get("MITRA_SIGN_DLIB"), os.environ.get("MITRA_SIGN_METADATA")
    for name, val in (("MITRA_SIGN_DLIB", dlib), ("MITRA_SIGN_METADATA", meta)):
        if not val or not Path(val).is_file():
            raise SystemExit(f"--sign needs {name} to point at an existing file (installer/README.md, 'Code signing').")
    tool = signtool_path()
    cmd = (f'$q{tool}$q sign /v /fd SHA256 /tr {SIGN_TIMESTAMP} /td SHA256 '
           f'/dlib $q{dlib}$q /dmdf $q{meta}$q $f')
    return tool, cmd


def say(text):
    print(f"  {text}", flush=True)


def fetch(url, dest):
    if dest.exists():
        return dest
    say(f"download {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)
    return dest


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def stage_app(ref):
    """The code at `ref` via git archive (honours export-ignore, so installer/ stays out)."""
    app = STAGE / "app"
    r = subprocess.run(["git", "-C", str(ROOT), "archive", "--format=tar", ref], capture_output=True)
    if r.returncode != 0:
        tags = subprocess.run(["git", "-C", str(ROOT), "tag", "--sort=-v:refname"], capture_output=True, text=True).stdout.split()[:3]
        raise SystemExit(f"no commit or tag named {ref!r} ({r.stderr.decode(errors='replace').strip()}). "
                         f"Latest tags: {', '.join(tags) or 'none'}; or leave out --ref to build HEAD.")
    shutil.rmtree(app, ignore_errors=True)
    app.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        t.extractall(app, filter="data")
    if "def home_arg" not in (app / "launch.py").read_text(encoding="utf-8"):
        raise SystemExit(f"{ref} is older than the installer: its launch.py has no --home, so the household folder would "
                         "land inside Program files. Build from a commit that has it (HEAD, or a tag made after it).")
    version = (app / "VERSION").read_text(encoding="utf-8").strip()
    say(f"app {ref} = version {version}")
    return version


def stage_runtime():
    """Standalone Python, checked, plus the packages from app/requirements.txt as wheels."""
    rt = STAGE / "runtime"
    shutil.rmtree(rt, ignore_errors=True)
    archive = fetch(f"{PBS_BASE}/{PBS_TAG}/{PBS_FILE}", CACHE / PBS_FILE)
    sums = fetch(f"{PBS_BASE}/{PBS_TAG}/SHA256SUMS", CACHE / f"SHA256SUMS-{PBS_TAG}")
    want = next((ln.split()[0] for ln in sums.read_text(encoding="utf-8").splitlines() if ln.strip().endswith(PBS_FILE)), None)
    got = sha256(archive)
    if want != got:
        archive.unlink(missing_ok=True)
        raise SystemExit(f"checksum mismatch for {PBS_FILE}: expected {want}, got {got}")
    say(f"python {PBS_PYTHON} checksum ok")
    with tarfile.open(archive) as t:
        t.extractall(STAGE, filter="data")
    (STAGE / "python").rename(rt)
    py = rt / "python.exe"
    wheels = rt / "mitrahome-wheels"
    subprocess.run([str(py), "-m", "pip", "download", "--disable-pip-version-check", "--only-binary=:all:",
                    "-r", str(STAGE / "app" / "requirements.txt"), "-d", str(wheels)], check=True)
    say(f"{len(list(wheels.glob('*.whl')))} wheels")


def iscc():
    found = shutil.which("ISCC") or next((str(p) for p in ISCC_PLACES if p.exists()), None)
    if not found:
        raise SystemExit("Inno Setup 6 not found. Install it (winget install JRSoftware.InnoSetup) or use --stage-only.")
    return found


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ref", default="HEAD", help="git ref to package (default HEAD; uncommitted changes are NOT included)")
    ap.add_argument("--stage-only", action="store_true")
    ap.add_argument("--sign", action="store_true", help="Authenticode-sign with Azure Artifact Signing (MITRA_SIGN_* variables)")
    a = ap.parse_args(argv)
    if sys.platform != "win32":
        raise SystemExit("build the Windows installer on Windows")
    sign = sign_setup() if a.sign and not a.stage_only else None  # fail on missing setup before the long downloads
    version = stage_app(a.ref)
    stage_runtime()
    if a.stage_only:
        say(f"staged in {STAGE}")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    args = [iscc(), f"/DAppVersion={version}", f"/DStage={STAGE}", f"/DOutDir={OUT}"]
    if sign:
        args += ["/DSign=1", f"/Smitrasign={sign[1]}"]
    subprocess.run(args + [str(HERE / "MitraHome.iss")], check=True)
    exe = OUT / f"MitraHome-Setup-{version}.exe"
    if sign:
        subprocess.run([sign[0], "verify", "/pa", str(exe)], check=True)
    say(f"built {exe} ({exe.stat().st_size // (1 << 20)} MB) sha256 {sha256(exe)}")
    say("signed and verified (Authenticode)" if sign else
        "unsigned: Windows SmartScreen will warn until it is code-signed (--sign, installer/README.md)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
