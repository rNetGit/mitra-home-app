"""Export every table of data/family.db as plain files: for a spreadsheet, an accountant, or leaving Mitra Home.

  python data/export_data.py                         -> exports/YYYY-MM-DD_HHMM/<table>.csv + manifest.json + README.txt
  python data/export_data.py --format json|csv|both  --tables bills,transactions  --out DIR  --zip

The export is exactly what the database holds: last-4 identifiers, vendor names, amounts, dates. No AI is involved
and nothing is sent anywhere. The archived originals under archive/ are not copied (they are already plain files);
`documents.filed_path` points at them. config/*.json is already readable as it is.
The exports/ folder is git-ignored; it still holds the family's data, so move or delete it when done.

Saved links also go out as bookmarks.html (every browser's "import bookmarks" reads it), private ones included: the
export is the whole household's data.
Library: export(out=None, fmt="csv", tables=None, zip_it=False) -> (folder, {table: rows})
"""
import brand
import argparse
import csv
import datetime as dt
import json
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import db  # noqa: E402

ROOT = HERE.parent
DB = paths.DB


def version():
    try:
        return (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "?"


def table_names(con):
    # doc_search* is the archive search index (FTS5 and its shadow tables): derived from archive/, rebuilt by
    # `python data/archive_search.py index --rebuild`, so it is not exported.
    return [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                                      "AND name NOT LIKE 'doc_search%' ORDER BY name")]


def rows(con, table):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})") if r[1] != "amount_cents"]  # generated column
    sel = ", ".join(f'"{c}"' for c in cols)
    return cols, con.execute(f'SELECT {sel} FROM "{table}"').fetchall()


def export(out=None, fmt="csv", tables=None, zip_it=False, con=None):
    own = con is None
    con = con or db.connect(DB, readonly=True)
    stamp = dt.datetime.now()
    folder = pathlib.Path(out) if out else paths.EXPORTS / stamp.strftime("%Y-%m-%d_%H%M")
    folder.mkdir(parents=True, exist_ok=True)
    counts = {}
    try:
        names = table_names(con)
        if tables:
            unknown = [t for t in tables if t not in names]
            if unknown:
                raise SystemExit(f"unknown table(s): {', '.join(unknown)}. Tables: {', '.join(names)}")
            names = [t for t in names if t in tables]
        for t in names:
            cols, data = rows(con, t)
            counts[t] = len(data)
            if fmt in ("csv", "both"):
                with open(folder / f"{t}.csv", "w", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(cols)
                    w.writerows(data)
            if fmt in ("json", "both"):
                (folder / f"{t}.json").write_text(json.dumps([dict(zip(cols, r)) for r in data], indent=1, default=str),
                                                  encoding="utf-8")
            if t == "saved_items":
                import saved
                live = [dict(zip(cols, r)) for r in data]
                (folder / "bookmarks.html").write_text(saved.bookmarks_html([r for r in live if r.get("status") == "active"]),
                                                       encoding="utf-8")
    finally:
        if own:
            con.close()
    manifest = {"exported_at": stamp.isoformat(timespec="seconds"), "version": version(), "format": fmt,
                "database": DB.name, "tables": counts}
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (folder / "README.txt").write_text(
        f"{brand.PRODUCT} {manifest['version']} export, {manifest['exported_at']}\n\n"
        "One file per table, straight from the family database. Open the .csv files in any spreadsheet.\n"
        "Identifiers are last-4 digits only, as stored. Archived documents stay under archive/ (see documents.*).\n"
        "This folder holds your family's data: keep it as private as the database.\n", encoding="utf-8")
    if zip_it:
        z = shutil.make_archive(str(folder), "zip", root_dir=folder)
        return folder, counts, pathlib.Path(z)
    return folder, counts, None


def main():
    ap = argparse.ArgumentParser(description="Export every table as CSV/JSON.")
    ap.add_argument("--out", help="folder to write (default exports/<date_time>/)")
    ap.add_argument("--format", choices=["csv", "json", "both"], default="csv")
    ap.add_argument("--tables", help="comma-separated subset (default all)")
    ap.add_argument("--zip", action="store_true", help="also zip the folder")
    a = ap.parse_args()
    tables = [t.strip() for t in a.tables.split(",") if t.strip()] if a.tables else None
    folder, counts, z = export(a.out, a.format, tables, a.zip)
    try:
        shown = paths.rel(folder)
    except ValueError:
        shown = str(folder)
    print(f"export: {len(counts)} table(s), {sum(counts.values())} row(s) -> {shown}/" + (f"  and {z.name}" if z else ""))
    for t, n in counts.items():
        if n:
            print(f"  {t:<24} {n:>6}")


if __name__ == "__main__":
    main()
