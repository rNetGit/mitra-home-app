"""0.98: the last classic-only screens in the web app. Inventory receipt / manual links, budget suggestions and
allowance lines, downloads (tax checklist, card transactions CSV, briefings), Settings extras (optional packs, tax
papers, reminder lead times, Advanced) and the work page (contracts, invoices, hours, schedule, profile, work calendar,
timesheet import). Adults only, CSRF on every change."""
import datetime as dt
import json
import re
import sqlite3

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def web(root, modules):
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    fam = dict(config.family())
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    return c, t


def _post(client_, path_, csrf_, **d):
    return client_.post(path_, data=d, headers={"X-CSRF-Token": csrf_})


def _sql(modules, sql, *params):
    con = sqlite3.connect(modules("paths").DB)
    try:
        with con:
            cur = con.execute(sql, params)
            return cur.lastrowid if sql.lstrip().upper().startswith("INSERT") else cur.fetchall()
    finally:
        con.close()


def test_inventory_receipt_and_manual_links(web, modules):
    c, t = web
    rec = _sql(modules, "INSERT INTO documents(doc_date, vendor, doc_type, filed_path) VALUES ('2026-01-02', 'Store', 'receipt', 'x.pdf')")
    man = _sql(modules, "INSERT INTO documents(doc_date, vendor, doc_type, filed_path) VALUES ('2026-01-03', 'Maker', 'manual', 'm.pdf')")
    stmt = _sql(modules, "INSERT INTO documents(doc_date, vendor, doc_type, filed_path) VALUES ('2026-01-04', 'Bank', 'statement', 's.pdf')")
    _post(c, "/records/add", t, part="home/inventory", name="Washer", category="appliance")
    aid = _sql(modules, "SELECT id FROM home_assets WHERE name='Washer'")[0][0]
    page = c.get(f"/records?ref=home_assets:{aid}").text
    assert "Receipt and manual" in page and f'value="{rec}"' in page and f'value="{stmt}"' not in page
    r = _post(c, "/records/edit", t, table="home_assets", id=str(aid), op="papers", receipt=str(stmt), manual="")
    assert "Pick the paper from the list" in r.text, "a statement is not a receipt"
    r = _post(c, "/records/edit", t, table="home_assets", id=str(aid), op="papers", receipt=str(rec), manual=str(man))
    assert "hx-redirect" in r.headers
    assert _sql(modules, "SELECT receipt_document_id, manual_document_id FROM home_assets WHERE id=?", aid) == [(rec, man)]
    _post(c, "/records/edit", t, table="home_assets", id=str(aid), op="papers", receipt="", manual=str(man))
    assert _sql(modules, "SELECT receipt_document_id FROM home_assets WHERE id=?", aid) == [(None,)]


def test_budget_suggestions_allowances_and_downloads(web, modules):
    c, t = web
    page = c.get("/money?part=budget").text
    assert "Suggested limits from the last six full months" in page and 'value="allowance:Sam"' in page
    r = c.get("/money/download?part=tax&year=2026")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown") and "2026_tax_prep.md" in r.headers["content-disposition"]
    # the pack for the tax preparer: checklist, year-end, and the year's filed tax papers from inside the archive only
    import io
    import zipfile
    paths = modules("paths")
    w2 = paths.ARCHIVE / "2026" / "tax" / "2026-01-30_acme_w2.pdf"
    w2.parent.mkdir(parents=True, exist_ok=True)
    w2.write_bytes(b"%PDF-1.4 w2")
    _sql(modules, "INSERT INTO documents (filed_path, doc_type, vendor, doc_date) VALUES (?, 'tax', 'Acme', '2026-01-30')",
         str(w2.relative_to(paths.HOME)))
    _sql(modules, "INSERT INTO documents (filed_path, doc_type, vendor, doc_date) VALUES ('../config/family.json', 'tax', 'x', '2026-02-01')")
    _sql(modules, "INSERT INTO documents (filed_path, doc_type, vendor, doc_date) VALUES ('archive/2025/tax/old_1099.pdf', 'tax', 'y', '2025-02-01')")
    assert "pack=1" in c.get("/money?part=tax&year=2026").text
    r = c.get("/money/download?part=tax&year=2026&pack=1")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip" and "2026_tax_pack.zip" in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert {"README.txt", "2026_tax_checklist.md", "2026_year_end.md", "papers/2026-01-30_acme_w2.pdf"} <= set(names)
    assert not any("family.json" in n or "1099" in n for n in names), "only this year's papers, only from the archive"
    acct = _sql(modules, "INSERT INTO accounts(name, type, last4) VALUES ('Test card', 'credit', '9999')")
    _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2026-03-05', '=HYPERLINK(\"x\")', -12.5)", acct)
    r = c.get("/money/download?part=ledger&from=2026-03-01&to=2026-03-31")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in r.text and "\n=HYPERLINK" not in r.text, "a formula is kept as text"
    assert 'href="/money/download?' in c.get("/money?part=ledger&from=2026-03-01&to=2026-03-31").text
    assert c.get("/money/download?part=bills").status_code == 404
    r = c.get("/brief/doc/emergency")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert c.get("/brief/doc/passwords").status_code == 404


