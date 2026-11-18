"""Network scanner (data/scanner.py, /add/scanner): mDNS records, the home-network fence, an eSCL scan into the Inbox
with a fake scanner (no network)."""
import socket
import struct

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from test_webapp import _login, web  # noqa: F401 (the web fixture)

PDF = b"%PDF-1.4 fake page"
CAPS = (b'<?xml version="1.0"?><scan:ScannerCapabilities xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" '
        b'xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm"><pwg:MakeAndModel>Test Jet 9000</pwg:MakeAndModel>'
        b'<scan:Platen><scan:PlatenInputCaps/></scan:Platen><scan:Adf><scan:AdfSimplexInputCaps/></scan:Adf>'
        b'<scan:SettingProfiles><scan:SettingProfile><scan:DocumentFormats><pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>'
        b'</scan:DocumentFormats></scan:SettingProfile></scan:SettingProfiles></scan:ScannerCapabilities>')
SC = {"host": "127.0.0.1", "port": 80, "tls": False, "root": "eSCL", "name": "Test"}


class FakeScanner:
    """Answers like an eSCL scanner: `sheets` pages, then 404; remembers every request."""
    def __init__(self, sheets=1, location="/eSCL/ScanJobs/7", busy_first=0):
        self.sheets, self.location, self.busy, self.calls = sheets, location, busy_first, []

    def __call__(self, method, url, body=None, headers=None, timeout=0):
        self.calls.append((method, url))
        if url.endswith("/ScannerCapabilities"):
            return 200, {}, CAPS
        if method == "POST":
            return 201, {"Location": "http://elsewhere.example" + self.location}, b""
        if url.endswith("/NextDocument"):
            if self.busy:
                self.busy -= 1
                return 503, {}, b""
            if self.sheets:
                self.sheets -= 1
                return 200, {}, PDF
            return 404, {}, b""
        return 200, {}, b""


def _name(n):
    return b"".join(bytes([len(p)]) + p.encode() for p in n.split(".")) + b"\x00"


def _rr(name, rtype, rdata):
    return _name(name) + struct.pack(">HHIH", rtype, 1, 120, len(rdata)) + rdata


def test_mdns_records_become_a_scanner(modules):
    sc = modules("scanner")
    inst = "Test Jet._uscan._tcp.local"
    txt = b"".join(bytes([len(x)]) + x for x in (b"rs=eSCL", b"ty=Test Jet 9000"))
    pkt = struct.pack(">6H", 0, 0x8400, 0, 4, 0, 0)
    pkt += _rr("_uscan._tcp.local", 12, _name(inst))
    pkt += _rr(inst, 33, struct.pack(">3H", 0, 0, 80) + _name("printer.local"))
    pkt += _rr(inst, 16, txt)
    pkt += _rr("printer.local", 1, socket.inet_aton("192.168.1.20"))
    found = sc.scanners_from(sc.parse_mdns(pkt))
    assert found == [{"name": "Test Jet 9000", "host": "192.168.1.20", "port": 80, "tls": False, "root": "eSCL"}]
    assert sc.parse_mdns(b"\x00\x01garbage") == [], "a broken packet is skipped, never raises"


def test_only_home_network_addresses_are_used(modules):
    sc = modules("scanner")
    assert sc.home_network_host("192.168.1.20") and sc.home_network_host("10.0.0.5")
    assert not sc.home_network_host("8.8.8.8")
    assert not sc.home_network_host("not a host!") and not sc.home_network_host("")
    with pytest.raises(sc.ScannerError):
        sc.check_host("8.8.8.8")


def test_scan_from_the_glass_returns_one_page_and_deletes_the_job(modules, monkeypatch):
    sc = modules("scanner")
    fake = FakeScanner(sheets=3)
    monkeypatch.setattr(sc, "_request", fake)
    pages = sc.scan(SC, "glass", sleep=lambda s: None)
    assert pages == [(PDF, ".pdf")]
    assert ("DELETE", "http://127.0.0.1:80/eSCL/ScanJobs/7") in fake.calls
    assert not any("elsewhere.example" in u for _, u in fake.calls), "a scanner's Location never sends this PC elsewhere"


def test_scan_from_the_feeder_takes_every_sheet_and_waits_while_busy(modules, monkeypatch):
    sc = modules("scanner")
    monkeypatch.setattr(sc, "_request", FakeScanner(sheets=3, busy_first=2))
    assert len(sc.scan(SC, "feeder", sleep=lambda s: None)) == 3


def test_scan_to_inbox_saves_each_page_and_explains_a_failure(modules, monkeypatch):
    sc = modules("scanner")
    monkeypatch.setattr(sc, "_request", FakeScanner(sheets=2))
    saved = []
    ok, msg, names = sc.scan_to_inbox(SC, "feeder", save=lambda n, d: (saved.append(n) or True, n), stamp="T")
    assert ok and names == ["scan_T_p1.pdf", "scan_T_p2.pdf"] and "2 pages" in msg
    monkeypatch.setattr(sc, "_request", FakeScanner(sheets=0))
    ok, msg, names = sc.scan_to_inbox(SC, "glass", save=lambda n, d: (True, n))
    assert not ok and "Nothing came out" in msg and names == []
    assert sc.scan_to_inbox({**SC, "host": "8.8.8.8"}, "glass", save=None)[0] is False


def test_scan_page_choose_and_forget(web, modules, monkeypatch):  # noqa: F811
    c, _, _ = web
    sc = modules("scanner")
    _login(c)
    assert "Scan with a scanner" in c.get("/add").text
    assert "Look for scanners" in c.get("/add/scanner").text
    monkeypatch.setattr(sc, "_request", FakeScanner())
    ok, msg = sc.choose({"host": "127.0.0.1", "port": 80})
    assert ok and sc.saved()["name"] == "Test Jet 9000"
    assert "Test Jet 9000" in c.get("/add/scanner").text
    sc.forget()
    assert sc.saved() is None
