"""Ed25519 signature VERIFY only (RFC 8032 section 5.1.7), pure Python standard library.

Used by data/updater.py to check that a release's SHA256SUMS was signed by the maintainers' key before any code is
replaced. It must run before `pip install`, so it cannot use the `cryptography` package. Verification only: no secret
key ever touches this code, so constant-time arithmetic is not needed. Follows the RFC 8032 reference implementation;
tests/test_release_signing.py checks it against RFC 8032 test vectors and against `cryptography`.
"""
import hashlib

P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493  # order of the base point


def _inv(x):
    return pow(x, P - 2, P)


D = -121665 * _inv(121666) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % P
    B = (a[1] + a[0]) * (b[1] + b[0]) % P
    C = 2 * a[3] * b[3] * D % P
    Dd = 2 * a[2] * b[2] % P
    E, F, G, H = B - A, Dd - C, Dd + C, B + A
    return (E * F % P, G * H % P, F * G % P, E * H % P)


def _mul(s, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % P == 0 and (a[1] * b[2] - b[1] * a[2]) % P == 0


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * _inv(5) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    """True only for a valid Ed25519 signature of `message` by `public_key` (32 bytes). Never raises on bad input."""
    try:
        if len(public_key) != 32 or len(signature) != 64:
            return False
        a = _decompress(public_key)
        r = _decompress(signature[:32])
        if a is None or r is None:
            return False
        s = int.from_bytes(signature[32:], "little")
        if s >= L:
            return False
        h = int.from_bytes(hashlib.sha512(signature[:32] + public_key + message).digest(), "little") % L
        return _equal(_mul(s, G), _add(r, _mul(h, a)))
    except (TypeError, ValueError):
        return False
