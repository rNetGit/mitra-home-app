"""Meals (migration 036 + data/meals.py): ingredient parsing, recipes saved and replaced, the plan (one meal per day and
slot, recipe or plain text), the week view, shopping: merged quantities, staples left off, nothing added twice, meals
marked shopped, identifiers refused, adults only through edit_actions, CLI, and Records > Home > Meals."""
import datetime as D

import pytest

from conftest import q, run

ADULT, KID = {"name": "Alex", "role": "adult"}, {"name": "Sam", "role": "limited"}
MON = D.date(2026, 10, 12)


@pytest.fixture(scope="module")
def M(root, modules):
    return modules("meals")


@pytest.fixture(scope="module")
def con(M, root):
    c = M.db.connect(root / "data" / "family.db")
    yield c
    c.close()


@pytest.mark.parametrize("line,out", [
    ("2 cups rice", ("rice", "2 cups", False)),
    ("1 lb ground beef", ("ground beef", "1 lb", False)),
    ("1/2 tsp cumin", ("cumin", "1/2 tsp", False)),
    ("8 tortillas", ("tortillas", "8", False)),
    ("- 3 onions", ("onions", "3", False)),
    ("salt (pantry)", ("salt", None, True)),
    ("~ olive oil", ("olive oil", None, True)),
    ("fresh basil", ("fresh basil", None, False)),
    ("   ", None),
])
def test_parse_ingredient(M, line, out):
    assert M.parse_ingredient(line) == out


def test_recipes_saved_and_replaced(M, con):
    M.add_recipe(con, "Tacos", ["1 lb ground beef", "8 tortillas", "2 onions", "salt (pantry)"], 4, "Quick, Mexican")
    M.add_recipe(con, "Soup", ["1 onion", "2 carrots", "1 can tomatoes"], tags="veg")
    con.commit()
    r = M.get_recipe(con, "tacos")
    assert r["servings"] == 4 and r["tags"] == "quick,mexican" and [i["text"] for i in r["ingredients"]][-1] == "salt"
    M.add_recipe(con, "TACOS", ["1 lb ground beef", "8 tortillas", "2 onions", "1 avocado", "salt (pantry)"], 4)
    assert len(M.get_recipe(con, "Tacos")["ingredients"]) == 5
    assert [r["name"] for r in M.recipes(con, "veg")] == ["Soup"]
    with pytest.raises(ValueError):
        M.add_recipe(con, "Card 4111 1111 1111 1111", [])
    with pytest.raises(ValueError):
        M.add_recipe(con, "Bad link", [], url="https://bank.example.com/x?token=abc")


def test_plan_and_week(M, con):
    M.plan_meal(con, MON, "dinner", "tacos")
    M.plan_meal(con, MON + D.timedelta(days=1), "dinner", "Soup", note="double batch")
    M.plan_meal(con, MON + D.timedelta(days=2), "dinner", "Leftovers")
    M.plan_meal(con, MON + D.timedelta(days=2), "dinner", "Eat out")  # replaces
    con.commit()
    w = M.week(con, MON.isoformat())
    assert [(r["day"][-2:], r["meal"]) for r in w] == [("12", "Tacos"), ("13", "Soup"), ("14", "Eat out")]
    with pytest.raises(ValueError):
        M.plan_meal(con, MON, "brunch", "x")
    with pytest.raises(ValueError):
        M.plan_meal(con, "next tuesday", "dinner", "x")


def test_shop_merges_skips_staples_and_never_twice(M, con, root):
    added, there, name = M.shop(con, MON.isoformat(), (MON + D.timedelta(days=6)).isoformat())
    con.commit()
    items = dict(q(root, "select text, qty from list_items l join lists s on s.id=l.list_id where s.name='Groceries' and l.status='open'"))
    assert name == "Groceries" and added == 7 and there == 0
    assert items["onions"] == "2" and items["onion"] == "1" and items["carrots"] == "2" and "salt" not in items
    assert M.shop(con, MON.isoformat(), (MON + D.timedelta(days=6)).isoformat())[:2] == (0, 0), "meals already shopped"
    assert M.shop(con, MON.isoformat(), (MON + D.timedelta(days=6)).isoformat(), again=True)[:2] == (0, 7)
    M.add_recipe(con, "Chili", ["2 onions", "1 can beans"])
    M.add_recipe(con, "Stew", ["1 onions", "3 potatoes"])
    M.plan_meal(con, MON + D.timedelta(days=20), "lunch", "Chili")
    M.plan_meal(con, MON + D.timedelta(days=20), "dinner", "Stew")
    d = (MON + D.timedelta(days=20)).isoformat()
    needs, meals = M.shopping_needs(con, d, d)
    assert dict(needs)["onions"] == "3" and len(meals) == 2
    added, _, _ = M.shop(con, d, d, list_name="Costco run")
    con.commit()
    assert added == 3 and q(root, "select kind from lists where name='Costco run'") == [("shopping",)]


def test_edit_actions_adults_only(root, modules, M):
    ea = modules("edit_actions")
    assert ea.recipe_save(KID, "Kid recipe", "1 cake")[0] is False
    assert ea.meal_plan_set(KID, MON.isoformat(), "lunch", "Soup")[0] is False
    ok, msg = ea.recipe_save(ADULT, "Pancakes", "2 cups flour\n2 eggs\nmilk\nsugar (pantry)", 4, "breakfast")
    assert ok, msg
    assert ea.meal_plan_set(ADULT, (MON + D.timedelta(days=30)).isoformat(), "breakfast", "pancakes")[0]
    ok, msg = ea.meal_shop(ADULT, (MON + D.timedelta(days=30)).isoformat(), (MON + D.timedelta(days=30)).isoformat())
    assert ok and msg.startswith("3 items"), msg
    assert ea.meal_plan_clear(ADULT, (MON + D.timedelta(days=30)).isoformat(), "breakfast") == (True, "Removed.")
    assert ea.recipe_archive(ADULT, "Pancakes")[0] and "Pancakes" not in [r["name"] for r in M.recipes(M.db.connect(root / "data" / "family.db"))]
    log = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "recipe_save" in log and "flour" not in log


def test_cli(root):
    r = run(["data/meals.py", "recipe", "add", "Omelette", "--ing", "3 eggs", "--ing", "cheese", "--serves", "1"], root)
    assert r.returncode == 0, r.stderr
    d = (D.date.today() + D.timedelta(days=1)).isoformat()
    assert run(["data/meals.py", "plan", d, "breakfast", "omelette"], root).returncode == 0
    r = run(["data/meals.py", "week", d], root)
    assert "Omelette" in r.stdout
    r = run(["data/meals.py", "shop", "--from", d, "--to", d], root)
    assert r.returncode == 0 and " added to Groceries" in r.stdout
    r = run(["data/meals.py", "plan", d, "brunch", "x"], root)
    assert r.returncode != 0 and "slot must be" in r.stderr


