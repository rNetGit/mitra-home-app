"""Brand constants (data/brand.py): the product name a person reads comes from one place, the older FamilyAgent name
survives only where an install from before the rename needs it, and renaming the Google calendar never makes a second
calendar."""
import ast
import re


# Literals that contain the product name on purpose: ids, not text a person reads.
FROZEN = {"-//Mitra Home//due dates//EN"}  # PRODID of the calendar file
# The only places the old name may still appear in code: things installed or saved before the rename, and values that
# older installs check (see the docstring of data/brand.py).
LEGACY_OK = {"FamilyAgent", "familyagent", "familyagent:", "@familyagent", "familyagent_home.txt", "rNetGit/FamilyAgent.Ai",
             "# FamilyAgent release manifest", "not a FamilyAgent release manifest"}


def _literals(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body \
                and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant):
            docs.add(id(n.body[0].value))
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
            yield n.lineno, n.value


def test_no_page_or_message_hard_codes_the_product_name(root):
    bad = []
    for p in sorted((root / "data").rglob("*.py")):
        if "backups_pre_upgrade" in p.parts or p.name.startswith("migrate_0") or p.name == "brand.py":
            continue
        for line, text in _literals(p):
            if "Mitra Home" in text and text not in FROZEN:
                bad.append(f"{p.relative_to(root)}:{line}: {text[:70]!r}")
            if re.search("(?i)family ?agent", text) and text not in LEGACY_OK:
                bad.append(f"{p.relative_to(root)}:{line}: old name {text[:70]!r}")
    assert not bad, "use brand.PRODUCT / brand.SLUG (or add an id to FROZEN, a pre-rename value to LEGACY_OK):\n" + "\n".join(bad)


def test_brand_names_and_frozen_names(modules):
    b = modules("brand")
    assert b.PRODUCT == "Mitra Home" and b.AGENT == "Mitra" and b.CALENDAR_NAME == b.PRODUCT
    assert "FamilyAgent" in b.KNOWN_CALENDAR_NAMES, "calendars made by earlier versions are still recognised"
    assert b.BACKUP_DIR == "Mitra-Home-Backup" and b.LEGACY_BACKUP_DIRS == ("MitraHome_backups", "FamilyAgent_backups")
    assert b.HOME_DIR == "Mitra-Home-Data"
    assert (b.SLUG, b.ENV_PREFIX, b.LEGACY_ENV_PREFIX) == ("MitraHome", "MITRAHOME_", "FAMILYAGENT_")
    ap = modules("agent_profile")
    assert ap.DEFAULTS["name"] == b.AGENT
    assert ap.TASK_NAMES == {"daily_digest": "Mitra Home Daily Digest", "weekly_digest": "Mitra Home Weekly Digest",
                             "weekly_backup": "Mitra Home Weekly Backup"}


def test_texts_follow_the_constant(modules, monkeypatch):
    import datetime

    b = modules("brand")
    ics = modules("export_ics")
    monkeypatch.setattr(b, "PRODUCT", "Hearth")
    text = ics.build([], datetime.date.today())
    assert "X-WR-CALDESC:Due dates from Hearth on this household" in text
    assert "Mitra Home" not in text.replace("-//Mitra Home//due dates//EN", ""), "only the frozen PRODID keeps the old name"
    aa = modules("admin_actions")
    assert aa.brand is b


def _fake_google(monkeypatch, cs, summary):
    calls = []

    def _get(path, params, token):
        calls.append(("GET", path))
        return {"summary": summary, "timeZone": "America/Chicago"}

    def _send(method, path, body=None, params=None, token=None):
        calls.append((method, path, body))
        return {"id": "cal-NEW@group.calendar.google.com", "summary": (body or {}).get("summary")}

    monkeypatch.setattr(cs.gc, "_get", _get)
    monkeypatch.setattr(cs.gc, "_send", _send)
    return calls


def test_renaming_the_calendar_renames_it_in_place(modules, monkeypatch):
    cs = modules("calendar_sync")
    monkeypatch.setattr(cs, "CAL_NAME", "Hearth")
    calls = _fake_google(monkeypatch, cs, "FamilyAgent")  # made by a version from before the rename
    st = {"calendar_id": "cal-OLD@group.calendar.google.com", "events": {"a": 1}}
    assert cs._ensure_calendar(st, "tok") == "cal-OLD@group.calendar.google.com"
    assert ("PATCH", "/calendars/cal-OLD%40group.calendar.google.com", {"summary": "Hearth"}) in calls
    assert not any(c[0] == "POST" for c in calls), "no second calendar"
    assert st["calendar_name"] == "Hearth" and st["events"] == {"a": 1}, "events are kept"
    calls.clear()
    _fake_google(monkeypatch, cs, "Hearth")  # now it already has the new name: nothing to change
    assert cs._ensure_calendar(st, "tok") == "cal-OLD@group.calendar.google.com"


def test_a_calendar_that_is_not_ours_is_never_touched(modules, monkeypatch):
    cs = modules("calendar_sync")
    calls = _fake_google(monkeypatch, cs, "Work stuff")
    st = {"calendar_id": "someone-elses@group.calendar.google.com", "events": {"a": 1}}
    cid = cs._ensure_calendar(st, "tok")
    assert cid == "cal-NEW@group.calendar.google.com", "a new calendar of our own is made"
    assert not any(c[0] == "PATCH" for c in calls) and st["events"] == {}
    assert cs._ours("Work stuff", {}) is False and cs._ours("Mitra Home", {}) is True and cs._ours("FamilyAgent", {}) is True and cs._ours("", {"calendar_name": ""}) is False
    assert cs._ours("Old Name", {"calendar_name": "Old Name"}) is True


def test_remove_deletes_a_renamed_calendar_only_by_a_known_name(modules, monkeypatch, root):
    cs = modules("calendar_sync")
    monkeypatch.setattr(cs, "_require", lambda: None)
    monkeypatch.setattr(cs.gc, "access_token", lambda: "tok")
    state = root / "config" / "calendar_sync.json"
    for summary, expect in (("FamilyAgent", True), ("Work stuff", False)):
        state.write_text('{"calendar_id": "cal-X@group.calendar.google.com", "calendar_name": "Hearth"}', encoding="utf-8")
        calls = _fake_google(monkeypatch, cs, summary)
        assert cs.remove() is True
        assert any(c[0] == "DELETE" for c in calls) is expect
        assert not state.exists()
