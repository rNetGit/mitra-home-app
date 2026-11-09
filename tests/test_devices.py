"""Phones (0.101): the QR encoder, this PC's certificate, pairing codes, per-phone tokens, scopes by role, revoke,
Settings > Phones and the /api/ endpoints (bearer token, HTTPS only, no CSRF, one-time codes, throttle)."""
import datetime as dt
import json
import re
import sqlite3

import pytest

NOW = dt.datetime(2026, 10, 14, 9, 0, 0)


# ---- QR -------------------------------------------------------------------------------------------------------------
@pytest.fixture()
def qr(modules):
    return modules("qr")


def test_qr_capacities_match_the_standard_tables(qr):
    # bytes in byte mode at level M (ISO/IEC 18004 table 7)
    for ver, cap in ((1, 14), (2, 26), (3, 42), (4, 62), (5, 84), (6, 106), (7, 122), (8, 152), (9, 180), (10, 213),
                     (20, 666), (40, 2331)):
        assert qr.capacity(ver, "M") == cap, ver
    assert (qr.capacity(1, "L"), qr.capacity(1, "Q"), qr.capacity(1, "H")) == (17, 11, 7)
    assert qr.capacity(40, "L") == 2953


def test_qr_has_finders_timing_and_the_dark_module(qr):
    m = qr.encode("hello", "M")
    n = len(m)
    assert n == 21  # version 1
    for x0, y0 in ((0, 0), (n - 7, 0), (0, n - 7)):
        ring = [m[y0][x0 + i] for i in range(7)] + [m[y0 + 6][x0 + i] for i in range(7)]
        assert all(ring) and m[y0 + 3][x0 + 3] and not m[y0 + 1][x0 + 1]
    assert [m[6][x] for x in range(8, n - 8)] == [x % 2 == 0 for x in range(8, n - 8)]
    assert m[n - 8][8], "the dark module is always dark"


def test_qr_known_format_bits(qr):
    # level M, mask 0 -> 101010000010010 (ISO/IEC 18004 annex C)
    m = qr.encode(b"hi", "M", version=1, mask=0)
    row = [m[8][x] for x in (0, 1, 2, 3, 4, 5, 7, 8)] + [m[y][8] for y in (7, 5, 4, 3, 2, 1, 0)]
    assert "".join("1" if v else "0" for v in row) == "101010000010010"


def test_qr_versions_grow_with_the_payload_and_long_text_is_refused(qr):
    payload = json.dumps({"v": 1, "h": "192.168.100.200", "p": 8701, "fp": "a" * 64, "s": "b" * 22}, separators=(",", ":"))
    assert 41 <= len(qr.encode(payload)) <= 53  # version 7..9
    with pytest.raises(ValueError):
        qr.encode(b"x" * 3000)


def test_qr_svg_is_dark_on_white_and_a_data_uri(qr):
    s = qr.svg("hi")
    assert s.startswith("<svg") and 'fill="#fff"' in s and 'fill="#000"' in s and "<script" not in s
    assert qr.data_uri("hi").startswith("data:image/svg+xml;base64,")


def test_qr_matches_an_independent_encoder_when_one_is_installed(qr):
    segno = pytest.importorskip("segno")
    import segno.encoder as E
    old = E.write_padding_bits
    E.write_padding_bits = lambda buff, version, length: buff.extend([0] * (-length % 8))  # segno pads a whole extra byte
    try:
        for ver, ecl, mask in ((1, "M", 0), (7, "M", 3), (10, "Q", 5), (27, "H", 6)):
            data = bytes(i % 256 for i in range(qr.capacity(ver, ecl)))
            ref = segno.make(data, error=ecl.lower(), version=ver, mask=mask, mode="byte", boost_error=False)
            assert [[bool(v) for v in r] for r in ref.matrix] == qr.encode(data, ecl, version=ver, mask=mask)
    finally:
        E.write_padding_bits = old


# ---- certificate ----------------------------------------------------------------------------------------------------
def test_certificate_is_made_once_and_its_fingerprint_is_the_der_sha256(modules, root):
    pytest.importorskip("cryptography")
    lt = modules("lan_tls")
    for p in (lt.cert_path(), lt.key_path()):
        p.unlink(missing_ok=True)
    assert lt.status()["exists"] is False and lt.fingerprint() is None
    fp, change = lt.ensure("192.168.1.20")
    assert change == "made" and re.fullmatch(r"[0-9a-f]{64}", fp)
    assert lt.ensure("192.168.1.20") == (fp, ""), "the same certificate while it fits: paired phones keep working"
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    c = x509.load_pem_x509_certificate(lt.cert_path().read_bytes())
    assert c.fingerprint(hashes.SHA256()).hex() == fp
    ips = [str(i) for i in c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)]
    assert "192.168.1.20" in ips and "127.0.0.1" in ips
    assert (c.not_valid_after_utc - c.not_valid_before_utc).days <= 397, "iPhones and iPads refuse longer ones"
    assert lt.pretty("abcd") == "AB:CD" and lt.lan_port(8601) == 8701
    assert str(lt.folder()).startswith(str(root)), "inside the household's config folder"
    # away from home: the private-network (Tailscale) address is named too, and a new one renews with the same key
    key = lt.key_fingerprint()
    assert lt.ensure("192.168.1.20", also=["100.101.102.103"])[1] == "renewed" and lt.key_fingerprint() == key
    c = x509.load_pem_x509_certificate(lt.cert_path().read_bytes())
    ips = [str(i) for i in c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)]
    assert {"192.168.1.20", "100.101.102.103"} <= set(ips)
    assert lt.ensure("192.168.1.20", also=["100.101.102.103"])[1] == ""
    assert lt.renew_reason("192.168.1.20", also=["100.101.102.104"]) == "new address"


