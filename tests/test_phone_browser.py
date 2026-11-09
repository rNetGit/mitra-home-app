"""Phones without the app (0.110): Settings > Phones shows the home Wi-Fi address as a QR code for the phone's camera
when the app runs "for phones". The code holds only the address; signing in still needs a PIN."""
import base64


def test_the_wifi_address_is_offered_as_a_code_only_in_phone_mode(root, modules, monkeypatch):
    sd, lan_tls = modules("settings_data"), modules("lan_tls")
    monkeypatch.delenv("MITRAHOME_WEB_LAN", raising=False)
    assert sd.phones_lan()["url_qr"] == "" and sd.phones_lan()["url"] == ""
    monkeypatch.setenv("MITRAHOME_WEB_LAN", "1")
    monkeypatch.setenv("MITRAHOME_WEB_LAN_PORT", "8701")
    monkeypatch.setattr(lan_tls, "lan_ip", lambda: "192.168.1.20")
    got = sd.phones_lan()
    assert got["url"] == "https://192.168.1.20:8701/"
    assert got["url_qr"].startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(got["url_qr"].split(",", 1)[1]).decode("utf-8")
    assert svg.startswith("<svg") and "192.168" not in svg, "drawn as modules, not text"


def test_the_pairing_code_carries_the_certificate_and_the_key(root, modules, monkeypatch):
    """The phone app 0.14+ pins the key ("k"), which survives a renewed certificate; older apps keep "fp"."""
    import json
    import pytest
    pytest.importorskip("cryptography")
    sd, lan_tls, qr = modules("settings_data"), modules("lan_tls"), modules("qr")
    monkeypatch.setattr(modules("auth"), "users", lambda: [{"name": "Alex", "role": "adult"}])  # pairing needs a PIN
    monkeypatch.setenv("MITRAHOME_WEB_LAN", "1")
    monkeypatch.setenv("MITRAHOME_WEB_LAN_PORT", "8701")
    monkeypatch.setattr(lan_tls, "lan_ip", lambda: "192.168.1.20")
    lan_tls.ensure("192.168.1.20")
    seen = []
    monkeypatch.setattr(qr, "data_uri", lambda text: seen.append(text) or "data:image/svg+xml;base64,")
    ok, msg, _pair = sd.phone_pair({"name": "Alex", "role": "adult"}, True, "Alex", "Alex phone")
    assert ok, msg
    code = json.loads(seen[-1])
    assert code["fp"] == lan_tls.fingerprint() and code["k"] == lan_tls.key_fingerprint() and code["k"] != code["fp"]
    assert code["h"] == "192.168.1.20" and code["p"] == 8701 and code["v"] == 1
