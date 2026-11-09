"""Safe file drop for the dashboard: saves an uploaded document into inbox/ (no Drive needed).

  python data/inbox_upload.py FILE [FILE ...]     copy files into inbox/ using the same checks

Checks: only document/image/spreadsheet types, size cap, the name is reduced to a plain file name (no folders, no
leading dots), and an existing file is never overwritten. Nothing is opened, run or sent anywhere here.
"""
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
import paths  # noqa: E402
ALLOWED = {".pdf", ".png", ".jpg", ".jpeg", ".heic", ".tif", ".tiff", ".webp", ".csv", ".txt", ".xlsx", ".xls",
           ".docx", ".doc", ".eml", ".ofx", ".qfx"}
MAX_BYTES = 25 * 1024 * 1024
SNIFF = {  # extension -> accepted leading bytes (the content must match the name)
    ".pdf": (b"%PDF",), ".png": (b"\x89PNG",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
    ".webp": (b"RIFF",), ".tif": (b"II*\x00", b"MM\x00*"), ".tiff": (b"II*\x00", b"MM\x00*"),
    ".xlsx": (b"PK\x03\x04",), ".docx": (b"PK\x03\x04",), ".xls": (b"\xd0\xcf\x11\xe0",),
    ".doc": (b"\xd0\xcf\x11\xe0",),
}
NEVER = (b"mz", b"\x7felf", b"#!", b"<script", b"<html", b"<!doctype", b"<?php")  # programs and web pages, any name


def content_ok(fname, data):
    """True when the bytes look like what the file name says (and never like a program or web page)."""
    head = bytes(data[:16])
    probe = bytes(data[:64])
    for bom in (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff"):  # a BOM or blank lines must not hide a web page or program
        if probe.startswith(bom):
            probe = probe[len(bom):]
            break
    probe = probe.replace(b"\x00", b"").lstrip()
    if any(head.lower().startswith(n) or probe.lower().startswith(n) for n in NEVER):
        return False
    ext = pathlib.Path(fname).suffix.lower()
    if ext == ".heic":
        return head[4:8] == b"ftyp"
    return ext not in SNIFF or any(head.startswith(m) for m in SNIFF[ext])


def clean_name(name):
    base = os.path.basename(str(name).replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._ ()-]", "_", base).lstrip(". ")
    stem, ext = os.path.splitext(base)
    return (stem[:100].rstrip() or "document") + ext.lower()


def save_upload(name, data, inbox=None):
    """Returns (ok, message). On success the message is the saved file name."""
    inbox = pathlib.Path(inbox) if inbox else paths.INBOX
    fname = clean_name(name)
    ext = os.path.splitext(fname)[1]
    if ext not in ALLOWED:
        return False, f"{ext or 'this'} files are not accepted (allowed: {', '.join(sorted(ALLOWED))})"
    if not data:
        return False, "the file is empty"
    if len(data) > MAX_BYTES:
        return False, f"too large ({len(data) // (1024 * 1024)} MB; limit {MAX_BYTES // (1024 * 1024)} MB)"
    inbox.mkdir(parents=True, exist_ok=True)
    stem = os.path.splitext(fname)[0]
    target, n = inbox / fname, 1
    while True:  # exclusive create: two uploads at once can never overwrite each other
        try:
            fh = open(target, "xb")
        except FileExistsError:
            n += 1
            target = inbox / f"{stem}_{n}{ext}"
            continue
        except OSError:
            return False, "the file could not be saved"
        try:
            with fh:
                fh.write(data)
            return True, target.name
        except OSError:
            target.unlink(missing_ok=True)  # never leave half a file behind (disk full)
            return False, "the file could not be saved (is the disk full?)"


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        p = pathlib.Path(arg)
        ok, msg = save_upload(p.name, p.read_bytes()) if p.is_file() else (False, "not a file")
        print(f"{'saved ' if ok else 'REFUSED '}{p.name}: {msg}")