def test_remote_ip_is_the_private_network_address_or_none(modules, monkeypatch):
    lt = modules("lan_tls")
    monkeypatch.setenv("MITRAHOME_REMOTE_IP", "10.8.0.5")
    assert lt.remote_ip() == "10.8.0.5", "another VPN: the family names its address"
    monkeypatch.setenv("MITRAHOME_REMOTE_IP", "not an address")
    assert lt.remote_ip() is None
    monkeypatch.delenv("MITRAHOME_REMOTE_IP")

    class Sock:
        def __init__(self, ip):
            self.ip = ip
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def connect(self, addr):
            assert addr == (lt.PRIVATE_DNS, 53)
        def getsockname(self):
            return (self.ip, 5000)
    monkeypatch.setattr(lt.socket, "socket", lambda *a: Sock("100.90.1.2"))
    assert lt.remote_ip() == "100.90.1.2", "Tailscale running: its address"
    monkeypatch.setattr(lt.socket, "socket", lambda *a: Sock("192.168.1.20"))
    assert lt.remote_ip() is None, "no Tailscale: the route goes out the Wi-Fi, which is not a private-network address"


def test_certificate_is_renewed_with_the_same_key(modules, root):
    """A new address, a certificate near its end or one made long-lived before 0.124.1: renewed, same private key, so
    a phone that pinned the key keeps working; nothing changes while it fits."""
    pytest.importorskip("cryptography")
    import datetime as dt
    from cryptography import x509
    lt = modules("lan_tls")
    for p in (lt.cert_path(), lt.key_path()):
        p.unlink(missing_ok=True)
    fp, _ = lt.ensure("192.168.1.20")
    key, key_pem = lt.key_fingerprint(), lt.key_path().read_bytes()
    assert re.fullmatch(r"[0-9a-f]{64}", key) and key != fp
    fp2, change = lt.ensure("192.168.1.120")
    assert change == "renewed" and fp2 != fp and lt.key_fingerprint() == key and lt.key_path().read_bytes() == key_pem
    c = x509.load_pem_x509_certificate(lt.cert_path().read_bytes())
    assert "192.168.1.120" in [str(i) for i in c.extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value.get_values_for_type(x509.IPAddress)]
    soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=380)
    assert lt.renew_reason("192.168.1.120", soon) == "ends soon"
    assert lt.ensure("192.168.1.120", soon)[1] == "renewed" and lt.key_fingerprint() == key
    lt.make("192.168.1.120", keep_key=True)
    old = lt.DAYS
    lt.DAYS = 3651  # a certificate made by 0.124.0 or earlier
    try:
        lt.make("192.168.1.120", keep_key=True)
    finally:
        lt.DAYS = old
    assert lt.renew_reason("192.168.1.120") == "too long for iPhones and iPads"
    assert lt.ensure("192.168.1.120")[1] == "renewed" and lt.renew_reason("192.168.1.120") == ""
    assert lt.key_fingerprint() == key, "the key survives every renewal"
    lt.make("192.168.1.120")
    assert lt.key_fingerprint() != key, "lan_tls.py new = a new key (phones pair again)"


# ---- pairing, tokens, scopes -----------------------------------------------------------------------------------------
@pytest.fixture()
def dv(modules, root):
    """(devices module, connection) with Alex (adult) and Sam (child) in the household; no phones."""
    d = modules("devices")
    con = d._con()
    con.execute("DELETE FROM device_pairings")
    con.execute("DELETE FROM devices")
    con.commit()
    yield d, con
    con.close()


def _pair(d, con, who="Alex", name="Alex's phone", now=NOW, **kw):
    secret, info = d.pair_start(con, who, name, now=now, **kw)
    return d.pair_redeem(con, secret, now=now + dt.timedelta(minutes=1)), secret, info


def test_pairing_stores_only_hashes_and_works_once(dv):
    d, con = dv
    (token, dev), secret, info = _pair(d, con)
    assert dev["member"] == "Alex" and dev["role"] == "adult" and info["expires_at"] == "2026-10-14T09:05:00"
    dump = "\n".join(str(tuple(r)) for t in ("devices", "device_pairings") for r in con.execute(f"SELECT * FROM {t}"))
    assert secret not in dump and token not in dump
    assert d.pair_redeem(con, secret, now=NOW + dt.timedelta(minutes=2)) is None, "a code works once"
    assert d.authenticate(con, token, now=NOW + dt.timedelta(minutes=3))["id"] == dev["id"]


def test_codes_expire_and_a_new_code_cancels_the_older_one(dv):
    d, con = dv
    s1, _ = d.pair_start(con, "Alex", "One", now=NOW)
    assert d.pair_redeem(con, s1, now=NOW + dt.timedelta(minutes=6)) is None, "expired after 5 minutes"
    s2, _ = d.pair_start(con, "Alex", "Two", now=NOW)
    s3, _ = d.pair_start(con, "Alex", "Three", now=NOW)
    assert d.pair_redeem(con, s2, now=NOW) is None
    assert d.pair_redeem(con, s3, now=NOW)[1]["name"] == "Three"
    for bad in ("", "x", "a" * 22 + "!", "../../" * 4, None, s3 + "A"):
        assert d.pair_redeem(con, bad, now=NOW) is None


