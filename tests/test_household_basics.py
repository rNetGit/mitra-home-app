"""Settings > Household profile > Your answers: family name, country and own / rent can be corrected after setup."""
from conftest import read_family

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


def test_the_first_run_answers_can_be_corrected_later(root, modules):
    ea = modules("edit_actions")
    sd = modules("settings_data")
    assert ea.household_basics_set(KID, "Smith", "US", "own")[0] is False, "adults only"
    assert ea.household_basics_set(ADULT, "", "US", "own")[0] is False, "a family name is needed"
    assert ea.household_basics_set(ADULT, "Smith", "ZZ-not-a-country", "own")[0] is False
    assert ea.household_basics_set(ADULT, "Smith", "US", "lease")[0] is False
    ok, msg = ea.household_basics_set(ADULT, "Khan", "US", "rent")
    assert ok, msg
    fam = read_family(root)
    assert (fam["family_name"], fam["household"]["tenure"]) == ("Khan", "rent")
    assert sd.basics()["family_name"] == "Khan" and sd.basics()["tenure"] == "rent"
    assert ea.household_basics_set(ADULT, "Khan", "US", "rent") == (True, "Nothing changed.")
    fam["region"] = {"place": "Austin", "state": "TX", "zip": "78701"}
    modules("config").write_json(root / "config" / "family.json", fam)
    ok, msg = ea.household_basics_set(ADULT, "Khan", "UK", "rent")
    assert ok and "cleared" in msg
    fam = read_family(root)
    assert fam["country"] == "UK" and fam["region"]["state"] == "" and fam["region"]["zip"] == ""
    assert fam["region"]["place"] == "Austin", "the city is kept"
    audit = (root / "logs" / "edits.log").read_text(encoding="utf-8")
    assert "household_basics_set" in audit and "Khan" not in audit
    ea.household_basics_set(ADULT, "Khan", "US", "")
    assert "tenure" not in read_family(root).get("household", {})
