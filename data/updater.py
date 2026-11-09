"""Update Mitra Home code from the official releases without touching a family's own data.

  python onboard.py check                     is a newer release available? (read-only)
  python onboard.py update                    update to the latest release, then migrate the database
  python onboard.py update --from FILE.zip    update from a zip you were sent (offline / no git)
  python onboard.py update --yes              no confirmation prompt

Git installs (cloned from the repo): fast-forward to the latest release tag; refuses if tracked files were edited.
Other installs: download the release zip (https, GitHub hosts only) and overlay CODE files; replaced files are
copied to data/backups_pre_upgrade/code_<old version>_<time>/ first. Never touched: config/, *.db, inbox/, archive/,
brief/, reports/, logs/, mitrahome_home.txt or familyagent_home.txt (and so the household folder it names),
CLAUDE.local.md,
.claude/settings.local.json, .claude/agents/local-*.md, scripts/private_terms.txt.
Nothing is ever deleted: code files the new release no longer has (a removed migration, page or agent) are moved
into that same backup folder under dropped/ so they stop running (audit A4); anything else is only listed.

Signed releases (0.31.0 and later): each GitHub release carries SHA256SUMS (the SHA-256 of every file in the tagged
tree, as `git archive` and GitHub's zip produce it) and SHA256SUMS.sig (an Ed25519 signature by the maintainers' key,
made with scripts/sign_release.py). Before any file is replaced, the signature is checked against the public key(s)
in THIS install's data/release_keys.json (never the downloaded one), then every file of the downloaded zip (or of the
fetched git tag) must match the list exactly: nothing missing, nothing extra, nothing changed. A bad signature or a
mismatch always stops the update. A release with no signature stops it too, unless --allow-unsigned is given.
For `--from FILE.zip`, SHA256SUMS and SHA256SUMS.sig are looked for next to the zip.
Downloads follow redirects only to GitHub hosts over https, and the token is never sent to a non-API host.
Standard library only.
"""
import brand
import base64
import datetime as dt
import fnmatch
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
import paths  # noqa: E402
REPO = "rNetGit/mitra-home-app"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
ALLOWED_HOSTS = {"api.github.com", "github.com", "codeload.github.com"}
ASSET_HOSTS = {"objects.githubusercontent.com", "release-assets.githubusercontent.com"}  # release-asset redirects
TOKEN_HOSTS = {"api.github.com", "github.com", "codeload.github.com"}  # the token never goes anywhere else
MAX_ZIP = 60 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
MANIFEST, SIGNATURE = "SHA256SUMS", "SHA256SUMS.sig"
KEYS = ROOT / "data" / "release_keys.json"

# Paths (relative, forward slashes, fnmatch) that belong to the family and are never overwritten.
PROTECTED = [
    ".git/*", "config/*.json", "data/*.db", "data/backups_pre_upgrade/*", "inbox/*", "archive/*", "brief/*",
    "reports/*", "logs/*", "CLAUDE.local.md", ".claude/settings.local.json", ".claude/agents/local-*.md",
    "scripts/private_terms.txt", "mitrahome_home.txt", "familyagent_home.txt", ".venv/*", ".dashboard.json", ".webapp.json", "*/__pycache__/*", "__pycache__/*",
]
UNPROTECT = ["config/*.example.json"]  # shipped examples are code
DROP_ASIDE = {".py", ".html", ".css", ".js", ".md", ".json", ".bat", ".command", ".sh", ".ps1", ".txt", ".svg", ".png"}


def parse(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3]) + (0,) * max(0, 3 - len(re.findall(r"\d+", str(v))[:3]))


def current_version():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0"


def protected(rel):
    if any(fnmatch.fnmatch(rel, g) for g in UNPROTECT):
        return False
    return any(fnmatch.fnmatch(rel, g) for g in PROTECTED)


