"""Signed releases: the stdlib Ed25519 verifier (RFC 8032 vectors, cross-checked with `cryptography`), the strict
SHA256SUMS format, `onboard.py update` refusing tampered / extra-file / unsigned / wrongly signed zips and accepting a
properly signed one, git mode checking the tag's files before fast-forwarding, safe redirects, and
scripts/sign_release.py init + sign producing files the updater accepts. Uses throwaway keys; never the real one."""
import base64
import hashlib
import importlib
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from conftest import DRY, SRC, bind, copy_template, run

crypto = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
from cryptography.hazmat.primitives import serialization as ser  # noqa: E402

RFC = [  # RFC 8032 section 7.1, tests 1-3: (public key, message, signature)
    ("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


def _key():
    k = crypto.Ed25519PrivateKey.generate()
    return k, k.public_key().public_bytes(ser.Encoding.Raw, ser.PublicFormat.Raw)


@pytest.fixture(scope="module")
def up(tmp_path_factory):
    root = copy_template(tmp_path_factory.mktemp("sig") / "t")
    bind(root)
    return importlib.import_module("updater"), importlib.import_module("ed25519_verify"), root


def test_verifier_rfc_vectors_and_cryptography(up):
    _, ed, _ = up
    for pk, msg, sig in RFC:
        pk, msg, sig = bytes.fromhex(pk), bytes.fromhex(msg), bytes.fromhex(sig)
        assert ed.verify(pk, msg, sig)
        assert not ed.verify(pk, msg + b"x", sig)
        assert not ed.verify(pk, msg, sig[:63] + bytes([sig[63] ^ 1]))
    k, pub = _key()
    for msg in (b"", b"hello", bytes(range(256)) * 50):
        sig = k.sign(msg)
        assert ed.verify(pub, msg, sig)
        assert not ed.verify(_key()[1], msg, sig), "another key"
    for bad in ((b"", b"m", b""), (pub, b"m", b"x" * 63), (b"\xff" * 32, b"m", b"\x00" * 64), (pub, b"m", b"\x00" * 32 + b"\xff" * 32)):
        assert not ed.verify(*bad), "malformed input is False, never an exception"


def test_manifest_format_is_strict(up):
    u, _, _ = up
    h = {"VERSION": "a" * 64, "data/x.py": "b" * 64}
    m = u.manifest_text("1.2.3", h)
    assert u.parse_manifest(m) == ("1.2.3", h)
    for bad in (m.replace(b"# FamilyAgent release manifest", b"# something else"), m.rstrip(b"\n"),
                m + ("c" * 64 + "  ../escape.py\n").encode(), m + ("c" * 64 + "  /abs.py\n").encode(),
                m + ("c" * 64 + "  VERSION\n").encode(), m.replace(b"# version 1.2.3", b"# version latest"),
                m.replace(b"a" * 64, b"A" * 64)):
        with pytest.raises(ValueError):
            u.parse_manifest(bad)


def test_verify_manifest_good_bad_unknown_and_none(up):
    u, _, _ = up
    k, pub = _key()
    m = u.manifest_text("1.2.3", {"VERSION": "a" * 64})
    line = lambda key, kid, msg: f"ed25519 {kid} {base64.b64encode(key.sign(msg)).decode()}".encode()  # noqa: E731
    assert u.verify_manifest(m, line(k, "t", m), {"t": pub})[0] == "1.2.3"
    with pytest.raises(ValueError, match="does not match"):
        u.verify_manifest(m.replace(b"a" * 64, b"b" * 64), line(k, "t", m), {"t": pub})
    with pytest.raises(ValueError, match="does not trust"):
        u.verify_manifest(m, line(k, "other", m), {"t": pub})
    with pytest.raises(ValueError, match="does not match"):
        u.verify_manifest(m, line(_key()[0], "t", m), {"t": pub}), "signed by someone else under the trusted id"
    with pytest.raises(ValueError):
        u.verify_manifest(m, b"rsa t AAAA", {"t": pub})
    with pytest.raises(u.Unsigned):
        u.verify_manifest(m, line(k, "t", m), {})


def test_redirects_stay_on_github_and_drop_the_token(up):
    u, _, _ = up
    import urllib.request
    h = u._SafeRedirect()
    req = urllib.request.Request("https://api.github.com/repos/x/y/releases/assets/1",
                                 headers={"Authorization": "Bearer secret", "Accept": "application/octet-stream"})
    new = h.redirect_request(req, None, 302, "Found", {}, "https://objects.githubusercontent.com/abc?sig=1")
    assert new.full_url.startswith("https://objects.githubusercontent.com/")
    assert not any(k.lower() == "authorization" for k in new.headers), "the token never leaves the API hosts"
    same = h.redirect_request(req, None, 302, "Found", {}, "https://codeload.github.com/x/y/zip/v1")
    assert any(k.lower() == "authorization" for k in same.headers), "codeload (private zipball) still needs it"
    for bad in ("https://evil.example/x.zip", "http://objects.githubusercontent.com/x", "https://github.com.evil.example/"):
        with pytest.raises(ValueError):
            h.redirect_request(req, None, 302, "Found", {}, bad)


# ---------------------------------------------------------------- end to end through onboard.py update --from
def _release_zip(folder, version, mutate=None):
    """A release zip (GitHub layout: one top folder) of this template at `version`, plus {path: sha256} of its files."""
    skip_dirs = {"__pycache__", ".git", "backups_pre_upgrade", ".pytest_cache", ".ruff_cache", "dist", "exports"}
    files = {}
    for f in SRC.rglob("*"):
        rel = f.relative_to(SRC)
        if not f.is_file() or skip_dirs & set(rel.parts) or rel.parts[0] in ("mobile", "installer") or f.suffix == ".db" \
                or f.name in ("family.json", "private_terms.txt", "heartbeat.json"):
            continue
        files[rel.as_posix()] = (version + "\n").encode() if rel.as_posix() == "VERSION" else f.read_bytes()
    files["data/signed_release_marker.py"] = f"# {version}\n".encode()
    hashes = {p: hashlib.sha256(b).hexdigest() for p, b in files.items()}
    if mutate:
        mutate(files)
    folder.mkdir(parents=True, exist_ok=True)
    zp = folder / f"Mitra Home-{version}.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for p, b in files.items():
            z.writestr("rNetGit-FamilyAgent.Ai-abc1234/" + p, b)
    return zp, hashes


def _sign(u, folder, version, hashes, key, kid="test-key"):
    m = u.manifest_text(version, hashes)
    (folder / "SHA256SUMS").write_bytes(m)
    (folder / "SHA256SUMS.sig").write_text(f"ed25519 {kid} {base64.b64encode(key.sign(m)).decode()}\n", encoding="utf-8")


def _trust(install, pub, kid="test-key"):
    (install / "data" / "release_keys.json").write_text(
        json.dumps({"keys": [{"id": kid, "ed25519": base64.b64encode(pub).decode()}]}), encoding="utf-8")


@pytest.fixture(scope="module")
def install(tmp_path_factory):
    old = copy_template(tmp_path_factory.mktemp("sig_install") / "old")
    assert run(["data/migrate.py"], old).returncode == 0
    run(["data/members.py", "sync"], old)
    return old


def _update(install, zp, *extra):
    return run(["onboard.py", "update", "--from", str(zp), "--yes", *extra], install, env=DRY)


def _version(install):
    return (install / "VERSION").read_text(encoding="utf-8").strip()


def test_tampered_extra_unsigned_and_foreign_signatures_are_refused(up, install, tmp_path):
    u, _, _ = up
    k, pub = _key()
    _trust(install, pub)
    before = _version(install)

    def evil(files):
        files["data/updater.py"] += b"\n# planted\n"
    zp, h = _release_zip(tmp_path / "tampered", "98.0.0", mutate=evil)
    _sign(u, zp.parent, "98.0.0", h, k)
    r = _update(install, zp, "--allow-unsigned")
    assert r.returncode != 0 and "changed: data/updater.py" in r.stdout, r.stdout[-600:]
    assert _version(install) == before and not (install / "data" / "signed_release_marker.py").exists(), "nothing copied"

    def extra(files):
        files["data/backdoor.py"] = b"print('hi')\n"
    zp, h = _release_zip(tmp_path / "extra", "98.0.0", mutate=extra)
    _sign(u, zp.parent, "98.0.0", h, k)
    r = _update(install, zp)
    assert r.returncode != 0 and "not in the signed list: data/backdoor.py" in r.stdout and not (install / "data" / "backdoor.py").exists()

    zp, h = _release_zip(tmp_path / "unsigned", "98.0.0")
    r = _update(install, zp)
    assert r.returncode != 0 and "not signed" in r.stdout and _version(install) == before

    zp, h = _release_zip(tmp_path / "foreign", "98.0.0")
    _sign(u, zp.parent, "98.0.0", h, _key()[0])  # right id, wrong key
    r = _update(install, zp, "--allow-unsigned")
    assert r.returncode != 0 and "signature check failed" in r.stdout, "--allow-unsigned never excuses a bad signature"
    _sign(u, zp.parent, "98.0.0", h, k, kid="someone-else")
    r = _update(install, zp, "--allow-unsigned")
    assert r.returncode != 0 and "does not trust" in r.stdout and _version(install) == before


def test_signed_zip_updates_and_unsigned_needs_the_flag(up, install, tmp_path):
    u, _, _ = up
    k, pub = _key()
    _trust(install, pub)
    zp, h = _release_zip(tmp_path / "good", "98.0.0")
    _sign(u, zp.parent, "98.0.0", h, k)
    r = _update(install, zp)
    assert r.returncode == 0 and "Signature OK" in r.stdout, (r.stdout + r.stderr)[-600:]
    assert _version(install) == "98.0.0" and (install / "data" / "signed_release_marker.py").read_text() == "# 98.0.0\n"
    _trust(install, pub)  # the release's own data/release_keys.json came in with the overlay; trust the test key again
    zp, _ = _release_zip(tmp_path / "unsigned_ok", "98.0.1")
    r = _update(install, zp, "--allow-unsigned")
    assert r.returncode == 0 and "WARNING: not verified" in r.stdout and _version(install) == "98.0.1"


def test_no_keys_installed_means_unsigned(up, install, tmp_path):
    u, _, _ = up
    k, pub = _key()
    (install / "data" / "release_keys.json").unlink()
    zp, h = _release_zip(tmp_path / "nokeys", "98.0.2")
    _sign(u, zp.parent, "98.0.2", h, k)
    r = _update(install, zp)
    assert r.returncode != 0 and "no release keys installed" in r.stdout and _version(install) == "98.0.1"


# ---------------------------------------------------------------- git mode and the maintainer tool
def git(cwd, *args):
    import subprocess
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                        "-c", "tag.gpgsign=false", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr[-300:]}"
    return r.stdout


@pytest.fixture
def repo(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git not on PATH")
    work = copy_template(tmp_path / "work", family=False)
    git(work, "init", "-q")
    git(work, "checkout", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(origin))
    git(work, "remote", "add", "origin", str(origin))
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(origin), str(other))
    (other / "data" / "signed_release_marker.py").write_text("# 97.0.0\n", encoding="utf-8")
    (other / "VERSION").write_text("97.0.0\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "release 97.0.0")
    git(other, "tag", "v97.0.0")
    git(other, "push", "-q", "origin", "main", "--tags")
    return work, other


@pytest.mark.git
def test_git_mode_checks_the_tag_before_fast_forward(repo):
    work, other = repo
    bind(work)
    u = importlib.import_module("updater")
    git(work, "fetch", "-q", "--tags", "origin")
    good = u.archive_hashes("v97.0.0", cwd=work)
    assert "data/signed_release_marker.py" in good
    wrong = dict(good, **{"data/updater.py": "0" * 64})
    ok, msg = u.update_git("v97.0.0", wrong)
    assert not ok and "changed: data/updater.py" in msg and not (work / "data" / "signed_release_marker.py").exists()
    ok, msg = u.update_git("v97.0.0", good)
    assert ok, msg
    assert (work / "VERSION").read_text(encoding="utf-8").strip() == "97.0.0"


@pytest.mark.git
def test_sign_release_tool_round_trip(repo, tmp_path):
    work, other = repo
    env = {"MITRAHOME_SIGNING_KEY": str(tmp_path / "keys" / "k.pem")}
    r = run(["scripts/sign_release.py", "init"], other, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PRIVATE" not in r.stdout and "BEGIN" not in r.stdout, "the private key is never printed"
    assert run(["scripts/sign_release.py", "init"], other, env=env).returncode != 0, "never overwrites a key"
    shipped = json.loads((SRC / "data" / "release_keys.json").read_text(encoding="utf-8"))["keys"]
    keys = json.loads((other / "data" / "release_keys.json").read_text(encoding="utf-8"))["keys"]
    assert len(keys) == len(shipped) + 1 and keys[:len(shipped)] == shipped, "init adds its key and keeps the others"
    assert keys[-1]["id"].startswith("familyagent-") and keys[-1]["id"] not in {k["id"] for k in shipped}
    (other / "VERSION").write_text("97.1.0\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "release 97.1.0 with key")
    git(other, "tag", "v97.1.0")
    r = run(["scripts/sign_release.py", "sign", "v97.1.0"], other, env=env)
    assert r.returncode == 0 and "gh release upload v97.1.0" in r.stdout, r.stdout + r.stderr
    dist = other / "dist" / "v97.1.0"
    bind(other)
    u = importlib.import_module("updater")
    version, hashes = u.verify_manifest((dist / "SHA256SUMS").read_bytes(), (dist / "SHA256SUMS.sig").read_bytes())
    assert version == "97.1.0" and hashes == u.archive_hashes("v97.1.0", cwd=other)
    assert "dist/v97.1.0/SHA256SUMS" not in hashes and not any(p.startswith("dist/") for p in hashes)
    assert run(["scripts/sign_release.py", "sign", "v97.0.0"], other, env=env).returncode == 0, "older tag signs too"
    (other / "VERSION").write_text("97.2.0\n", encoding="utf-8")
    git(other, "commit", "-qam", "bump")
    git(other, "tag", "v97.9.9")
    r = run(["scripts/sign_release.py", "sign", "v97.9.9"], other, env=env)
    assert r.returncode != 0 and "VERSION in the tag" in (r.stdout + r.stderr), "tag and VERSION must agree"
    assert Path(env["MITRAHOME_SIGNING_KEY"]).exists()
