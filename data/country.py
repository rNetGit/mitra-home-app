"""Country profile: the one place that knows which tax papers, ID types, home-office rule, units, address fields,
seasonal pack and starter categorisation rules apply to this household.

    import country
    p = country.profile()            # the family's profile (config/family.json `country`, default US)
    p["tax"]["checklist"]            # [[label, keywords, note], ...] for tax_prep
    country.units()["area"]          # "sq ft" or "m²"
    country.codes()                  # profiles shipped in packs/country/

Profiles are JSON files in packs/country/<code>.json; a file with the same name in config/country/ overrides the
shipped one (so a family can fix a label or add a form without waiting for a release). Codes with no file of their
own (CA, AU, NZ, IN, ...) fall back to generic.json plus the currency, units and seasonal pack from FALLBACK below.
"""
import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import paths  # noqa: E402
import config  # noqa: E402

SHIPPED = HERE.parent / "packs" / "country"
LOCAL = paths.CONFIG / "country"
ALIASES = {"USA": "US", "UNITED STATES": "US", "UNITED KINGDOM": "UK", "GB": "UK", "ENGLAND": "UK", "SCOTLAND": "UK", "WALES": "UK",
           "CANADA": "CA", "AUSTRALIA": "AU", "NEW ZEALAND": "NZ", "INDIA": "IN", "IRELAND": "IE", "GERMANY": "DE"}
# currency, metric?, seasonal packs by climate; used when there is no packs/country/<code>.json
FALLBACK = {
    "CA": ("CAD", True, {"cold": "canada_cold", "mild": "canada_cold", "hot": "canada_cold"}),
    "AU": ("AUD", True, {"cold": "australia_nz", "mild": "australia_nz", "hot": "australia_nz"}),
    "NZ": ("NZD", True, {"cold": "australia_nz", "mild": "australia_nz", "hot": "australia_nz"}),
    "IN": ("INR", True, {"cold": "india", "mild": "india", "hot": "india"}),
    "IE": ("EUR", True, {"cold": "uk", "mild": "uk", "hot": "uk"}),
}
_CACHE = {}


def normalize(code):
    c = (code or "US").strip().upper()
    return ALIASES.get(c, c)


def codes():
    out = set()
    for folder in (SHIPPED, LOCAL):
        if folder.exists():
            out |= {f.stem.upper() for f in folder.glob("*.json")}
    return sorted(out | set(FALLBACK))


def _read(code, folder=SHIPPED):
    f = folder / f"{code.lower()}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def load(code):
    """Profile dict for a country code; unknown codes get the generic profile tagged with that code."""
    code = normalize(code)
    key = (code, tuple(sorted(f.name + str(f.stat().st_mtime_ns) for f in LOCAL.glob("*.json"))) if LOCAL.exists() else (code,))
    if key in _CACHE:
        return copy.deepcopy(_CACHE[key])
    base = _read("generic") or {}
    own = _read(code)
    local = _read(code, LOCAL)  # the family's own edits sit on top of the shipped profile
    prof = copy.deepcopy(base)
    if own or local:
        _merge(prof, own or {})
        _merge(prof, local or {})
        prof.setdefault("code", code)
    else:
        prof["code"] = code
        cur, metric, packs = FALLBACK.get(code, (prof.get("currency", "USD"), prof.get("metric", True), prof.get("seasonal_packs", {})))
        prof["currency"], prof["metric"], prof["seasonal_packs"] = cur, metric, packs
        prof["name"] = code
    if not prof.get("metric", True):
        prof.setdefault("units", {}).update({"area": "sq ft", "distance": "mi", "temperature": "F"})
    else:
        prof.setdefault("units", {}).update({k: v for k, v in (("area", "m²"), ("distance", "km"), ("temperature", "C")) if k not in prof.get("units", {})})
    _CACHE[key] = prof
    return copy.deepcopy(prof)


def _merge(base, over):
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v


def code():
    return normalize(config.family().get("country", "US"))


def profile():
    return load(code())


def units():
    return profile()["units"]


def seasonal_pack(climate="cold", code_=None):
    p = load(code_) if code_ else profile()
    packs = p.get("seasonal_packs") or {}
    return packs.get((climate or "cold").lower()) or packs.get("cold") or "generic"


def describe(p=None):
    p = p or profile()
    ho = p.get("home_office", {})
    return (f"{p.get('name', p.get('code'))} ({p.get('code')}): currency {p.get('currency')}, {p['units']['area']} / {p['units']['distance']}, "
            f"tax year from {p.get('tax', {}).get('year_start', '01-01')} ({p.get('tax', {}).get('authority', '')}), "
            f"home office: {ho.get('label', 'none')}, {len(p.get('tax', {}).get('checklist', []))} tax papers, "
            f"{len(p.get('id_types', []))} ID types, {len(p.get('starter_rules', []))} starter rules")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else None
    if which == "list":
        for c in codes():
            print(f"{c:<4} {describe(load(c))}")
    else:
        print(describe(load(which) if which else profile()))
