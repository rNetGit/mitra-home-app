"""A recipe from a web address (data/recipe_web.py): schema.org Recipe data in the page fills the Save a recipe form;
fetched only through the look-ups switch and fence."""
import json

import pytest

from test_webapp import _csrf, _login, _post, web  # noqa: F401 (the web fixture)

PAGE = """<html><head><title>x</title>
<script type="application/ld+json">{"@context": "https://schema.org", "@graph": [{"@type": "WebPage", "name": "Site"},
 {"@type": ["Recipe"], "name": "Chana &amp; spinach curry", "recipeYield": ["4 servings", "4"],
  "recipeIngredient": ["1 can <b>chickpeas</b>", "200 g spinach", " "],
  "recipeInstructions": [{"@type": "HowToSection", "name": "Prep", "itemListElement": [{"@type": "HowToStep", "text": "Chop the onion."}]},
                         {"@type": "HowToStep", "text": "Simmer 20 minutes.<script>alert(1)<\\/script>"}]}]}</script>
</head><body>...</body></html>"""


def test_parse_reads_the_recipe_data(modules):
    rw = modules("recipe_web")
    r = rw.parse(PAGE, "https://example.com/curry")
    assert r["name"] == "Chana & spinach curry" and r["servings"] == "4"
    assert r["ingredients"] == "1 can chickpeas\n200 g spinach"
    assert r["notes"].startswith("Prep:\n1. Chop the onion.\n2. Simmer 20 minutes.")
    assert "<script" not in r["notes"] and r["url"] == "https://example.com/curry"
    with pytest.raises(rw.RecipeError):
        rw.parse("<html>no recipe</html>")
    plain = '<script type="application/ld+json">' + json.dumps({"@type": "Recipe", "name": "Toast", "recipeIngredient": ["bread"],
                                                                 "recipeInstructions": "Toast it.\\nButter it.", "recipeYield": "2"}) + "</script>"
    r = rw.parse(plain)
    assert r["notes"] == "1. Toast it.\\nButter it." or r["notes"].startswith("1. Toast it.")


def test_the_meals_form_fills_in_only_with_look_ups_on(web, modules, monkeypatch):  # noqa: F811
    c, _, _ = web
    _login(c)
    token = _csrf(c)
    lk = modules("lookups")
    assert "Fill it in from a web address" in c.get("/records?domain=home&section=meals").text
    monkeypatch.setattr(lk, "enabled", lambda cfg=None: False)
    r = _post(c, "/records/recipe/url", token, url="https://example.com/curry")
    assert "Online look-ups are off" in r.text
    monkeypatch.setattr(lk, "enabled", lambda cfg=None: True)
    monkeypatch.setattr(lk, "_public_host", lambda h: True)
    monkeypatch.setattr(lk, "_open", lambda req: (200, "text/html; charset=utf-8", PAGE.encode(), req.full_url))
    r = _post(c, "/records/recipe/url", token, url="https://example.com/curry")
    assert "Filled in from example.com" in r.text and 'value="Chana &amp; spinach curry"' in r.text
    assert "1 can chickpeas" in r.text and 'value="4"' in r.text
    monkeypatch.setattr(lk, "_open", lambda req: (200, "text/html", b"<html>nothing</html>", req.full_url))
    assert "no recipe this app can read" in _post(c, "/records/recipe/url", token, url="https://example.com/x").text
