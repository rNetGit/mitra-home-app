"""A scanner on the home network (eSCL, also called AirScan or Mopria): find it and scan a page into the Inbox.

Standard library only. Nothing leaves the home network: the scanner's address must be a private (home Wi-Fi / LAN)
address, a scanner's answer is never followed to another host, and the pages go through the same checks as any file added
to the Inbox (`inbox_data.save_file`). The address of the chosen scanner is kept in family.json `scanner`
({host, port, tls, root, name}); no password or account is involved.

  find        look for scanners with mDNS (`_uscan._tcp`, `_uscans._tcp`) for a few seconds
  use HOST    check a scanner at an address you type (when the search does not find it)
  scan        scan one page from the glass (or the feeder with --feeder) into the Inbox
"""
import ipaddress
import re
import socket
import ssl
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import config

MDNS_GROUP, MDNS_PORT = "224.0.0.251", 5353
SERVICES = ("_uscan._tcp.local", "_uscans._tcp.local")
FIND_SECONDS = 3.0
TIMEOUT = 30            # one request to the scanner
JOB_SECONDS = 150       # a whole scan, warm-up and feeder included
MAX_PAGES = 50
MAX_BYTES = 25 * 1024 * 1024
HOST_RE = re.compile(r"^[A-Za-z0-9]([A-Za-z0-9.-]{0,98}[A-Za-z0-9])?$")
SOURCES = {"glass": "Platen", "feeder": "Feeder"}


class ScannerError(Exception):
    """A plain-words reason (shown to the person as it is)."""


# ---- the address fence -----------------------------------------------------------------------------------------------
def _addresses(host):
    try:
        return {ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
    except (OSError, ValueError):
        return set()


def home_network_host(host):
    """True when the host is a literal or resolved address on this home network (private, link-local or this PC)."""
    if not HOST_RE.match(str(host or "")):
        return False
    ips = _addresses(host)
    return bool(ips) and all(ip.is_private or ip.is_link_local or ip.is_loopback for ip in ips)


def check_host(host):
    host = str(host or "").strip()
    if not home_network_host(host):
        raise ScannerError("That address is not on your home network. Only a scanner on the same Wi-Fi or cable is used.")
    return host


# ---- mDNS: find the scanner --------------------------------------------------------------------------------------------
def _name(buf, pos, depth=0):
    """(dotted name, position after it) of a DNS name that may use compression pointers."""
    labels, end = [], None
    while True:
        if pos >= len(buf) or depth > 20:
            raise ValueError("bad name")
        n = buf[pos]
        if n == 0:
            pos += 1
            break
        if n & 0xC0 == 0xC0:
            ptr = ((n & 0x3F) << 8) | buf[pos + 1]
            if end is None:
                end = pos + 2
            pos, depth = ptr, depth + 1
            continue
        labels.append(buf[pos + 1:pos + 1 + n].decode("utf-8", "replace"))
        pos += 1 + n
    return ".".join(labels), (end if end is not None else pos)


def parse_mdns(buf):
    """The records of one mDNS packet: a list of (type, name, value). PTR / SRV / TXT / A only; anything odd is skipped."""
    out = []
    try:
        qd, an, ns, ar = struct.unpack(">4H", buf[4:12])
        pos = 12
        for _ in range(qd):
            _, pos = _name(buf, pos)
            pos += 4
        for _ in range(an + ns + ar):
            name, pos = _name(buf, pos)
            rtype, _cls, _ttl, rdlen = struct.unpack(">HHIH", buf[pos:pos + 10])
            pos += 10
            data, rend = buf[pos:pos + rdlen], pos + rdlen
            if rtype == 12:
                out.append(("PTR", name, _name(buf, pos)[0]))
            elif rtype == 33 and rdlen >= 6:
                _prio, _w, port = struct.unpack(">3H", data[:6])
                out.append(("SRV", name, (_name(buf, pos + 6)[0], port)))
            elif rtype == 16:
                txt, i = {}, 0
                while i < len(data):
                    n = data[i]
                    part = data[i + 1:i + 1 + n].decode("utf-8", "replace")
                    if "=" in part:
                        k, v = part.split("=", 1)
                        txt[k.lower()] = v
                    i += 1 + n
                out.append(("TXT", name, txt))
            elif rtype == 1 and rdlen == 4:
                out.append(("A", name, socket.inet_ntoa(data)))
            pos = rend
    except (ValueError, struct.error, IndexError):
        pass
    return out


def scanners_from(records):
    """Scanners named by the records: [{name, host, port, tls, root}], one per service instance with an address."""
    ptr, srv, txt, addr = {}, {}, {}, {}
    for kind, name, value in records:
        if kind == "PTR" and name in SERVICES:
            ptr[value] = name
        elif kind == "SRV":
            srv[name] = value
        elif kind == "TXT":
            txt[name] = value
        elif kind == "A":
            addr.setdefault(name, value)
    found = []
    for inst, service in ptr.items():
        if inst not in srv:
            continue
        target, port = srv[inst]
        ip = addr.get(target)
        if not ip or not home_network_host(ip):
            continue
        t = txt.get(inst, {})
        root = (t.get("rs") or "eSCL").strip("/") or "eSCL"
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,40}", root):
            root = "eSCL"
        found.append({"name": (t.get("ty") or inst.split("._")[0])[:60], "host": ip, "port": int(port),
                      "tls": service == "_uscans._tcp.local", "root": root})
    return found


