"""Drive <-> Mitra Home sync (Google Drive for Desktop, G:\\My Drive\\MitraHome).

pull (also `sweep`): move files from Drive Inbox into local inbox/ (raw docs stay on this PC). Only document/image/sheet
  types, plain file names, size-capped, and only once they have stopped changing (no half-synced files). The Drive copy is
  removed only after the copy on this PC is verified; anything left behind is reported.
push: latest daily brief + latest weekly digest + latest monthly report -> Drive Brief/ as phone-sized PDFs (iPhone Drive can't open .md), plus the
  calendar file brief/mitrahome.ics and lists.pdf (open items on the family lists; adults-only lists left out, no file
  when nothing is open); older ones archived locally. config/family.json "drive": {"push": ["daily", "weekly",
  "monthly", "this_week", "ics", "lists", "saved"]} changes the list (default daily + weekly + monthly + ics + lists). "saved" (off unless
  listed) adds saved.pdf: the PINNED family saved items (links may be personal, so it is opt-in).
Usage: python data/sync_drive.py [pull|sweep|push|both]
"""
import shutil
import subprocess
import sys
import tempfile
import time
from html import escape as html_escape
from pathlib import Path

for _s in (sys.stdout, sys.stderr):  # filenames may hold chars cp1252 can't print (e.g. U+202F)
    _s.reconfigure(errors="replace")

ROOT = Path(__file__).resolve().parent.parent
import paths  # noqa: E402
import config  # noqa: E402
DRIVE = config.drive_path() or Path("DRIVE_NOT_CONFIGURED")
SKIP_SUFFIX = {".tmp", ".crdownload", ".gdoc", ".gsheet", ".gslides", ".gdraw", ".part", ".partial", ".download"}
SETTLE_SECONDS = 60  # a file changed more recently than this may still be syncing


def pull(drive=None, dst=None, settle=SETTLE_SECONDS):
    """Move settled files from <drive>/Inbox to dst. Returns (pulled_names, [(name, why left behind)])."""
    import inbox_upload as iu
    src = Path(drive or DRIVE) / "Inbox"
    dst = Path(dst or paths.INBOX)
    dst.mkdir(parents=True, exist_ok=True)
    src.mkdir(parents=True, exist_ok=True)
    pulled, left = [], []
    for f in sorted(src.iterdir()):
        name = f.name
        if name.startswith((".", "~")) or name.lower() == "desktop.ini" or f.suffix.lower() in SKIP_SUFFIX:
            continue  # sync bookkeeping, lock files and online-only Google docs: not ours to move
        if not f.is_file():
            left.append((name, "folders are not swept; put files directly in Inbox"))
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        if f.suffix.lower() not in iu.ALLOWED:
            left.append((name, f"{f.suffix or 'this'} type is not accepted"))
            continue
        if st.st_size == 0 or st.st_size > iu.MAX_BYTES:
            left.append((name, "empty or larger than the size limit"))
            continue
        if time.time() - st.st_mtime < settle:
            left.append((name, "still syncing; next sweep"))
            continue
        clean = iu.clean_name(name)
        target, i = dst / clean, 2
        while target.exists():
            target = dst / f"{Path(clean).stem}_{i}{Path(clean).suffix}"
            i += 1
        try:
            shutil.copy2(f, target)
            if target.stat().st_size != st.st_size:
                raise OSError("size mismatch after copy")
            try:
                f.unlink()  # copied and verified; Drive copy removed
            except OSError:
                target.unlink()  # could not remove the Drive copy: keep ONE copy (in Drive) and retry next sweep
                left.append((name, "Drive would not release the file; next sweep"))
                continue
        except OSError as e:
            target.unlink(missing_ok=True)
            left.append((name, f"copy failed ({e}); next sweep"))
            continue
        pulled.append(name)
        print(f"pulled {name}")
    for name, why in left:
        print(f"left in Drive: {name} ({why})")
    print(f"pull: {len(pulled)} file(s)")
    return pulled, left


