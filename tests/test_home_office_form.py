"""Money > Home office: the "Set up your home office" Add form (edit_money.home_office_set, records_edit.add)."""
from conftest import q

ADULT = {"name": "Alex", "role": "adult"}
KID = {"name": "Sam", "role": "limited"}


def test_adults_set_up_and_update_a_home_office_profile(root, modules):
    ea, re_ = modules("edit_actions"), modules("records_edit")
    assert ("money", "home_office") in re_.EDIT_PARTS
    assert [a["table"] for a in re_.adds(("money", "home_office"))] == ["home_office_profile"]
    ok, msg = ea.home_office_set(ADULT, "2026", "Alex", "120", "1800", "12", "simplified", "1", "1", "1", "", "50000")
    assert ok, msg
    assert q(root, "SELECT who, office_sqft, home_sqft, months_used, method, self_employed, exclusive_use, regular_use, "
                   "principal_place, gross_income FROM home_office_profile WHERE tax_year=2026") == \
        [("Alex", 120.0, 1800.0, 12, "simplified", 1, 1, 1, None, 50000.0)]
    ok, msg = ea.home_office_set(ADULT, "2026", "Alex", office_sqft="150", principal="0")
    assert ok, msg
    assert q(root, "SELECT office_sqft, home_sqft, principal_place FROM home_office_profile") == [(150.0, 1800.0, 0)], \
        "saving again updates only what was sent"


def test_home_office_form_refusals(root, modules):
    ea, re_ = modules("edit_actions"), modules("records_edit")
    before = q(root, "SELECT COUNT(*) FROM home_office_profile")
    assert ea.home_office_set(KID, "2026", "Alex", "10", "100")[0] is False, "children cannot"
    assert ea.home_office_set(ADULT, "2026", "Nobody", "10", "100")[0] is False
    assert ea.home_office_set(ADULT, "1999", "Alex", "10", "100")[0] is False
    assert ea.home_office_set(ADULT, "2026", "Alex", "10", "100", method="bogus")[0] is False
    assert ea.home_office_set(ADULT, "2026", "Alex", "10", "100", months="13")[0] is False
    assert ea.home_office_set(ADULT, "2026", "Alex", "10", "100", exclusive="2")[0] is False
    assert q(root, "SELECT COUNT(*) FROM home_office_profile") == before, "a refusal writes nothing"
    ok, msg = re_.add(ADULT, ("money", "home_office"), {"table": "home_office_profile", "year": "2025", "who": "Alex",
                                                       "office": "100", "home": "1000", "months": "6", "method": "regular",
                                                       "self_employed": "1", "exclusive": "", "regular": "", "principal": "",
                                                       "income": ""})
    assert ok, msg
    assert q(root, "SELECT months_used, method, exclusive_use FROM home_office_profile WHERE tax_year=2025 AND who='Alex'") == [(6, "regular", None)]

