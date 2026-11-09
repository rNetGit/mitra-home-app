"""Archive search (migration 035 + data/archive_search.py): masked full-text index of filed documents, only new or
changed files re-read, safe query building, path checks, adults only on the dashboard, `/find` in chat returns
titles and dates but never document text, export leaves the derived index out."""
import datetime as D
import os

import pytest

from conftest import db, q, run

NOW = D.datetime(2026, 10, 9, 9, 0, 0)
CARD = "4111 1111 1111 1234"


@pytest.fixture(scope="module")
def A(root, modules):
    return modules("archive_search")


@pytest.fixture(scope="module")
def docs(root):
    """Two filed text documents and one row whose file is gone."""
    arc = root / "archive" / "2026" / "utilities"
    arc.mkdir(parents=True, exist_ok=True)
    (arc / "2026-03-02_aquacity_bill.txt").write_text(
        f"AquaCity water service. Meter reading 4471. Paid with card {CARD}. Contact billing@aquacity.example\n" * 3,
        encoding="utf-8")
    (arc / "2026-04-11_zappower_bill.txt").write_text("ZapPower electricity statement for April, kilowatt hours 812.\n" * 3,
                                                       encoding="utf-8")
    c = db(root)
    ids = []
    for fp, typ, vendor, d in [("2026/utilities/2026-03-02_aquacity_bill.txt", "bill", "AquaCity", "2026-03-02"),
                               ("archive/2026/utilities/2026-04-11_zappower_bill.txt", "bill", "ZapPower", "2026-04-11"),
                               ("2026/utilities/2026-05-01_gone_bill.pdf", "bill", "Gone Co", "2026-05-01")]:
        ids.append(c.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES (?,?,?,?)",
                             (fp, typ, vendor, d)).lastrowid)
    c.commit()
    c.close()
    return ids


@pytest.fixture(scope="module")
def con(A, root, docs):
    c = A._db.connect(root / "data" / "family.db")
    A.index(c, archive=root / "archive")
    yield c
    c.close()


def test_tables_exist(root):
    names = {r[0] for r in q(root, "select name from sqlite_master where type='table'")}
    assert {"doc_search", "doc_search_state"} <= names


def test_index_masks_identifiers(con, docs):
    st = dict(con.execute("SELECT doc_id, status FROM doc_search_state").fetchall())
    assert st[docs[0]] == "ok" and st[docs[1]] == "ok" and st[docs[2]] == "missing"
    body = con.execute("SELECT body FROM doc_search WHERE rowid=?", (docs[0],)).fetchone()[0]
    assert "AquaCity water" in body and "1234" in body
    assert CARD not in body and CARD.replace(" ", "") not in body and "billing@aquacity.example" not in body


def test_search_words_prefix_and_ranking(A, con, docs):
    assert [h["id"] for h in A.search(con, "water meter")] == [docs[0]]
    assert [h["id"] for h in A.search(con, "kilowat")] == [docs[1]]  # prefix match
    assert [h["id"] for h in A.search(con, "gone")] == [docs[2]]  # missing file: still found by vendor / title
    assert A.search(con, "water kilowatt") == []  # every word must appear
    h = A.search(con, "zappower", snippets=True)[0]
    assert h["date"] == "2026-04-11" and h["type"] == "bill" and "[ZapPower]" in h["snippet"]


@pytest.mark.parametrize("words", ['water OR "x', "NEAR(water meter)", "body:water", "* - ^", "", "'''"])
def test_query_operators_never_reach_fts(A, con, words):
    A.search(con, words)  # never raises
    assert '"' not in A.match_expr(words).replace('"*', "").replace(' "', "").lstrip('"')


def test_only_changed_files_reread(A, con, root, docs):
    seen = []

    def ext(p):
        seen.append(p.name)
        import doc_text
        return doc_text.extract(p)
    c = A.index(con, archive=root / "archive", extract=ext)
    assert seen == [] and c["skipped"] == 3
    f = root / "archive" / "2026" / "utilities" / "2026-04-11_zappower_bill.txt"
    f.write_text("ZapPower electricity, now with solar credit.\n" * 3, encoding="utf-8")
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 5_000_000_000))
    A.index(con, archive=root / "archive", extract=ext)
    assert seen == ["2026-04-11_zappower_bill.txt"]
    assert [h["id"] for h in A.search(con, "solar")] == [docs[1]] and A.search(con, "kilowatt") == []


def test_removed_documents_leave_the_index(A, con, root):
    i = con.execute("INSERT INTO documents(filed_path, doc_type, vendor) VALUES ('2026/x/temp.txt','other','Tempco')").lastrowid
    con.commit()
    A.index(con, archive=root / "archive")
    assert A.search(con, "tempco")
    con.execute("DELETE FROM documents WHERE id=?", (i,))
    con.commit()
    assert A.index(con, archive=root / "archive")["removed"] == 1 and A.search(con, "tempco") == []


@pytest.mark.parametrize("fp", ["../secrets.env", "/etc/passwd", "C:/Windows/win.ini", "2026/../../config/x", "", None])
def test_resolve_stays_in_archive(A, root, fp):
    assert A.resolve(fp, root / "archive") is None


def test_chat_find_titles_only(root, modules, con):
    C = modules("chat_core")
    c = C._con(root / "data" / "family.db")
    try:
        for name, uid in (("Alex", "8801"), ("Sam", "8802")):
            code, *_ = C.invite(c, name, platform="telegram", now=NOW)
            C.handle("telegram", uid, f"/start {code}", db=root / "data" / "family.db", now=NOW)
    finally:
        c.close()

    def H(uid, text, private=True):
        return C.handle("telegram", uid, text, private=private, db=root / "data" / "family.db", now=NOW)
    r = H("8801", "/find water")
    assert "2026-03-02" in r and "aquacity bill" in r and "Meter" not in r and "1234" not in r
    assert "private chat" in H("8801", "/find water", private=False) and "aquacity" not in H("8801", "/find water", private=False)
    assert "adults" in H("8802", "/find water") and "aquacity" not in H("8802", "/find water")
    assert "No filed document" in H("8801", "/find nothinglikethis")
    assert "/find" in H("8801", "/help")
    assert not any("water" in str(r) for r in q(root, "select * from chat_log"))


def test_cli_and_export(root, con):
    r = run(["data/archive_search.py", "find", "water"], root)
    assert r.returncode == 0 and "AquaCity" in r.stdout
    r = run(["data/archive_search.py", "status"], root)
    assert r.returncode == 0 and "ok" in r.stdout
    r = run(["data/archive_search.py", "index", "--rebuild"], root)
    assert r.returncode == 0 and "ok" in r.stdout
    r = run(["data/export_data.py", "--out", str(root / "exports" / "t")], root)
    assert r.returncode == 0, r.stderr
    assert not any(p.name.startswith("doc_search") for p in (root / "exports" / "t").iterdir())
