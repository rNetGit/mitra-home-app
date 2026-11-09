"""The Filter box on a Records part page (Papers & IDs > Filed papers): every word has to show up in the vendor, type,
date, notes or file name; the 300-row cap applies to the matches."""
import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from test_webapp import _login, web  # noqa: F401 (the web fixture)


def _papers(modules, rows):
    con = sqlite3.connect(modules("paths").DB)
    try:
        for path, typ, vendor, day, notes in rows:
            con.execute("INSERT INTO documents (filed_path, doc_type, vendor, doc_date, notes) VALUES (?,?,?,?,?)",
                        (path, typ, vendor, day, notes))
        con.commit()
    finally:
        con.close()


def test_filter_finds_papers_by_vendor_type_notes_and_file(web, modules):  # noqa: F811
    c, _, _ = web
    _login(c)
    rows = [(f"archive/2026/bills/2026-01-{i % 28 + 1:02d}_misc{i}_bill.pdf", "bill", f"Vendor{i}", f"2026-01-{i % 28 + 1:02d}", "")
            for i in range(8)]
    rows.append(("archive/2024/tax/2024-04-01_irs_return.pdf", "tax", "IRS", "2024-04-01", "federal return filed late"))
    _papers(modules, rows)
    page = c.get("/records?domain=papers&section=papers").text
    assert 'name="f"' in page and "Filter this list" in page
    hit = c.get("/records?domain=papers&section=papers&f=irs+tax").text
    assert "IRS" in hit and "Vendor3" not in hit and "1 of 9" in hit
    assert "IRS" in c.get("/records?domain=papers&section=papers&f=late").text, "words in the notes count"
    assert "IRS" in c.get("/records?domain=papers&section=papers&f=irs_return").text, "so does the file name"
    none = c.get("/records?domain=papers&section=papers&f=nomatchxyz").text
    assert "0 of 9" in none and "Vendor3" not in none
    assert "Vendor3" in c.get("/records?domain=papers&section=papers&f=vendor3").text
