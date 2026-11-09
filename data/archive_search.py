"""Archive search: find any filed document by the words in it, on this PC, with no AI.

  python data/archive_search.py index [--rebuild]     read new or changed files under archive/ into the index
  python data/archive_search.py find WORDS...         title, date, type and vendor of the best matches (adults)
  python data/archive_search.py status                how many documents are indexed, scanned, missing

The text comes from the same extractor intake uses (data/doc_text.py) and is masked before it is stored
(data/pii.py: full account/card numbers, SSNs, emails and phone numbers become placeholders), so the index holds
nothing the documents table would not. Scans and photos have no text layer: they are found by vendor, type and file
name only. The daily task and every inbox check run `index`; it only reads files that are new or changed.
Search is for adults: children never see archive results on the dashboard or in chat.
"""
import argparse
import datetime as dt
import pathlib
import re
import sqlite3
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import db as _db  # noqa: E402

DB = paths.DB
ARCHIVE = paths.ARCHIVE
MAX_BODY = 200_000  # characters stored per document
_WORD = re.compile(r"[\w'-]+", re.UNICODE)


def resolve(filed_path, archive=None):
    """documents.filed_path is relative to archive/ (intake) but older rows may start with 'archive/'."""
    archive = pathlib.Path(archive or ARCHIVE)
    p = pathlib.PurePosixPath(str(filed_path or "").replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not p.parts or ":" in p.parts[0]:
        return None
    if p.parts[0] == "archive":
        p = pathlib.PurePosixPath(*p.parts[1:]) if len(p.parts) > 1 else None
    return archive.joinpath(*p.parts) if p else None


def _key(f):
    s = f.stat()
    return f"{s.st_size}:{s.st_mtime_ns}"


def _title(filed_path):
    return pathlib.PurePosixPath(str(filed_path or "").replace("\\", "/")).stem.replace("_", " ")


def _masker():
    import pii
    return pii.redactor().redact  # built once per run: reads the household's names once


def index(con, archive=None, rebuild=False, extract=None, mask=None):
    """Bring the index up to date. Returns counts by status (plus 'skipped' for unchanged, 'removed' for deleted rows)."""
    if extract is None:
        import doc_text
        extract = doc_text.extract
    mask = mask or _masker()
    if rebuild:
        con.execute("DELETE FROM doc_search")
        con.execute("DELETE FROM doc_search_state")
    state = {r[0]: r[1] for r in con.execute("SELECT doc_id, file_key FROM doc_search_state")}
    docs = con.execute("SELECT id, filed_path, doc_type, vendor FROM documents").fetchall()
    counts = {"skipped": 0, "removed": 0}
    now = dt.datetime.now().isoformat(timespec="seconds")
    seen = set()
    for doc_id, fp, typ, vendor in docs:
        seen.add(doc_id)
        f = resolve(fp, archive)
        key = _key(f) if f and f.is_file() else None
        if doc_id in state and state[doc_id] == key:
            counts["skipped"] += 1
            continue
        body, status = "", "missing"
        if key:
            text, status = extract(f)
            if status == "ok":
                body = mask(text)[:MAX_BODY]
        con.execute("DELETE FROM doc_search WHERE rowid=?", (doc_id,))
        con.execute("INSERT INTO doc_search(rowid, title, vendor, doc_type, body) VALUES (?,?,?,?,?)",
                    (doc_id, _title(fp), vendor or "", typ or "", body))
        con.execute("INSERT OR REPLACE INTO doc_search_state(doc_id, file_key, status, chars, indexed_at) VALUES (?,?,?,?,?)",
                    (doc_id, key, status, len(body), now))
        counts[status] = counts.get(status, 0) + 1
    for gone in set(state) - seen:
        con.execute("DELETE FROM doc_search WHERE rowid=?", (gone,))
        con.execute("DELETE FROM doc_search_state WHERE doc_id=?", (gone,))
        counts["removed"] += 1
    con.commit()
    return counts


def match_expr(words):
    """Plain words -> a safe FTS5 query: every word must appear (prefix match), FTS operators are never passed through."""
    toks = [t.strip("'-") for t in _WORD.findall(words or "")]
    toks = [t for t in toks if t][:12]
    return " ".join(f'"{t}"*' for t in toks)


def search(con, words, limit=20, snippets=False):
    """Best matches first: list of dicts id, title, date, type, vendor, path (and snippet when asked)."""
    expr = match_expr(words)
    if not expr:
        return []
    snip = ", snippet(doc_search, 3, '[', ']', ' ... ', 12)" if snippets else ""
    try:
        rows = con.execute(
            f"SELECT d.id, s.title, d.doc_date, d.doc_type, d.vendor, d.filed_path{snip} FROM doc_search s "
            "JOIN documents d ON d.id = s.rowid WHERE doc_search MATCH ? ORDER BY bm25(doc_search, 5.0, 3.0, 2.0, 1.0), "
            "d.doc_date DESC LIMIT ?", (expr, int(limit))).fetchall()
    except sqlite3.OperationalError:
        return []
    out = []
    for r in rows:
        d = {"id": r[0], "title": r[1], "date": r[2] or "", "type": r[3] or "", "vendor": r[4] or "", "path": r[5]}
        if snippets:
            d["snippet"] = r[6] or ""
        out.append(d)
    return out


def status(con):
    rows = dict(con.execute("SELECT status, COUNT(*) FROM doc_search_state GROUP BY status").fetchall())
    total = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    rows["not yet indexed"] = total - sum(rows.values())
    return total, rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("--rebuild", action="store_true", help="forget the index and read every file again")
    p = sub.add_parser("find")
    p.add_argument("words", nargs="+")
    p.add_argument("--limit", type=int, default=20)
    sub.add_parser("status")
    a = ap.parse_args(argv)
    con = _db.connect(DB)
    try:
        if a.cmd == "index":
            c = index(con, rebuild=a.rebuild)
            print("archive index: " + ", ".join(f"{k} {v}" for k, v in sorted(c.items()) if v) if any(c.values())
                  else "archive index: nothing to do")
            if c.get("scanned"):
                print(f"{c['scanned']} scan(s)/photo(s) have no text: found by vendor, type and file name only.")
        elif a.cmd == "find":
            hits = search(con, " ".join(a.words), a.limit, snippets=True)
            for h in hits:
                print(f"{h['date']:<10}  {h['type']:<10} {h['vendor'][:20]:<20} {h['title']}")
                if h["snippet"]:
                    print(f"            {h['snippet']}")
            if not hits:
                print("no filed document matches (run `index` if files were added by hand)")
        else:
            total, rows = status(con)
            print(f"{total} filed document(s): " + ", ".join(f"{k} {v}" for k, v in sorted(rows.items()) if v))
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
