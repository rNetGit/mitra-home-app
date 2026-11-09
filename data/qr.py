"""QR codes without a third-party library (standard library only), for the phone pairing code in Settings > Phones.

  import qr
  m = qr.encode(b"hello")            # list of rows of bools (True = dark), no quiet zone
  svg = qr.svg("hello")              # an SVG document, black on white, 4-module quiet zone
  uri = qr.data_uri("hello")         # data:image/svg+xml;base64,... (the app's CSP allows img data: only)

Byte mode, versions 1 to 40, error correction L / M / Q / H (default M), mask chosen by the standard penalty rules.
The algorithm follows ISO/IEC 18004 as laid out by Project Nayuki's QR Code generator (MIT).
"""
import base64

# error correction level -> (format bits, index into the tables below)
ECL = {"L": (1, 0), "M": (0, 1), "Q": (3, 2), "H": (2, 3)}
ECC_PER_BLOCK = (
    (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28,
     28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30,
     30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
)
NUM_BLOCKS = (
    (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19,
     20, 21, 22, 24, 25),
    (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35,
     37, 38, 40, 43, 45, 47, 49),
    (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45,
     48, 51, 53, 56, 59, 62, 65, 68),
    (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54,
     57, 60, 63, 66, 70, 74, 77, 81),
)
MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


# ---- capacity --------------------------------------------------------------------------------------------------------
def raw_modules(ver):
    """Data + error correction modules of a version (everything but the function patterns)."""
    n = (16 * ver + 128) * ver + 64
    if ver >= 2:
        k = ver // 7 + 2
        n -= (25 * k - 10) * k - 55
        if ver >= 7:
            n -= 36
    return n


def data_codewords(ver, ecl="M"):
    i = ECL[ecl][1]
    return raw_modules(ver) // 8 - ECC_PER_BLOCK[i][ver] * NUM_BLOCKS[i][ver]


def _count_bits(ver):
    return 8 if ver <= 9 else 16


def capacity(ver, ecl="M"):
    """How many bytes fit in byte mode."""
    return (data_codewords(ver, ecl) * 8 - 4 - _count_bits(ver)) // 8


# ---- Reed-Solomon over GF(256), polynomial 0x11D ----------------------------------------------------------------------
def _mul(x, y):
    z = 0
    for i in reversed(range(8)):
        z = (z << 1) ^ ((z >> 7) * 0x11D)
        z ^= ((y >> i) & 1) * x
    return z


def _divisor(degree):
    out = [0] * (degree - 1) + [1]
    root = 1
    for _ in range(degree):
        for j in range(degree):
            out[j] = _mul(out[j], root)
            if j + 1 < degree:
                out[j] ^= out[j + 1]
        root = _mul(root, 0x02)
    return out


def _remainder(data, divisor):
    out = [0] * len(divisor)
    for b in data:
        factor = b ^ out.pop(0)
        out.append(0)
        for i, coef in enumerate(divisor):
            out[i] ^= _mul(coef, factor)
    return out


# ---- encoding ---------------------------------------------------------------------------------------------------------
def _codewords(data, ver, ecl):
    """Data bits -> padded data codewords -> blocks with error correction, interleaved."""
    bits = []

    def put(val, n):
        bits.extend((val >> i) & 1 for i in reversed(range(n)))

    put(0b0100, 4)
    put(len(data), _count_bits(ver))
    for b in data:
        put(b, 8)
    cap = data_codewords(ver, ecl) * 8
    put(0, min(4, cap - len(bits)))
    put(0, -len(bits) % 8)
    pad = 0xEC
    while len(bits) < cap:
        put(pad, 8)
        pad ^= 0xEC ^ 0x11
    words = [int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8)]

    i = ECL[ecl][1]
    nblocks, ecc_len = NUM_BLOCKS[i][ver], ECC_PER_BLOCK[i][ver]
    raw = raw_modules(ver) // 8
    nshort = nblocks - raw % nblocks
    short_len = raw // nblocks
    div = _divisor(ecc_len)
    blocks, k = [], 0
    for b in range(nblocks):
        n = short_len - ecc_len + (0 if b < nshort else 1)
        dat = words[k:k + n]
        k += n
        ecc = _remainder(dat, div)
        if b < nshort:
            dat = dat + [0]  # placeholder, skipped when interleaving
        blocks.append(dat + ecc)
    out = []
    for col in range(len(blocks[0])):
        for b, blk in enumerate(blocks):
            if col != short_len - ecc_len or b >= nshort:
                out.append(blk[col])
    assert len(out) == raw
    return out


