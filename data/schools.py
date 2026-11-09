"""Schools near home and college names, from the US Department of Education's public school directory (NCES EDGE
locations: public and private schools, school districts, colleges). No key, no AI, US only.

Only the home ZIP code, a radius around it, and words of a school or college name leave this PC, through lookups.get()
(the family's switch and privacy fence). Nothing about a person is sent.

  python data/schools.py near ZIP [--km 12]       schools around a ZIP code
  python data/schools.py college "NAME" [--state NJ]   is this a college's name? (closest matches)

Library: near(zip_code, km=12) -> [school]; colleges(text, state=None) -> [college]; check_college(text, state=None) ->
{"match": college | None, "suggest": [college]}. A school / college = {"kind", "name", "ext_id", "district", "city",
"state", "zip", "km"}.
"""
import argparse
import difflib
import json
import math
import re
import sys
import urllib.parse

import pathlib
HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import lookups  # noqa: E402

BASE = "https://nces.ed.gov/opengis/rest/services"
# The newest layer of each kind checked on 2026-10-18; NCES adds a layer each year and keeps the older ones.
LAYERS = {"public": "K12_School_Locations/EDGE_GEOCODE_PUBLICSCH_2425",
          "private": "K12_School_Locations/EDGE_GEOCODE_PRIVATESCH_2324",
          "district": "K12_School_Locations/EDGE_GEOCODE_PUBLICLEA_2425",
          "college": "Postsecondary_School_Locations/EDGE_GEOCODE_POSTSECONDARYSCH_2526"}
ID_FIELD = {"public": "NCESSCH", "private": "PPIN", "college": "UNITID", "district": "LEAID"}
ZIP = re.compile(r"^\d{5}$")
MAX_ROWS = 400
SHOWN = 60
NAME_WORD = re.compile(r"[A-Za-z0-9&]+")
STOP = {"of", "the", "and", "at", "in", "for", "school", "college", "university", "academy", "inc"}


class SchoolError(ValueError):
    pass


def _query(layer, params):
    q = {"outFields": "*", "f": "json", "returnGeometry": "false", "resultRecordCount": str(MAX_ROWS), **params}
    url = f"{BASE}/{LAYERS[layer]}/MapServer/0/query?" + urllib.parse.urlencode(q)
    _ctype, body, _final = lookups.get(url, accept="application/json")
    try:
        data = json.loads(body.decode("utf-8", "replace"))
    except ValueError:
        raise SchoolError("The school directory sent something unreadable; try again later.") from None
    if "error" in data:
        raise SchoolError("The school directory did not answer the question; try again later.")
    return [f.get("attributes") or {} for f in data.get("features") or []]


def _km(a_lat, a_lon, b_lat, b_lon):
    p = math.pi / 180
    h = (math.sin((b_lat - a_lat) * p / 2) ** 2
         + math.cos(a_lat * p) * math.cos(b_lat * p) * math.sin((b_lon - a_lon) * p / 2) ** 2)
    return 12742 * math.asin(math.sqrt(h))


def _title(s):
    """'LINCOLN MIDDLE SCHOOL' -> 'Lincoln Middle School' (names already in mixed case stay as they are)."""
    s = " ".join(str(s or "").split())
    if s.isupper():
        s = " ".join(w if len(w) <= 3 and w in ("PS", "IS", "MS", "HS", "JHS", "K-8", "STEM", "KIPP") else w.capitalize()
                     for w in s.split())
    return s[:100]


def _row(kind, a, lat=None, lon=None, districts=None):
    out = {"kind": "college" if kind == "college" else "school", "name": _title(a.get("NAME")),
           "ext_id": str(a.get(ID_FIELD[kind]) or "")[:20] or None, "district": None,
           "city": _title(a.get("CITY"))[:60] or None, "state": (a.get("STATE") or "")[:20] or None,
           "zip": str(a.get("ZIP") or "")[:5] or None, "km": None, "private": kind == "private"}
    if districts and a.get("LEAID"):
        out["district"] = districts.get(str(a["LEAID"]))
    if lat is not None and a.get("LAT") is not None and a.get("LON") is not None:
        out["km"] = round(_km(lat, lon, float(a["LAT"]), float(a["LON"])), 1)
    return out


def _districts(ids):
    ids = sorted({i for i in ids if re.fullmatch(r"\d{7}", str(i or ""))})[:100]
    if not ids:
        return {}
    where = "LEAID IN (" + ",".join(f"'{i}'" for i in ids) + ")"
    try:
        rows = _query("district", {"where": where, "outFields": "LEAID,NAME"})
    except (SchoolError, lookups.Refused):
        return {}
    return {str(r.get("LEAID")): _title(r.get("NAME")) for r in rows if r.get("LEAID")}