def _safe_url(url, hosts=ALLOWED_HOSTS):
    u = urlparse(url)
    if u.scheme != "https" or u.hostname not in hosts:
        raise ValueError(f"refusing to download from {url}")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Follow a redirect only to GitHub hosts over https; drop the token when leaving the API hosts."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _safe_url(newurl, ALLOWED_HOSTS | ASSET_HOSTS)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urlparse(newurl).hostname not in TOKEN_HOSTS:
            for k in list(new.headers):
                if k.lower() == "authorization":
                    del new.headers[k]
        return new


_OPENER = urllib.request.build_opener(_SafeRedirect)


LAST_ERROR = ""


def _token():
    """Optional GitHub token (env MITRAHOME_TOKEN or GH_TOKEN) for a private repo; never printed or stored."""
    return paths.env("MITRAHOME_TOKEN") or os.environ.get("GH_TOKEN") or ""


def _get(url, timeout=15, accept="application/vnd.github+json"):
    headers = {"User-Agent": "MitraHome-updater", "Accept": accept}
    if _token():
        headers["Authorization"] = "Bearer " + _token()
    req = urllib.request.Request(_safe_url(url), headers=headers)
    return _OPENER.open(req, timeout=timeout)


def _explain(e):
    global LAST_ERROR
    code = getattr(e, "code", None)
    if code in (401, 403, 404):
        LAST_ERROR = (f"GitHub answered {code}: the repository {REPO} is private, or has no release/tag yet. "
                      "Ask the maintainer to make it public or to invite you, then set a read-only token in the "
                      "MITRAHOME_TOKEN environment variable.")
    else:
        LAST_ERROR = f"{type(e).__name__}: {e}"


SITE_REPO = "rNetGit/mitra-home"  # the public site: its releases carry the installers anyone can download
SITE_URL = "https://rnetgit.github.io/mitra-home/"
SITE_INSTALL_URL = SITE_URL + "install.html"
SITE_API = f"https://api.github.com/repos/{SITE_REPO}/releases?per_page=10"
INSTALLER_EXT = {"win32": (".exe",), "darwin": (".dmg",)}  # the installer a computer can use (Linux installs from source)


def site_release(platform=None):
    """The newest public release on the site that has an installer for this computer -> {'version', 'tag', 'notes', 'url'},
    or None (offline, nothing newer, or no installer for this system). A plain public read: no token is sent, and only
    a version number, its notes and the link to the install page are kept. For a PC that cannot read the private app
    repository (every family but the maintainer's): it can say a new version exists, not install it by itself."""
    exts = INSTALLER_EXT.get(platform or sys.platform)
    if not exts:
        return None
    try:
        req = urllib.request.Request(_safe_url(SITE_API), headers={"User-Agent": "MitraHome-updater", "Accept": "application/vnd.github+json"})
        with _OPENER.open(req, timeout=10) as r:
            rels = json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 (offline or rate limited: no answer, never an error on the page)
        return None
    best = None
    for d in rels if isinstance(rels, list) else []:
        m = re.fullmatch(r"mitra-home-(\d+\.\d+\.\d+)", str(d.get("tag_name") or ""))
        if not m or d.get("draft") or d.get("prerelease"):
            continue
        if not any(str(a.get("name") or "").endswith(exts) for a in d.get("assets") or []):
            continue
        if best is None or parse(m.group(1)) > parse(best["version"]):
            best = {"version": m.group(1), "tag": d["tag_name"], "notes": d.get("body") or "", "url": SITE_INSTALL_URL}
    return best


def latest_release():
    """{'version', 'tag', 'zip_url', 'notes'} or None if offline / no release yet."""
    try:
        with _get(API, 10) as r:
            d = json.loads(r.read().decode("utf-8"))
        assets = {a["name"]: a["url"] for a in d.get("assets") or [] if a.get("name") in (MANIFEST, SIGNATURE)}
        return {"version": d["tag_name"].lstrip("v"), "tag": d["tag_name"], "zip_url": d["zipball_url"], "notes": d.get("body") or "",
                "assets": assets}
    except Exception as e:
        _explain(e)
    try:  # no formal Release published: fall back to the highest version tag
        with _get(f"https://api.github.com/repos/{REPO}/tags?per_page=100", 10) as r:
            tags = [t["name"] for t in json.loads(r.read().decode("utf-8")) if re.fullmatch(r"v?\d+\.\d+\.\d+", t["name"])]
        if not tags:
            return None
        tag = max(tags, key=parse)
        return {"version": tag.lstrip("v"), "tag": tag, "zip_url": f"https://github.com/{REPO}/archive/refs/tags/{tag}.zip", "notes": "",
                "assets": {}}
    except Exception as e:
        _explain(e)
        return None