class _Grid:
    def __init__(self, ver):
        self.ver = ver
        self.size = ver * 4 + 17
        self.mod = [[False] * self.size for _ in range(self.size)]
        self.fn = [[False] * self.size for _ in range(self.size)]

    def set_fn(self, x, y, dark):
        self.mod[y][x] = dark
        self.fn[y][x] = True

    def align_positions(self):
        if self.ver == 1:
            return []
        k = self.ver // 7 + 2
        step = (self.ver * 8 + k * 3 + 5) // (k * 4 - 4) * 2
        return [6] + list(reversed([self.size - 7 - i * step for i in range(k - 1)]))

    def draw_function_patterns(self):
        s = self.size
        for i in range(s):
            self.set_fn(6, i, i % 2 == 0)
            self.set_fn(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (s - 4, 3), (3, s - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < s and 0 <= y < s:
                        self.set_fn(x, y, max(abs(dx), abs(dy)) not in (2, 4))
        pos = self.align_positions()
        n = len(pos)
        for i in range(n):
            for j in range(n):
                if (i, j) in ((0, 0), (0, n - 1), (n - 1, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self.set_fn(pos[i] + dx, pos[j] + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0, 0)  # reserve the area; the real bits come after masking
        if self.ver >= 7:
            rem = self.ver
            for _ in range(12):
                rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
            bits = self.ver << 12 | rem
            for i in range(18):
                dark = (bits >> i) & 1 == 1
                a, b = s - 11 + i % 3, i // 3
                self.set_fn(a, b, dark)
                self.set_fn(b, a, dark)

    def draw_format(self, ecl_bits, mask):
        data = ecl_bits << 3 | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = (data << 10 | rem) ^ 0x5412

        def bit(i):
            return (bits >> i) & 1 == 1

        s = self.size
        for i in range(6):
            self.set_fn(8, i, bit(i))
        self.set_fn(8, 7, bit(6))
        self.set_fn(8, 8, bit(7))
        self.set_fn(7, 8, bit(8))
        for i in range(9, 15):
            self.set_fn(14 - i, 8, bit(i))
        for i in range(8):
            self.set_fn(s - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self.set_fn(8, s - 15 + i, bit(i))
        self.set_fn(8, s - 8, True)  # the dark module

    def draw_codewords(self, words):
        s, i, total = self.size, 0, len(words) * 8
        right = s - 1
        while right >= 1:
            if right == 6:
                right = 5
            for vert in range(s):
                for j in range(2):
                    x = right - j
                    up = ((right + 1) & 2) == 0
                    y = s - 1 - vert if up else vert
                    if not self.fn[y][x] and i < total:
                        self.mod[y][x] = (words[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, m):
        f = MASKS[m]
        for y in range(self.size):
            for x in range(self.size):
                if not self.fn[y][x] and f(x, y):
                    self.mod[y][x] = not self.mod[y][x]


def penalty(mod):
    """The four penalty rules of ISO/IEC 18004 (lower = easier to scan)."""
    s = len(mod)
    score = 0
    lines = [row for row in mod] + [[mod[y][x] for y in range(s)] for x in range(s)]
    finder = ([True, False, True, True, True, False, True, False, False, False, False],
              [False, False, False, False, True, False, True, True, True, False, True])
    for line in lines:
        run, prev = 0, None
        for v in line:
            if v == prev:
                run += 1
            else:
                if run >= 5:
                    score += run - 2
                run, prev = 1, v
        if run >= 5:
            score += run - 2
        padded = [False] * 4 + list(line) + [False] * 4
        for i in range(len(padded) - 10):
            if padded[i:i + 11] in finder:
                score += 40
    for y in range(s - 1):
        for x in range(s - 1):
            c = mod[y][x]
            if c == mod[y][x + 1] == mod[y + 1][x] == mod[y + 1][x + 1]:
                score += 3
    dark = sum(sum(r) for r in mod)
    total = s * s
    k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
    return score + max(k, 0) * 10


def encode(data, ecl="M", version=None, mask=None):
    """-> rows of bools (True = dark). `data` = bytes or str (UTF-8). `version` / `mask` force a choice (tests)."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    if ecl not in ECL:
        raise ValueError("ecl must be L, M, Q or H")
    if version is None:
        version = next((v for v in range(1, 41) if capacity(v, ecl) >= len(data)), None)
        if version is None:
            raise ValueError("too long for a QR code")
    elif capacity(version, ecl) < len(data):
        raise ValueError("too long for this version")
    words = _codewords(data, version, ecl)
    g = _Grid(version)
    g.draw_function_patterns()
    g.draw_codewords(words)
    ecl_bits = ECL[ecl][0]
    if mask is None:
        best = None
        for m in range(8):
            g.apply_mask(m)
            g.draw_format(ecl_bits, m)
            p = penalty(g.mod)
            if best is None or p < best[0]:
                best = (p, m)
            g.apply_mask(m)  # XOR again = undo
        mask = best[1]
    g.apply_mask(mask)
    g.draw_format(ecl_bits, mask)
    return g.mod


def svg(data, ecl="M", border=4):
    """An SVG document (black on white, also in the dark theme: scanners need dark on light)."""
    m = encode(data, ecl)
    n = len(m) + 2 * border
    path = "".join(f"M{x + border},{y + border}h1v1h-1z" for y, row in enumerate(m) for x, v in enumerate(row) if v)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" shape-rendering="crispEdges">'
            f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>')


def data_uri(data, ecl="M"):
    return "data:image/svg+xml;base64," + base64.b64encode(svg(data, ecl).encode("ascii")).decode("ascii")