EDGE = next((p for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                         r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if Path(p).exists()), None)
# Phone-sized pages (~95x180 mm) so text is readable without pinch-zoom; tables become cards.
CSS = ("@page{size:95mm 180mm;margin:5mm}"
       "body{font-family:Segoe UI,Arial,sans-serif;font-size:11pt;line-height:1.4;margin:0;color:#111;overflow-wrap:anywhere}"
       "h1{font-size:17pt;margin:0 0 6px}h2{font-size:14pt;margin:14px 0 6px;color:#0b5394;break-after:avoid}"
       "h3{font-size:12pt;margin:10px 0 4px}p{margin:4px 0}ul,ol{padding-left:18px;margin:4px 0}li{margin:4px 0}"
       "a{color:#0b5394}code{background:#eee;padding:0 2px}"
       ".card{border:1px solid #d0d0d0;border-left:4px solid #0b5394;border-radius:4px;padding:5px 7px;margin:5px 0;break-inside:avoid}"
       ".card.bad{border-left-color:#c0392b;background:#fdf1f0}"
       ".top{display:flex;justify-content:space-between;gap:8px;font-weight:600}"
       ".amt{white-space:nowrap}.meta{font-size:9.5pt;color:#555;margin-top:1px}")


def _cards(m):
    from html.parser import HTMLParser
    import re
    rows, cur, cell = [], None, None

    class P(HTMLParser):
        def handle_starttag(self, t, a):
            nonlocal cur, cell
            if t == "tr": cur = []
            elif t in ("td", "th"): cell = ""
            elif t == "a" and cell is not None:  # keep links inside cards
                href = dict(a).get("href") or ""
                ok = re.match(r"(?i)(https?://|mailto:)", href)  # the parser unescaped it: escape it again
                cell += f'<a href="{html_escape(href)}">' if ok else ""
        def handle_endtag(self, t):
            nonlocal cur, cell
            if t == "a" and cell is not None and "<a " in cell and not cell.endswith("</a>") and cell.count("<a ") > cell.count("</a>"):
                cell += "</a>"
            elif t in ("td", "th") and cell is not None: cur.append(cell.strip()); cell = None
            elif t == "tr" and cur is not None: rows.append(cur); cur = None
        def handle_data(self, d):
            nonlocal cell
            if cell is not None: cell += html_escape(d)
    P().feed(m.group(0))
    out = []
    hdr = rows[0] if rows else []
    for r in rows[1:]:
        cells = [c for c in r if c]
        if not cells: continue
        amt = next((c for c in cells if re.fullmatch(r"[-+]?\$[\d,.]+(\.\d+)?", c)), "")
        rest = [c for c in cells if c != amt]
        ti = next((i for i, h in enumerate(hdr) if h.lower() in ("item", "task", "description", "name") and i < len(r) and r[i]), None)
        title = r[ti] if ti is not None else (max(rest, key=len) if rest else amt)
        meta = " · ".join(c for c in rest if c != title)
        bad = any("OVERDUE" in c.upper() or "Due now" in c for c in cells)
        out.append(f'<div class="card{" bad" if bad else ""}"><div class="top"><span>{title}</span>'
                   f'<span class="amt">{amt}</span></div>' + (f'<div class="meta">{meta}</div>' if meta else "") + "</div>")
    return "".join(out)


PDF_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:"


def pdf_html(md_text):
    """The page Edge prints for a brief or list (markdown text -> one HTML document)."""
    import markdown
    import re
    # list items and notes are typed by anyone in the family (a child, a wall, a phone): escape them first so none of
    # it becomes a tag, and the page itself allows no script, no fetch and no frame while Edge prints it
    text = html_escape(md_text, quote=False)
    body = markdown.markdown(text, extensions=["tables", "sane_lists"])
    body = re.sub(r"<table>.*?</table>", _cards, body, flags=re.S)
    return (f'<!doctype html><meta charset=utf-8><meta http-equiv="Content-Security-Policy" content="{PDF_CSP}">'
            f"<style>{CSS}</style>{body}")