# ---------------------------------------------------------------- signed manifest (SHA256SUMS + SHA256SUMS.sig)
class Unsigned(Exception):
    """No signature to check (release without SHA256SUMS assets, or no keys installed)."""


def manifest_text(version, hashes):
    """The exact bytes that are signed: a header with the version, then `<sha256>  <path>` sorted by path."""
    lines = ["# FamilyAgent release manifest", f"# version {version}"]
    lines += [f"{h}  {p}" for p, h in sorted(hashes.items())]
    return ("\n".join(lines) + "\n").encode("utf-8")


def parse_manifest(data):
    """-> (version, {path: sha256}). Strict: anything unexpected raises ValueError."""
    lines = data.decode("utf-8").split("\n")
    if len(lines) < 3 or lines[-1] != "" or lines[0] != "# FamilyAgent release manifest" or not lines[1].startswith("# version "):
        raise ValueError("not a FamilyAgent release manifest")
    version, out = lines[1][len("# version "):].strip(), {}
    for ln in lines[2:-1]:
        m = re.fullmatch(r"([0-9a-f]{64})  (\S(?:.*\S)?)", ln)
        if not m or m.group(2) in out or m.group(2).startswith("/") or ".." in m.group(2).split("/"):
            raise ValueError(f"bad manifest line: {ln[:80]}")
        out[m.group(2)] = m.group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not out:
        raise ValueError("manifest has no version or no files")
    return version, out


def release_keys():
    """{key id: 32-byte Ed25519 public key} from THIS install's data/release_keys.json."""
    try:
        d = json.loads(KEYS.read_text(encoding="utf-8"))
        return {k["id"]: base64.b64decode(k["ed25519"], validate=True) for k in d.get("keys") or []}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def verify_manifest(manifest, sig_line, keys=None):
    """Check SHA256SUMS against SHA256SUMS.sig with an installed key. -> (version, hashes). Raises ValueError when it
    does not verify, Unsigned when no key is installed."""
    import ed25519_verify
    keys = release_keys() if keys is None else keys
    if not keys:
        raise Unsigned("no release keys installed (data/release_keys.json)")
    parts = sig_line.decode("utf-8", "replace").strip().split()
    if len(parts) != 3 or parts[0] != "ed25519":
        raise ValueError("SHA256SUMS.sig is not an ed25519 signature line")
    pub = keys.get(parts[1])
    if pub is None:
        raise ValueError(f"signed with key '{parts[1][:40]}', which this install does not trust")
    try:
        sig = base64.b64decode(parts[2], validate=True)
    except ValueError:
        raise ValueError("SHA256SUMS.sig is not valid base64") from None
    if not ed25519_verify.verify(pub, manifest, sig):
        raise ValueError("the signature on SHA256SUMS does not match: this download was not made by the maintainers")
    return parse_manifest(manifest)


def tree_hashes(folder):
    folder = Path(folder)
    return {f.relative_to(folder).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in sorted(folder.rglob("*")) if f.is_file()}


def archive_hashes(tag, cwd=None):
    """SHA-256 of every file in `git archive <tag>` (the same bytes as GitHub's release zip)."""
    r = subprocess.run(["git", "archive", "--format=tar", tag], cwd=cwd or ROOT, capture_output=True, env=_git_env(cwd or ROOT))
    if r.returncode:
        raise ValueError("git archive failed: " + r.stderr.decode("utf-8", "replace").strip()[-200:])
    out = {}
    with tarfile.open(fileobj=io.BytesIO(r.stdout)) as t:
        for m in t:
            if m.isfile():
                out[m.name] = hashlib.sha256(t.extractfile(m).read()).hexdigest()
    return out