def _query(name):
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return q + struct.pack(">HH", 12, 1)


def find(seconds=FIND_SECONDS, sock=None):
    """Ask the home network which scanners are there (mDNS, multicast, no internet). -> list of scanners."""
    own = sock is None
    if own:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    records, seen = [], set()
    try:
        packet = struct.pack(">6H", 0, 0, len(SERVICES), 0, 0, 0) + b"".join(_query(s) for s in SERVICES)
        sock.sendto(packet, (MDNS_GROUP, MDNS_PORT))
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            sock.settimeout(max(0.05, end - time.monotonic()))
            try:
                data, _ = sock.recvfrom(9000)
            except socket.timeout:
                break
            except OSError:
                break
            records += parse_mdns(data)
    finally:
        if own:
            sock.close()
    out = []
    for s in scanners_from(records):
        key = (s["host"], s["port"])
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


# ---- eSCL ---------------------------------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


def base_url(sc):
    return f"{'https' if sc.get('tls') else 'http'}://{sc['host']}:{int(sc['port'])}/{sc.get('root') or 'eSCL'}"


def _request(method, url, body=None, headers=None, timeout=TIMEOUT):
    """-> (status, headers, bytes). Tests replace this. Home-network hosts only (checked by the caller); a scanner's
    self-signed certificate is accepted because the address is a private one; redirects are not followed."""
    handlers = [_NoRedirect]
    if url.startswith("https:"):
        ctx = ssl.create_default_context()
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with opener.open(req, timeout=timeout) as r:  # noqa: S310 (scheme fixed above, host checked)
            return r.status, dict(r.headers), r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b""
    except (urllib.error.URLError, OSError, ssl.SSLError) as e:
        raise ScannerError("The scanner did not answer. Is it on and on the same Wi-Fi?") from e


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def capabilities(sc):
    """(model name, formats, sources) read from the scanner; raises ScannerError when it is not an eSCL scanner."""
    check_host(sc["host"])
    status, _, body = _request("GET", base_url(sc) + "/ScannerCapabilities")
    if status != 200:
        raise ScannerError("That is not a scanner that can scan from here (it needs eSCL / AirScan).")
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise ScannerError("The scanner's answer could not be read.") from e
    model, formats, sources = "", [], []
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "MakeAndModel" and el.text:
            model = el.text.strip()[:60]
        elif tag == "DocumentFormat" and el.text and el.text.strip() not in formats:
            formats.append(el.text.strip())
        elif tag == "Platen" and "glass" not in sources:
            sources.append("glass")
        elif tag == "Adf" and "feeder" not in sources:
            sources.append("feeder")
    return model, formats, sources


def _settings_xml(source, fmt, dpi, color):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<scan:ScanSettings xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm" '
            'xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03">'
            f"<pwg:Version>2.0</pwg:Version><pwg:InputSource>{SOURCES[source]}</pwg:InputSource>"
            f"<scan:ColorMode>{color}</scan:ColorMode><scan:XResolution>{dpi}</scan:XResolution>"
            f"<scan:YResolution>{dpi}</scan:YResolution><pwg:DocumentFormat>{fmt}</pwg:DocumentFormat>"
            "</scan:ScanSettings>").encode()