def near(zip_code, km=12):
    """Public and private schools within km of the ZIP code's schools (the ZIP's centre is the mean of its schools'
    positions; a ZIP with no school of its own: ask with a nearby ZIP). Nearest first, at most SHOWN."""
    z = str(zip_code or "").strip()[:5]
    if not ZIP.match(z):
        raise SchoolError("The home ZIP code is missing or not 5 digits (Family > House > edit).")
    here = _query("public", {"where": f"ZIP='{z}'", "outFields": "LAT,LON"}) + \
        _query("private", {"where": f"ZIP='{z}'", "outFields": "LAT,LON"})
    pts = [(float(r["LAT"]), float(r["LON"])) for r in here if r.get("LAT") is not None and r.get("LON") is not None]
    if not pts:
        raise SchoolError(f"No schools are listed in ZIP {z}. Try a nearby ZIP code, or type the school's name.")
    lat = sum(p[0] for p in pts) / len(pts)
    lon = sum(p[1] for p in pts) / len(pts)
    km = max(2, min(float(km), 40))
    dlat = km / 111.0
    dlon = km / (111.0 * max(0.2, math.cos(lat * math.pi / 180)))
    box = {"geometry": f"{lon - dlon:.4f},{lat - dlat:.4f},{lon + dlon:.4f},{lat + dlat:.4f}",
           "geometryType": "esriGeometryEnvelope", "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
           "where": "1=1"}
    pub = _query("public", box)
    priv = _query("private", box)
    dist = _districts(r.get("LEAID") for r in pub)
    rows = [_row("public", a, lat, lon, dist) for a in pub] + [_row("private", a, lat, lon) for a in priv]
    rows = [r for r in rows if r["name"] and (r["km"] is None or r["km"] <= km)]
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["km"] if r["km"] is not None else 999, r["name"])):
        k = (r["name"].lower(), r["city"])
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out[:SHOWN]


def _words(text):
    return [w.upper() for w in NAME_WORD.findall(str(text or "")) if w.lower() not in STOP and len(w) >= 2][:5]


def colleges(text, state=None):
    """Colleges whose name holds every word typed (school words like 'University' are not needed), best first."""
    words = _words(text)
    if not words:
        raise SchoolError("Type a few letters of the college's name.")
    lookups.check_out(" ".join(words))
    where = " AND ".join(f"UPPER(NAME) LIKE '%{w}%'" for w in words)
    st = str(state or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}", st):
        where += f" AND STATE='{st}'"
    rows = [_row("college", a) for a in _query("college", {"where": where, "outFields": "UNITID,NAME,CITY,STATE,ZIP"})]
    want = " ".join(str(text).split()).lower()
    for r in rows:
        r["score"] = round(difflib.SequenceMatcher(None, want, r["name"].lower()).ratio(), 3)
    return sorted(rows, key=lambda r: (-r["score"], r["name"]))[:10]


def _plain(s):
    return " ".join(re.findall(r"[a-z0-9&]+", str(s or "").lower()))


def _near_spelling(text, state=None):
    """A typo in the name ('Prinston'): every college whose name has a word starting like the longest word typed,
    ranked by how close the whole name is."""
    words = sorted(_words(text), key=len, reverse=True)
    if not words or len(words[0]) < 4:
        return []
    w = words[0][:3]
    where = f"(UPPER(NAME) LIKE '{w}%' OR UPPER(NAME) LIKE '% {w}%')"
    st = str(state or "").strip().upper()
    if re.fullmatch(r"[A-Z]{2}", st):
        where += f" AND STATE='{st}'"
    rows = [_row("college", a) for a in _query("college", {"where": where, "outFields": "UNITID,NAME,CITY,STATE,ZIP"})]
    want = _plain(text)
    for r in rows:
        r["score"] = round(difflib.SequenceMatcher(None, want, _plain(r["name"])).ratio(), 3)
    return [r for r in sorted(rows, key=lambda r: (-r["score"], r["name"])) if r["score"] >= 0.6][:10]


def check_college(text, state=None):
    """{"match": the college when the name typed is exactly one college's name (case and punctuation aside),
    "suggest": closest names}. A name with a typo gets the closest spellings."""
    found = colleges(text, state)
    if not found:
        found = _near_spelling(text, state)
    want = _plain(text)
    exact = [r for r in found if _plain(r["name"]) == want]
    return {"match": exact[0] if len(exact) == 1 else None, "suggest": [r for r in found if r not in exact][:6] or exact}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("near")
    n.add_argument("zip")
    n.add_argument("--km", type=float, default=12)
    c = sub.add_parser("college")
    c.add_argument("name")
    c.add_argument("--state")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "near":
            for r in near(a.zip, a.km):
                print(f"{r['km']:5.1f} km  {r['name']}  ({r['city']}, {r['state']}){' private' if r['private'] else ''}"
                      + (f"  - {r['district']}" if r["district"] else ""))
        else:
            res = check_college(a.name, a.state)
            print("Match: " + (f"{res['match']['name']} ({res['match']['city']}, {res['match']['state']})"
                               if res["match"] else "none"))
            for r in res["suggest"]:
                print(f"  did you mean {r['name']} ({r['city']}, {r['state']})?")
    except (SchoolError, lookups.Refused) as e:
        print(e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