def compare(expected, actual):
    """'' when the trees match exactly, else a short description of the first differences."""
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(p for p in set(expected) & set(actual) if expected[p] != actual[p])
    if not (missing or extra or changed):
        return ""
    bits = [f"{label}: {', '.join(xs[:3])}{' ...' if len(xs) > 3 else ''}" for label, xs in
            (("changed", changed), ("not in the signed list", extra), ("missing", missing)) if xs]
    return "files do not match the signed list (" + "; ".join(bits) + ")"


def _read_asset(url):
    with _get(url, 30, accept="application/octet-stream") as r:
        data = r.read(MAX_MANIFEST + 1)
    if len(data) > MAX_MANIFEST:
        raise ValueError("signature file too large")
    return data


def signed_manifest(rel=None, zip_path=None):
    """(manifest bytes, signature bytes) for a GitHub release or for SHA256SUMS(.sig) next to a zip. Raises Unsigned."""
    if zip_path is not None:
        m, s = Path(zip_path).with_name(MANIFEST), Path(zip_path).with_name(SIGNATURE)
        if not (m.exists() and s.exists()):
            raise Unsigned(f"no {MANIFEST} and {SIGNATURE} next to {Path(zip_path).name}")
        if m.stat().st_size > MAX_MANIFEST or s.stat().st_size > MAX_MANIFEST:
            raise ValueError("signature files too large")
        return m.read_bytes(), s.read_bytes()
    assets = (rel or {}).get("assets") or {}
    if MANIFEST not in assets or SIGNATURE not in assets:
        raise Unsigned(f"release {(rel or {}).get('tag', '?')} has no {MANIFEST} / {SIGNATURE}")
    return _read_asset(assets[MANIFEST]), _read_asset(assets[SIGNATURE])


def is_git():
    return (ROOT / ".git").exists() and shutil.which("git") is not None


def _git_env(folder):
    """Environment that trusts `folder` for this git call only. File systems that record no owner (exFAT / USB
    drives) make git refuse with "dubious ownership"; no global git config is touched."""
    env = dict(os.environ)
    n = int(env.get("GIT_CONFIG_COUNT") or 0) if str(env.get("GIT_CONFIG_COUNT") or "0").isdigit() else 0
    env["GIT_CONFIG_COUNT"] = str(n + 1)
    env[f"GIT_CONFIG_KEY_{n}"] = "safe.directory"
    env[f"GIT_CONFIG_VALUE_{n}"] = Path(folder).resolve().as_posix()
    return env


def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, env=_git_env(ROOT))


def check(quiet=False):
    """Print and return (current, latest_or_None, newer: bool)."""
    cur = current_version()
    rel = latest_release()
    if not rel:
        if not quiet:
            print(f"{brand.PRODUCT} {cur}. Could not check for updates. {LAST_ERROR or 'Offline?'}")
        return cur, None, False
    newer = parse(rel["version"]) > parse(cur)
    if not quiet:
        print(f"{brand.PRODUCT} {cur}; latest release {rel['version']}." + (" Update available: python onboard.py update" if newer else " Up to date."))
    return cur, rel, newer


def changelog_between(old, new, text=None):
    """Sections of a changelog newer than `old` up to `new`. `text` defaults to the installed CHANGELOG.md."""
    if text is None:
        f = ROOT / "CHANGELOG.md"
        if not f.exists():
            return ""
        text = f.read_text(encoding="utf-8")
    out, keep = [], False
    for line in text.splitlines():
        m = re.match(r"^## \[?v?(\d+\.\d+\.\d+)", line)
        if m:
            keep = parse(old) < parse(m.group(1)) <= parse(new)
        if keep:
            out.append(line)
    return "\n".join(out).strip()


