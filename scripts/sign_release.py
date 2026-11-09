"""Sign a Mitra Home release (maintainers only; needs the `cryptography` package from requirements.txt).

  python scripts/sign_release.py init                 make the signing key (once) and add its PUBLIC key to
                                                      data/release_keys.json; commit that file before the next tag
  python scripts/sign_release.py sign vX.Y.Z          write dist/vX.Y.Z/SHA256SUMS + SHA256SUMS.sig for a local tag
  python scripts/sign_release.py pubkey               print the public key line (safe to share)

The private key lives OUTSIDE the repository: env MITRAHOME_SIGNING_KEY, else ~/.mitrahome/release_signing_ed25519.pem
(~/.familyagent/ from before the rename is still used when that is where the key is).
It is never printed. Back it up somewhere safe and offline: without it, families cannot verify new releases until they
install a release with a new key by hand (python onboard.py update --allow-unsigned, or a fresh install).

SHA256SUMS lists the SHA-256 of every file in `git archive <tag>`, which is byte-for-byte what GitHub serves as the
release zip and what a git install checks out from the tag. data/updater.py verifies it with the public keys of the
family's INSTALLED copy (data/ed25519_verify.py, standard library only) before replacing any file.
After signing:  gh release upload vX.Y.Z dist/vX.Y.Z/SHA256SUMS dist/vX.Y.Z/SHA256SUMS.sig
"""
import base64
import hashlib
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "data"))
import updater  # noqa: E402

KEYS = ROOT / "data" / "release_keys.json"


def key_path():
    env = os.environ.get("MITRAHOME_SIGNING_KEY") or os.environ.get("FAMILYAGENT_SIGNING_KEY")
    new, old = (pathlib.Path.home() / d / "release_signing_ed25519.pem" for d in (".mitrahome", ".familyagent"))
    return pathlib.Path(env) if env else (old if old.exists() and not new.exists() else new)


def _raw_public(priv):
    from cryptography.hazmat.primitives import serialization as s
    return priv.public_key().public_bytes(s.Encoding.Raw, s.PublicFormat.Raw)


def key_id(pub):
    return "familyagent-" + hashlib.sha256(pub).hexdigest()[:12]


def load_private():
    from cryptography.hazmat.primitives import serialization as s
    p = key_path()
    if not p.exists():
        raise SystemExit(f"no signing key at {p}. Run: python scripts/sign_release.py init")
    return s.load_pem_private_key(p.read_bytes(), password=None)


def init():
    from cryptography.hazmat.primitives import serialization as s
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    p = key_path()
    if p.exists():
        raise SystemExit(f"a signing key already exists at {p}; not overwriting it")
    p.parent.mkdir(parents=True, exist_ok=True)
    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(s.Encoding.PEM, s.PrivateFormat.PKCS8, s.NoEncryption())
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(pem)
    pub = _raw_public(priv)
    add_public(pub)
    print(f"signing key written to {p} (private: back it up offline, never commit it)")
    print(f"public key {key_id(pub)} added to {KEYS.relative_to(ROOT).as_posix()}: commit it before the next release")


def add_public(pub):
    d = json.loads(KEYS.read_text(encoding="utf-8")) if KEYS.exists() else {}
    keys = [k for k in d.get("keys") or [] if k.get("id") != key_id(pub)]
    keys.append({"id": key_id(pub), "ed25519": base64.b64encode(pub).decode("ascii")})
    d = {"note": "Public keys that sign Mitra Home releases (data/updater.py checks SHA256SUMS.sig against these). "
                 "Public, safe to share. Changing this file only takes effect after an update that was itself signed.",
         "keys": keys}
    KEYS.write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")


def sign(tag, out=None):
    version = tag.lstrip("v")
    hashes = updater.archive_hashes(tag, cwd=ROOT)
    tagged_version = updater._git("show", f"{tag}:VERSION").stdout.strip()
    if tagged_version != version:
        raise SystemExit(f"{tag}: VERSION in the tag is {tagged_version!r}, not {version}")
    priv = load_private()
    pub = _raw_public(priv)
    manifest = updater.manifest_text(version, hashes)
    line = f"ed25519 {key_id(pub)} {base64.b64encode(priv.sign(manifest)).decode('ascii')}\n".encode("ascii")
    v, h = updater.verify_manifest(manifest, line, {key_id(pub): pub})  # self-check with the stdlib verifier
    assert v == version and h == hashes
    trusted = updater.release_keys()
    if key_id(pub) not in trusted:
        print(f"WARNING: {key_id(pub)} is not in {KEYS.relative_to(ROOT).as_posix()}; installs will refuse this signature")
    folder = pathlib.Path(out) if out else ROOT / "dist" / tag
    folder.mkdir(parents=True, exist_ok=True)
    (folder / updater.MANIFEST).write_bytes(manifest)
    (folder / updater.SIGNATURE).write_bytes(line)
    try:
        shown = folder.relative_to(ROOT).as_posix()
    except ValueError:
        shown = str(folder)
    print(f"signed {tag}: {len(hashes)} files, key {key_id(pub)} -> {shown}/")
    print(f"next: gh release upload {tag} {shown}/{updater.MANIFEST} {shown}/{updater.SIGNATURE}")


def main():
    a = sys.argv[1:]
    if not a or a[0] not in ("init", "sign", "pubkey"):
        raise SystemExit(__doc__)
    if a[0] == "init":
        return init()
    if a[0] == "pubkey":
        pub = _raw_public(load_private())
        print(key_id(pub), base64.b64encode(pub).decode("ascii"))
        return
    if len(a) < 2:
        raise SystemExit("usage: python scripts/sign_release.py sign vX.Y.Z [--out DIR]")
    sign(a[1], a[a.index("--out") + 1] if "--out" in a and a.index("--out") + 1 < len(a) else None)


if __name__ == "__main__":
    main()
