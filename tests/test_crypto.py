"""data/crypto_box.py: FAB2 round trip, every kind of tampering is detected, FAB1 files from older releases still open."""
import os

import pytest

pytest.importorskip("cryptography")
SALT = b"0123456789abcdef"


@pytest.fixture(scope="module")
def cb(modules):
    return modules("crypto_box")


@pytest.fixture(scope="module")
def c(cb):
    return cb.cipher("correct horse battery staple", SALT)


def test_round_trip_small_and_multichunk(cb, c, tmp_path):
    for size in (0, 1, cb.CHUNK - 1, cb.CHUNK, cb.CHUNK + 1, 2 * cb.CHUNK + 7):
        data = os.urandom(size)
        src, enc, out = tmp_path / f"s{size}", tmp_path / f"e{size}", tmp_path / f"o{size}"
        src.write_bytes(data)
        cb.encrypt_file(src, enc, c)
        assert enc.read_bytes()[:4] == b"FAB2"
        cb.decrypt_file(enc, out, c)
        assert out.read_bytes() == data
    assert cb.decrypt_bytes(cb.encrypt_bytes(b"hello", c), c) == b"hello"
    assert cb.encrypt_bytes(b"hello", c) != cb.encrypt_bytes(b"hello", c), "fresh file id each time"


def _chunks(blob):
    """Split a FAB2 blob into (header, [chunk bytes...])."""
    head, rest, out = blob[:20], blob[20:], []
    while rest:
        n = int.from_bytes(rest[:4], "big")
        out.append(rest[:5 + n])
        rest = rest[5 + n:]
    return head, out


def test_truncation_reorder_drop_and_swap_are_detected(cb, c, tmp_path):
    from cryptography.exceptions import InvalidTag
    data = os.urandom(3 * cb.CHUNK + 5)
    blob = cb.encrypt_bytes(data, c)
    head, ch = _chunks(blob)
    assert len(ch) == 4 and cb.decrypt_bytes(head + b"".join(ch), c) == data
    with pytest.raises(ValueError):
        cb.decrypt_bytes(head + b"".join(ch[:-1]), c)  # final chunk missing
    with pytest.raises(ValueError):
        cb.decrypt_bytes(blob[:-10], c)  # cut mid-chunk
    with pytest.raises(InvalidTag):
        cb.decrypt_bytes(head + b"".join([ch[1], ch[0], ch[2], ch[3]]), c)  # reordered
    with pytest.raises(InvalidTag):
        cb.decrypt_bytes(head + b"".join([ch[0], ch[2], ch[3]]), c)  # one dropped
    other = cb.encrypt_bytes(os.urandom(3 * cb.CHUNK + 5), c)
    _, och = _chunks(other)
    with pytest.raises(InvalidTag):
        cb.decrypt_bytes(head + b"".join([ch[0], och[1], ch[2], ch[3]]), c)  # chunk from another file
    flipped = bytearray(blob)
    flipped[40] ^= 1
    with pytest.raises(InvalidTag):
        cb.decrypt_bytes(bytes(flipped), c)
    with pytest.raises(ValueError):
        cb.decrypt_bytes(blob + b"x", c)  # trailing data


def test_wrong_passphrase_fails(cb, c):
    from cryptography.exceptions import InvalidTag
    blob = cb.encrypt_bytes(b"secret", c)
    with pytest.raises(InvalidTag):
        cb.decrypt_bytes(blob, cb.cipher("wrong", SALT))
    with pytest.raises(InvalidTag):
        cb.decrypt_bytes(blob, cb.cipher("correct horse battery staple", b"fedcba9876543210"))


def test_legacy_fab1_files_still_decrypt(cb, c, tmp_path):
    """Backups written by 0.4.0 to 0.12.0 (per-chunk Fernet, scrypt 2^15) restore with the new code."""
    from cryptography.fernet import Fernet
    f = Fernet(cb.derive_key("correct horse battery staple", SALT, version=1))
    data = os.urandom(cb.CHUNK + 100)
    legacy = b"FAB1"
    for i in range(0, len(data), cb.CHUNK):
        tok = f.encrypt(data[i:i + cb.CHUNK])
        legacy += len(tok).to_bytes(4, "big") + tok
    assert cb.decrypt_bytes(legacy, c) == data
    src = tmp_path / "legacy.enc"
    src.write_bytes(legacy)
    cb.decrypt_file(src, tmp_path / "legacy.out", c)
    assert (tmp_path / "legacy.out").read_bytes() == data
    with pytest.raises(Exception):
        cb.decrypt_bytes(legacy, cb.cipher("wrong", SALT))


def test_decrypt_file_leaves_no_partial_output_on_failure(cb, c, tmp_path):
    src = tmp_path / "bad.enc"
    src.write_bytes(cb.encrypt_bytes(b"x" * 100, c)[:-3])
    out = tmp_path / "out.bin"
    with pytest.raises(ValueError):
        cb.decrypt_file(src, out, c)
    assert not out.exists() and not list(tmp_path.glob("out.bin.*"))


def test_key_derivation_is_versioned(cb):
    k2 = cb.derive_key("pw", SALT)
    k1 = cb.derive_key("pw", SALT, version=1)
    assert len(k2) == 32 and k1 != k2 and cb.derive_key("pw", SALT) == k2


def test_store_passphrase_uses_the_secrets_file(root, cb, modules):
    cb.store_passphrase("file-pass-ZZ")
    try:
        assert cb.load_passphrase() == "file-pass-ZZ" or os.environ.get("MITRAHOME_BACKUP_PASSPHRASE")
        assert "file-pass-ZZ" in (root / "config" / "secrets.env").read_text(encoding="utf-8")
    finally:
        (root / "config" / "secrets.env").unlink(missing_ok=True)