def update_git(tag, expected=None):
    """Fast-forward to `tag`. expected = {path: sha256} from a verified manifest: the tag's files must match it first."""
    if _git("status", "--porcelain", "--untracked-files=no").stdout.strip():
        return False, "tracked files have local edits; move your changes to CLAUDE.local.md / settings.local.json / local-*.md agents, or `git stash`, then retry"
    f = _git("fetch", "--tags", "--quiet", "origin")
    if f.returncode:
        return False, "git fetch failed: " + f.stderr.strip()[-200:]
    if expected is not None:
        try:
            bad = compare(expected, archive_hashes(tag))
        except ValueError as e:
            return False, str(e)
        if bad:
            return False, f"{tag}: {bad}"
    m = _git("merge", "--ff-only", tag)
    if m.returncode:
        return False, "cannot fast-forward to " + tag + ": " + (m.stderr.strip() or m.stdout.strip())[-200:]
    return True, ""


def _download(url):
    """The release zip in a temp folder of its own; the caller removes that folder (`_forget_download`)."""
    tmp = Path(tempfile.mkdtemp(prefix="mitrahome_dl_")) / "release.zip"
    try:
        with _get(url, 60) as r, open(tmp, "wb") as out:
            total = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_ZIP:
                    raise ValueError("download too large")
                out.write(chunk)
    except BaseException:
        _forget_download(tmp)
        raise
    return tmp


def _forget_download(zp):
    """Each update downloaded up to 60 MB into the temp folder and left it there: remove the download's own folder."""
    if zp is not None and zp.parent.name.startswith("mitrahome_dl_"):
        shutil.rmtree(zp.parent, ignore_errors=True)


def update_zip(zip_path, force=False, expected=None):
    """Overlay code from a release zip. expected = {path: sha256} from a verified manifest: every file must match it
    before anything is copied. Returns (ok, message, new_version, obsolete_files)."""
    zp = Path(zip_path)
    tmp = Path(tempfile.mkdtemp(prefix="mitrahome_up_"))
    try:
        with zipfile.ZipFile(zp) as z:
            for n in z.namelist():  # zip-slip guard
                dest = (tmp / n).resolve()
                if tmp.resolve() not in dest.parents and dest != tmp.resolve():
                    return False, f"unsafe path in zip: {n}", None, []
            z.extractall(tmp)
        tops = [p for p in tmp.iterdir() if p.is_dir()]
        src = tops[0] if len(tops) == 1 and not (tmp / "onboard.py").exists() else tmp
        if not (src / "onboard.py").exists() or not (src / "VERSION").exists():
            return False, f"this does not look like a {brand.PRODUCT} release (onboard.py / VERSION missing)", None, []
        new_v = (src / "VERSION").read_text(encoding="utf-8").strip()
        if expected is not None:
            bad = compare(expected, tree_hashes(src))
            if bad:
                return False, "Not updated: " + bad, new_v, []
        old_v = current_version()
        if parse(new_v) < parse(old_v) and not force:
            return False, f"zip is version {new_v}, older than installed {old_v} (use --force to downgrade code; the database is never downgraded)", new_v, []
        bk = paths.PRE_UPGRADE / f"code_{old_v}_{dt.datetime.now():%Y%m%d_%H%M%S}"
        copied = 0
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            rel = f.relative_to(src).as_posix()
            if protected(rel):
                continue
            dst = ROOT / rel
            if dst.exists():
                if dst.read_bytes() == f.read_bytes():
                    continue
                (bk / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dst, bk / rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
            copied += 1
        new_files = {f.relative_to(src).as_posix() for f in src.rglob("*") if f.is_file()}
        obsolete = []
        for d in ("data", "tasks", "scripts", ".claude/agents", "packs", "tests"):
            for f in (ROOT / d).rglob("*") if (ROOT / d).exists() else []:
                rel = f.relative_to(ROOT).as_posix()
                if f.is_file() and not protected(rel) and rel not in new_files and "__pycache__" not in rel and not Path(rel).name.startswith("local-"):
                    obsolete.append(rel)
        moved = []
        for rel in obsolete:  # old code would keep running (a removed migration still migrates): set it aside
            if Path(rel).suffix.lower() not in DROP_ASIDE:
                continue
            aside = bk / "dropped" / rel
            try:
                aside.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(ROOT / rel), str(aside))
                moved.append(rel)
            except OSError:
                pass
        if moved:
            print(f"{len(moved)} file(s) this release no longer has moved to {paths.rel(bk / 'dropped')} "
                  "(put one back from there if you need it):\n  " + "\n  ".join(moved[:20]))
        obsolete = [r for r in obsolete if r not in moved]
        return True, f"{copied} file(s) updated" + (f"; previous versions saved in {paths.rel(bk)}" if bk.exists() else ""), new_v, obsolete
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _verified(rel=None, zip_path=None, allow_unsigned=False, want_version=None):
    """-> (ok, expected hashes or None). Prints why when it stops. (True, None) = unsigned and allowed."""
    try:
        manifest, sig = signed_manifest(rel, zip_path)
        version, hashes = verify_manifest(manifest, sig)
    except Unsigned as e:
        if allow_unsigned:
            print(f"WARNING: not verified ({e}); continuing because of --allow-unsigned.")
            return True, None
        print(f"Update stopped: this release is not signed ({e}). Ask the maintainer, or rerun with --allow-unsigned "
              "only if you trust where it came from.")
        return False, None
    except Exception as e:  # bad signature, unknown key, malformed files, download error: never allowed
        print(f"Update stopped: signature check failed: {e}")
        return False, None
    if want_version and version != want_version:
        print(f"Update stopped: the signed list is for {version}, not {want_version}.")
        return False, None
    print(f"Signature OK: {MANIFEST} for {version} ({len(hashes)} files) signed by the maintainers' key.")
    return True, hashes


