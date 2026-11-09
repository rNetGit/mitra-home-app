"""The FamilyAgent -> Mitra Home rename (0.109): an install made before it keeps working. Keys saved under the old
FAMILYAGENT_ names are found, old environment variables still count, a Gmail setup saved without a label keeps the old
label, the old backup folder is kept, and scheduled tasks are recognised under their old names so they can move."""
import pytest

from conftest import imported_from, SRC


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    with imported_from(SRC / "data", "config") as config:
        monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
        for n in ("MITRAHOME_OPENAI_API_KEY", "FAMILYAGENT_OPENAI_API_KEY"):
            monkeypatch.delenv(n, raising=False)
        yield config


def test_a_key_saved_under_the_old_name_is_found_and_replaced_on_the_next_save(cfg, tmp_path):
    (tmp_path / "secrets.env").write_text("FAMILYAGENT_OPENAI_API_KEY=sk-old\nOTHER=1\n", encoding="utf-8")
    assert cfg.read_secret("MITRAHOME_OPENAI_API_KEY") == "sk-old"
    cfg.write_secret("MITRAHOME_OPENAI_API_KEY", "sk-new")
    text = (tmp_path / "secrets.env").read_text(encoding="utf-8")
    assert "MITRAHOME_OPENAI_API_KEY=sk-new" in text and "FAMILYAGENT_" not in text and "OTHER=1" in text
    assert cfg.read_secret("MITRAHOME_OPENAI_API_KEY") == "sk-new"


def test_the_new_name_wins_and_the_environment_wins_over_the_file(cfg, tmp_path, monkeypatch):
    (tmp_path / "secrets.env").write_text("FAMILYAGENT_OPENAI_API_KEY=old\nMITRAHOME_OPENAI_API_KEY=new\n", encoding="utf-8")
    assert cfg.read_secret("MITRAHOME_OPENAI_API_KEY") == "new"
    monkeypatch.setenv("FAMILYAGENT_OPENAI_API_KEY", "from-env")
    assert cfg.read_secret("MITRAHOME_OPENAI_API_KEY") == "from-env"
    assert cfg.read_secret("SIMPLEFIN_ACCESS_URL") == "", "names without the prefix have no older form"


def test_old_environment_variables_still_count(monkeypatch):
    with imported_from(SRC / "data", "paths") as paths:
        monkeypatch.delenv("MITRAHOME_TOKEN", raising=False)
        monkeypatch.setenv("FAMILYAGENT_TOKEN", "t-old")
        assert paths.env("MITRAHOME_TOKEN") == "t-old"
        monkeypatch.setenv("MITRAHOME_TOKEN", "t-new")
        assert paths.env("MITRAHOME_TOKEN") == "t-new"
        assert paths.env("MITRAHOME_NOT_SET_ANYWHERE", "dflt") == "dflt"


def test_gmail_label_default_old_and_new(modules, root):
    import json
    gm = modules("google_gmail")
    f = root / "config" / "family.json"
    fam = json.loads(f.read_text(encoding="utf-8"))
    try:
        fam.pop("gmail", None)
        f.write_text(json.dumps(fam), encoding="utf-8")
        assert gm.settings()["label"] == "MitraHome", "a new setup gets the new label"
        fam["gmail"] = {"enabled": True}
        f.write_text(json.dumps(fam), encoding="utf-8")
        assert gm.settings()["label"] == "FamilyAgent", "a setup saved before the rename without a label keeps the old one"
        fam["gmail"] = {"enabled": True, "label": "Bills"}
        f.write_text(json.dumps(fam), encoding="utf-8")
        assert gm.settings()["label"] == "Bills"
        assert {"MitraHome/Processed", "FamilyAgent/Processed", "FamilyAgent/Needs review"} <= set(gm.SKIP_LABELS)
    finally:
        fam.pop("gmail", None)
        f.write_text(json.dumps(fam), encoding="utf-8")


def test_scheduled_task_names_and_their_older_form(modules):
    tr = modules("task_register")
    names = [t[0] for t in tr.TASKS] + [tr.INBOX_TASK[0], tr.SWEEP_TASK[0]]
    assert all(n.startswith("Mitra Home ") for n in names)
    assert tr.legacy_name("Mitra Home Daily Digest") == "FamilyAgent Daily Digest"
    assert tr.legacy_name("Something else") is None
    assert all(line.endswith("  # MitraHome") for line in tr.cron_lines(["daily_digest"]))
    assert tr._ours("0 7 * * * cd x && py tasks/run_task.py daily_digest  # FamilyAgent")
    assert tr._ours("0 7 * * * cd x && py tasks/run_task.py daily_digest  # MitraHome")
    assert not tr._ours("0 7 * * * backup_my_photos.sh")
    ap = modules("autostart")
    assert ap._legacy("Mitra Home Telegram Bot") == "FamilyAgent Telegram Bot"


def test_the_old_backup_folder_is_kept_until_a_new_one_exists(tmp_path):
    with imported_from(SRC / "data", "paths") as paths:
        assert paths.backups_dir(tmp_path) == tmp_path / "Mitra-Home-Backup", "a new install"
        (tmp_path / "FamilyAgent_backups").mkdir()
        assert paths.backups_dir(tmp_path) == tmp_path / "FamilyAgent_backups", "an install from before the rename"
        (tmp_path / "MitraHome_backups").mkdir()
        assert paths.backups_dir(tmp_path) == tmp_path / "MitraHome_backups", "0.109: the newer old name wins"
        (tmp_path / "MitraHome_backups" / "family_1.db").write_text("x")
        assert paths.adopt_legacy_backups(tmp_path) == "MitraHome_backups", "upgrade renames it"
        assert (tmp_path / "Mitra-Home-Backup" / "family_1.db").exists() and not (tmp_path / "MitraHome_backups").exists()
        assert paths.backups_dir(tmp_path) == tmp_path / "Mitra-Home-Backup"
        assert paths.adopt_legacy_backups(tmp_path) == "", "the new folder is there: the older one is left alone"
        assert (tmp_path / "FamilyAgent_backups").exists()
