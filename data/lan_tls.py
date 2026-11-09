"""The certificate that encrypts phone connections on the home Wi-Fi (HTTPS), made on this PC the first time it is needed.

  python data/lan_tls.py status     where the certificate is, its fingerprint and until when it is valid
  python data/lan_tls.py new        make a new key and certificate (every paired phone must then be paired again)

Self-signed on purpose: no certificate authority, nothing to install on a phone. The phone app learns from the pairing
QR code the SHA-256 of the certificate (`fp`) and of its public key (`k`, phone app 0.14+) and accepts only that server
(pinning), whatever address the PC has on the Wi-Fi. A browser on a phone or tablet shows a warning the first time;
compare the fingerprint, then continue.

iPhones and iPads refuse a certificate valid for more than 825 days outright (no "continue" button), so the certificate
is valid for DAYS (397) and names this PC's current address, and its address on a private network such as Tailscale
when there is one (remote_ip(): reach the app away from home, docs/REMOTE_ACCESS.md). ensure() renews it, with the SAME private key, when it is
too long-lived (made before 0.124.1), within RENEW_DAYS of its end, or names another address: a phone that pinned the key
keeps working; one that pinned the certificate (an app before 0.14, the iPhone app) pairs again.

Files: `config/tls/cert.pem` and `config/tls/key.pem` in the household folder (never in a backup sent anywhere, never
in an export; the private key is readable by this user only on Mac/Linux). `cryptography` (requirements.txt) makes
them; the rest of this module is standard library only, so launch.py can import it.
"""
import datetime as dt
import hashlib
import ipaddress
import os
import pathlib
import socket
import ssl
import sys

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

LAN_PORT_OFFSET = 100   # phones use HTTPS on the app's port + 100 (8601 -> 8701); the PC keeps http://127.0.0.1:8601
DAYS = 397          # under Apple's 398-day limit for any HTTPS certificate
APPLE_MAX_DAYS = 825  # longer = refused outright by iOS / iPadOS 13+
RENEW_DAYS = 30
PRIVATE_NET = ipaddress.ip_network("100.64.0.0/10")  # Tailscale (and other shared-address VPNs) hand out addresses here
PRIVATE_DNS = "100.100.100.100"  # Tailscale's own resolver: the route to it shows this PC's Tailscale address


def folder():
    import paths  # here, not at the top: launch.py imports this module before the household folder may exist
    return paths.CONFIG / "tls"


def cert_path():
    return folder() / "cert.pem"


def key_path():
    return folder() / "key.pem"


def lan_port(port):
    return int(port) + LAN_PORT_OFFSET


