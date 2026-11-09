"""0.135: phones and walls on the home Wi-Fi by default (Settings > Phones > Connection switch + Restart), the Windows
Firewall check and its one-click rule (data/firewall.py), the large wall pairing code, and Settings > Data > Where
things are (with Open folder). Nothing here changes the real firewall, starts a server or opens a window."""
import json
import subprocess

import pytest

from test_devices import _flash, _post, phones  # noqa: F401 (the fixture)


# ---- data/firewall.py (a fake runner stands in for netsh and PowerShell) -------------------------------------------
class Runner:
    """Answers netsh / PowerShell calls from a script: rule names that exist (-> their port) and the network JSON."""

    def __init__(self, rules=None, nets=None, allow_adds=False, allow_err=""):
        self.rules, self.nets, self.allow_adds, self.allow_err, self.calls = dict(rules or {}), nets or [], allow_adds, allow_err, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "netsh":
            name = cmd[5].split("=", 1)[1]
            if name in self.rules:
                return subprocess.CompletedProcess(cmd, 0, f"Rule Name: {name}\nLocalPort: {self.rules[name]}\n", "")
            return subprocess.CompletedProcess(cmd, 1, "No rules match the specified criteria.\n", "")
        script = cmd[-1]
        if script.startswith("Start-Process"):
            if self.allow_adds:
                self.rules["Mitra Home phones"] = 8701
            return subprocess.CompletedProcess(cmd, 1 if self.allow_err else 0, "", self.allow_err)
        return subprocess.CompletedProcess(cmd, 0, json.dumps(self.nets), "")


NETS = [{"name": "Guest", "category": "Public", "iface": "VPN", "ip": "10.5.0.2"},
        {"name": "Home Wi-Fi", "category": "Private", "iface": "Wi-Fi", "ip": "192.168.1.20"}]


@pytest.fixture()
def fw(modules, monkeypatch):
    m = modules("firewall")
    monkeypatch.setattr(m, "supported", lambda: True)
    m._cache.clear()
    return m


def test_read_finds_our_rule_by_port_and_the_network_that_carries_the_lan_address(fw):
    r = fw.read(8701, "192.168.1.20", run=Runner({"Mitra Home phones": 8701}, NETS))
    assert r["rule"] and r["network"] == "Private" and r["network_name"] == "Home Wi-Fi" and not r["error"]
    r = fw.read(8701, "10.5.0.2", run=Runner({"Mitra Home": 8701}, NETS))
    assert r["rule"], "the rule name launch.py printed before counts too"
    assert r["network"] == "Public"
    assert not fw.read(8701, "192.168.1.20", run=Runner({"Mitra Home phones": 8702}, NETS))["rule"], "another port"
    assert not fw.read(8701, None, run=Runner({}, NETS[:1]))["rule"]


def test_read_says_when_windows_does_not_answer_and_is_quiet_elsewhere(fw, monkeypatch):
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 15)
    assert "did not answer" in fw.read(8701, run=slow)["error"]
    monkeypatch.setattr(fw, "supported", lambda: False)
    r = fw.read(8701, run=slow)
    assert r == {"supported": False, "port": 8701, "rule": False, "network": "", "network_name": "", "error": ""}


def test_the_allow_command_is_one_private_inbound_rule_for_that_port_only(fw):
    line = fw.allow_command(8701)
    assert line.startswith("Start-Process -FilePath netsh -Verb RunAs -Wait")
    for part in ("'name=\"Mitra Home phones\"'", "'dir=in'", "'action=allow'", "'protocol=TCP'", "'localport=8701'",
                 "'profile=private'"):
        assert part in line
    for bad in (80, "8701;calc", 70000, -1):
        with pytest.raises(ValueError):
            fw.allow_command(bad)


def test_allow_adds_the_rule_once_and_reports_a_refused_prompt(fw):
    run = Runner({}, NETS, allow_adds=True)
    ok, msg = fw.allow(8701, "192.168.1.20", run=run)
    assert ok and "port 8701" in msg and "Private" in msg
    ok, msg = fw.allow(8701, "192.168.1.20", run=run)
    assert ok and "already" in msg
    assert sum(1 for c in run.calls if c[0] != "netsh" and c[-1].startswith("Start-Process")) == 1, "asked Windows once"
    ok, msg = fw.allow(8701, run=Runner({}, NETS, allow_err="The operation was canceled by the user."))
    assert not ok and "not given" in msg


def test_status_keeps_the_answer_a_minute(fw):
    run = Runner({}, NETS)
    fw.status(8701, "192.168.1.20", run=run)
    n = len(run.calls)
    fw.status(8701, "192.168.1.20", run=run)
    assert len(run.calls) == n
    fw.status(8701, "192.168.1.20", fresh=True, run=run)
    assert len(run.calls) > n


