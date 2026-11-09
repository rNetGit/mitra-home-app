"""config/family.json is never replaced by something smaller because it could not be read: config.write_json refuses
to write over a file that does not parse, writers report that instead of saving {}, and every write uses its own temp
file (two writers at once never install each other's half-written file)."""
import pytest

from conftest import run

ADULT = {"name": "Alex", "role": "adult"}
BROKEN = '{"family_name": "Test", "members": [{"name": "Alex"'  # a hand edit cut short


def _fam(root):
    return root / "config" / "family.json"


def test_write_json_refuses_a_file_that_does_not_parse(root, modules):
    config = modules("config")
    good = _fam(root).read_text(encoding="utf-8")
    try:
        _fam(root).write_text(BROKEN, encoding="utf-8")
        with pytest.raises(config.Broken):
            config.write_json(_fam(root), {"members": []})
        assert _fam(root).read_text(encoding="utf-8") == BROKEN, "left exactly as it was"
        config.write_json(_fam(root), {"family_name": "Repaired"}, replace_broken=True)
        assert '"Repaired"' in _fam(root).read_text(encoding="utf-8")
    finally:
        _fam(root).write_text(good, encoding="utf-8")


def test_an_empty_file_can_be_written_and_no_temp_files_are_left(root, modules, tmp_path):
    config = modules("config")
    p = tmp_path / "prefs.json"
    p.write_text("", encoding="utf-8")
    config.write_json(p, {"a": 1})
    config.write_json(p, {"a": 2})
    assert p.read_text(encoding="utf-8").strip().endswith("}") and '"a": 2' in p.read_text(encoding="utf-8")
    assert [f.name for f in tmp_path.iterdir()] == ["prefs.json"]


def test_writers_report_a_broken_file_instead_of_wiping_it(root, modules):
    ea = modules("edit_actions")
    good = _fam(root).read_text(encoding="utf-8")
    try:
        _fam(root).write_text(BROKEN, encoding="utf-8")
        ok, msg = ea.household_set(ADULT, "tenure", "own")
        assert ok is False and "cannot be read" in msg, msg
        assert _fam(root).read_text(encoding="utf-8") == BROKEN
        r = run(["data/purge.py", "person", "Sam", "--yes"], root)
        assert r.returncode != 0 and "cannot be read" in r.stdout + r.stderr
        assert _fam(root).read_text(encoding="utf-8") == BROKEN
    finally:
        _fam(root).write_text(good, encoding="utf-8")


def test_family_edit_never_loses_a_concurrent_change(root, modules):
    """Read-modify-write under one lock: two writers at once both land (before, the later save dropped the other)."""
    import threading
    config = modules("config")
    with config.family_edit() as cfg:
        cfg["counter"] = 0

    def bump():
        for _ in range(15):
            with config.family_edit() as cfg:
                cfg["counter"] = cfg.get("counter", 0) + 1
                config.write_json(_fam(root), cfg)  # re-entrant: a save inside the block does not wait for itself

    ts = [threading.Thread(target=bump) for _ in range(3)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert config.family()["counter"] == 45


def test_family_edit_refuses_a_broken_file_and_saves_nothing_on_error(root, modules):
    config = modules("config")
    good = _fam(root).read_text(encoding="utf-8")
    try:
        _fam(root).write_text(BROKEN, encoding="utf-8")
        with pytest.raises(config.Broken):
            with config.family_edit() as cfg:
                cfg["x"] = 1
        assert _fam(root).read_text(encoding="utf-8") == BROKEN
    finally:
        _fam(root).write_text(good, encoding="utf-8")
    with pytest.raises(RuntimeError):
        with config.family_edit() as cfg:
            cfg["half_done"] = True
            raise RuntimeError("stopped")
    assert "half_done" not in config.family()


def test_family_edit_gives_up_with_a_sentence_when_the_lock_stays_taken(root, modules, monkeypatch):
    import os
    import time
    config, jl = modules("config"), modules("joblock")
    real = jl.held
    monkeypatch.setattr(jl, "held", lambda name, stale_after=0, wait=0: real(name, stale_after, 0.2))
    p = jl.lock_path("family_json")
    p.write_text(f"{os.getppid()} {int(time.time())}\n", encoding="utf-8")
    try:
        with pytest.raises(config.Busy, match="nothing was changed"):
            with config.family_edit():
                pass
    finally:
        p.unlink(missing_ok=True)
