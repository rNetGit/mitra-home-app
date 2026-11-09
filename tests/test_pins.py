"""Sign-in PINs from the dashboard (admin_actions.pin_set, Settings > Agent > Sign-in PINs)."""
import pytest
from conftest import read_family, write_family


@pytest.fixture()
def aa(root, modules, chdir_root):
    import admin_actions
    import auth
    fam = read_family(root)
    fam.pop("dashboard_users", None)
    fam.pop("dashboard_pin", None)
    fam["members"] = [{"name": "Asha", "role": "adult"}, {"name": "Ravi", "role": "child"}]
    write_family(root, fam)
    auth.config.family.cache_clear() if hasattr(auth.config.family, "cache_clear") else None
    return admin_actions


ADULT = {"name": "", "role": "adult"}


def test_first_pin_needs_no_current_pin_and_children_are_limited(aa):
    import auth
    ok, msg = aa.pin_set(ADULT, "Asha", "4821", "4821")
    assert ok, msg
    assert [u["name"] for u in auth.users()] == ["Asha"]
    ok, msg = aa.pin_set({"name": "Asha", "role": "adult"}, "Ravi", "7352", "7352", current="4821")
    assert ok, msg
    assert {u["name"]: u["role"] for u in auth.users()} == {"Asha": "adult", "Ravi": "limited"}
    assert auth.login("Ravi", "7352")


def test_refusals(aa):
    import auth
    assert not aa.pin_set({"name": "Ravi", "role": "limited"}, "Ravi", "4821", "4821")[0]
    assert "same" in aa.pin_set(ADULT, "Asha", "4821", "4822")[1]
    assert "4 characters" in aa.pin_set(ADULT, "Asha", "12", "12")[1]
    assert not aa.pin_set(ADULT, "Asha", "1111", "1111")[0]
    assert not aa.pin_set(ADULT, "Nobody", "4821", "4821")[0]
    assert aa.pin_set(ADULT, "Asha", "4821", "4821")[0]
    me = {"name": "Asha", "role": "adult"}
    assert aa.pin_set(me, "Asha", "9753", "9753")[0], "a forgotten PIN is replaced without the old one"
    assert aa.pin_set(me, "Asha", "8642", "8642", current="wrong")[0], "a typed old PIN is ignored"
    assert auth.login("Asha", "8642") and not auth.login("Asha", "9753")
    assert not aa.pin_set({"name": "Ravi", "role": "limited"}, "Asha", "1357", "1357")[0], "children still cannot change a PIN"
    assert auth.login("Asha", "8642")


def test_audit_never_holds_the_pin(aa, root):
    aa.pin_set(ADULT, "Asha", "4821", "4821")
    log = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "pin_set" in log and "4821" not in log
