"""Recipes and the week's meal plan, feeding the shared shopping list (migration 036). No AI, nothing fetched or bought.

  python data/meals.py recipe add "<name>" [--serves 4] [--tags "quick,veg"] [--url URL] [--note TEXT]
                                    [--ing "2 cups rice" --ing "salt (pantry)" ...]
  python data/meals.py recipe show "<name>"
  python data/meals.py recipes [--tag TAG]              active recipes with their ingredient count
  python data/meals.py recipe archive "<name>"
  python data/meals.py plan DATE SLOT "<recipe or text>" [--note TEXT]     SLOT: breakfast lunch dinner snack
  python data/meals.py unplan DATE SLOT
  python data/meals.py week [START]                     seven days from START (default: this Monday)
  python data/meals.py shop [--from D] [--to D] [--list Groceries] [--again]
                                    ingredients of planned recipes onto the shopping list (default: the next 7 days)

Ingredient lines: a leading amount becomes the quantity ("2 cups rice" -> rice, qty "2 cups"); "(pantry)" at the end
or "~" at the start marks a staple the family always has, which `shop` leaves off the list. `shop` merges the same
ingredient across meals (plain numbers are added: 2 + 1 onion -> 3), skips what is already open on the list, and
marks those meals shopped so a second run does not add them again (`--again` does). Library: add_recipe,
get_recipe, recipes, archive_recipe, plan_meal, unplan, week, shop; they raise ValueError on bad input.
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
import dates  # noqa: E402
import db  # noqa: E402
import validators as v  # noqa: E402

DB = paths.DB
SLOTS = ["breakfast", "lunch", "dinner", "snack"]
MAX_INGREDIENTS = 60
_UNITS = (r"(?:cups?|c|tbsp|tablespoons?|tsp|teaspoons?|g|grams?|kg|ml|l|litres?|liters?|lbs?|pounds?|oz|ounces?|"
          r"cloves?|cans?|tins?|packs?|packets?|pcs?|pieces?|bunch(?:es)?|slices?|heads?|sticks?|pinch(?:es)?|dozen|x)")
_AMOUNT = re.compile(r"^\s*((?:\d+(?:[.,/]\d+)?|\d+\s+\d/\d|[½¼¾⅓⅔])(?:\s*-\s*\d+(?:[.,/]\d+)?)?(?:\s*" + _UNITS + r"\b\.?)?)\s+(.+)$",
                     re.I)
_PANTRY = re.compile(r"\s*\((?:pantry|staple)\)\s*$", re.I)


def _now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _clean(validator, value, label):
    try:
        return validator(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"{label}: {e}") from None


def _rows(con, sql, params=()):
    con.row_factory = sqlite3.Row
    return [dict(r) for r in con.execute(sql, params).fetchall()]


def parse_ingredient(line):
    """'2 cups rice' -> ('rice', '2 cups', False); '~salt' or 'salt (pantry)' -> ('salt', None, True). None for blank."""
    s = " ".join(str(line or "").split()).lstrip("-*• ").strip()
    if not s:
        return None
    pantry = False
    if s.startswith("~"):
        pantry, s = True, s[1:].strip()
    if _PANTRY.search(s):
        pantry, s = True, _PANTRY.sub("", s).strip()
    m = _AMOUNT.match(s)
    qty, text = (m.group(1).strip(), m.group(2).strip()) if m else (None, s)
    text = _clean(v.text(120), text, "ingredient")
    qty = _clean(v.text(20), qty, "quantity") if qty else None
    return text, qty, pantry


def _url(url):
    if not url:
        return None
    import saved
    return saved.clean_url(url)[0]


def find_recipe(con, name, active=True):
    name = " ".join(str(name or "").split())
    rs = _rows(con, "SELECT * FROM recipes WHERE name=? COLLATE NOCASE" + (" AND status='active'" if active else ""), (name,))
    if not rs:
        rs = _rows(con, "SELECT * FROM recipes WHERE name LIKE ? AND status='active' ORDER BY name", (f"%{name}%",))
        if len(rs) > 1:
            raise ValueError(f"'{name}' matches {', '.join(r['name'] for r in rs[:5])}: be more exact")
    if not rs:
        raise ValueError(f"no recipe called '{name}'")
    return rs[0]


def add_recipe(con, name, ingredients=(), servings=None, tags=None, url=None, notes=None, by=None):
    """Add a recipe, or replace the details and ingredients of one with the same name. Returns its id."""
    name = _clean(v.text(80), name, "recipe name")
    servings = _clean(v.integer(1, 50), servings, "servings") if servings not in (None, "") else None
    tags = ",".join(t.strip().lower() for t in str(tags or "").split(",") if t.strip()) or None
    if tags:
        tags = _clean(v.text(120), tags, "tags")
    url = _url(url)
    notes = " ".join(str(notes).split()) if notes else None
    if notes and len(notes) > 5000:
        raise ValueError("notes: at most 5000 characters")
    if notes:
        _clean(v.text(5000), notes, "notes")
    parsed = [p for p in (parse_ingredient(x) for x in ingredients or ()) if p]
    if len(parsed) > MAX_INGREDIENTS:
        raise ValueError(f"at most {MAX_INGREDIENTS} ingredients")
    old = _rows(con, "SELECT id FROM recipes WHERE name=? COLLATE NOCASE", (name,))
    if old:
        rid = old[0]["id"]
        con.execute("UPDATE recipes SET servings=?, tags=?, url=?, notes=?, status='active' WHERE id=?",
                    (servings, tags, url, notes, rid))
        if parsed:
            con.execute("DELETE FROM recipe_ingredients WHERE recipe_id=?", (rid,))
    else:
        rid = con.execute("INSERT INTO recipes(name, servings, tags, url, notes, added_by, added_at) VALUES (?,?,?,?,?,?,?)",
                          (name, servings, tags, url, notes, by or None, _now())).lastrowid
    for pos, (text, qty, pantry) in enumerate(parsed):
        con.execute("INSERT INTO recipe_ingredients(recipe_id, text, qty, pantry, pos) VALUES (?,?,?,?,?)",
                    (rid, text, qty, int(pantry), pos))
    return rid


def get_recipe(con, name_or_id):
    r = (_rows(con, "SELECT * FROM recipes WHERE id=?", (int(name_or_id),)) or [None])[0] if str(name_or_id).isdigit() \
        else find_recipe(con, name_or_id, active=False)
    if not r:
        raise ValueError(f"no recipe {name_or_id}")
    r["ingredients"] = _rows(con, "SELECT text, qty, pantry FROM recipe_ingredients WHERE recipe_id=? ORDER BY pos, id", (r["id"],))
    return r


def recipes(con, tag=None):
    rs = _rows(con, "SELECT r.id, r.name, r.servings, r.tags, r.url, (SELECT COUNT(*) FROM recipe_ingredients i "
                    "WHERE i.recipe_id=r.id) AS ingredients FROM recipes r WHERE r.status='active' ORDER BY r.name COLLATE NOCASE")
    if tag:
        t = tag.strip().lower()
        rs = [r for r in rs if t in (r["tags"] or "").split(",")]
    return rs


def archive_recipe(con, name):
    r = find_recipe(con, name)
    con.execute("UPDATE recipes SET status='archived' WHERE id=?", (r["id"],))
    return r


def _day(d):
    return _clean(v.iso_date, d.isoformat() if isinstance(d, dt.date) else d, "date")


def plan_meal(con, day, slot, what, note=None, by=None):
    """Put a recipe (matched by name) or plain text on DAY/SLOT, replacing what was there. Returns the meal_plan id."""
    day = _day(day)
    slot = str(slot or "").strip().lower()
    if slot not in SLOTS:
        raise ValueError(f"slot must be one of {', '.join(SLOTS)}")
    what = _clean(v.text(80), what, "meal")
    note = _clean(v.text(200), note, "note") if note else None
    rid, title = None, None
    try:
        rid = find_recipe(con, what)["id"]
    except ValueError:
        title = what
    con.execute("DELETE FROM meal_plan WHERE day=? AND slot=?", (day, slot))
    return con.execute("INSERT INTO meal_plan(day, slot, recipe_id, title, note, added_by, added_at) VALUES (?,?,?,?,?,?,?)",
                       (day, slot, rid, title, note, by or None, _now())).lastrowid


def unplan(con, day, slot):
    return con.execute("DELETE FROM meal_plan WHERE day=? AND slot=?", (_day(day), str(slot).lower())).rowcount


def monday(d=None):
    d = d or dates.today()
    return d - dt.timedelta(days=d.weekday())


def week(con, start=None, days=7):
    """Planned meals from START for DAYS days: list of dicts day, slot, meal, recipe_id, note, shopped."""
    start = dt.date.fromisoformat(_day(start)) if start else monday()
    end = start + dt.timedelta(days=days - 1)
    rows = _rows(con, "SELECT m.id, m.day, m.slot, m.recipe_id, COALESCE(r.name, m.title) AS meal, m.note, m.shopped_at "
                      "FROM meal_plan m LEFT JOIN recipes r ON r.id=m.recipe_id WHERE m.day BETWEEN ? AND ?",
                 (start.isoformat(), end.isoformat()))
    order = {s: i for i, s in enumerate(SLOTS)}
    return sorted(rows, key=lambda r: (r["day"], order[r["slot"]]))


def _num(q):
    try:
        return float(q.replace(",", "."))
    except (AttributeError, ValueError):
        return None


def _merge_qty(qs):
    qs = [q for q in qs if q]
    if not qs:
        return None
    nums = [_num(q) for q in qs]
    if len(qs) > 1 and all(n is not None for n in nums):
        t = sum(nums)
        return f"{t:g}"
    out = " + ".join(dict.fromkeys(qs))
    return out if len(out) <= 20 else out[:19] + "…"


def shopping_needs(con, start, end, again=False):
    """(merged [(text, qty)], meal ids) for planned recipes between start and end, staples left out."""
    rows = _rows(con, "SELECT m.id AS meal_id, i.text, i.qty FROM meal_plan m JOIN recipe_ingredients i ON i.recipe_id=m.recipe_id "
                      "WHERE m.day BETWEEN ? AND ? AND i.pantry=0" + ("" if again else " AND m.shopped_at IS NULL") +
                 " ORDER BY m.day, i.pos", (start, end))
    merged = {}
    for r in rows:
        k = r["text"].lower()
        merged.setdefault(k, [r["text"], []])[1].append(r["qty"])
    meals = sorted({r["meal_id"] for r in rows})
    return [(t, _merge_qty(qs)) for t, qs in merged.values()], meals


def shop(con, start=None, end=None, list_name="Groceries", again=False, by=None):
    """Put the planned recipes' ingredients onto a shopping list. Returns (added, already_there, list name)."""
    import lists as L
    start = _day(start) if start else dates.today().isoformat()
    end = _day(end) if end else (dt.date.fromisoformat(start) + dt.timedelta(days=6)).isoformat()
    if end < start:
        raise ValueError("--to is before --from")
    try:
        lst = L.find_list(con, list_name)
    except ValueError:
        lid = L.new_list(con, list_name, "shopping", "family", by)
        lst = L.get_list(con, lid)
    needs, meal_ids = shopping_needs(con, start, end, again)
    added = there = 0
    for text, qty in needs:
        _, new = L.add_item(con, lst["id"], text, qty, None, by or "meal plan")
        added, there = added + new, there + (not new)
    if meal_ids:
        con.executemany("UPDATE meal_plan SET shopped_at=? WHERE id=?", [(_now(), i) for i in meal_ids])
    return added, there, lst["name"]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("recipe")
    p.add_argument("action", choices=["add", "show", "archive"])
    p.add_argument("name")
    p.add_argument("--serves", type=int)
    p.add_argument("--tags")
    p.add_argument("--url")
    p.add_argument("--note")
    p.add_argument("--ing", action="append", default=[])
    p = sub.add_parser("recipes")
    p.add_argument("--tag")
    p = sub.add_parser("plan")
    p.add_argument("day")
    p.add_argument("slot")
    p.add_argument("what")
    p.add_argument("--note")
    p = sub.add_parser("unplan")
    p.add_argument("day")
    p.add_argument("slot")
    p = sub.add_parser("week")
    p.add_argument("start", nargs="?")
    p = sub.add_parser("shop")
    p.add_argument("--from", dest="start")
    p.add_argument("--to", dest="end")
    p.add_argument("--list", default="Groceries")
    p.add_argument("--again", action="store_true")
    a = ap.parse_args(argv)
    con = db.connect(DB)
    try:
        if a.cmd == "recipe" and a.action == "add":
            add_recipe(con, a.name, a.ing, a.serves, a.tags, a.url, a.note)
            con.commit()
            print(f"recipe saved: {a.name} ({len(a.ing)} ingredient line(s))")
        elif a.cmd == "recipe" and a.action == "show":
            r = get_recipe(con, a.name)
            print(f"{r['name']}" + (f" (serves {r['servings']})" if r["servings"] else "") + (f"  [{r['tags']}]" if r["tags"] else ""))
            for i in r["ingredients"]:
                print(f"  - {i['text']}" + (f" ({i['qty']})" if i["qty"] else "") + ("  [pantry]" if i["pantry"] else ""))
            if r["url"]:
                print(f"  {r['url']}")
            if r["notes"]:
                print(f"  {r['notes']}")
        elif a.cmd == "recipe":
            print(f"archived: {archive_recipe(con, a.name)['name']}")
            con.commit()
        elif a.cmd == "recipes":
            rs = recipes(con, a.tag)
            for r in rs:
                print(f"{r['name']:<30} {r['ingredients']:>2} ingredients" + (f"  [{r['tags']}]" if r["tags"] else ""))
            if not rs:
                print('No recipes yet. python data/meals.py recipe add "Tacos" --ing "1 lb ground beef" --ing "8 tortillas"')
        elif a.cmd == "plan":
            plan_meal(con, a.day, a.slot, a.what, a.note)
            con.commit()
            print(f"planned {a.day} {a.slot}: {a.what}")
        elif a.cmd == "unplan":
            n = unplan(con, a.day, a.slot)
            con.commit()
            print("removed" if n else "nothing planned there")
        elif a.cmd == "week":
            rows = week(con, a.start)
            for r in rows:
                print(f"{r['day']} {dt.date.fromisoformat(r['day']):%a}  {r['slot']:<9} {r['meal']}" +
                      (f"  ({r['note']})" if r["note"] else "") + ("  [shopped]" if r["shopped_at"] else ""))
            if not rows:
                print("Nothing planned this week.")
        elif a.cmd == "shop":
            added, there, name = shop(con, a.start, a.end, a.list, a.again)
            con.commit()
            print(f"{added} item(s) added to {name}" + (f", {there} already there" if there else ""))
    except ValueError as e:
        raise SystemExit(str(e)) from None
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