def test_ledger_summary_sits_in_a_side_panel_after_the_list(web, modules):
    """The Ledger's tiles, notes, how they add up and the download sit in one side panel (a folded summary line on a
    phone), so the filters are followed straight by the kinds and the transactions. Other Money pages are unchanged."""
    c, _ = web
    acct = _sql(modules, "INSERT INTO accounts(name, type, last4) VALUES ('Panel card', 'credit', '8888')")
    _sql(modules, "INSERT INTO transactions(account_id, txn_date, description, amount) VALUES (?, '2026-04-05', 'PANEL SHOP', -20)", acct)
    page = c.get("/money?part=ledger&from=2026-04-01&to=2026-04-30").text
    grid = page.split('<div class="lgrid">', 1)[1]
    side, main = grid.split('<div class="lmain">', 1)
    assert side.lstrip().startswith("<details") and "data-lside" in side and 'class="lside-sum"' in side
    assert 'class="kpis rk"' in side and "How the tiles add up" in side and 'href="/money/download?' in side
    assert "Transactions" in main and 'class="fchips wrap lchips"' in main
    assert 'class="kpis rk"' not in main and "How the tiles add up" not in main, "the summary is not repeated in the list"
    assert page.index('class="rsearch ffilter frange fledger"') < page.index('<div class="lgrid">'), "filters first"
    assert '<div class="lgrid">' not in c.get("/money?part=paid").text, "other parts keep their layout"


def test_money_lists_put_their_tiles_in_the_side_panel(web, modules):
    """Bills, Receipts, Subscriptions and Accounts show the list first and their tiles and notes in the side panel."""
    c, _ = web
    acct = _sql(modules, "INSERT INTO accounts(name, type, last4) VALUES ('Side checking', 'checking', '7777')")
    _sql(modules, "INSERT INTO bills(name, vendor, amount, due_date, status) VALUES ('Side water', 'City', 40, date('now'), 'due')")
    _sql(modules, "INSERT INTO account_balances(account_id, as_of, balance) VALUES (?, date('now'), 100)", acct)
    for part, heading in (("bills", "Bills due in"), ("receipts", "Waiting for a charge"),
                          ("subs", "Other recurring payments seen"), ("accounts", "Accounts and statement coverage")):
        page = c.get(f"/money?part={part}").text
        assert '<div class="lgrid' in page, part
        side, main = page.split('<div class="lgrid', 1)[1].split('<div class="lmain">', 1)
        assert "data-lside" in side and 'class="kpis rk"' in side, part
        assert 'class="kpis rk"' not in main and heading in main, part


def test_settings_packs_tax_leads_and_advanced(web, modules, root):
    c, t = web
    page = c.get("/settings?group=household").text
    for words in ("Optional features", "Work contracts", "Tax papers", "How early to remind", "Run the setup interview again"):
        assert words in page, words
    assert "classic" not in page.lower()
    _post(c, "/settings/packs", t, pack="contracts")
    assert json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))["packs"]["contracts"] is True
    _post(c, "/settings/tax", t, payers="Big Bank 123456789")
    assert "names only" in c.get("/settings?group=household").text.lower()
    _post(c, "/settings/tax", t, payers="Big Bank, Credit Union", state="Comptroller")
    assert "Big Bank, Credit Union" in c.get("/settings?group=household").text
    _post(c, "/settings/lead", t, type="warranty", days="45")
    assert "45 days" in c.get("/settings?group=household").text
    _post(c, "/settings/lead", t, type="warranty", reset="1")
    assert "warranty" in c.get("/settings?group=household").text
    adv = c.get("/settings?group=data").text
    assert "App folder (code)" in adv and "Advanced" in adv


