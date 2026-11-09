"""Windows Firewall and the phones' port: is it open on the home Wi-Fi, and open it with one confirmed click.

Settings > Phones > Connection shows what `status()` finds; "Allow phones through Windows Firewall" runs `allow()`,
which asks Windows to add ONE inbound rule (TCP, the phones' HTTPS port only, Private networks only) and Windows shows
its own administrator prompt (UAC) for the family to confirm. Nothing here changes a network from Public to Private:
`open_network_settings()` opens Windows' own page for that. Reading needs no administrator rights. Windows only;
elsewhere `status()` says the check is not needed here.

    python data/firewall.py status [PORT]
"""
import json
import os
import subprocess
import sys
import time

import brand

RULE = f"{brand.PRODUCT} phones"
OLD_RULES = (brand.PRODUCT,)  # the name launch.py printed before 0.135
CACHE_SECONDS = 60
_cache = {}

# Network profiles with their IPv4 addresses, as JSON (enum names are English on every Windows language). Rules are read
# with netsh instead: Get-NetFirewallRule walks every rule on the PC and takes several seconds.
_NETS_PS = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$ips=@(Get-NetIPAddress -AddressFamily IPv4);"
    "@(Get-NetConnectionProfile | ForEach-Object { $i=$_.InterfaceIndex; [pscustomobject]@{"
    "name=$_.Name; category=[string]$_.NetworkCategory; iface=$_.InterfaceAlias;"
    "ip=(@($ips | Where-Object InterfaceIndex -eq $i).IPAddress -join ',') } }) | ConvertTo-Json -Compress"
)


def supported():
    return os.name == "nt"


def _port(port):
    p = int(port)
    if not 1024 <= p <= 65535:
        raise ValueError("port out of range")
    return p


def _ps(command, timeout=20, run=subprocess.run):
    return run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True,
               timeout=timeout, stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0)


def _list(v):
    return v if isinstance(v, list) else [v] if v else []


def has_rule(port, run=subprocess.run):
    """True when a rule of ours (RULE, or the older name) names this port. netsh answers 1 when no rule has the name;
    its other words are in the PC's language, so only the exit code and the port number are read."""
    for name in (RULE, *OLD_RULES):
        r = run(["netsh", "advfirewall", "firewall", "show", "rule", f"name={name}", "dir=in"], capture_output=True,
                text=True, timeout=15, stdin=subprocess.DEVNULL, creationflags=0x08000000 if os.name == "nt" else 0)
        if r.returncode == 0 and any(str(port) in line.split() or line.rstrip().endswith(" " + str(port))
                                     for line in (r.stdout or "").splitlines()):
            return True
    return False


def read(port, lan_ip=None, run=subprocess.run):
    """-> {'supported', 'port', 'rule', 'network', 'network_name', 'error'} (no cache). rule: True / False; network:
    'Private', 'Public', 'DomainAuthenticated' or '' (unknown) for the network that carries `lan_ip`."""
    port = _port(port)
    out = {"supported": supported(), "port": port, "rule": False, "network": "", "network_name": "", "error": ""}
    if not out["supported"]:
        return out
    try:
        out["rule"] = has_rule(port, run=run)
        r = _ps(_NETS_PS, run=run)
        nets = _list(json.loads(r.stdout) if (r.stdout or "").strip() else [])
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        out["error"] = f"the Windows check did not answer ({type(e).__name__})"
        return out
    mine = [n for n in nets if lan_ip and lan_ip in str(n.get("ip") or "").split(",")] or nets[:1]
    if mine:
        out["network"] = str(mine[0].get("category") or "")
        out["network_name"] = str(mine[0].get("name") or "")
    return out


def status(port, lan_ip=None, fresh=False, run=subprocess.run):
    """read(), kept for CACHE_SECONDS so the Settings page does not wait on PowerShell every time."""
    key = (int(port), lan_ip)
    hit = _cache.get(key)
    if hit and not fresh and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    res = read(port, lan_ip, run=run)
    _cache[key] = (time.time(), res)
    return res


def allow_command(port):
    """The one PowerShell line that asks Windows (UAC) to add the rule: inbound TCP on `port`, Private networks."""
    port = _port(port)
    args = ",".join("'" + a + "'" for a in ("advfirewall", "firewall", "add", "rule", f'name="{RULE}"', "dir=in",
                                             "action=allow", "protocol=TCP", f"localport={port}", "profile=private"))
    return f"Start-Process -FilePath netsh -Verb RunAs -Wait -WindowStyle Hidden -ArgumentList {args}"


def allow(port, lan_ip=None, run=subprocess.run):
    """Ask Windows to add the rule (the family confirms Windows' own prompt). -> (ok, message)."""
    if not supported():
        return False, f"This check is for Windows. On a Mac, allow {brand.PRODUCT} when macOS asks about incoming connections."
    port = _port(port)
    before = read(port, lan_ip, run=run)
    if before["rule"]:
        _cache.pop((port, lan_ip), None)
        return True, "Windows Firewall already lets phones in on this port."
    try:
        r = _ps(allow_command(port), timeout=180, run=run)
    except (OSError, subprocess.SubprocessError) as e:
        return False, f"Windows did not run the request ({type(e).__name__})."
    after = read(port, lan_ip, run=run)
    _cache[(port, lan_ip)] = (time.time(), after)
    if after["rule"]:
        return True, f"Done: Windows Firewall lets phones in on port {port}, on Private networks only."
    if "cancel" in ((r.stderr or "") + (r.stdout or "")).lower():
        return False, "Windows asked for permission and it was not given. Nothing was changed."
    return False, "The rule was not added. Try again, or ask the person who manages this PC (it needs an administrator)."


def open_network_settings(run=subprocess.run):
    """Windows' Wi-Fi settings page, where the network can be set to Private. -> (ok, message)."""
    if not supported():
        return False, "This is for Windows."
    try:
        os.startfile("ms-settings:network-wifi")  # noqa: S606 (a fixed Windows settings page)
    except OSError:
        return False, "Open Settings > Network & internet > Wi-Fi > your network, and choose Private."
    return True, "Windows' Wi-Fi settings are open: choose your network, then Network profile type > Private."


def main(argv):
    if not argv or argv[0] != "status":
        raise SystemExit(__doc__)
    port = int(argv[1]) if len(argv) > 1 else 8701
    print(json.dumps(read(port), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
