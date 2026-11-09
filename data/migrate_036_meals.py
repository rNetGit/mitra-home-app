"""Apply migration 036 to data/family.db (idempotent): recipes and the meal plan.

`recipes` (name, servings, tags, a link, short notes) with `recipe_ingredients` (one line each, optional quantity,
`pantry` = 1 for staples the family always has, which are not put on the shopping list). `meal_plan` holds one meal
per day and slot (breakfast, lunch, dinner, snack): a recipe or plain text ("leftovers", "eat out").
`shopped_at` records when that meal's ingredients went onto a shopping list, so they are not added twice.
Manage with data/meals.py or the dashboard Family > Meals tab. Nothing is fetched from a link; nothing is bought.
"""
import sqlite3

import paths  # noqa: E402
c = sqlite3.connect(paths.DB)
c.executescript("""
CREATE TABLE IF NOT EXISTS recipes (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE COLLATE NOCASE CHECK (length(name) BETWEEN 1 AND 80),
  servings INTEGER CHECK (servings IS NULL OR servings BETWEEN 1 AND 50),
  tags TEXT CHECK (tags IS NULL OR length(tags) <= 120),
  url TEXT CHECK (url IS NULL OR (length(url) <= 2000 AND (url LIKE 'http://%' OR url LIKE 'https://%'))),
  notes TEXT CHECK (notes IS NULL OR length(notes) <= 5000),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
  added_by TEXT,
  added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS recipe_ingredients (
  id INTEGER PRIMARY KEY,
  recipe_id INTEGER NOT NULL REFERENCES recipes(id),
  text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 120),
  qty TEXT CHECK (qty IS NULL OR length(qty) <= 20),
  pantry INTEGER NOT NULL DEFAULT 0 CHECK (pantry IN (0,1)),
  pos INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recipe_ingredients ON recipe_ingredients(recipe_id, pos);
CREATE TABLE IF NOT EXISTS meal_plan (
  id INTEGER PRIMARY KEY,
  day TEXT NOT NULL CHECK (day GLOB '[0-9][0-9][0-9][0-9]-[0-1][0-9]-[0-3][0-9]'),
  slot TEXT NOT NULL CHECK (slot IN ('breakfast','lunch','dinner','snack')),
  recipe_id INTEGER REFERENCES recipes(id),
  title TEXT CHECK (title IS NULL OR length(title) <= 80),
  note TEXT CHECK (note IS NULL OR length(note) <= 200),
  shopped_at TEXT,
  added_by TEXT,
  added_at TEXT NOT NULL,
  UNIQUE (day, slot),
  CHECK (recipe_id IS NOT NULL OR title IS NOT NULL)
);
""")
c.commit()
print("migration 036 ok;", c.execute("SELECT COUNT(*) FROM recipes").fetchone()[0], "recipes,",
      c.execute("SELECT COUNT(*) FROM meal_plan").fetchone()[0], "planned meals")
