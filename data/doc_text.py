"""Text extraction for the Python intake pipeline.

  python data/doc_text.py FILE        print extracted text (first 2000 chars) and the status

Returns (text, status) with status: ok | scanned (no text layer: needs OCR or a Claude agent) | unsupported | error.
Plain text/CSV/Markdown/JSON/HTML/EML are read directly; PDFs use `pypdf` if installed (pip install pypdf), else the
`pdftotext` tool if present. Images are not read here (use the Claude intake agent, which can view images).
"""
import html
import pathlib
import re
import shutil
import subprocess
import sys

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".eml", ".log", ".tsv"}
MIN_CHARS = 40


def extract(path):
    p = pathlib.Path(path)
    ext = p.suffix.lower()
    try:
        if ext in TEXT_EXT:
            return p.read_text(encoding="utf-8", errors="replace"), "ok"
        if ext in (".htm", ".html"):
            t = re.sub(r"(?is)<(script|style).*?</\1>", " ", p.read_text(encoding="utf-8", errors="replace"))
            return html.unescape(re.sub(r"<[^>]+>", " ", t)), "ok"
        if ext == ".pdf":
            text = ""
            try:
                from pypdf import PdfReader
                text = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
            except ImportError:
                if shutil.which("pdftotext"):
                    text = subprocess.run(["pdftotext", "-layout", str(p), "-"], capture_output=True, text=True, timeout=60).stdout
                else:
                    return "", "unsupported"
            return text, ("ok" if len(text.strip()) >= MIN_CHARS else "scanned")
        return "", "unsupported"
    except Exception:
        return "", "error"


if __name__ == "__main__":
    t, s = extract(sys.argv[1])
    print(s, len(t))
    print(t[:2000])
