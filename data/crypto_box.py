"""Backup encryption helpers (AES-256-GCM via the `cryptography` package; key from a passphrase via scrypt).

The passphrase comes from the MITRAHOME_BACKUP_PASSPHRASE environment variable or `config/secrets.env`
(git-ignored, never backed up). Without the passphrase an encrypted backup cannot be restored: keep a copy of it
somewhere safe that is NOT this PC.

File format FAB2 (written since 0.13.0):
  b"FAB2" + 16-byte file id, then chunks of [4-byte big-endian length][1-byte flags][AES-GCM ciphertext+tag].
  Chunk i uses nonce = file id[:8] + i (4 bytes) and authenticates, as associated data, the magic, the file id,
  the chunk index and the flags. The last chunk carries flag 0x01, so a file that was truncated, had chunks
  dropped, reordered or swapped in from another file fails to decrypt instead of restoring silently wrong data.
  The key is scrypt(passphrase, salt, n=2^17, r=8, p=1) (about 128 MiB of memory, under a second on a PC).
FAB1 (0.4.0 to 0.12.0: per-chunk Fernet tokens, scrypt n=2^15) is still read, so older backups restore as before;
a destination may hold both formats side by side.
"""
import base64
import hashlib
import hmac
import os
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
import brand  # noqa: E402
MAGIC = b"FAB2"
MAGIC_V1 = b"FAB1"
CHUNK = 1 << 20
CHECK_TEXT = b"FamilyAgent backup check"
LAST = 0x01


class CryptoUnavailable(RuntimeError):
    pass


def _lib():
    try:
        from cryptography.fernet import Fernet
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        return Fernet, AESGCM
    except ImportError as e:
        raise CryptoUnavailable("The `cryptography` package is needed for encrypted backups: python -m pip install cryptography") from e


def available():
    """Raise CryptoUnavailable if the cryptography package is missing (used by onboard.py and backup.py)."""
    _lib()


# ---------- passphrase and secrets file

PASSPHRASE_NAME = "MITRAHOME_BACKUP_PASSPHRASE"  # FAMILYAGENT_BACKUP_PASSPHRASE before the rename, still read

def load_passphrase():
    import config
    return config.read_secret(PASSPHRASE_NAME)


def store_passphrase(passphrase):
    """Save to config/secrets.env (git-ignored, owner-only permissions). Replaces an existing entry; keeps other lines."""
    import config
    config.write_secret(PASSPHRASE_NAME, passphrase)


# ---------- keys

def derive_key(passphrase, salt, version=2):
    if version == 1:
        raw = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1, maxmem=96 * 1024 * 1024, dklen=32)
        return base64.urlsafe_b64encode(raw)
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2 ** 17, r=8, p=1, maxmem=256 * 1024 * 1024, dklen=32)


class Cipher:
    """AES-GCM for new files; a Fernet instance (derived on first use) for FAB1 files written by older releases."""

    def __init__(self, passphrase, salt):
        Fernet, AESGCM = _lib()
        self._pw, self._salt = passphrase, salt
        self.aead = AESGCM(derive_key(passphrase, salt))
        self._fernet_cls, self._fernet = Fernet, None

    def legacy(self):
        if self._fernet is None:
            self._fernet = self._fernet_cls(derive_key(self._pw, self._salt, version=1))
        return self._fernet


def cipher(passphrase, salt):
    return Cipher(passphrase, salt)


def opaque_name(salt, relpath):
    return hmac.new(salt, relpath.encode("utf-8"), hashlib.sha256).hexdigest()[:32] + ".enc"


# ---------- FAB2 stream

def _nonce(fid, i):
    return fid[:8] + i.to_bytes(4, "big")


def _aad(fid, i, flags):
    return MAGIC + fid + i.to_bytes(4, "big") + bytes([flags])


def _write_stream(reader, out, c):
    fid = os.urandom(16)
    out.write(MAGIC + fid)
    i = 0
    chunk = reader(CHUNK)
    while True:
        nxt = reader(CHUNK)
        flags = LAST if not nxt else 0
        tok = c.aead.encrypt(_nonce(fid, i), chunk, _aad(fid, i, flags))
        out.write(len(tok).to_bytes(4, "big") + bytes([flags]) + tok)
        if flags & LAST:
            return
        chunk, i = nxt, i + 1


def _read_stream(inp, out, c):
    head = inp.read(4)
    if head == MAGIC_V1:
        f = c.legacy()
        while True:
            n = inp.read(4)
            if not n:
                return
            out(f.decrypt(inp.read(int.from_bytes(n, "big"))))
    if head != MAGIC:
        raise ValueError(f"not a {brand.PRODUCT} encrypted file")
    fid = inp.read(16)
    if len(fid) != 16:
        raise ValueError("truncated encrypted file")
    i = 0
    while True:
        hdr = inp.read(5)
        if len(hdr) < 5:
            raise ValueError("encrypted file ends before its final chunk (truncated or damaged)")
        n, flags = int.from_bytes(hdr[:4], "big"), hdr[4]
        tok = inp.read(n)
        if len(tok) != n:
            raise ValueError("encrypted file ends before its final chunk (truncated or damaged)")
        out(c.aead.decrypt(_nonce(fid, i), tok, _aad(fid, i, flags)))  # raises InvalidTag on any tampering
        if flags & LAST:
            if inp.read(1):
                raise ValueError("data after the final chunk")
            return
        i += 1


def encrypt_file(src, dst, c):
    dst = pathlib.Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    with open(src, "rb") as i, open(tmp, "wb") as o:
        _write_stream(i.read, o, c)
    os.replace(tmp, dst)


def decrypt_file(src, dst, c):
    dst = pathlib.Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dst.name + ".", suffix=".part", dir=dst.parent)
    try:
        with open(src, "rb") as i, os.fdopen(fd, "wb") as o:
            _read_stream(i, o.write, c)
        os.replace(tmp, dst)
    except BaseException:
        pathlib.Path(tmp).unlink(missing_ok=True)
        raise


def encrypt_bytes(data, c):
    import io
    out = io.BytesIO()
    _write_stream(io.BytesIO(data).read, out, c)
    return out.getvalue()


def decrypt_bytes(blob, c):
    import io
    parts = []
    _read_stream(io.BytesIO(blob), parts.append, c)
    return b"".join(parts)
