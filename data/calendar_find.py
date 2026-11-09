"""Find where a school's, college's or employer's year calendar lives on the web, so an adult can pick it and import it
(calendar_import). Nothing is imported here and no date is read here.

1. The page the calendar came from last time (a new school year usually sits on the same page).
2. The family's AI searches the web (llm.web_lookup; API providers only) with the public name, city and state and the
   school year: "official 2026-27 calendar of <school>, <district>, <city> <state>". No one's name goes out.
3. Each page found is read for links that look like the calendar itself (.ics feeds, PDFs named for the year).
Every request passes lookups (the family's switch and the privacy fence). At most MAX_FETCH pages per search.

  python data/calendar_find.py ORG_ID          candidates for one org (needs look-ups on)
"""
import argparse
import html
import json
import re
import sqlite3
import sys
import urllib.parse

import pathlib
HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import dates  # noqa: E402
import lookups  # noqa: E402

MAX_FETCH = 6
SHOWN = 6
HREF = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
URL = re.compile(r"""(?:https?|webcal)://[^\s"'<>\)\]}]+""", re.I)
BAD = re.compile(r"(?i)\b(?:board|minutes|agenda|meeting|lunch|menu|athletic|sports?|bus|budget|testing|exams?|"
                 r"newsletter|login|signin)\b|facebook\.|twitter\.|instagram\.|youtube\.|mailto:")
WORDS = {"school": "school year calendar", "college": "academic calendar", "employer": "holiday schedule"}


class FindError(ValueError):
    pass


def years(today=None):
    """School years worth looking for: the current one first; in May and June next year's first."""
    t = today or dates.today()
    y = t.year if t.month >= 7 else t.year - 1
    now, nxt = (y, y + 1), (y + 1, y + 2)
    order = [nxt, now] if 5 <= t.month <= 6 else [now, nxt]
    return [f"{a}-{str(b)[2:]}" for a, b in order]


def _year_forms(label):
    a, b2 = label.split("-")
    b = str(int(a[:2]) * 100 + int(b2))
    return [label, f"{a}-{b}", f"{a}_{b}", f"{a}{b}", f"{a[2:]}-{b2}", f"{a}-{b2}"]


def _norm(u, base=None):
    u = html.unescape(u.strip())
    if u.lower().startswith("webcal://"):
        u = "https://" + u[9:]
    if base:
        u = urllib.parse.urljoin(base, u)
    u = u.rstrip(".,;")
    try:
        return lookups.safe_url(u)
    except lookups.Refused:
        return None


def kind_of(url):
    p = urllib.parse.urlsplit(url).path.lower()
    q = urllib.parse.urlsplit(url).query.lower()
    if p.endswith(".ics") or "ical" in p or "format=ics" in q or "/ics" in p:
        return "ics"
    if p.endswith(".pdf"):
        return "pdf"
    return "page"


def score(url, text, labels):
    """How much an address and its link text look like this year's calendar (the host name is not read)."""
    u = urllib.parse.urlsplit(url)
    t = f"{u.netloc if re.search(r'facebook|twitter|instagram|youtube', u.netloc) else ''} {u.path} {u.query} {text}".lower()
    s = {"ics": 5, "pdf": 4, "page": 0}[kind_of(url)]
    s += 3 if "calendar" in t else 0
    s += 2 if re.search(r"academic|instructional|district|holiday|closings|year", t) else 0
    if any(f.lower() in t for f in _year_forms(labels[0])):
        s += 4
    elif len(labels) > 1 and any(f.lower() in t for f in _year_forms(labels[1])):
        s += 2
    if BAD.search(t):
        s -= 6
    return s


def links_in(raw_html, base):
    """[(absolute url, link text)] of a page, http(s) only, each address once."""
    out, seen = [], set()
    for href, inner in HREF.findall(raw_html):
        u = _norm(href, base)
        if not u or u in seen:
            continue
        seen.add(u)
        out.append((u, " ".join(html.unescape(re.sub(r"<[^>]+>", " ", inner)).split())[:120]))
    return out


def _question(org, label):
    where = ", ".join(x for x in (org.get("district") if org["kind"] == "school" else None, org.get("city"),
                                   org.get("state")) if x)
    what = WORDS[org["kind"]]
    q = (f"Find the official {label} {what} of {org['name']}" + (f" ({where})" if where else "") + ". "
         "Prefer the organisation's own website: an .ics calendar feed, a calendar PDF for that year, or the calendar page. "
         'Answer ONLY with JSON: {"urls": [{"url": "https://...", "what": "a few words"}]} with at most 4 links.')
    return q


def ask_ai(org, label):
    """URLs the family's AI found on the web (public name only). [] when no web-capable AI is set up."""
    import llm
    if llm.web_ready():
        return []
    q = _question(org, label)
    lookups.check_out(q)
    try:
        text = llm.web_lookup(q)
    except llm.LLMError:
        return []
    urls = []
    m = re.search(r"\{.*\}", text or "", re.S)
    try:
        for x in (json.loads(m.group(0)).get("urls") or []) if m else []:
            if isinstance(x, dict) and x.get("url"):
                urls.append((str(x["url"]), str(x.get("what") or "")[:80]))
    except (ValueError, AttributeError):
        pass
    if not urls:
        urls = [(u, "") for u in URL.findall(text or "")]
    out, seen = [], set()
    for u, what in urls:
        n = _norm(u)
        if n and n not in seen:
            seen.add(n)
            out.append((n, what))
    return out[:4]


def find(org, today=None):
    """-> {"candidates": [{"url", "text", "kind", "score"}], "asked_ai": bool, "notes": [plain words]}."""
    lookups.need_on()
    labels = years(today)
    seeds, notes = [], []
    if org.get("calendar_url"):
        seeds.append((org["calendar_url"], "where the calendar was last time"))
    found = ask_ai(org, labels[0])
    asked = bool(found)
    if not found:
        import llm
        why = llm.web_ready()
        if why:
            notes.append(f"Your AI cannot search the web ({why}). Paste the calendar's link instead.")
        else:
            notes.append("Your AI found no calendar link.")
    seeds += found
    cands, fetched = {}, 0
    for u, text in seeds:
        cands.setdefault(u, {"url": u, "text": text, "kind": kind_of(u), "score": score(u, text, labels) + 2})
        if kind_of(u) != "page" or fetched >= MAX_FETCH:
            continue
        try:
            ctype, body, final = lookups.get(u)
            fetched += 1
        except lookups.Refused as e:
            notes.append(str(e))
            cands[u]["score"] -= 3
            continue
        if "html" not in ctype:
            continue
        for link, ltext in links_in(body.decode("utf-8", "replace"), final):
            s = score(link, ltext, labels)
            if s >= 5 and link not in cands:
                cands[link] = {"url": link, "text": ltext, "kind": kind_of(link), "score": s}
    ranked = sorted(cands.values(), key=lambda c: (-c["score"], c["url"]))
    return {"candidates": [c for c in ranked if c["score"] > 0][:SHOWN], "asked_ai": asked, "notes": notes}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("org_id", type=int)
    a = ap.parse_args(argv)
    import db
    import paths
    with db.open(paths.DB, readonly=True) as con:
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM orgs WHERE id=?", (a.org_id,)).fetchone()
    if not r:
        print("No such school, college or employer.")
        return 1
    try:
        res = find(dict(r))
    except lookups.Refused as e:
        print(e)
        return 1
    for n in res["notes"]:
        print(n)
    for c in res["candidates"]:
        print(f"{c['score']:3d} {c['kind']:<5} {c['url']}  {c['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