def run_update(from_zip=None, assume_yes=False, force=False, ask=input, post=None, allow_unsigned=False):
    """Whole flow. `post` is called after the code is updated (onboard.upgrade). Returns True on success."""
    old_v = current_version()
    if from_zip:
        mode, target, rel = "zip", Path(from_zip), None
        if not target.exists():
            print(f"No such file: {from_zip}")
            return False
    else:
        _, rel, newer = check(quiet=True)
        if not rel:
            print(f"Could not check for updates. {LAST_ERROR or 'Offline?'} Use `--from FILE.zip` if you were sent a zip.")
            return False
        if not newer and not force:
            print(f"Already on the latest release ({old_v}).")
            return True
        mode = "git" if is_git() else "zip"
        target = rel["tag"]
        print(f"Updating {old_v} -> {rel['version']} ({mode}).")
        notes = changelog_between(old_v, rel["version"], rel["notes"]) or changelog_between(old_v, rel["version"])
        if notes:
            print("\n" + notes[:3000] + "\n")
    if not assume_yes:
        try:
            answer = ask("Your data (config, database, archive, inbox) is not touched; the database is backed up first. Continue? (Y/n): ")
        except EOFError:  # no one to answer (a remote or scheduled shell): stop before anything changes
            print("\nNo answer could be read here, so nothing was changed. Run it again with --yes to go ahead.")
            return False
        if answer.strip().lower().startswith("n"):
            print("Cancelled.")
            return False
    if mode == "git":
        ok, expected = _verified(rel, allow_unsigned=allow_unsigned, want_version=rel["version"])
        if not ok:
            return False
        ok, msg = update_git(target, expected)
        if not ok:
            print("Update stopped: " + msg)
            return False
    else:
        try:
            zp = Path(from_zip) if from_zip else _download(rel["zip_url"])
        except Exception as e:
            print(f"Download failed: {e}")
            return False
        try:
            ok, expected = _verified(rel, zp if from_zip else None, allow_unsigned, None if from_zip else rel["version"])
            if not ok:
                return False
            ok, msg, new_v, obsolete = update_zip(zp, force, expected)
        finally:
            if not from_zip:  # never the family's own --from file
                _forget_download(zp)
        print(msg)
        if not ok:
            return False
        if obsolete:
            print("Files no longer in this release (kept, safe to delete later):\n  " + "\n  ".join(obsolete[:20]))
    print(f"Code is now {current_version()}.")
    try:
        import log
        log.get("updater").info("updated %s -> %s (%s)", old_v, current_version(), mode)
    except Exception:
        pass
    if post:
        post()
    return True


if __name__ == "__main__":
    check()