def test_role_defaults_and_limits(dv):
    d, con = dv
    (_, adult), _, _ = _pair(d, con)
    assert adult["scopes"] == ["bills", "calendar", "notes", "lists", "scan", "web"], "finance detail and IDs start off"
    (_, kid), _, _ = _pair(d, con, "sam", "Sam's phone")
    assert kid["member"] == "Sam" and kid["role"] == "limited" and kid["scopes"] == ["own", "calendar", "lists", "web"]
    assert d.set_scopes(con, kid["id"], ["finance", "ids", "bills", "notes", "scan", "calendar"]) == ["calendar"]
    assert d.set_scopes(con, adult["id"], ["finance", "ids", "own", "bogus"]) == ["finance", "ids"]
    with pytest.raises(ValueError):
        d.pair_start(con, "Biscuit", "Dog's collar", now=NOW)  # a pet
    with pytest.raises(ValueError):
        d.pair_start(con, "Mallory", "x", now=NOW)
    with pytest.raises(ValueError):
        d.pair_start(con, "Alex", " \t ", now=NOW)
    _, info = d.pair_start(con, "Alex", "  Tab\tand   spaces " + "x" * 60, now=NOW)
    assert info["name"].startswith("Tab and spaces x") and len(info["name"]) == 40


def test_revoke_and_a_person_leaving_stop_the_token_at_once(dv, modules, root):
    d, con = dv
    (tok, dev), _, _ = _pair(d, con)
    (tok2, dev2), _, _ = _pair(d, con, "Sam", "Sam's phone")
    assert d.revoke(con, dev["id"]) and not d.revoke(con, dev["id"])
    assert d.authenticate(con, tok) == {"revoked": True}
    assert d.authenticate(con, "A" * 43) is None and d.authenticate(con, "short") is None
    config = modules("config")
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    saved = json.dumps(fam)
    try:
        fam["members"] = [m for m in fam["members"] if m["name"] != "Sam"]
        config.write_json(root / "config" / "family.json", fam)
        assert d.authenticate(con, tok2) == {"revoked": True}
    finally:
        (root / "config" / "family.json").write_text(saved, encoding="utf-8")
    assert d.authenticate(con, tok2) == {"revoked": True}, "stays revoked when the person comes back"


def test_migration_045_gives_older_phones_the_web_scope(dv, root):
    from conftest import run
    d, con = dv
    (_, old), _, _ = _pair(d, con)
    (_, gone), _, _ = _pair(d, con, name="Old phone")
    con.execute("UPDATE devices SET scopes='bills,calendar' WHERE id=?", (old["id"],))
    con.execute("UPDATE devices SET scopes='', revoked_at='2026-10-01T00:00:00' WHERE id=?", (gone["id"],))
    con.commit()
    r = run(["data/migrate_045_phone_web_scope.py"], root)
    assert r.returncode == 0, r.stderr
    rows = dict(con.execute("SELECT id, scopes FROM devices"))
    assert rows[old["id"]] == "bills,calendar,web" and rows[gone["id"]] == "", "revoked phones are left alone"
    assert run(["data/migrate_045_phone_web_scope.py"], root).returncode == 0
    assert dict(con.execute("SELECT id, scopes FROM devices"))[old["id"]] == "bills,calendar,web", "added once"
    assert d.web_ok(con, old["id"])

def test_live_role_wins_over_the_role_at_pairing(dv, modules, root):
    d, con = dv
    auth, config = modules("auth"), modules("config")
    (tok, dev), _, _ = _pair(d, con)
    d.set_scopes(con, dev["id"], ["bills", "finance", "calendar"])
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    saved = json.dumps(fam)
    try:
        fam["dashboard_users"] = [{"name": "Alex", "role": "limited", "pin_hash": auth.hash_pin("1234")}]
        config.write_json(root / "config" / "family.json", fam)
        got = d.authenticate(con, tok)
        assert got["role"] == "limited" and got["scopes"] == ["calendar"]
    finally:
        (root / "config" / "family.json").write_text(saved, encoding="utf-8")


def test_last_seen_is_written_at_most_once_a_minute(dv):
    d, con = dv
    (tok, dev), _, _ = _pair(d, con)
    seen = lambda: con.execute("SELECT last_seen FROM devices WHERE id=?", (dev["id"],)).fetchone()[0]  # noqa: E731
    first = seen()
    d.authenticate(con, tok, now=NOW + dt.timedelta(minutes=1, seconds=30))
    assert seen() == first
    d.authenticate(con, tok, now=NOW + dt.timedelta(minutes=3))
    assert seen() == "2026-10-14T09:03:00"


def test_at_most_twenty_phones(dv, monkeypatch):
    d, con = dv
    monkeypatch.setattr(d, "MAX_DEVICES", 2)
    _pair(d, con)
    s, _ = d.pair_start(con, "Sam", "two", now=NOW)
    assert d.pair_redeem(con, s, now=NOW)
    with pytest.raises(ValueError):
        d.pair_start(con, "Alex", "three", now=NOW)


def test_purge_person_revokes_their_phones_so_they_wipe(modules, root):
    """Audit M11/M12: the phone row stays revoked (its token still answers `wipe`), the name goes; pending pairing
    codes are deleted; the other name columns and the allowance line go too."""
    purge, d = modules("purge"), modules("devices")
    assert ("devices", "member") not in purge.OWNED and ("device_pairings", "member") in purge.OWNED
    tok_pat, tok_lee = "P" * 43, "L" * 43
    con = d._con()
    try:
        con.execute("DELETE FROM device_pairings")
        con.execute("DELETE FROM devices")
        for name, member, tok in (("Pat phone", "Pat", tok_pat), ("Lee phone", "Lee", tok_lee)):
            con.execute("INSERT INTO devices(name, member, role, scopes, token_hash, created_at, created_by) VALUES "
                        "(?, ?, 'adult', 'own', ?, '2026-01-01T10:00:00', 'Pat')", (name, member, d._hash(tok)))
        con.execute("INSERT OR REPLACE INTO budget(category, monthly_limit) VALUES ('allowance:Pat', 20)")
        con.execute("INSERT OR REPLACE INTO budget(category, monthly_limit) VALUES ('allowance:Lee', 20)")
        con.commit()
        delete, clear, _, _ = purge.person_plan(con, "Pat")
        assert "budget" in delete and clear.get("devices (phones revoked)") == 1 and clear.get("devices") == 2
    finally:
        con.close()
    fam = purge.config.family()
    fam["members"] = (fam.get("members") or []) + [{"name": "Pat", "role": "adult"}]
    purge.config.write_json(root / "config" / "family.json", fam)
    assert purge.purge_person("Pat", True) == 0
    con = d._con()
    try:
        rows = [tuple(r) for r in con.execute("SELECT member, revoked_at IS NOT NULL, created_by FROM devices ORDER BY id")]
        assert rows == [("(removed)", 1, None), ("Lee", 0, None)]
        assert d.authenticate(con, tok_pat) == {"revoked": True}, "the purged person's phone is told to wipe"
        assert [r[0] for r in con.execute("SELECT category FROM budget WHERE category LIKE 'allowance:%'")] == ["allowance:Lee"]
    finally:
        con.close()


