"""Work S5: the paperwork of a job (work_papers, migration 068): attach a filed paper, upload one, imported timesheets link
themselves, remove a link without losing the paper, private jobs stay private."""
import datetime as D

import pytest
from conftest import db, q

ADULT = {"name": "Alex", "role": "adult"}
OTHER = {"name": "Bo", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


@pytest.fixture(autouse=True)
def _clean(root, modules):
    modules("edit_actions")
    with db(root) as con:
        for t in ("work_papers", "work_match_rules", "work_hours", "contracts"):
            con.execute(f"DELETE FROM {t}")
    yield


def _job(ea, root, name="Acme Corp"):
    ok, msg = ea.work_contract_add(ADULT, name, None, None, "Alex", None, None, None, "employment", "primary", True)
    assert ok, msg
    return q(root, "SELECT id FROM contracts WHERE client=?", name)[0][0]


def _doc(root, name="offer.pdf"):
    with db(root) as con:
        cur = con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES (?, 'other', 'Acme', '2026-01-05')",
                          (f"archive/2026/other/{name}",))
        return cur.lastrowid


def test_attach_list_and_remove_without_losing_the_paper(root, modules):
    ea, W = modules("edit_actions"), modules("work")
    cid, doc = _job(ea, root), _doc(root)
    assert ea.work_paper_attach(KID, cid, doc, "offer_letter")[0] is False
    assert ea.work_paper_attach(ADULT, cid, doc, "bogus")[0] is False
    assert ea.work_paper_attach(ADULT, cid, 99999, "contract")[0] is False, "no such paper"
    assert ea.work_paper_attach(ADULT, 99999, doc, "contract")[0] is False, "no such job"
    ok, msg = ea.work_paper_attach(ADULT, cid, doc, "offer_letter")
    assert ok, msg
    assert ea.work_paper_attach(ADULT, cid, doc, "contract")[0], "again = change the kind"
    con = db(root)
    rows = W.papers(con, cid)
    assert [(r["document"], r["kind"], r["name"]) for r in rows] == [(doc, "contract", "offer.pdf")]
    assert W.paper_choices(con, cid) == [], "an attached paper is not offered again"
    con.close()
    assert ea.work_paper_remove(ADULT, cid, doc)[0]
    assert ea.work_paper_remove(ADULT, cid, doc)[0] is False
    assert q(root, "SELECT COUNT(*) FROM documents WHERE id=?", doc) == [(1,)], "the paper stays filed"


def test_uploaded_paper_is_filed_and_kept_and_a_timesheet_links_itself(root, modules):
    ea, paths = modules("edit_actions"), modules("paths")
    cid = _job(ea, root)
    f = paths.INBOX / "w2_2025.txt"
    f.write_text("W-2 copy placeholder\n", encoding="utf-8")
    ok, msg = ea.work_paper_upload(ADULT, f.name, cid, "w2")
    assert ok, msg
    assert q(root, "SELECT p.kind, d.doc_type, d.vendor FROM work_papers p JOIN documents d ON d.id=p.document_id") == [("w2", "tax", "Acme Corp W-2")]
    assert not f.exists(), "the original moved into the archive"
    day = D.date.today().replace(day=1)
    t = paths.INBOX / "march.csv"
    t.write_text(f"Date,Hours\n{day:%m/%d/%Y},6\n", encoding="utf-8")
    ok, msg = ea.work_import(ADULT, t.name, "timesheet", contract_id=cid)
    assert ok, msg
    assert q(root, "SELECT kind FROM work_papers ORDER BY id") == [("w2",), ("timesheet",)], "an imported timesheet is kept by itself"


def test_private_job_papers_are_guarded(root, modules):
    ea, wd = modules("edit_actions"), modules("work_data")
    wd.on = lambda: True
    cid = _job(ea, root)
    doc = _doc(root)
    ea.work_profile(ADULT, cid, visibility="private")
    ok, msg = wd.act(OTHER, "paper_attach", {"c": str(cid), "document": str(doc), "kind": "contract"})
    assert (ok, msg) == (False, "That job is private to its owner.")
    ok, msg = wd.act(ADULT, "paper_attach", {"c": str(cid), "document": str(doc), "kind": "contract"})
    assert ok, msg
    assert wd.view(ADULT, {"c": str(cid), "tab": "papers"})["papers"]["rows"][0]["document"] == doc
    assert wd.view(OTHER, {"c": str(cid), "tab": "papers"})["c"] is None or wd.view(OTHER, {"c": str(cid), "tab": "papers"})["c"]["id"] != cid
