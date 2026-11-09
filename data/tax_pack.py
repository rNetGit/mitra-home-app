"""A pack for the tax preparer: one zip per tax year with what they usually ask for.

  python data/tax_pack.py [YEAR]     -> exports/<YEAR>_tax_pack.zip  (default: last year)

Inside: README.txt, the tax-paper checklist (tax_prep.py), the year-end summary (year_end.py), the home-office figures
when there is a profile (home_office.py), and copies of that year's filed tax papers (documents of type tax, or filed
under a tax folder, dated or filed in that year), only from inside this install's archive. Records and arithmetic
only, not tax advice. Money > Look back > Tax papers offers it as a download (adults).
"""
import io
import pathlib
import sqlite3
import sys
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brand  # noqa: E402
import dates  # noqa: E402
import db  # noqa: E402
import paths  # noqa: E402
import records  # noqa: E402

MAX_BYTES = 150 * 1024 * 1024  # papers beyond this stay out of the zip (listed in README.txt)


def papers(con, year):
    """[(filed_path, file)] for the year's filed tax papers that exist on disk inside the archive."""
    ystr = str(year)
    rows = con.execute("SELECT filed_path, doc_date FROM documents WHERE doc_type='tax' OR LOWER(filed_path) LIKE '%tax%' "
                       "ORDER BY filed_path").fetchall()
    out = []
    for path, day in rows:
        if ystr not in str(path or "") and ystr not in str(day or ""):
            continue
        f = records.source_file(path)
        if f:
            out.append((path, f))
    return out


def build(con, year, today=None):
    """(file name, zip bytes)."""
    import tax_prep
    import year_end
    today = today or dates.today()
    buf = io.BytesIO()
    included, left_out = [], []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{year}_tax_checklist.md", tax_prep.build(con, year))
        z.writestr(f"{year}_year_end.md", year_end.build(con, year, today))
        try:
            import home_office
            if home_office._profile(con, year):
                z.writestr(f"{year}_home_office.md", home_office.report(con, year).read_text(encoding="utf-8"))
        except (ImportError, OSError, sqlite3.OperationalError):
            pass
        size, used = 0, set()
        for path, f in papers(con, year):
            n = f.stat().st_size
            if size + n > MAX_BYTES:
                left_out.append(path)
                continue
            name, k = f.name, 1
            while name in used:  # two papers with the same file name in different folders
                k += 1
                name = f"{f.stem}_{k}{f.suffix}"
            used.add(name)
            z.write(f, f"papers/{name}")
            size += n
            included.append(name)
        readme = [f"Tax papers for {year}, made by {brand.PRODUCT} on {today:%B %d, %Y}.", "",
                  f"{year}_tax_checklist.md   which expected forms are on file, and the year's tax-related totals",
                  f"{year}_year_end.md        the year in figures: income, spending by category, accounts",
                  f"{year}_home_office.md     home-office figures (only when a profile is on file)",
                  f"papers/                  copies of the year's filed tax papers ({len(included)})", ""]
        if left_out:
            readme += ["Too large to include (find them in the archive folder on the family PC):"] + [f"- {p}" for p in left_out] + [""]
        readme += ["These are the family's own records, added up. Nothing here is tax advice."]
        z.writestr("README.txt", "\n".join(readme) + "\n")
    return f"{year}_tax_pack.zip", buf.getvalue()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    year = int(argv[0]) if argv else dates.today().year - 1
    con = db.connect(paths.DB, readonly=True)
    try:
        name, body = build(con, year)
    finally:
        con.close()
    out = paths.EXPORTS / name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(body)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