# ---- web: Settings > Phones and /api/ --------------------------------------------------------------------------------
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture()
def phones(root, modules, monkeypatch):
    """(client signed in as Ann on this PC, phone client over HTTPS, app module, devices, set_local, set_lan)."""
    pytest.importorskip("cryptography")
    auth, config = modules("auth"), modules("config")
    app_mod = modules("webapp.app")
    modules("webapp.sessions").clear()
    auth.THROTTLE.unlink(missing_ok=True)
    d = modules("devices")
    with d._con() as con:
        con.execute("DELETE FROM device_pairings")
        con.execute("DELETE FROM devices")
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    saved = json.dumps(fam)
    fam["members"] = fam["members"] + [{"name": "Ann", "role": "adult"}, {"name": "Kid", "role": "child"}]
    fam["dashboard_users"] = [{"name": "Ann", "role": "adult", "pin_hash": auth.hash_pin("1234")},
                              {"name": "Kid", "role": "limited", "pin_hash": auth.hash_pin("0000")}]
    config.write_json(root / "config" / "family.json", fam)
    modules("lan_tls").ensure("192.168.1.20")
    monkeypatch.setattr(modules("lan_tls"), "lan_ip", lambda: "192.168.1.20")

    def local(on=True):
        monkeypatch.setattr(app_mod, "LOCAL_HOSTS", {"testclient"} if on else {"127.0.0.1"})

    def lan(on=True):
        monkeypatch.setenv("MITRAHOME_WEB_LAN", "1" if on else "")
        monkeypatch.setenv("MITRAHOME_WEB_LAN_PORT", "8701" if on else "")

    local(True)
    lan(True)
    c = TestClient(app_mod.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    c.post("/login", data={"name": "Ann", "pin": "1234"})
    phone = TestClient(app_mod.app, base_url="https://192.168.1.20:8701", follow_redirects=False)
    yield c, phone, app_mod, d, local, lan
    (root / "config" / "family.json").write_text(saved, encoding="utf-8")
    modules("webapp.sessions").clear()


def _token(c):
    return re.search(r'name="csrf-token" content="([^"]+)"', c.get("/settings?group=phones").text).group(1)


def _post(c, path, **data):
    return c.post(path, data=data, headers={"X-CSRF-Token": _token(c), "Origin": "http://127.0.0.1:8601"})


def _flash(c):
    return c.get("/settings?group=phones").text


def test_settings_phones_shows_the_connection_and_a_one_time_code(phones, root):
    c, _, _, d, _, _ = phones
    page = c.get("/settings?group=phones").text
    assert "Show the pairing code" in page and 'data-dlg="dlg-phone-add"' in page
    assert 'href="/settings?group=phones&amp;tab=connection"' in page
    assert "https://192.168.1.20:8701" in c.get("/settings?group=phones&tab=connection").text
    r = _post(c, "/settings/phones/add", who="Kid", name="Kid's tablet")
    assert r.status_code == 200 and r.headers["HX-Redirect"] == "/settings?group=phones"
    page = c.get("/settings?group=phones").text
    assert 'src="data:image/svg+xml;base64,' in page and "Kid&#39;s tablet" in page and "until" in page
    assert 'id="dlg-pair" data-dlg-auto' in page, "the fresh code opens in its own window"
    again = c.get("/settings?group=phones").text
    assert "Pairing code for" not in again and "Scan this with" not in again, "the code is shown once"
    assert 'alt="Code with the address https://192.168.1.20:8701/"' in c.get("/settings?group=phones&tab=connection").text,         "the address code (no secret) stays"
    assert 'data-dlg-auto' not in again
    con = sqlite3.connect(root / "data" / "family.db")
    row = con.execute("SELECT member, role, scopes FROM device_pairings WHERE used_at IS NULL").fetchone()
    con.close()
    assert row == ("Kid", "limited", "own,calendar,lists,web")
    log = (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    assert "phone_pair_code" in log and "Kid" in log


def test_adding_a_phone_needs_this_pc_the_lan_and_an_adult(phones):
    c, _, _, _, local, lan = phones
    local(False)
    assert "Add a phone from this PC" in c.get("/settings?group=phones").text
    _post(c, "/settings/phones/add", who="Ann", name="x")
    assert "pairing code is shown only here" in _flash(c)
    local(True)
    lan(False)
    assert "started for this PC only" in c.get("/settings?group=phones").text
    _post(c, "/settings/phones/add", who="Ann", name="x")
    assert "for phones" in _flash(c)
    lan(True)
    k = TestClient(c.app, base_url="http://127.0.0.1:8601", follow_redirects=False)
    k.post("/login", data={"name": "Kid", "pin": "0000"})
    assert k.get("/settings?group=phones").status_code == 403
    assert c.post("/settings/phones/add", data={"who": "Ann", "name": "x"}).status_code == 403, "CSRF token required"


def test_phone_pairs_pings_and_is_revoked(phones, root):
    c, phone, _, d, _, _ = phones
    with d._con() as con:
        secret, _ = d.pair_start(con, "Ann", "Ann's phone")
    r = phone.post("/api/pair", json={"secret": secret})
    assert r.status_code == 200, r.text
    body = r.json()
    tok, dev = body["token"], body["device"]
    assert dev["member"] == "Ann" and "finance" not in dev["scopes"] and "set-cookie" not in r.headers
    assert phone.post("/api/pair", json={"secret": secret}).status_code == 401, "a code works once"
    ping = phone.get("/api/ping", headers={"Authorization": f"Bearer {tok}"})
    assert ping.status_code == 200 and ping.json()["device"]["name"] == "Ann's phone"
    assert ping.headers["Cache-Control"] == "no-store"
    assert phone.get("/api/ping").status_code == 401
    assert phone.get("/api/ping", headers={"Authorization": "Bearer " + "x" * 43}).json() == {"error": "unknown_device"}
    page = c.get("/settings?group=phones").text
    assert "Ann&#39;s phone" in page and "last seen" in page
    _post(c, "/settings/phones/scopes", id=str(dev["id"]), scope=["finance", "calendar"])
    assert "Saved: Calendar, Finance detail." in _flash(c)
    assert phone.get("/api/ping", headers={"Authorization": f"Bearer {tok}"}).json()["device"]["scopes"] == ["calendar", "finance"]
    _post(c, "/settings/phones/revoke", id=str(dev["id"]), sure="1")
    assert "Removed" in _flash(c)
    r = phone.get("/api/ping", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401 and r.json() == {"error": "revoked", "wipe": True}
    assert "No phone is paired yet" in c.get("/settings?group=phones").text


def test_api_is_https_only_and_needs_no_csrf(phones):
    _, _, app_mod, d, local, _ = phones
    local(False)
    lan_http = TestClient(app_mod.app, base_url="http://192.168.1.20:8601", follow_redirects=False)
    assert lan_http.post("/api/pair", json={"secret": "x"}).status_code == 403
    assert lan_http.get("/api/ping").status_code == 403
    # a session cookie and a foreign Origin change nothing: /api/ uses only the bearer token
    phone = TestClient(app_mod.app, base_url="https://192.168.1.20:8701", follow_redirects=False)
    r = phone.post("/api/pair", content=b"not json", headers={"Origin": "https://evil.example"})
    assert r.status_code == 401 and r.json() == {"error": "bad_code"}


def test_wrong_pairing_codes_are_throttled(phones):
    _, phone, _, d, _, _ = phones
    for _ in range(5):
        assert phone.post("/api/pair", json={"secret": "A" * 22}).status_code == 401
    with d._con() as con:
        secret, _ = d.pair_start(con, "Ann", "late")
    assert phone.post("/api/pair", json={"secret": secret}).status_code == 429, "even a right code waits"
    # audit 2026-10-28: the lock is for that device; another phone on the Wi-Fi still pairs
    other = TestClient(phone.app, base_url="https://192.168.1.20:8701", follow_redirects=False,
                       client=("192.168.1.31", 50000))
    assert other.post("/api/pair", json={"secret": secret}).status_code == 200



# ---- the phone app opens the web app (0.104): POST /api/session, GET /phone/open -------------------------------------
def _paired(phone, d, who="Ann"):
    with d._con() as con:
        secret, _ = d.pair_start(con, who, who + "'s phone")
    body = phone.post("/api/pair", json={"secret": secret}).json()
    return body["token"], body["device"]


def _open(phone, tok):
    r = phone.post("/api/session", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    assert r.json()["expires_in"] == 60 and "set-cookie" not in r.headers
    return r.json()["open"]


def test_phone_app_opens_a_web_session_once(phones):
    _, phone, app_mod, d, _, _ = phones
    tok, dev = _paired(phone, d)
    assert "web" in dev["scopes"]
    url = _open(phone, tok)
    assert url.startswith("/phone/open?code=")
    r = phone.get(url)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "samesite=strict" in cookie.lower()
    assert phone.get("/").status_code == 200
    assert phone.get("/money").status_code == 200, "an adult's phone sees what Ann's PIN would"
    fresh = TestClient(app_mod.app, base_url="https://192.168.1.20:8701", follow_redirects=False)
    r = fresh.get(url)
    assert r.status_code == 401 and "ran out" in r.text, "a code works once"
    assert fresh.get("/phone/open?code=" + "x" * 43).status_code == 401
    assert fresh.get("/phone/open").status_code == 401


def test_phone_session_follows_the_person_and_the_phone(phones, modules, root):
    _, phone, app_mod, d, _, _ = phones
    sessions = modules("webapp.sessions")
    tok, dev = _paired(phone, d, "Kid")
    phone.get(_open(phone, tok))
    assert phone.get("/").status_code == 200
    assert phone.get("/money").status_code == 403, "a child's phone gets the child's view"
    # the web scope off: no new session, and the open one ends at the next check
    with d._con() as con:
        d.set_scopes(con, dev["id"], ["calendar"])
    assert phone.post("/api/session", headers={"Authorization": f"Bearer {tok}"}).json() == {"error": "no_web"}
    for s in sessions._store.values():
        s["device_checked"] = 0
    assert phone.get("/").status_code == 303, "signed out once the phone may no longer open the app"


def test_phone_session_ends_when_the_phone_is_removed_and_needs_a_pin(phones, modules, root):
    c, phone, app_mod, d, _, _ = phones
    sessions = modules("webapp.sessions")
    tok, dev = _paired(phone, d)
    url = _open(phone, tok)
    with d._con() as con:
        d.revoke(con, dev["id"])
    assert phone.get(url).status_code == 401, "a code from a phone removed meanwhile is refused"
    tok, dev = _paired(phone, d)
    phone.get(_open(phone, tok))
    assert phone.get("/").status_code == 200
    with d._con() as con:
        d.revoke(con, dev["id"])
    assert phone.get("/").status_code == 200, "checked at most once a minute"
    for s in sessions._store.values():
        s["device_checked"] = 0
    assert phone.get("/").status_code == 303
    assert c.get("/").status_code == 200, "the PC's own session is not tied to any phone"
    # a person with no PIN: the phone pairs and syncs, but the web app needs a PIN first
    config = modules("config")
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    fam["members"].append({"name": "Gran", "role": "adult"})
    config.write_json(root / "config" / "family.json", fam)
    tok, _ = _paired(phone, d, "Gran")
    r = phone.post("/api/session", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 409 and r.json() == {"error": "no_pin"}


def test_phone_session_is_https_only_and_a_pin_change_ends_the_code(phones, modules, root):
    _, phone, app_mod, d, local, _ = phones
    auth, config = modules("auth"), modules("config")
    tok, _ = _paired(phone, d)
    url = _open(phone, tok)
    local(False)
    lan_http = TestClient(app_mod.app, base_url="http://192.168.1.20:8601", follow_redirects=False)
    assert lan_http.post("/api/session", headers={"Authorization": f"Bearer {tok}"}).status_code == 403
    assert lan_http.get(url).status_code == 403
    assert phone.post("/api/session").json() == {"error": "unknown_device"}
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    fam["dashboard_users"][0]["pin_hash"] = auth.hash_pin("9876")
    config.write_json(root / "config" / "family.json", fam)
    assert phone.get(url).status_code == 401, "made before the PIN changed"
    phone.get(_open(phone, tok))
    assert phone.get("/").status_code == 200


def test_handoff_codes_expire(modules):
    sessions = modules("webapp.sessions")
    code = sessions.handoff_create({"name": "Ann", "role": "adult"}, "b", 1, now=1000)
    assert sessions.handoff_take(code, now=1061) is None
    code = sessions.handoff_create({"name": "Ann", "role": "adult"}, "b", 1, now=1000)
    assert sessions.handoff_take(code, now=1030)["device"] == 1 and sessions.handoff_take(code, now=1030) is None
    assert sessions.handoff_take(None) is None and sessions.handoff_take(["x"]) is None

# ---- scans from phones (0.102): POST /api/upload, data/phone_upload.py ----------------------------------------------
PDF = b"%PDF-1.4\n% a phone scan\n" + b"x" * 200


def _sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


@pytest.fixture()
def pu(dv, modules):
    """(phone_upload, connection, adult phone, limited phone, inbox folder); the inbox starts empty of phone files."""
    d, con = dv
    p = modules("phone_upload")
    inbox = modules("paths").INBOX
    inbox.mkdir(parents=True, exist_ok=True)
    for f in inbox.glob("*_phone_*"):
        f.unlink()
    con.execute("DELETE FROM device_uploads")
    con.commit()
    (_, adult), _, _ = _pair(d, con)
    (_, kid), _, _ = _pair(d, con, "Sam", "Sam's phone")
    yield p, con, adult, kid, inbox
    for f in inbox.glob("*_phone_*"):
        f.unlink()


def test_phone_upload_saves_once_and_a_retry_gets_the_first_answer(pu):
    p, con, adult, _, inbox = pu
    st, body = p.accept(con, adult, "client-0001", "scan.pdf", PDF, _sha(PDF), now=NOW)
    assert st == 200 and body["status"] == "saved" and body["name"].endswith("_phone_scan.pdf")
    assert (inbox / body["name"]).read_bytes() == PDF
    st2, again = p.accept(con, adult, "client-0001", "scan.pdf", PDF, _sha(PDF), now=NOW)
    assert st2 == 200 and again == dict(body, repeat=True)
    assert len(list(inbox.glob("*_phone_*"))) == 1, "a retry never makes a second copy"
    other = PDF + b"y"
    assert p.accept(con, adult, "client-0001", "scan.pdf", other, _sha(other), now=NOW) == (409, {"error": "client_id_reused"})


def test_phone_upload_refuses_damaged_or_malformed_sends(pu):
    p, con, adult, _, inbox = pu
    assert p.accept(con, adult, "client-0002", "scan.pdf", PDF, _sha(PDF + b"!"), now=NOW) == (400, {"error": "hash_mismatch"})
    for cid, sha in (("short", _sha(PDF)), ("bad id with spaces", _sha(PDF)), ("x" * 65, _sha(PDF)),
                     ("client-0003", "zz" * 32), ("client-0003", ""), (None, _sha(PDF))):
        assert p.accept(con, adult, cid, "scan.pdf", PDF, sha, now=NOW) == (400, {"error": "bad_request"}), (cid, sha)
    exe = b"MZ\x90\x00" + b"\x00" * 100
    st, body = p.accept(con, adult, "client-0004", "scan.pdf", exe, _sha(exe), now=NOW)
    assert st == 400 and body["error"] == "refused"
    st, body = p.accept(con, adult, "client-0005", "evil.exe", PDF, _sha(PDF), now=NOW)
    assert st == 400 and "not accepted" in body["message"]
    assert not list(inbox.glob("*_phone_*")), "nothing refused is saved"
    assert con.execute("SELECT COUNT(*) FROM device_uploads").fetchone()[0] == 0, "refusals are not remembered"


def test_phone_upload_knows_exact_copies(pu):
    p, con, adult, _, inbox = pu
    waiting = inbox / "dropped_on_pc_phone_test.pdf"
    waiting.write_bytes(PDF)
    try:
        assert p.accept(con, adult, "client-0010", "scan.pdf", PDF, _sha(PDF), now=NOW) == \
            (200, {"ok": True, "status": "duplicate"})
    finally:
        waiting.unlink()
    other = PDF + b"2"
    assert p.accept(con, adult, "client-0011", "a.pdf", other, _sha(other), now=NOW)[1]["status"] == "saved"
    assert p.accept(con, adult, "client-0012", "b.pdf", other, _sha(other), now=NOW)[1] == \
        {"ok": True, "status": "duplicate"}


def test_phone_upload_needs_the_scan_scope_and_an_adult(pu):
    p, con, adult, kid, _ = pu
    assert p.accept(con, kid, "client-0020", "scan.pdf", PDF, _sha(PDF), now=NOW) == (403, {"error": "no_scope"})
    no_scan = dict(adult, scopes=["bills", "calendar"])
    assert p.accept(con, no_scan, "client-0021", "scan.pdf", PDF, _sha(PDF), now=NOW) == (403, {"error": "no_scope"})
    assert p.limits(con, kid) is None and p.limits(con, adult, NOW)["left_today"] == p.MAX_PER_DAY


def test_phone_upload_daily_limit(pu, monkeypatch):
    p, con, adult, _, _ = pu
    monkeypatch.setattr(p, "MAX_PER_DAY", 2)
    for i in range(2):
        b = PDF + bytes([i])
        assert p.accept(con, adult, f"client-01{i:02d}", "s.pdf", b, _sha(b), now=NOW)[0] == 200
    b = PDF + b"third"
    assert p.accept(con, adult, "client-0199", "s.pdf", b, _sha(b), now=NOW) == (429, {"error": "daily_limit", "per_day": 2})
    assert p.accept(con, adult, "client-0199", "s.pdf", b, _sha(b), now=NOW + dt.timedelta(days=1))[0] == 200


def test_removing_a_phone_removes_its_upload_rows(pu):
    p, con, adult, _, _ = pu
    p.accept(con, adult, "client-0300", "s.pdf", PDF, _sha(PDF), now=NOW)
    con.execute("DELETE FROM devices WHERE id=?", (adult["id"],))
    con.commit()
    assert con.execute("SELECT COUNT(*) FROM device_uploads").fetchone()[0] == 0


def test_inbox_save_never_overwrites(modules, tmp_path):
    iu = modules("inbox_upload")
    names = [iu.save_upload("same.pdf", PDF, inbox=tmp_path)[1] for _ in range(3)]
    assert names == ["same.pdf", "same_2.pdf", "same_3.pdf"]


def _up(phone, tok, data, cid="client-web-01", name="scan%20one.pdf", sha=None):
    return phone.post("/api/upload", content=data, headers={
        "Authorization": f"Bearer {tok}", "X-Client-Id": cid, "X-Filename": name, "X-Sha256": sha or _sha(data),
        "Content-Type": "application/octet-stream"})


def test_api_upload_end_to_end(phones, modules):
    c, phone, app_mod, d, local, _ = phones
    inbox = modules("paths").INBOX
    with d._con() as con:
        con.execute("DELETE FROM device_uploads")
        s_ann, _ = d.pair_start(con, "Ann", "Ann's phone")
        s_kid, _ = d.pair_start(con, "Kid", "Kid's tablet")
    tok = phone.post("/api/pair", json={"secret": s_ann}).json()["token"]
    kid = phone.post("/api/pair", json={"secret": s_kid}).json()["token"]
    ping = phone.get("/api/ping", headers={"Authorization": f"Bearer {tok}"}).json()
    assert ping["upload"]["max_bytes"] == 25 * 1024 * 1024 and ".pdf" in ping["upload"]["types"] and "server_time" in ping
    assert phone.get("/api/ping", headers={"Authorization": f"Bearer {kid}"}).json()["upload"] is None
    data = PDF + b"web"
    try:
        r = _up(phone, tok, data)
        assert r.status_code == 200 and r.json()["status"] == "saved", r.text
        saved = r.json()["name"]
        assert saved.endswith("_phone_scan one.pdf") and (inbox / saved).read_bytes() == data
        assert _up(phone, tok, data).json() == {"ok": True, "status": "saved", "name": saved, "repeat": True}
        assert _up(phone, kid, data, cid="client-kid-01").status_code == 403
        assert _up(phone, tok, data, cid="client-web-02", sha="0" * 64).json() == {"error": "hash_mismatch"}
        big = phone.post("/api/upload", content=b"x", headers={"Authorization": f"Bearer {tok}", "Content-Length": str(26 * 1024 * 1024)})
        assert big.status_code == 413
        assert phone.post("/api/upload", content=data).status_code == 401
        local(False)
        lan_http = TestClient(app_mod.app, base_url="http://192.168.1.20:8601", follow_redirects=False)
        assert _up(lan_http, tok, data, cid="client-web-03").status_code == 403, "HTTPS only"
        local(True)
        # a signed-in browser session is not enough: /api/ needs the phone's token
        assert c.post("/api/upload", content=data, headers={"X-Client-Id": "client-web-04", "X-Sha256": _sha(data)}).status_code == 401
        with d._con() as con:
            dev_id = con.execute("SELECT id FROM devices WHERE name=?", ("Ann's phone",)).fetchone()[0]
            d.revoke(con, dev_id)
        assert _up(phone, tok, PDF + b"later", cid="client-web-05").json() == {"error": "revoked", "wipe": True}
    finally:
        for f in inbox.glob("*_phone_*"):
            f.unlink()


def test_a_broken_family_json_pauses_phones_instead_of_revoking_them(phones, root):
    """audit 2026-10-14: an unreadable people list must never look like 'this person left' (that wiped every phone)."""
    c, phone, _, d, _, _ = phones
    with d._con() as con:
        secret, _ = d.pair_start(con, "Ann", "Ann's phone")
    tok = phone.post("/api/pair", json={"secret": secret}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert phone.get("/api/ping", headers=h).status_code == 200
    fam_path = root / "config" / "family.json"
    saved = fam_path.read_text(encoding="utf-8")
    fam_path.write_text('{"family_name": "Broken", "members": [', encoding="utf-8")
    try:
        r = phone.get("/api/ping", headers=h)
        assert r.status_code == 503 and r.json() == {"error": "unavailable"} and "wipe" not in r.text
        assert phone.get("/api/sync/pull", headers=h).status_code == 503
    finally:
        fam_path.write_text(saved, encoding="utf-8")
    r = phone.get("/api/ping", headers=h)
    assert r.status_code == 200, "nothing was revoked meanwhile"
    with d._con() as con:
        assert con.execute("SELECT revoked_at FROM devices").fetchone()[0] is None


def test_a_phone_whose_person_left_is_revoked_and_audited(phones, root, modules):
    """Audit doc drift: the automatic revoke (the person is no longer in the household) is in admin_audit.log."""
    c, phone, _, d, _, _ = phones
    with d._con() as con:
        secret, _ = d.pair_start(con, "Ann", "Ann's phone")
    tok = phone.post("/api/pair", json={"secret": secret}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    fam_path = root / "config" / "family.json"
    saved = fam_path.read_text(encoding="utf-8")
    fam = json.loads(saved)
    fam["members"] = [m for m in fam["members"] if m.get("name") != "Ann"]
    fam_path.write_text(json.dumps(fam), encoding="utf-8")
    try:
        r = phone.get("/api/ping", headers=h)
        assert r.status_code == 401 and r.json().get("wipe") is True
    finally:
        fam_path.write_text(saved, encoding="utf-8")
    log = (modules("paths").LOGS / "admin_audit.log").read_text(encoding="utf-8")
    assert "phone_revoke_auto" in log


def test_content_sniff_sees_through_bom_and_blank_lines():
    import inbox_upload as iu
    assert not iu.content_ok("a.txt", b"\xef\xbb\xbf<html><script>x</script>")
    assert not iu.content_ok("a.csv", b"\n\n  <!DOCTYPE html>")
    assert not iu.content_ok("a.txt", "<script>".encode("utf-16"))
    assert iu.content_ok("a.txt", b"\xef\xbb\xbfdate,amount\n")


def test_phone_ids_reject_unicode_digits():
    import settings_data as sd
    assert sd.phone_revoke({"role": "adult"}, "\u00b2") == (False, "Pick a phone.")
    assert sd.phone_scopes({"role": "adult"}, "\u0663", []) == (False, "Pick a phone.")


def test_a_phone_older_than_min_phone_is_told_to_update(phones):
    """Version handshake: the phone sends X-App-Version; an older one gets 426 on every call and changes nothing.
    A phone from before the header (none sent) is served as before."""
    c, phone, _, d, _, _ = phones
    import sync_data
    with d._con() as con:
        secret, _ = d.pair_start(con, "Ann", "Old phone")
    tok = phone.post("/api/pair", json={"secret": secret}).json()["token"]
    auth = {"Authorization": f"Bearer {tok}"}
    ping = phone.get("/api/ping", headers=auth).json()
    assert ping["min_phone"] == sync_data.MIN_PHONE and "list_add" in ping["sync"]["ops"]
    assert phone.get("/api/ping", headers={**auth, "X-App-Version": sync_data.MIN_PHONE}).status_code == 200
    old = phone.get("/api/ping", headers={**auth, "X-App-Version": "0.1.0"})
    assert old.status_code == 426 and old.json() == {"error": "phone_too_old", "min_phone": sync_data.MIN_PHONE}
    pushed = phone.post("/api/sync/push", headers={**auth, "X-App-Version": "0.1.0"},
                        json={"ops": [{"id": "x1", "op": "note_add", "text": "never stored"}]})
    assert pushed.status_code == 426
    assert sync_data.phone_too_old("0.8.9") and not sync_data.phone_too_old("0.10.0")
    assert not sync_data.phone_too_old("") and not sync_data.phone_too_old("garbage")


def test_a_busy_database_does_not_end_a_phone_session(phones, modules, monkeypatch):
    """S9: a database that cannot be read for a moment is not a revoke; a session not checked for 10 minutes ends."""
    import sqlite3
    import time
    _, phone, app_mod, d, _, _ = phones
    sessions = modules("webapp.sessions")
    tok, _ = _paired(phone, d)
    phone.get(_open(phone, tok))
    assert phone.get("/").status_code == 200

    def busy(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(app_mod.devices, "web_ok", busy)
    for s in sessions._store.values():
        if s.get("device"):
            s["device_checked"] = time.time() - app_mod.PHONE_CHECK_EVERY - 5
    assert phone.get("/").status_code == 200, "a minute since the last check: kept"
    for s in sessions._store.values():
        if s.get("device"):
            s["device_checked"] = time.time() - app_mod.PHONE_ERROR_GRACE - 5
    assert phone.get("/").status_code == 303, "not checked for over ten minutes: signed out"


def test_device_rows_carry_a_seen_label(modules, monkeypatch):
    """Settings > Phones rows: never seen = new, 14 days quiet = quiet, else ok."""
    import datetime as dt
    sd, dates = modules("settings_data"), modules("dates")
    monkeypatch.setattr(dates, "today", lambda: dt.date(2026, 10, 24))
    assert sd.seen_state(None) == "new" and sd.seen_state("") == "new"
    assert sd.seen_state("2026-10-24T09:00:00") == "ok" and sd.seen_state("2026-10-11 08:00") == "ok"
    assert sd.seen_state("2026-10-10T08:00:00") == "quiet"