def md_to_pdf(md: Path, pdf: Path):
    html = pdf_html(md.read_text(encoding="utf-8"))
    pdf.unlink(missing_ok=True)  # an older copy must not pass for this one if Edge writes nothing
    with tempfile.TemporaryDirectory() as td:
        h = Path(td) / "doc.html"
        h.write_text(html, encoding="utf-8")
        # no --blink-settings=scriptEnabled=false: with it Edge exits 0 and writes no PDF (seen on the PC, 28 Oct);
        # the escaping and the page's CSP keep scripts out
        subprocess.run([EDGE, "--headless", "--disable-gpu", "--no-pdf-header-footer", f"--user-data-dir={td}",
                        f"--print-to-pdf={pdf}", h.as_uri()],
                       check=True, timeout=90, capture_output=True)
    if not pdf.exists() or not pdf.stat().st_size:
        raise RuntimeError("Edge finished but wrote no PDF")


def push():
    """Drive Brief/ keeps only the latest daily brief, weekly digest and monthly report (as PDFs); older ones go to local archive/old_drive_briefs/."""
    import re
    out = DRIVE / "Brief"
    out.mkdir(exist_ok=True)
    src = paths.BRIEF
    daily = sorted(f for f in src.glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", f.name))[-1:]
    want = (config.family().get("drive") or {}).get("push") or ["daily", "weekly", "monthly", "ics", "lists"]
    daily = daily if "daily" in want else []
    lists_md = []
    if "lists" in want:  # family lists' open items, rebuilt now (adults-only lists never go to Drive)
        try:
            import lists as _lists
            lists_md = [p for p in [_lists.write_brief()] if p]
        except Exception as e:  # older database without the lists tables
            print(f"lists brief skipped: {e}")
    if "saved" in want:  # opt-in: pinned family saved items (adults-only and private never go to Drive)
        try:
            import saved as _saved
            lists_md += [p for p in [_saved.write_brief()] if p]
        except Exception as e:
            print(f"saved brief skipped: {e}")
    weekly = (sorted(src.glob("*_weekly_digest.md"))[-1:] if "weekly" in want else []) + \
             (sorted(src.glob("*_this_week.md"))[-1:] if "this_week" in want else [])
    monthly = sorted(paths.REPORTS.glob("*_monthly.md"))[-1:] if "monthly" in want else []
    keep = set()
    n = 0
    for f in daily + weekly + monthly + lists_md:
        t = out / (f.stem + ".pdf")
        keep.add(t.name)
        if not t.exists() or f.stat().st_mtime > t.stat().st_mtime:
            try:
                md_to_pdf(f, t)
            except Exception as e:  # fall back to raw .md so nothing is lost
                print(f"pdf failed for {f.name}: {e}")
                shutil.copy2(f, out / f.name)
                keep.add(f.name)
            n += 1
    ics = src / "mitrahome.ics"
    if "ics" in want and ics.exists():  # one calendar file, overwritten in place: the phone's calendar app re-imports it
        t = out / ics.name
        keep.add(t.name)
        if not t.exists() or ics.stat().st_mtime > t.stat().st_mtime:
            shutil.copy2(ics, t)
            n += 1
    if "audio" in want:  # opt-in: the newest spoken brief (data/make_audio_brief.py)
        for f in sorted(src.glob("*_audio.wav"))[-1:]:
            t = out / f.name
            keep.add(t.name)
            if not t.exists() or f.stat().st_mtime > t.stat().st_mtime:
                shutil.copy2(f, t)
                n += 1
    arch = paths.ARCHIVE / "old_drive_briefs"
    arch.mkdir(parents=True, exist_ok=True)
    for old in out.iterdir():
        if old.is_file() and old.name not in keep and old.suffix.lower() in (".pdf", ".md", ".ics", ".wav"):
            shutil.move(str(old), str(arch / old.name))
            print(f"archived {old.name}")
    print(f"push: {n} file(s)")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"
    if config.drive_path() is None:
        sys.exit(0)  # phone sync is optional; nothing configured
    if not DRIVE.exists():
        sys.exit("Drive not mounted at " + str(DRIVE))
    if mode in ("pull", "sweep", "both"):
        pull()
    if mode in ("push", "both"):
        push()
