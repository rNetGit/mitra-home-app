"""iPhone photos (HEIC) turned into JPEG on this PC, so the family's AI can read them (receipt photos in the inbox, card
photos in the Wallet). The AI providers do not take HEIC; JPEG they all do.

  python data/heic.py                 says whether this PC can convert HEIC photos
  python data/heic.py FILE.heic       converts one (prints the JPEG size; nothing is written)

Optional: needs Pillow and pillow-heif (requirements.txt). Without them `available()` is False and a HEIC photo waits for
a person with a plain reason, as before. The JPEG is made in memory only (no temporary file to clean up): longest side
at most MAX_SIDE pixels, turned upright, and with no EXIF, so the phone's GPS position and camera details never leave
the PC. The HEIC itself is what gets filed in archive/.
"""
import io
import pathlib
import sys

MAX_SIDE = 2048  # pixels; plenty for a receipt or a card, and keeps the JPEG well under llm.PHOTO_MAX
QUALITY = 85
MAX_BYTES = 30 * 1024 * 1024  # a HEIC larger than this is not decoded
MISSING = "this PC cannot convert iPhone photos (HEIC) to JPG: Pillow and pillow-heif are not installed"


def _libs():
    """(PIL.Image, PIL.ImageOps, pillow_heif) or None when either package is missing or broken."""
    try:
        from PIL import Image, ImageOps
        import pillow_heif
    except Exception:  # ImportError, or a wheel that does not load on this PC
        return None
    return Image, ImageOps, pillow_heif


def available():
    """True when HEIC photos can be converted here."""
    return _libs() is not None


def to_jpeg(src):
    """JPEG bytes of a HEIC photo (`src` = a path or the HEIC bytes). Raises ValueError with a plain reason when it
    cannot: the packages are missing, the file is too big, or it is not a HEIC picture this PC can decode."""
    libs = _libs()
    if libs is None:
        raise ValueError(MISSING)
    Image, ImageOps, pillow_heif = libs
    data = src if isinstance(src, (bytes, bytearray)) else pathlib.Path(src).read_bytes()
    if len(data) > MAX_BYTES:
        raise ValueError(f"HEIC photo larger than {MAX_BYTES // (1024 * 1024)} MB")
    if bytes(data[4:8]) != b"ftyp":
        raise ValueError("not a HEIC photo")
    pillow_heif.register_heif_opener()
    try:
        with Image.open(io.BytesIO(bytes(data))) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            out = io.BytesIO()
            im.convert("RGB").save(out, "JPEG", quality=QUALITY)  # no exif= given: the JPEG carries none
    except Exception as e:  # damaged file, unknown brand, decompression-bomb guard
        raise ValueError(f"the HEIC photo could not be converted ({type(e).__name__})") from e
    return out.getvalue()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("HEIC photos: " + ("converted to JPG here" if available() else MISSING))
    else:
        try:
            print(f"JPEG {len(to_jpeg(sys.argv[1]))} bytes")
        except ValueError as e:
            sys.exit(f"Not converted: {e}")
