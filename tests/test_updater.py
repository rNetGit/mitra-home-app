"""python onboard.py update: zip overlay keeps family files, refuses older/zip-slip/foreign zips; git mode fast-forwards
to a release tag and refuses when tracked files were edited. Signature checks: tests/test_release_signing.py
(these overlay tests pass --allow-unsigned). Uses a fake 99.0.0 release so it never meets a real one."""
import importlib
import shutil
import sqlite3
import subprocess
import zipfile

import pytest

from conftest import DRY, SRC, bind, copy_template, q, run

KEEP = {
    "CLAUDE.local.md": "my family rules\n",
    ".claude/agents/local-note.md": "---\nname: local-note\n---\nmine\n",
    ".claude/settings.local.json": "{}\n",
}


def make_zip(path, version, extra=None):
    with zipfile.ZipFile(path, "w") as z:
        for f in SRC.rglob("*"):
            rel = f.relative_to(SRC)
            if f.is_file() and not any(p in ("__pycache__", ".git", "backups_pre_upgrade", ".pytest_cache", ".ruff_cache") for p in rel.parts) \
                    and rel.parts[0] not in ("mobile", "dist", "installer") \
                    and f.suffix != ".db" and f.name not in ("family.json", "private_terms.txt", "heartbeat.json"):
                data = (version + "\n").encode() if rel.as_posix() == "VERSION" else f.read_bytes()
                z.writestr("rNetGit-FamilyAgent.Ai-abc1234/" + rel.as_posix(), data)
        z.writestr("rNetGit-FamilyAgent.Ai-abc1234/data/new_feature_marker.py", "# from the new release\n")
        for n, d in (extra or {}).items():
            z.writestr(n, d)