def lan_ip():
    """This PC's address on the home network, or None. (A UDP connect sends nothing; it only picks the route.)"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 9))
            ip = s.getsockname()[0]
    except OSError:
        return None
    return None if ip.startswith(("127.", "0.")) else ip


def remote_ip():
    """This PC's address on a private network that reaches it away from home, or None: MITRAHOME_REMOTE_IP when the
    family set one (another VPN), else the Tailscale address (100.64.0.0/10) when Tailscale is running. A UDP connect
    sends nothing; it only picks the route."""
    try:
        import paths
        fixed = paths.env("MITRAHOME_REMOTE_IP").strip()
    except Exception:  # noqa: BLE001 (launch.py may call this before the household folder exists)
        fixed = ""
    if fixed:
        try:
            return str(ipaddress.ip_address(fixed))
        except ValueError:
            return None
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((PRIVATE_DNS, 53))
            ip = s.getsockname()[0]
    except OSError:
        return None
    try:
        return ip if ipaddress.ip_address(ip) in PRIVATE_NET and ip != PRIVATE_DNS else None
    except ValueError:
        return None


def fingerprint(pem=None):
    """SHA-256 of the certificate (DER), 64 lowercase hex characters, or None when there is no certificate yet."""
    try:
        text = pem if pem is not None else cert_path().read_text(encoding="ascii")
        der = ssl.PEM_cert_to_DER_cert(text)
    except (OSError, ValueError):
        return None
    return hashlib.sha256(der).hexdigest()


def key_fingerprint(pem=None):
    """SHA-256 of the certificate's public key (SubjectPublicKeyInfo, DER), 64 lowercase hex characters, or None.
    It stays the same when the certificate is renewed with the same key (the phone app's pin from 0.14)."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import serialization
        c = x509.load_pem_x509_certificate(pem.encode("ascii") if pem is not None else cert_path().read_bytes())
        der = c.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    except (ImportError, OSError, ValueError):
        return None
    return hashlib.sha256(der).hexdigest()


def pretty(fp):
    """AB:CD:... in groups, the way phones and browsers show a certificate's fingerprint."""
    return ":".join(fp[i:i + 2] for i in range(0, len(fp or ""), 2)).upper()


def _load_key():
    from cryptography.hazmat.primitives import serialization
    try:
        return serialization.load_pem_private_key(key_path().read_bytes(), password=None)
    except (OSError, ValueError, TypeError):
        return None


def make(ip=None, now=None, keep_key=False, also=()):
    """Write a self-signed certificate (EC P-256, valid DAYS, naming localhost, 127.0.0.1, `ip` and the addresses in
    `also`, such as the Tailscale one). keep_key = sign it with the existing private key (a renewal: the key pin stays);
    else a new key. -> fingerprint."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
    import brand
    now = now or dt.datetime.now(dt.timezone.utc)
    key = _load_key() if keep_key else None
    new_key = key is None
    if new_key:
        key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"{brand.PRODUCT} on this PC")])
    alt = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    for a in [ip, *also]:
        if not a:
            continue
        try:
            addr = x509.IPAddress(ipaddress.ip_address(a))
        except ValueError:
            continue
        if addr not in alt:
            alt.append(addr)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=DAYS - 1))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
            .sign(key, hashes.SHA256()))
    folder().mkdir(parents=True, exist_ok=True)
    if new_key:
        kp = key_path()
        tmp = kp.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                      serialization.NoEncryption()))
        os.replace(tmp, kp)
    cp = cert_path()
    tmp = cp.with_suffix(".tmp")
    tmp.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.replace(tmp, cp)
    return fingerprint()


def renew_reason(ip=None, now=None, also=()):
    """Why the certificate should be renewed now ('' = it is fine): too long for iPhones and iPads, ending soon, or
    not naming this PC's current address (or one of `also`, its private-network address)."""
    from cryptography import x509
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        c = x509.load_pem_x509_certificate(cert_path().read_bytes())
    except (OSError, ValueError):
        return "unreadable"
    if (c.not_valid_after_utc - c.not_valid_before_utc).days > APPLE_MAX_DAYS:
        return "too long for iPhones and iPads"
    if c.not_valid_after_utc - now < dt.timedelta(days=RENEW_DAYS):
        return "ends soon"
    want = [a for a in [ip, *also] if a]
    if want:
        try:
            names = c.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            ips = {str(a) for a in names.get_values_for_type(x509.IPAddress)}
        except x509.ExtensionNotFound:
            ips = set()
        if any(a not in ips for a in want):
            return "new address"
    return ""


def ensure(ip=None, now=None, also=None):
    """The certificate's fingerprint, made or renewed first when needed. `also` = other addresses to name (default:
    this PC's private-network address, remote_ip()). A renewal keeps the private key, so the key pin (key_fingerprint)
    stays. -> (fingerprint, change) with change '' (kept), 'made' or 'renewed'."""
    also = [a for a in ([remote_ip()] if also is None else also) if a]
    if not key_path().exists() or _load_key() is None:
        return make(ip, now, also=also), "made"
    why = renew_reason(ip, now, also)
    if not why:
        return fingerprint(), ""
    return make(ip, now, keep_key=True, also=also), "renewed"


def status():
    """{'exists','fingerprint','not_after'} without making anything."""
    fp = fingerprint()
    out = {"exists": bool(fp), "fingerprint": fp, "not_after": None}
    if fp:
        try:
            from cryptography import x509
            c = x509.load_pem_x509_certificate(cert_path().read_bytes())
            out["not_after"] = c.not_valid_after_utc.date().isoformat()
        except (ImportError, OSError, ValueError):
            pass
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    cmd = argv[0] if argv else "status"
    if cmd == "new":
        fp = make(lan_ip(), also=[a for a in [remote_ip()] if a])
        print("New key and certificate made. Pair every phone again (Settings > Phones).")
        print("Fingerprint (SHA-256):", pretty(fp))
        return 0
    if cmd == "status":
        st = status()
        if not st["exists"]:
            print("No certificate yet: it is made when the app first starts for phones (Start ... for phones).")
            return 0
        print("Certificate:", cert_path())
        print("Fingerprint (SHA-256):", pretty(st["fingerprint"]))
        if st["not_after"]:
            print("Valid until:", st["not_after"])
        print("Key (SHA-256):", pretty(key_fingerprint() or ""))
        if remote_ip():
            print("Away from home (private network):", remote_ip())
        why = renew_reason(lan_ip(), also=[a for a in [remote_ip()] if a])
        if why:
            print(f"Renewed at the next start for phones ({why}).")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
