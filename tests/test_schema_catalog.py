"""The data dictionary the chat assistant reads (data/schema_catalog.py): every table is described or denied, the
PC-only tables never reach the AI, the recipes run, and the assistant's prompt and describe action carry it."""
import json

import pytest

from conftest import KEYS, q, run


@pytest.fixture(scope="module")
def cat(root, modules):
    return modules("schema_catalog")


@pytest.fixture(scope="module")
def con(root, modules):
    db, paths = modules("db"), modules("paths")
    c = db.connect(paths.DB, readonly=True)
    yield c
    c.close()


def test_every_table_is_described_or_denied(cat, con):
    assert cat.undescribed(con) == [], "a migration added a table: give it an entry in schema_catalog.TABLES or DENY"
    assert not set(cat.TABLES) & cat.DENY
    in_db = {n for n, _ in con.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')")}
    assert set(cat.TABLES) <= in_db, set(cat.TABLES) - in_db


def test_private_tables_are_never_listed_or_described(cat, con):
    c = cat.build(con)
    assert not set(c["tables"]) & cat.DENY
    text = cat.overview(c) + cat.describe(["member_info", "home_contacts", "wallet_cards", "chat_links"], c)
    for name in ("member_info", "home_contacts", "wallet_cards", "chat_links"):
        assert f"{name}: not a table the chat can read" in text
        assert f"- {name}:" not in text


def test_describe_carries_columns_statuses_relations_and_this_households_values(cat, con):
    d = cat.describe(["bills", "transactions", "life_items"], cat.build(con))
    assert "status: due = not paid yet; overdue = past the due date, not paid; paid = paid on paid_date" in d
    assert "document_id -> documents.id (the bill itself)" in d and "account_id -> accounts.id (paid from)" in d
    assert "NEGATIVE = money out" in d and "values of category in this household:" in d
    assert "groceries (" in d, "the demo household's own category names are listed with counts"
    assert "values of domain in this household:" in d and "shown in Records: people/life" in d
    assert len(cat.describe([f"t{i}" for i in range(20)], cat.build(con)).split("\n\n")) == cat.MAX_DESCRIBE


def test_overview_is_one_line_per_table_and_small(cat, con):
    o = cat.overview(cat.build(con))
    lines = o.splitlines()
    assert all(ln.startswith("- ") for ln in lines) and len(lines) == len(cat.build(con)["tables"])
    assert "- bills: Bills to pay" in o and "status due/overdue/paid" in o and "- v_monthly_cashflow: VIEW" in o
    assert len(o) < 12000, "the overview rides in every planning prompt"


def test_cache_is_reused_for_the_same_schema_and_rebuilt_after_a_migration(cat, con, root, modules):
    paths = modules("paths")
    f = paths.LOGS / "schema_catalog.json"
    f.unlink(missing_ok=True)
    c1 = cat.load(con)
    assert f.exists()
    c2 = cat.load(con)
    assert c2["built"] == c1["built"], "second load came from the cache"
    stale = json.loads(f.read_text(encoding="utf-8"))
    stale["stamp"] = -1
    f.write_text(json.dumps(stale), encoding="utf-8")
    assert cat.load(con)["stamp"] == c1["stamp"], "a different migration count rebuilds it"


@pytest.mark.parametrize("key", ["spend_by_category_month", "spend_at_payee", "balances_latest", "bills_open", "bills_paid_to_vendor",
                                 "open_for_person", "cashflow_months", "premium_history", "subscriptions_active", "expiring"])
def test_every_recipe_runs_and_passes_the_sql_gate(cat, con, key, modules):
    ask_sql, assistant = modules("ask_sql"), modules("assistant")
    sql = cat.recipe_sql(key, name="O'Brien")
    assert assistant.select_sql(sql) == sql.rstrip(";"), "a recipe must pass the chat's own SELECT check"
    out = ask_sql.run(con, sql)
    assert " | " in out.splitlines()[0] or out.splitlines()[0], out


def test_recipes_give_the_demo_households_numbers(cat, con, modules):
    ask_sql = modules("ask_sql")
    out = ask_sql.run(con, cat.recipe_sql("spend_by_category_month", month="2026-09"))
    assert "groceries" in out and "salary" not in out, "income lines are not spending"
    out = ask_sql.run(con, cat.recipe_sql("bills_open"))
    assert "Electric" in out and "due" in out


def test_cli(root):
    assert "every table is described or denied" in run(["data/schema_catalog.py", "check"], root).stdout
    r = run(["data/schema_catalog.py", "describe", "bills", "member_info"], root)
    assert "status: due" in r.stdout and "member_info: not a table" in r.stdout and "phone" not in r.stdout
    r = run(["data/schema_catalog.py", "recipes"], root)
    assert "bills_open" in r.stdout and "SELECT" not in r.stdout
    assert "Electric" in run(["data/schema_catalog.py", "recipes", "bills_open"], root).stdout


def test_ask_sql_run_refuses_what_the_cli_refuses(con, modules):
    ask_sql = modules("ask_sql")
    for bad in ("DELETE FROM members", "SELECT 1; DROP TABLE members", "SELECT * FROM member_info", "SELECT * FROM sqlite_master"):
        with pytest.raises(ValueError):
            ask_sql.run(con, bad)
    assert ask_sql.run(con, "SELECT COUNT(*) AS n FROM members").splitlines()[0] == "n"


# ---- the assistant uses it

def say(reply, actions=None, question=None):
    return json.dumps({"reply": reply, "actions": actions or [], "question": question})


@pytest.fixture(scope="module")
def ask(root, mock_llm):
    def go(*replies, text="request"):
        mock_llm.use("anthropic")
        mock_llm.seen = []
        mock_llm.queue = [r if isinstance(r, str) else json.dumps(r) for r in replies]
        return run(["data/assistant.py", "--yes", text], root, env=KEYS)
    yield go
    mock_llm.queue = []


def test_the_planning_prompt_carries_the_overview_rules_and_recipes(root, ask, mock_llm):
    r = ask(say("Hello!"), text="hi")
    assert r.returncode == 0, r.stdout + r.stderr[-300:]
    sent = json.dumps(mock_llm.seen[0]["body"])
    assert "- bills: Bills to pay" in sent and "- transactions: Every line" in sent and "- policies: Insurance policies" in sent
    assert "describe(tables)" in sent and "Query rules:" in sent
    assert "bills_open: bills not paid yet" in sent and "FROM v_balance_latest" in sent
    assert "member_info" not in sent and "wallet_cards" not in sent and "home_contacts" not in sent


def test_describe_is_a_read_only_round_whose_result_feeds_the_next_plan(root, ask, mock_llm):
    r = ask(say("Looking.", [{"name": "describe", "args": {"tables": "bills, transactions"}}]),
            say("Querying.", [{"name": "sql_query", "args": {"sql": "SELECT COUNT(*) AS n FROM bills WHERE status = 'due'"}}]),
            say("Two bills are open."), text="how many bills are open?")
    assert r.returncode == 0 and "Two bills are open." in r.stdout, r.stdout + r.stderr[-300:]
    assert len(mock_llm.seen) == 3
    second = json.dumps(mock_llm.seen[1]["body"])
    assert "status: due = not paid yet" in second and "values of category in this household" in second
    assert "describe" not in r.stdout and "SELECT" not in r.stdout


def test_denied_tables_and_bad_names_never_run(root, ask):
    before = (root / "logs" / "assistant.log").read_text(encoding="utf-8") if (root / "logs" / "assistant.log").exists() else ""
    r = ask(say("ok", [{"name": "sql_query", "args": {"sql": "SELECT value FROM member_info"}},
                       {"name": "sql_query", "args": {"sql": "SELECT * FROM proposals"}},
                       {"name": "describe", "args": {"tables": "bills; DROP TABLE bills"}}]), text="x")
    assert "I couldn't do one part of that" in r.stdout and "member_info" not in r.stdout
    log = (root / "logs" / "assistant.log").read_text(encoding="utf-8")[len(before):]
    assert log.count("a table the chat may not read") == 2 and "table names" in log
    assert "rc=" not in log, "nothing ran"
    assert q(root, "select count(*) from members")[0][0] == 3
