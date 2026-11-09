"""Country profile (audit item 17): one place for tax papers, ID types, home-office rule, units, address labels,
seasonal pack and starter rules; US and UK shipped, generic fallback, family override in config/country/."""
import json

import pytest

from conftest import db, q, read_family, run, write_family


def _set_country(root, code):
    fam = read_family(root)
    fam["country"] = code
    write_family(root, fam)


@pytest.fixture
def uk(root):
    _set_country(root, "UK")
    yield root
    _set_country(root, "US")


def test_profiles_load_and_fall_back(modules):
    c = modules("country")
    us, uk, ca, xx = c.load("US"), c.load("gb"), c.load("Canada"), c.load("ZZ")
    assert us["units"]["area"] == "sq ft" and us["tax"]["authority"] == "IRS" and us["seasonal_packs"]["mild"] == "us_mild"
    assert uk["code"] == "UK" and uk["currency"] == "GBP" and uk["tax"]["year_start"] == "04-06" and uk["units"]["area"] == "m²"
    assert ca["code"] == "CA" and ca["currency"] == "CAD" and ca["seasonal_packs"]["cold"] == "canada_cold"
    assert ca["tax"]["checklist"], "a country without its own file still gets the generic tax checklist"
    assert xx["code"] == "ZZ" and xx["currency"] == "USD"
    assert {"US", "UK", "GENERIC", "CA", "IN"} <= set(c.codes())
    for p in (us, uk, xx):
        assert all(len(r) == 3 for r in p["tax"]["checklist"]) and all(len(r) == 4 for r in p["starter_rules"])
        assert p["home_office"]["method"] in ("per_area", "flat_rate_weekly", "none")
    assert c.seasonal_pack("hot", "US") == "us_hot" and c.seasonal_pack("cold", "UK") == "uk"
    assert "P60" in json.dumps(uk["tax"]["checklist"]) and "W-2" in json.dumps(us["tax"]["checklist"])


def test_family_override_wins_over_the_shipped_profile(root, modules):
    c = modules("country")
    over = root / "config" / "country" / "us.json"
    over.parent.mkdir(exist_ok=True)
    over.write_text(json.dumps({"address": {"state": "Commonwealth"}, "tax": {"authority": "IRS (ours)"}}), encoding="utf-8")
    try:
        p = c.load("US")
        assert p["address"]["state"] == "Commonwealth" and p["tax"]["authority"] == "IRS (ours)"
        assert p["address"]["zip"] == "ZIP (optional)" and p["starter_rules"], "everything not overridden is kept"
    finally:
        over.unlink()
    assert c.load("US")["address"]["state"] == "State"


def test_tax_checklist_follows_the_country(root, uk):
    r = run(["data/tax_prep.py", "2026"], root)
    assert r.returncode == 0, r.stderr[-300:]
    md = (root / "reports" / "2026_tax_prep.md").read_text(encoding="utf-8")
    assert "P60" in md and "HMRC" in md and "6 April" in md and "W-2" not in md
    _set_country(root, "US")
    run(["data/tax_prep.py", "2026"], root)
    md = (root / "reports" / "2026_tax_prep.md").read_text(encoding="utf-8")
    assert "W-2" in md and "P60" not in md


def test_home_office_uses_the_country_rule(root, uk, modules):
    ho = modules("home_office")
    con = db(root)
    con.execute("INSERT OR IGNORE INTO home_office_profile(tax_year, who, office_sqft, home_sqft, months_used, self_employed) "
                "VALUES (2031, 'Alex', 10, 100, 12, 1)")
    con.commit()
    try:
        c = ho.compute(con, 2031, "Alex")
        assert c["simplified"] == 6.0 * 52 and c["unit"] == "m²" and c["rule"]["method"] == "flat_rate_weekly"
        _set_country(root, "US")
        c = ho.compute(con, 2031, "Alex")
        assert c["simplified"] == 10 * 5.0 and c["unit"] == "sq ft"
    finally:
        con.execute("DELETE FROM home_office_profile WHERE tax_year=2031 AND who='Alex'")
        con.commit()
        con.close()


def test_starter_rules_and_id_types_follow_the_country(root, uk):
    assert run(["data/apply_rules.py"], root).returncode == 0
    pats = {p for (p,) in q(root, "select pattern from category_rules")}
    assert "TESCO%" in pats and "HMRC%" in pats
    r = run(["data/id_docs.py", "add", "Alex", "brp", "--expires", "2030-01-01"], root)
    assert r.returncode == 0, r.stderr[-200:]
    r = run(["data/id_docs.py", "add", "Alex", "green_card", "--expires", "2030-01-01"], root)
    assert r.returncode != 0, "a US-only document type is not offered to a UK family"
    assert run(["data/seasonal_packs.py", "recommend", "GB"], root).stdout.strip() == "uk"
    assert run(["data/seasonal_packs.py", "recommend", "US", "hot"], root).stdout.strip() == "us_hot"


def test_country_cli_describes_profiles(root):
    out = run(["data/country.py", "list"], root).stdout
    assert "United Kingdom" in out and "United States" in out and "GBP" in out