# ---- config + launch read the same switch --------------------------------------------------------------------------
def test_phones_wanted_is_on_unless_switched_off(modules):
    config = modules("config")
    assert config.phones_wanted({}) and config.phones_wanted({"phones": {}}) and config.phones_wanted({"phones": "x"})
    assert not config.phones_wanted({"phones": {"lan": False}})


# ---- Settings > Phones > Connection --------------------------------------------------------------------------------
def test_connection_tab_switch_restart_and_firewall_check(phones, root, modules, monkeypatch):  # noqa: F811
    c, _, app_mod, _, local, lan = phones
    page = c.get("/settings?group=phones&tab=connection").text
    assert "Phones and walls on the home Wi-Fi" in page and "Switch off" in page and "Restart for" not in page
    if modules("settings_data").phones_mode()["windows"]:
        assert 'hx-get="/settings/phones/firewall"' in page
    _post(c, "/settings/phones/mode", on="0")
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    assert fam["phones"] == {"lan": False}
    page = c.get("/settings?group=phones&tab=connection").text
    assert "Switch on" in page and "Restart for this PC only" in page, "running for phones while switched off"
    assert "phones_set\toff" in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    _post(c, "/settings/phones/mode", on="1")
    lan(False)
    page = c.get("/settings?group=phones&tab=connection").text
    assert "Restart for phones" in page and "Restart it for phones" in c.get("/settings?group=phones").text
    assert "Step 2 of 2" in page and "Step 1 of 2" not in page, "a PIN exists: one restart is all that is left"
    conn = c.get("/settings?group=connections").text
    assert 'href="/settings?group=phones"' not in conn.split("</nav>")[1], "Phones and walls are no longer a card under Connections"
    home = c.get("/settings").text
    assert 'href="/settings?group=phones"' in home and "Phones and walls" in home, "they sit on the Settings home"

    started, closed = [], []
    monkeypatch.setattr(modules("restore_backup"), "start_relaunch", lambda port, lan=False: started.append((port, lan)))
    monkeypatch.setattr(modules("maintenance_data"), "close_soon", lambda seconds=2.0: closed.append(seconds))
    local(False)
    _post(c, "/settings/phones/restart")
    assert not started and "from the PC itself" in _flash(c)
    local(True)
    r = _post(c, "/settings/phones/restart")
    assert started == [(8601, True)] and closed and "for phones and walls" in r.text
    assert 'data-wait-back="/settings?group=phones&amp;tab=connection"' in r.text


def test_firewall_routes_are_for_this_pc_and_adults(phones, modules, monkeypatch):  # noqa: F811
    c, _, _, _, local, _ = phones
    fwm = modules("firewall")
    monkeypatch.setattr(fwm, "supported", lambda: True)
    fwm._cache.clear()
    monkeypatch.setattr(fwm, "status", lambda port, ip=None, fresh=False, run=None: {
        "supported": True, "port": port, "rule": False, "network": "Public", "network_name": "Home", "error": ""})
    asked = []
    monkeypatch.setattr(fwm, "allow", lambda port, ip=None, run=None: asked.append(port) or (True, "Done: rule added."))
    html = c.get("/settings/phones/firewall").text
    assert "Allow phones through Windows Firewall" in html and "set to Public" in html and "Open Windows' Wi-Fi settings" in html
    _post(c, "/settings/phones/firewall", op="allow")
    assert asked == [8701] and "Done: rule added." in _flash(c)
    local(False)
    assert c.get("/settings/phones/firewall").text == ""
    _post(c, "/settings/phones/firewall", op="allow")
    assert asked == [8701] and "own screen" in _flash(c)
    assert _post(c, "/settings/phones/firewall", op="x").status_code == 400


# ---- the wall code, large ------------------------------------------------------------------------------------------
def test_the_wall_code_is_large_with_copy_and_full_screen(phones, modules):  # noqa: F811
    c, _, _, _, _, _ = phones
    _post(c, "/settings/wall/add", name="Kitchen")
    page = c.get("/settings?group=phones&tab=walls").text
    code = __import__("re").search(r'<div class="wcode"[^>]*>([A-Z0-9]{4}-[A-Z0-9]{4})</div>', page)
    assert code, "the code is shown large"
    assert f'data-copy="{code.group(1)}"' in page and 'data-dlg="wall-code-full"' in page
    assert 'id="wall-code-full"' in page and 'class="wcode big"' in page
    assert "Show Details" in page, "iPad Safari's first warning is explained"


