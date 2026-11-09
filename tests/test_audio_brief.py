"""Spoken morning brief (data/make_audio_brief.py): the script from action items (no symbols, amounts in words, a cap
with "and N more"), engines none / system / voicestudio (loopback only, through a local stand-in server), setup in
family.json, the Drive push only when "audio" is listed, and a week of files kept."""
import datetime as D
import http.server
import json
import platform
import threading

import pytest

from conftest import read_family, run, write_family


@pytest.fixture(scope="module")
def A(root, modules):
    return modules("make_audio_brief")


def test_script_reads_items(root, A, modules):
    db = modules("db")
    con = db.connect(root / "data" / "family.db", readonly=True)
    try:
        text = A.script(con, D.date.today())
    finally:
        con.close()
    assert text.startswith("Good morning") and text.rstrip().endswith("Have a good day.")
    assert "$" not in text and "#" not in text
    lines = text.splitlines()
    assert len(lines) <= 2 + A.MAX_ITEMS + 3


def test_text_only_and_engine_none(root):
    r = run(["data/make_audio_brief.py"], root)
    assert r.returncode == 0 and "no voice engine set" in r.stdout, r.stdout + r.stderr
    today = D.date.today().isoformat()
    assert (root / "brief" / f"{today}_audio.txt").is_file() and not (root / "brief" / f"{today}_audio.wav").exists()


def test_setup_refuses_remote_voicestudio(root):
    r = run(["data/make_audio_brief.py", "setup", "--engine", "voicestudio", "--url", "http://192.168.1.20:3900/v1/audio/speech"], root)
    assert r.returncode != 0 and "on this PC" in r.stderr
    assert "audio" not in read_family(root) or read_family(root)["audio"].get("engine") != "voicestudio"


def test_voicestudio_engine_through_local_server(root):
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            got["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            got["path"] = self.path
            wav = b"RIFF" + b"\x00" * 60
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.end_headers()
            self.wfile.write(wav)

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_port}/v1/audio/speech"
        assert run(["data/make_audio_brief.py", "setup", "--engine", "voicestudio", "--url", url], root).returncode == 0
        r = run(["data/make_audio_brief.py"], root)
        assert r.returncode == 0, r.stderr[-300:]
        assert got["path"] == "/v1/audio/speech" and got["body"]["input"].startswith("Good morning")
        assert (root / "brief" / f"{D.date.today().isoformat()}_audio.wav").read_bytes()[:4] == b"RIFF"
    finally:
        srv.shutdown()
        fam = read_family(root)
        fam.pop("audio", None)
        write_family(root, fam)


@pytest.mark.skipif(platform.system() != "Windows", reason="Windows speech only")
def test_windows_voice_makes_a_wav(root, A, tmp_path):
    out = A._wav_system("Testing one two three.", tmp_path / "t.wav")
    assert out.read_bytes()[:4] == b"RIFF" and out.stat().st_size > 1000


def test_old_audio_files_are_tidied(root, A):
    old = root / "brief" / "2020-01-01_audio.wav"
    old.parent.mkdir(exist_ok=True)
    old.write_bytes(b"RIFF")
    A.tidy(D.date.today())
    assert not old.exists()


@pytest.mark.parametrize("voice", ["a\u2019+(calc)+\u2019", "x'); calc; ('", "a\"b", "$(calc)", "a;b", "x" * 61])
def test_setup_refuses_a_voice_that_is_not_a_plain_name(root, voice):
    """audit 2026-10-28: the voice went into a PowerShell string with only ' removed; curly quotes are quotes there too"""
    r = run(["data/make_audio_brief.py", "setup", "--engine", "system", "--voice", voice], root)
    assert r.returncode != 0 and "voice name" in (r.stdout + r.stderr)
    assert (read_family(root).get("audio") or {}).get("voice") != voice


def test_plain_voice_names_pass_and_a_bad_saved_one_is_dropped(root, A):
    for ok in ("Microsoft Zira Desktop", "Samantha", "en-us+f3", "Google UK English (Female)"):
        assert A.clean_voice(ok) == ok
    fam = read_family(root)
    write_family(root, {**fam, "audio": {"engine": "system", "voice": "a\u2019+(calc)+\u2019"}})
    try:
        assert A.settings()["voice"] == "", "a name saved before the check falls back to the default voice"
    finally:
        write_family(root, fam)
