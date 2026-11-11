"""data/pair_cli.py: pairing a phone app or a wall from a terminal (the Docker image has no PC screen for Settings > Phones)."""
import json
import os

import pytest

from conftest import run

HOST = ["--host", "192.168.1.20", "--no-qr"]


def _payload(out):
    return json.loads(next(ln.strip() for ln in out.splitlines() if ln.strip().startswith('{"v":1')))


def test_render_draws_a_quiet_zone_and_half_blocks(modules):
    import pair_cli
    rows = modules("qr").encode("hello")
    text = pair_cli.render(rows)
    lines = text.split("\n")
    assert len(lines) == 13 and all(len(ln) == 25 for ln in lines), "21 modules + 2 quiet modules each side, two rows per line"
    assert lines[0] == "█" * 25, "the quiet zone is light (a full block on a dark terminal)"
    assert pair_cli.render(rows, invert=True).split("\n")[0] == " " * 25


def test_target_needs_a_clean_address_and_port(modules, monkeypatch):
    import pair_cli
    monkeypatch.delenv("MITRAHOME_PUBLIC_HOST", raising=False)
    monkeypatch.delenv("MITRAHOME_PUBLIC_PORT", raising=False)
    with pytest.raises(ValueError, match="--host"):
        pair_cli.target(None, None)
    for bad in ("http://192.168.1.20", "192.168.1.20:8701", "a b", "x/y"):
        with pytest.raises(ValueError, match="address"):
            pair_cli.target(bad, None)
    with pytest.raises(ValueError, match="port"):
        pair_cli.target("192.168.1.20", "99999")
    assert pair_cli.target("192.168.1.20", None) == ("192.168.1.20", 8701)
    monkeypatch.setenv("MITRAHOME_PUBLIC_HOST", "server.lan")
    monkeypatch.setenv("MITRAHOME_PUBLIC_PORT", "9701")
    assert pair_cli.target(None, None) == ("server.lan", 9701)


def test_it_refuses_without_a_pin_a_certificate_or_a_person(root, modules):
    devices, auth, config = modules("devices"), modules("auth"), modules("config")
    adult = next(p["name"] for p in devices.people() if p["role"] == "adult")
    with config.family_edit() as fam:
        fam["dashboard_users"] = []
    r = run(["data/pair_cli.py", "phone", adult, "Test phone", *HOST], root)
    assert r.returncode == 1 and "Set a PIN" in r.stderr and not r.stdout.strip()
    with config.family_edit() as fam:
        fam["dashboard_users"] = [{"name": adult, "role": "adult", "pin_hash": auth.hash_pin("1234")}]
    cert = modules("lan_tls").cert_path()
    cert.unlink(missing_ok=True)
    r = run(["data/pair_cli.py", "phone", adult, "Test phone", *HOST], root)
    assert r.returncode == 1 and "no certificate" in r.stderr
    assert run(["data/lan_tls.py", "new"], root).returncode == 0
    r = run(["data/pair_cli.py", "phone", "Nobody Here", "Test phone", *HOST], root)
    assert r.returncode == 1 and "Pick a person" in r.stderr
    r = run(["data/pair_cli.py", "phone", adult, "Test phone", "--host", "http://x"], root)
    assert r.returncode == 1 and "address" in r.stderr


def test_a_phone_code_pairs_once_and_names_the_certificate(root, modules):
    devices, lan = modules("devices"), modules("lan_tls")
    adult = next(p["name"] for p in devices.people() if p["role"] == "adult")
    r = run(["data/pair_cli.py", "phone", adult, "Test's phone", "--host", "192.168.1.20"], root)
    assert r.returncode == 0, r.stderr
    code = _payload(r.stdout)
    assert (code["v"], code["h"], code["p"]) == (1, "192.168.1.20", 8701)
    assert code["fp"] == lan.fingerprint() and code["k"] == lan.key_fingerprint() and code["s"]
    assert "█" in r.stdout and lan.pretty(lan.fingerprint())[:23] in r.stdout
    con = devices._con()
    try:
        token, dev = devices.pair_redeem(con, code["s"])
        assert token and dev["name"] == "Test's phone"
        assert devices.pair_redeem(con, code["s"]) is None, "one use"
    finally:
        con.close()
    audit = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "phone_pair_code" in audit and code["s"] not in audit


def test_a_wall_code_has_the_code_in_the_payload_and_the_browser_url(root, modules):
    r = run(["data/pair_cli.py", "wall", "Kitchen", "wall", "--host", "server.lan", "--port", "9701", "--no-qr"], root)
    assert r.returncode == 0, r.stderr
    code = _payload(r.stdout)
    assert (code["h"], code["p"]) == ("server.lan", 9701) and len(code["w"].replace("-", "")) == 8
    assert f"https://server.lan:9701/wall?code={code['w']}" in r.stdout and "Kitchen wall" in r.stdout


def test_the_container_entrypoint_runs_pair():
    from pathlib import Path
    sh = (Path(__file__).resolve().parent.parent / "docker" / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'pair)   shift; exec python data/pair_cli.py "$@"' in sh


def test_env_host_is_used(root, modules):
    devices = modules("devices")
    adult = next(p["name"] for p in devices.people() if p["role"] == "adult")
    r = run(["data/pair_cli.py", "phone", adult, "Env phone", "--no-qr"], root, env={"MITRAHOME_PUBLIC_HOST": "nas.lan"})
    assert r.returncode == 0, r.stderr
    assert _payload(r.stdout)["h"] == "nas.lan"
    assert "MITRAHOME_PUBLIC_HOST" not in os.environ