def test_work_page_job_hours_schedule_calendar(web, modules):
    c, t = web
    _post(c, "/settings/packs", t)  # every pack off (the copy is shared by this file's tests)
    assert "Turn it on" in c.get("/work").text
    _post(c, "/settings/packs", t, pack="contracts")
    r = _post(c, "/work", t, op="contract_add", client="Acme", kind="employment", rank="primary", needs_timesheets="1", start="2026-01-01", end="2026-12-31", person="Alex")
    assert r.headers["hx-redirect"].startswith("/work")
    cid = _sql(modules, "SELECT id FROM contracts WHERE client='Acme'")[0][0]
    page = c.get(f"/work?c={cid}&tab=hours").text
    day = re.search(r'name="h_(\d{4}-\d\d-\d\d)"', page).group(1)
    _post(c, "/work", t, op="hours", c=str(cid), tab="hours", **{f"h_{day}": "7.5", f"w_{day}": "offsite"})
    assert _sql(modules, "SELECT hours, location FROM work_hours WHERE contract_id=? AND work_date=?", cid, day) == [(7.5, "offsite")]
    _post(c, "/work", t, op="hours", c=str(cid), **{f"h_{day}": ""})
    assert _sql(modules, "SELECT COUNT(*) FROM work_hours WHERE contract_id=? AND work_date=?", cid, day) == [(0,)]
    d0 = dt.date.today().replace(day=1)
    _post(c, "/work", t, op="hours", c=str(cid), **{f"h_{d0.isoformat()}": "8"})
    page = c.get(f"/work?c={cid}&tab=schedule").text
    n = len(re.findall(r'name="p_\d+"', page))
    _post(c, "/work", t, op="schedule", c=str(cid), anchor=dt.date.today().isoformat(), **{f"p_{i}": "H" for i in range(n)})
    assert _sql(modules, "SELECT schedule FROM contracts WHERE id=?", cid) == [("H" * n,)]
    _post(c, "/work", t, op="schedule", c=str(cid), tab="schedule", p_0="X")
    assert "Pick each day from the list" in c.get(f"/work?c={cid}&tab=schedule").text
    _post(c, "/work", t, op="profile", c=str(cid), client="Acme Corp", kind="rental", rank="secondary", needs_timesheets="1", visibility="shared", hours_per_day="7.5",
          timesheet_cycle="weekly", anchor="2026-01-05", calendar="Acme cal", status="active")
    assert _sql(modules, "SELECT client, kind, rank, visibility, timesheet_cycle FROM contracts WHERE id=?", cid) == \
        [("Acme Corp", "rental", "secondary", "shared", "weekly")]
    assert _post(c, "/work", t, op="invoice_make", c=str(cid), start="2026-01-01", end="2026-01-31").status_code == 400, "no invoices here"
    assert 'href="/work"' in c.get("/family").text, "Work is a chip on Family while the pack is on"
    assert "does not need timesheets" not in c.get(f"/work?c={cid}&tab=hours").text
    _post(c, "/work", t, op="profile", c=str(cid), client="Acme Corp", kind="rental", rank="secondary", needs_timesheets="0", visibility="shared",
          person="Alex", timesheet_cycle="weekly", anchor="2026-01-05", calendar="Acme cal", status="active")
    assert "does not need timesheets" in c.get(f"/work?c={cid}&tab=hours").text
    _post(c, "/work", t, op="profile", c=str(cid), client="Acme Corp", kind="rental", rank="secondary", needs_timesheets="1", visibility="shared",
          person="Alex", timesheet_cycle="weekly", anchor="2026-01-05", calendar="Acme cal", status="active")
    paper = c.get(f"/work?c={cid}&tab=papers").text
    assert "Add a paper" in paper and "Paperwork for" in paper and 'data-upload-to="/work/import?kind=paper' in paper
    assert "Billing" not in c.get(f"/work?c={cid}").text and "Add a job" in c.get("/work").text
    _post(c, "/work", t, op="cal_add", c=str(cid), calendar="Acme cal", day="2026-12-25", kind="holiday", title="Christmas")
    _post(c, "/work", t, op="paydays", c=str(cid), calendar="Acme cal", rule="every14", first="2026-01-09", last="2026-03-31")
    page = c.get(f"/work?c={cid}&tab=calendar&year=2026").text
    assert "Christmas" in page and "payday" in page
    csv_body = f"Date,Hours\n{d0:%m/%d/%Y},6\n".encode()
    r = c.post(f"/work/import?kind=timesheet&c={cid}", content=csv_body,
               headers={"X-CSRF-Token": t, "X-Filename": "hours.csv"})
    assert r.json()["ok"] is True, r.json()
    assert _sql(modules, "SELECT hours FROM work_hours WHERE contract_id=? AND work_date=?", cid, d0.isoformat()) == [(6.0,)]
    assert c.post(f"/work/import?kind=timesheet&c={cid}", content=b"MZ\x90", headers={"X-CSRF-Token": t,
                  "X-Filename": "evil.exe"}).json()["ok"] is False
    assert _post(c, "/work", t, op="drop_tables").status_code == 400


def test_extras_need_an_adult(web):
    c, _ = web
    c.cookies.clear()
    c.post("/login", data={"name": "Kid", "pin": "0000"})
    t = re.search(r'name="csrf-token" content="([^"]+)"', c.get("/").text).group(1)
    for path, d in (("/settings/packs", {"pack": "contracts"}), ("/settings/tax", {}), ("/settings/lead", {}),
                    ("/work", {"op": "contract_add"})):
        assert _post(c, path, t, **d).status_code == 403, path
    for path in ("/work", "/money/download?part=tax", "/brief/doc/emergency"):
        assert c.get(path).status_code == 403, path
    assert c.post("/work/import?kind=timesheet", content=b"x", headers={"X-CSRF-Token": t}).status_code == 403
