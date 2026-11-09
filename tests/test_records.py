"""Records (0.52): data/records.py (refs, labels, which rows a query used, detail, history, search) and the Records page
(data/dashboard/records_page.py) reached from the rail search, links and ?page=records."""
import datetime as D
from types import SimpleNamespace

import pytest

from conftest import db

ADULT = {"name": "Alex", "role": "adult"}


@pytest.fixture(scope="module")
def R(root, modules):
    return modules("records")


@pytest.fixture(scope="module")
def con(root):
    c = db(root)
    yield c
    c.close()


def _bill(con, name="Water bill", vendor="City Water", amount=48.5, doc=None):
    cur = con.execute("INSERT INTO bills(name, vendor, amount, due_date, status, document_id) VALUES (?,?,?,?, 'due', ?)",
                      (name, vendor, amount, (D.date.today() + D.timedelta(days=3)).isoformat(), doc))
    con.commit()
    return cur.lastrowid


def test_refs_parse_only_citable_tables(R):
    assert R.parse_ref("bills:12") == ("bills", [12])
    assert R.parse_ref("transactions:1,2,3") == ("transactions", [1, 2, 3])
    for bad in ("chat_links:1", "proposals:2", "bills", "bills:x", "bills:1;DROP", "sqlite_master:1", "bills:" + ",".join(["1"] * 51)):
        assert R.parse_ref(bad) is None, bad
    assert R.ref_str("bills", [3, 4]) == "bills:3,4"


def test_which_rows_a_query_used(R, con):
    n_out = con.execute("SELECT COUNT(*) FROM transactions WHERE amount < 0").fetchone()[0]
    t, ids = R.rows_used(con, "SELECT category, ROUND(SUM(-amount),2) FROM transactions t WHERE t.amount < 0 GROUP BY 1 ORDER BY 2 DESC LIMIT 3")
    assert t == "transactions" and len(ids) == n_out > 0, "a SUM cites every row it added up, not only the top 3 groups"
    t, ids = R.rows_used(con, "SELECT COUNT(*) FROM members")
    assert t == "members" and len(ids) == q_count(con, "members")
    bid = _bill(con)
    t, ids = R.rows_used(con, "SELECT b.name FROM bills b LEFT JOIN accounts a ON a.id = b.account_id WHERE b.vendor LIKE '%Water%'")
    assert (t, ids) == ("bills", [bid])
    assert R.rows_used(con, "WITH x AS (SELECT 1) SELECT * FROM x") == (None, [])
    assert R.rows_used(con, "SELECT * FROM (SELECT * FROM bills)") == (None, [])
    assert R.rows_used(con, "SELECT * FROM chat_links") == (None, [])
    assert R.rows_used(con, "SELECT name FROM bills WHERE name = 'from where (group by)'") == ("bills", [])
    refs = R.refs_for_sql(con, "SELECT SUM(amount) FROM bills WHERE vendor = 'City Water'")
    assert refs == [{"ref": f"bills:{bid}", "label": refs[0]["label"], "table": "bills", "ids": [bid]}]
    assert refs[0]["label"].startswith("City Water, due ") and R.words_date("x 2031-01-02") == "x January 2, 2031"
    many = R.refs_for_sql(con, "SELECT * FROM transactions")
    assert len(many) == 1 and many[0]["label"].endswith("payments") and many[0]["ref"].startswith("transactions:")


def q_count(con, table):
    return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_detail_source_paper_and_history(root, R, con, modules):
    (root / "archive" / "2026" / "bills").mkdir(parents=True, exist_ok=True)
    (root / "archive" / "2026" / "bills" / "2026-10-01_power_bill.txt").write_text("power bill", encoding="utf-8")
    cur = con.execute("INSERT INTO documents(filed_path, doc_type, vendor, doc_date) VALUES ('2026/bills/2026-10-01_power_bill.txt', "
                      "'utility_bill', 'Power Co', '2026-10-01')")
    con.commit()
    bid = _bill(con, "Power bill", "Power Co", 90, cur.lastrowid)
    d = R.detail(con, "bills", bid, ADULT)
    fields = dict(d["fields"])
    assert d["label"].startswith("Power Co, due ") and "-" not in d["label"], "dates in words"
    assert fields["amount"].endswith("90.00") and "id" not in fields and "document id" not in fields and "amount cents" not in fields
    assert d["source"]["label"].startswith("Power Co utility bill") and (d["domain"], d["section"]) == ("money", "bills")
    assert R.source_file(d["source"]["path"]).read_text(encoding="utf-8") == "power bill"
    assert R.source_file("../config/family.json") is None and R.source_file("../../data/family.db") is None
    ea = modules("edit_actions")
    ok, _ = ea.life_add(ADULT, "school", "Field trip form", "Sam", None, None)
    lid = con.execute("SELECT MAX(id) FROM life_items").fetchone()[0]
    assert ok and [h["what"] for h in R.history("life_items", lid)] == ["life add"]
    assert R.history("life_items", lid + 1000) == []
    rec = con.execute("SELECT id FROM recurring_items WHERE category='Health' LIMIT 1").fetchone()
    if rec:
        assert R.where("recurring_items", {"category": "Health"}) == ("people", "health")
    assert R.where("recurring_items", {"category": "Home"}) == ("home", "upkeep")