def scan(sc, source="glass", dpi=300, color="RGB24", sleep=time.sleep):
    """Scan from the glass (one page) or the feeder (every sheet). -> [(bytes, '.pdf' | '.jpg')]. Raises ScannerError."""
    if source not in SOURCES:
        raise ScannerError("Choose the glass or the feeder.")
    _, formats, sources = capabilities(sc)
    if source not in sources:
        raise ScannerError("This scanner has no " + ("document feeder." if source == "feeder" else "glass."))
    fmt, ext = ("application/pdf", ".pdf") if "application/pdf" in formats else ("image/jpeg", ".jpg")
    base = base_url(sc)
    status, headers, _ = _request("POST", base + "/ScanJobs", _settings_xml(source, fmt, int(dpi), color),
                                  {"Content-Type": "text/xml"})
    loc = next((v for k, v in headers.items() if k.lower() == "location"), "")
    if status not in (200, 201) or not loc:
        raise ScannerError("The scanner did not start (busy, no paper, or the lid is open). Try again.")
    path = urllib.parse.urlparse(loc).path  # only the path: a scanner cannot send this PC to another address
    if not path.startswith("/") or ".." in path:
        raise ScannerError("The scanner gave an answer that was not used.")
    job = f"{'https' if sc.get('tls') else 'http'}://{sc['host']}:{int(sc['port'])}{path.rstrip('/')}"
    pages, end = [], time.monotonic() + JOB_SECONDS
    try:
        while len(pages) < MAX_PAGES and time.monotonic() < end:
            status, _, body = _request("GET", job + "/NextDocument")
            if status == 200 and body:
                if len(body) > MAX_BYTES:
                    raise ScannerError("A scanned page was too large.")
                pages.append((body, ext))
                if source == "glass":
                    break
            elif status in (503, 409):  # warming up, or the next sheet is on its way
                sleep(1.0)
            else:
                break  # 404 = no more pages
    finally:
        try:
            _request("DELETE", job, timeout=5)
        except ScannerError:
            pass
    if not pages:
        raise ScannerError("Nothing came out of the scanner. Check the paper or the lid and try again.")
    return pages


def scan_to_inbox(sc, source="glass", save=None, stamp=None, **kw):
    """Scan and put each page in the Inbox through `save(name, bytes)` (inbox_data.save_file). -> (ok, message, [names])."""
    if save is None:
        import inbox_data
        save = inbox_data.save_file
    try:
        pages = scan(sc, source, **kw)
    except ScannerError as e:
        return False, str(e), []
    stamp = stamp or time.strftime("%Y-%m-%d_%H%M%S")
    names, why = [], ""
    for i, (data, ext) in enumerate(pages, 1):
        ok, msg = save(f"scan_{stamp}_p{i}{ext}", data)
        if ok:
            names.append(msg)
        else:
            why = msg
    if not names:
        return False, why or "The scan could not be saved.", []
    n = len(names)
    return True, f"{n} page{'s' if n != 1 else ''} scanned and put in the Inbox." + (f" Not saved: {why}" if why else ""), names


# ---- the chosen scanner -------------------------------------------------------------------------------------------------
def saved():
    sc = config.family().get("scanner")
    if isinstance(sc, dict) and sc.get("host") and home_network_host(sc["host"]):
        return {"host": sc["host"], "port": int(sc.get("port") or 80), "tls": bool(sc.get("tls")),
                "root": sc.get("root") or "eSCL", "name": str(sc.get("name") or "Scanner")[:60]}
    return None


def choose(sc):
    """Check the scanner answers, then keep it. -> (ok, message)."""
    sc = {"host": check_host(sc.get("host")), "port": int(sc.get("port") or 80), "tls": bool(sc.get("tls")),
          "root": sc.get("root") or "eSCL", "name": sc.get("name") or ""}
    if not 1 <= sc["port"] <= 65535:
        raise ScannerError("That port is not right.")
    model, _, _ = capabilities(sc)
    sc["name"] = (model or sc["name"] or "Scanner")[:60]
    with config.family_edit() as cfg:
        cfg["scanner"] = sc
    return True, f"{sc['name']} is ready."


def forget():
    with config.family_edit() as cfg:
        cfg.pop("scanner", None)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else ""
    try:
        if cmd == "find":
            for s in find():
                print(f"{s['name']}  {s['host']}:{s['port']}{' (tls)' if s['tls'] else ''}")
            return 0
        if cmd == "use" and len(argv) > 1:
            host, _, port = argv[1].partition(":")
            print(choose({"host": host, "port": int(port) if port.isdigit() else 80})[1])
            return 0
        if cmd == "scan":
            sc = saved()
            if not sc:
                print("No scanner chosen yet: python data/scanner.py find | use HOST")
                return 1
            ok, msg, _ = scan_to_inbox(sc, "feeder" if "--feeder" in argv else "glass")
            print(msg)
            return 0 if ok else 1
    except ScannerError as e:
        print(e)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