# ---- Settings > Data > Where things are ----------------------------------------------------------------------------
def test_where_things_are_lists_the_folders_and_opens_them_here_only(phones, root, modules, monkeypatch):  # noqa: F811
    c, _, _, _, local, _ = phones
    sd = modules("settings_data")
    w = sd.where()
    keys = [r["key"] for r in w["rows"]]
    assert keys == ["app", "home", "archive", "inbox", "backups", "exports", "logs"] and w["db"].endswith("family.db")
    page = c.get("/settings?group=data").text
    assert "Where things are" in page and str(modules("paths").ARCHIVE) in page and 'hx-post="/settings/folder"' in page
    opened = []
    monkeypatch.setattr(sd, "_reveal", opened.append)
    modules("paths").ARCHIVE.mkdir(parents=True, exist_ok=True)
    ok, msg = sd.open_folder({"role": "adult", "name": "Ann"}, True, "archive")
    assert ok and opened == [modules("paths").ARCHIVE] and "open_folder\tarchive" in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")
    _post(c, "/settings/folder", key="logs")
    assert opened[-1] == modules("paths").LOGS
    assert sd.open_folder({"role": "adult"}, True, "../etc") == (False, "Unknown folder.")
    assert not sd.open_folder({"role": "limited"}, True, "archive")[0]
    assert not sd.open_folder({"role": "adult"}, False, "archive")[0]
    local(False)
    assert 'hx-post="/settings/folder"' not in c.get("/settings?group=data").text


def test_stop_is_for_this_pc_leaves_the_note_and_closes(phones, root, modules, monkeypatch, tmp_path):  # noqa: F811
    """0.137: the app runs with no window, so Settings > Data has Stop; the note keeps the 5-minute task from starting
    it again until a start by hand or a restart of the PC."""
    c, _, _, _, local, _ = phones
    sd = modules("settings_data")
    note = tmp_path / "MitraHome" / "stopped.txt"
    monkeypatch.setattr(sd, "stop_note", lambda: note)
    closed = []
    monkeypatch.setattr(modules("maintenance_data"), "close_soon", lambda seconds=2.0: closed.append(seconds))
    assert 'hx-post="/settings/stop"' in c.get("/settings?group=data").text
    local(False)
    assert 'hx-post="/settings/stop"' not in c.get("/settings?group=data").text
    _post(c, "/settings/stop")
    assert not closed and not note.exists() and "from the PC itself" in _flash(c)
    local(True)
    r = _post(c, "/settings/stop")
    assert closed and note.exists() and "has stopped" in r.text and "data-wait-back" not in r.text
    assert "web_stop" in (root / "logs" / "admin_audit.log").read_text(encoding="utf-8")


def test_pairing_without_a_pin_says_to_set_one_up_first(phones, root, modules):  # noqa: F811
    sd, config = modules("settings_data"), modules("config")
    fam = json.loads((root / "config" / "family.json").read_text(encoding="utf-8"))
    fam.pop("dashboard_users", None)
    config.write_json(root / "config" / "family.json", fam)
    adult = {"name": "Ann", "role": "adult"}
    ok, msg, pair = sd.phone_pair(adult, True, "Ann", "Ann's phone")
    assert not ok and pair is None and "set up a PIN before you connect a phone" in msg
    ok, msg, pair = sd.wall_pair(adult, True, "Kitchen wall")
    assert not ok and pair is None and "set up a PIN before you connect a phone" in msg



def test_wall_screen_preview_shows_the_form_choices_without_saving(phones, root, modules):  # noqa: F811
    c, _, app_mod, _, local, lan = phones
    before = (root / "config" / "family.json").read_text(encoding="utf-8")
    r = c.get("/settings/wall/preview", params={"clock": "analog", "photos": "0", "photo_seconds": "20", "clock_seconds": "30",
                                                "per_turn": "3", "photos_from": "08:00", "photos_to": "20:00",
                                                "night_from": "21:00", "night_to": "06:00", "night_tone": "dim", "zone": "",
                                                "photo_style": "", "theme": "", "rotate_seconds": "0"})
    assert r.status_code == 200 and 'data-preview="1"' in r.text, r.text[:300]
    assert r.headers["x-frame-options"] == "SAMEORIGIN" and "frame-ancestors 'self'" in r.headers["content-security-policy"]
    bad = c.get("/settings/wall/preview", params={"clock": "nonsense"})
    assert bad.status_code == 200 and "Cannot preview" in bad.text and 'data-preview="1"' not in bad.text
    assert (root / "config" / "family.json").read_text(encoding="utf-8") == before, "a preview saves nothing"
    page = c.get("/settings?group=phones&tab=walls").text
    assert "data-wall-preview" in page and 'id="wprev"' in page
    assert c.get("/settings").headers["x-frame-options"] == "DENY"