def test_private_saved_items_stay_private(R, con):
    cur = con.execute("INSERT INTO saved_items(kind, title, audience, owner, status, added_at) VALUES ('note', 'Surprise party plan', 'private', 'Alex', 'active', '2026-10-01')")
    con.commit()
    sid = cur.lastrowid
    assert R.label(con, "saved_items", sid, ADULT) == "Surprise party plan"
    assert R.label(con, "saved_items", sid, {"name": "Sam", "role": "adult"}) is None
    assert R.detail(con, "saved_items", sid, {"name": "Sam", "role": "adult"}) is None
    assert not [h for h in R.search(con, "surprise party", {"name": "Sam", "role": "adult"}) if h["table"] == "saved_items"]


def test_search_rows_and_papers(R, con):
    _bill(con, "Gas bill", "Lakeshore Gas", 61)
    hits = R.search(con, "lakeshore gas", ADULT)
    assert hits and hits[0]["table"] == "bills" and hits[0]["domain"] == "money"
    assert R.search(con, "", ADULT) == [] and R.search(con, "zzzz-nothing-like-this", ADULT) == []


# ------------------------------------------------------------------ the page
AppTest = pytest.importorskip("streamlit.testing.v1").AppTest


def _qp(at, k):
    v = at.query_params.get(k)
    return v[0] if isinstance(v, list) else v


class _St:
    """Just enough of streamlit for common.pick: query params, info, and a dataframe that reports ticked rows."""

    def __init__(self, ref=None, ticked=()):
        self.query_params = {"ref": ref} if ref else {}
        self.session_state = {}
        self.ticked, self.drawn, self.infos = list(ticked), [], []

    def info(self, text):
        self.infos.append(text)

    def markdown(self, html, **kw):  # the empty state (theme.empty): text is between <b> tags
        self.infos.append(html.split("<b>")[1].split("</b>")[0])

    def dataframe(self, df, **kw):
        self.drawn.append((list(df.columns), kw))
        return SimpleNamespace(selection=SimpleNamespace(rows=self.ticked))




def test_private_jobs_stay_private(R, con, root, modules):
    sam = {"name": "Sam", "role": "adult"}
    ids = []
    for vis in ("private", "shared"):
        cid = con.execute("INSERT INTO contracts(person, client, status, visibility) VALUES ('Alex', ?, 'active', ?)",
                          (f"Client {vis}", vis)).lastrowid
        con.execute("INSERT INTO work_hours(contract_id, work_date, hours) VALUES (?, '2026-10-01', 8)", (cid,))
        ids.append((cid, con.execute("SELECT max(id) FROM work_hours").fetchone()[0]))
    con.commit()
    (pc, ph), (sc, sh) = ids
    assert R.label(con, "contracts", pc, ADULT)
    assert R.label(con, "contracts", pc, sam) is None
    assert R.detail(con, "contracts", pc, sam) is None
    assert R.detail(con, "work_hours", ph, sam) is None
    assert R.detail(con, "work_hours", ph, ADULT) is not None
    assert R.detail(con, "contracts", sc, sam) is not None and R.detail(con, "work_hours", sh, sam) is not None
    assert not [h for h in R.search(con, "client private", sam) if h["table"] == "contracts"]
    assert [h for h in R.search(con, "client private", ADULT) if h["table"] == "contracts"]
    assert R.cite(con, "contracts", [pc, sc], sam)["ids"] == [sc]
    ask = modules("ask_sql")
    rows = ask.run(con, "SELECT client FROM contracts")
    assert "Client private" not in rows and "Client shared" in rows
    assert "Client private" not in ask.run(con, "SELECT client FROM contracts c JOIN work_hours h ON h.contract_id = c.id")
    assert ask.refused("SELECT client FROM main.contracts")


def test_chat_sql_leaves_out_private_saved_items(root, modules):
    # fresh connections: the shared one already holds ask_sql's TEMP views, which the sync triggers would hit on insert
    w = db(root)
    w.execute("INSERT INTO saved_items(kind, title, audience, owner, status, added_at) VALUES ('note', 'Secret gift idea', 'private', 'Alex', 'active', '2026-10-02')")
    w.execute("INSERT INTO saved_items(kind, title, audience, owner, status, added_at) VALUES ('note', 'Family picnic spot', 'family', 'Alex', 'active', '2026-10-02')")
    w.commit()
    w.close()
    r = db(root)
    out = modules("ask_sql").run(r, "SELECT title FROM saved_items")
    r.close()
    assert "Secret gift idea" not in out and "Family picnic spot" in out