@pytest.fixture(scope="module")
def install(tmp_path_factory):
    """A migrated install with family customisations and one locally edited code file."""
    old = copy_template(tmp_path_factory.mktemp("upd") / "old")
    assert run(["data/migrate.py"], old).returncode == 0
    run(["data/members.py", "sync"], old)
    run(["data/seed_demo.py"], old)
    for rel, txt in KEEP.items():
        (old / rel).parent.mkdir(parents=True, exist_ok=True)
        (old / rel).write_text(txt, encoding="utf-8")
    budget_py = old / "data" / "budget.py"
    budget_py.write_text(budget_py.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    return old


def test_zip_update_keeps_family_files(install, tmp_path):
    fam_before = (install / "config" / "family.json").read_text(encoding="utf-8")
    newer = tmp_path / "release_99.0.0.zip"
    make_zip(newer, "99.0.0")
    gone = install / "data" / "migrate_998_removed_upstream.py"  # in the old code, not in the new release
    gone.write_text("def run(con):\n    raise RuntimeError('a dropped migration must not run')\n", encoding="utf-8")
    r = run(["onboard.py", "update", "--from", str(newer), "--yes", "--allow-unsigned"], install, env=DRY)
    assert r.returncode == 0, (r.stdout + r.stderr)[-400:]
    assert not gone.exists() and "no longer has moved to" in r.stdout, "audit A4: dropped code is set aside"
    assert list((install / "data" / "backups_pre_upgrade").glob("code_*/dropped/data/migrate_998_removed_upstream.py"))
    assert (install / "data" / "new_feature_marker.py").exists()
    assert (install / "VERSION").read_text(encoding="utf-8").strip() == "99.0.0"
    assert (install / "config" / "family.json").read_text(encoding="utf-8") == fam_before
    for rel, txt in KEEP.items():
        assert (install / rel).read_text(encoding="utf-8") == txt, rel
    assert list((install / "data" / "backups_pre_upgrade").glob("code_*/data/budget.py")), "edited file saved before replacement"
    assert (install / "data" / "family.db").exists()
    dbv = sqlite3.connect(install / "data" / "family.db").execute("select value from meta where key='template_version'").fetchone()
    assert dbv and dbv[0] == "99.0.0"



def test_zip_update_with_a_separate_household_folder(tmp_path):
    """The household lives outside the app folder (the default since the move): the copies of replaced code go to its
    backups_pre_upgrade/, and reporting where they went must not crash (0.105.0 -> main on a USB install did)."""
    app = copy_template(tmp_path / "app")
    assert run(["onboard.py", "home", str(tmp_path / "home")], app, env=DRY).returncode == 0
    assert run(["data/migrate.py"], app).returncode == 0
    budget_py = app / "data" / "budget.py"
    budget_py.write_text(budget_py.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    newer = tmp_path / "release_99.0.0.zip"
    make_zip(newer, "99.0.0")
    r = run(["onboard.py", "update", "--from", str(newer), "--yes", "--allow-unsigned"], app, env=DRY)
    assert r.returncode == 0, (r.stdout + r.stderr)[-600:]
    assert "previous versions saved in backups_pre_upgrade/code_" in r.stdout
    assert list((tmp_path / "home" / "backups_pre_upgrade").glob("code_*/data/budget.py"))
    assert (app / "VERSION").read_text(encoding="utf-8").strip() == "99.0.0"

def test_zip_update_refuses_older_zip_slip_and_foreign(install, tmp_path):
    older = tmp_path / "release_0.1.0.zip"
    make_zip(older, "0.1.0")
    r = run(["onboard.py", "update", "--from", str(older), "--yes", "--allow-unsigned"], install, env=DRY)
    assert r.returncode != 0 and (install / "VERSION").read_text(encoding="utf-8").strip() == "99.0.0"
    evil = tmp_path / "evil.zip"
    make_zip(evil, "9.9.9", extra={"../evil_escape.txt": "x"})
    r = run(["onboard.py", "update", "--from", str(evil), "--yes", "--allow-unsigned"], install, env=DRY)
    assert r.returncode != 0 and not (tmp_path / "evil_escape.txt").exists()
    assert run(["onboard.py", "update", "--from", str(tmp_path / "nonexistent.zip"), "--yes", "--allow-unsigned"], install, env=DRY).returncode != 0
    notfa = tmp_path / "notfa.zip"
    with zipfile.ZipFile(notfa, "w") as z:
        z.writestr("x/README.md", "hi")
    assert run(["onboard.py", "update", "--from", str(notfa), "--yes", "--allow-unsigned"], install, env=DRY).returncode != 0


def test_updater_only_downloads_from_github_over_https(modules):
    up = modules("updater")
    assert up._safe_url("https://api.github.com/repos/x/y/releases/latest")
    for bad in ("http://api.github.com/x", "https://evil.example/x.zip", "https://github.com.evil.example/x"):
        with pytest.raises(ValueError):
            up._safe_url(bad)


def test_update_stops_cleanly_when_no_one_can_answer(modules, monkeypatch, tmp_path, capsys):
    """A shell with no input (remote, scheduled): the Continue? prompt stops the update before anything changes."""
    up = modules("updater")
    zp = tmp_path / "release.zip"
    zp.write_bytes(b"PK")
    touched = []
    monkeypatch.setattr(up, "_verified", lambda *a, **k: touched.append("verified") or (True, None))
    monkeypatch.setattr(up, "update_zip", lambda *a, **k: touched.append("update_zip"))

    def no_input(prompt):
        raise EOFError
    assert up.run_update(from_zip=str(zp), ask=no_input) is False
    assert touched == []
    assert "--yes" in capsys.readouterr().out


def test_downloads_do_not_pile_up_in_temp(modules, monkeypatch, tmp_path):
    """S11: the downloaded release zip's folder is removed after the update, also when it was too large."""
    import io
    import tempfile
    up = modules("updater")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(up, "_get", lambda url, timeout: Answer(b"PK" + b"x" * 100))
    zp = up._download("https://api.github.com/x.zip")
    assert zp.exists() and zp.parent.name.startswith("mitrahome_dl_")
    up._forget_download(zp)
    assert not zp.parent.exists()
    monkeypatch.setattr(up, "MAX_ZIP", 10)
    with pytest.raises(ValueError):
        up._download("https://api.github.com/x.zip")
    assert not list(tmp_path.glob("mitrahome_dl_*")), "a refused download leaves nothing behind"
    family_zip = tmp_path / "MitraHome.zip"
    family_zip.write_bytes(b"PK")
    up._forget_download(family_zip)
    assert family_zip.exists(), "never the family's own --from file"


# ---- git mode

def git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false", *args],
                       cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr[-300:]}"
    return r.stdout


@pytest.fixture
def git_install(tmp_path):
    if not shutil.which("git"):
        pytest.skip("git not on PATH")
    work = copy_template(tmp_path / "work")
    git(work, "init", "-q")
    git(work, "checkout", "-q", "-b", "main")
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", "base")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(origin))
    git(work, "remote", "add", "origin", str(origin))
    other = tmp_path / "other"
    git(tmp_path, "clone", "-q", str(origin), str(other))
    (other / "data" / "new_feature_marker.py").write_text("# from the new release\n", encoding="utf-8")
    (other / "VERSION").write_text("99.0.0\n", encoding="utf-8")
    git(other, "add", "-A")
    git(other, "commit", "-q", "-m", "release 99.0.0")
    git(other, "tag", "v99.0.0")
    git(other, "push", "-q", "origin", "main", "--tags")
    assert run(["data/migrate.py"], work).returncode == 0
    return work


@pytest.mark.git
def test_git_update_fast_forwards_to_the_tag(git_install):
    bind(git_install)
    up = importlib.import_module("updater")
    assert up.is_git()
    ok, msg = up.update_git("v99.0.0")
    assert ok, msg
    assert (git_install / "data" / "new_feature_marker.py").exists()
    assert (git_install / "VERSION").read_text(encoding="utf-8").strip() == "99.0.0"
    assert (git_install / "data" / "family.db").exists(), "the database is untouched"


@pytest.mark.git
def test_git_update_refuses_local_edits(git_install):
    bind(git_install)
    up = importlib.import_module("updater")
    budget_py = git_install / "data" / "budget.py"
    budget_py.write_text(budget_py.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
    ok, msg = up.update_git("v99.0.0")
    assert not ok and "local edits" in msg
    assert not (git_install / "data" / "new_feature_marker.py").exists()
    assert q(git_install, "select count(*) from sqlite_master") is not None


def test_git_calls_trust_the_install_folder_for_that_call_only(git_install, monkeypatch):
    bind(git_install)
    up = importlib.import_module("updater")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "false")
    env = up._git_env(git_install)
    assert env["GIT_CONFIG_COUNT"] == "2"
    assert (env["GIT_CONFIG_KEY_0"], env["GIT_CONFIG_VALUE_0"]) == ("core.autocrlf", "false")
    assert env["GIT_CONFIG_KEY_1"] == "safe.directory"
    assert env["GIT_CONFIG_VALUE_1"] == git_install.resolve().as_posix()
