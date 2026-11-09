"""A recipe from a web address, without AI: most recipe sites publish the recipe as schema.org data (JSON-LD) in the page;
this reads its name, servings, ingredients and method to fill in Records > Home > Meals > Save a recipe, for an adult to
check before saving.

  python data/recipe_web.py URL      what would be filled in

The page is fetched through lookups.get: only while "Look things up online" is on (Family > House), only from a public
host, at most 8 MB, and the address goes through the same fence as every look-up. The page's text is untrusted data:
it only fills form fields (shown escaped), nothing in it is followed or run.
"""
import html
import json
import re
import sys

MAX_INGREDIENTS = 80
MAX_METHOD = 5000
NAME_MAX = 80


class RecipeError(ValueError):
    pass


def _text(v):
    """Plain text from a JSON-LD value (tags and entities removed, spaces tidied)."""
    if isinstance(v, (list, tuple)):
        v = " ".join(_text(x) for x in v)
    elif isinstance(v, dict):
        v = v.get("text") or v.get("name") or ""
    s = html.unescape(re.sub(r"<[^>]+>", " ", str(v or "")))
    return " ".join(s.split())


def _types(node):
    t = node.get("@type") if isinstance(node, dict) else None
    return {str(x).lower() for x in (t if isinstance(t, list) else [t]) if x}


def _find(node):
    """The first schema.org Recipe in a JSON-LD tree (top level, a list, or an @graph)."""
    if isinstance(node, list):
        for x in node:
            got = _find(x)
            if got:
                return got
        return None
    if not isinstance(node, dict):
        return None
    if "recipe" in _types(node):
        return node
    for key in ("@graph", "mainEntity", "itemListElement"):
        if key in node:
            got = _find(node[key])
            if got:
                return got
    return None


def _steps(v):
    """The method as lines: a string, a list of strings, HowToStep or HowToSection (with its itemListElement)."""
    out = []
    if isinstance(v, str):
        out += [x.strip() for x in re.split(r"\n+", html.unescape(re.sub(r"<[^>]+>", "\n", v))) if x.strip()]
    elif isinstance(v, list):
        for x in v:
            out += _steps(x)
    elif isinstance(v, dict):
        if "howtosection" in _types(v):
            name = _text(v.get("name"))
            if name:
                out.append(name + ":")
            out += _steps(v.get("itemListElement") or [])
        else:
            t = _text(v.get("text") or v.get("name"))
            if t:
                out.append(t)
    return [" ".join(x.split()) for x in out if x.strip()]


def _servings(v):
    m = re.search(r"\d+", _text(v[0] if isinstance(v, list) and v else v))
    if not m:
        return ""
    n = int(m.group())
    return str(n) if 1 <= n <= 50 else ""


def parse(page, url=""):
    """{'name','servings','ingredients' (one per line),'notes' (the method),'url'} from a page's HTML. RecipeError when the
    page has no recipe data."""
    for block in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        r = _find(data)
        if not r:
            continue
        name = _text(r.get("name"))[:NAME_MAX]
        ings = [_text(x) for x in (r.get("recipeIngredient") or r.get("ingredients") or []) if _text(x)][:MAX_INGREDIENTS]
        if not name or not ings:
            continue
        steps = _steps(r.get("recipeInstructions") or [])
        lines, n = [], 0
        for s in steps:  # a section heading ("Prep:") takes no number
            if s.endswith(":"):
                lines.append(s)
            else:
                n += 1
                lines.append(f"{n}. {s}")
        notes = "\n".join(lines)[:MAX_METHOD]
        return {"name": name, "servings": _servings(r.get("recipeYield")), "ingredients": "\n".join(ings),
                "notes": notes, "url": url[:500], "tags": ""}
    raise RecipeError("that page has no recipe this app can read (it reads the recipe data most recipe sites include)")


def from_url(url):
    """Fetch through the look-ups fence and parse. Raises lookups.Refused or RecipeError."""
    import lookups
    ctype, body, final = lookups.get(url, accept="text/html, application/xhtml+xml;q=0.9, */*;q=0.5")
    if "html" not in ctype and not body.lstrip()[:200].lower().startswith((b"<!doctype", b"<html")):
        raise RecipeError("that address is not a web page")
    return parse(body.decode("utf-8", "replace"), final or url)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    import lookups
    try:
        r = from_url(argv[0])
    except (RecipeError, lookups.Refused) as e:
        print(e)
        return 1
    print(f"{r['name']} (serves {r['servings'] or '?'})\n\n{r['ingredients']}\n\n{r['notes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
