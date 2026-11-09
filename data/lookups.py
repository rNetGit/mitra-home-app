"""Online look-ups (schools near home, a college's name, a school's or employer's year calendar, the local weather): the
one door to the internet for them, with the family's switch and a privacy fence.

Off until an adult turns it on (Family > House > "Look things up online"; config/family.json lookups.online). What may go
out: the home ZIP code and state, the public name of a school, college, district or employer, a school year, and the
address of a public web page. What never goes out: anyone's name, the family name, the names printed on papers, account,
card, ID or SSN-shaped numbers, email addresses, phone numbers or a street address. Every outgoing text (the URL with its
query, and any question for the family's AI) passes check_out() first; a refusal stops the look-up and nothing is sent.

Downloads: http(s) only, public hosts only (never this PC, the home network or a link-local address), at most MAX_BYTES,
TIMEOUT seconds. Tests replace _open().

  python data/lookups.py status
  python data/lookups.py check "TEXT"        would this text be allowed out? (nothing is sent)
"""
import argparse
import http.client
import ipaddress
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

import pathlib
HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import brand  # noqa: E402
import config  # noqa: E402
import pii  # noqa: E402

TIMEOUT = 20
MAX_BYTES = 8_000_000
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)")
STREET = re.compile(r"(?i)\b\d{1,6}\s+(?:[NSEW]\.?\s+)?[A-Za-z][A-Za-z .'-]{1,40}\s(?:st|street|ave|avenue|rd|road|dr|drive|"
                    r"ln|lane|ct|court|blvd|boulevard|way|pl|place|ter|terrace|cir|circle|pkwy|parkway|hwy|highway)\b\.?")


def _card(digits):
    """True for a run of 13-19 digits that passes the Luhn check (a payment card number)."""
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


class Refused(ValueError):
    """The look-up was stopped before anything left this PC."""


def enabled(cfg=None):
    cfg = config.family() if cfg is None else cfg
    return bool((cfg.get("lookups") or {}).get("online"))


def _terms():
    """Words that must never leave: everyone's names (and their parts of 3+ letters), the family name, paper names."""
    names, extra, _on = pii.household_terms()  # names even when masking for the AI is off: the fence is separate
    fam = config.family()
    names = list(names) + [m.get("name", "") for m in fam.get("members", [])]
    names += list((fam.get("privacy") or {}).get("paper_names") or []) + pii.surname_words(fam.get("family_name"))
    out = set()
    for n in list(names) + list(extra):
        for w in re.findall(r"[^\W\d_]+", n or ""):
            if len(w) >= 3:
                out.add(w.lower())
    return out


def problem(text, terms=None):
    """-> why this text may not go out, or ''."""
    t = urllib.parse.unquote_plus(str(text or ""))
    if PHONE.search(t):
        return "it carries a phone number"
    if pii.contains_hard(t):
        return "it carries an account, ID or SSN-shaped number or an email address"
    if STREET.search(t):
        return "it carries a street address"
    words = {w.lower() for w in re.findall(r"[^\W\d_]+", t)}
    hit = sorted(words & (_terms() if terms is None else terms))
    if hit:
        return "it carries a name from this family"
    return ""


def check_out(*texts):
    """Raise Refused when any text may not leave this PC."""
    terms = _terms()
    for t in texts:
        why = problem(t, terms)
        if why:
            raise Refused(f"Nothing was looked up: {why}. Only public names of schools, colleges or employers, the ZIP "
                          "code and the state go out.")


def need_on():
    if not enabled():
        raise Refused("Online look-ups are off. Turn them on in Family > House (edit) first.")


def _public_ips(host):
    """The addresses the host resolves to when every one is public (no loopback, private, link-local or reserved),
    else []."""
    if not host:
        return []
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError, OSError):
        return []
    ips = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            return []
        if not ip.is_global or ip.is_multicast:
            return []
        ips.append(str(ip))
    return ips


def _public_host(host):
    """True when every address the host resolves to is a public one."""
    return bool(_public_ips(host))


def _connect_public(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **_kw):
    """Open the socket to an address checked in this same call: a name that answers public for the check and private
    for the connection (DNS rebinding, audit L2) cannot reach this PC or the home network."""
    host, port = address[0], address[1]
    ips = _public_ips(host)
    if not ips:
        raise Refused("That address is not on the public internet.")
    err = None
    for ip in ips:  # like socket.create_connection by name: the next address when one does not answer
        try:
            return socket.create_connection((ip, port), timeout, source_address)
        except OSError as e:
            err = e
    raise err


class _PublicHTTP(http.client.HTTPConnection):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_public


class _PublicHTTPS(http.client.HTTPSConnection):  # the certificate is still checked against the host name
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._create_connection = _connect_public


class _PublicHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTP, req)


class _PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPS, req, context=self._context)


PUBLIC_CAL_ID = re.compile(r"(?i)[\w.-]+(?:%40|@)(?:group|import)\.calendar\.google\.com")


def url_text(url):
    """The part of a web address the fence reads: long numbers in a path (file and page ids) and public Google
    calendar ids are not personal; a card number, a personal address (someone@gmail.com) or a name still is."""
    t = PUBLIC_CAL_ID.sub(" calendar ", urllib.parse.unquote(str(url or "")))
    # a long number passes as an id, except a card number: that one stays for problem() to refuse
    return re.sub(r"\d{9,}", lambda m: m.group() if _card(m.group()) else "N", t)


def safe_url(url):
    """-> the URL when it is an http(s) address of a public host with no user info, else Refused."""
    u = urllib.parse.urlsplit(str(url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
        raise Refused("That is not a web address (http or https) this app can open.")
    if len(url) > 2000:
        raise Refused("That web address is too long.")
    return urllib.parse.urlunsplit(u)


class _NoPrivateRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        u = urllib.parse.urlsplit(newurl)
        if u.scheme not in ("http", "https") or not _public_host(u.hostname):
            raise Refused("The page sent the look-up somewhere this app does not open.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open(req):
    """Open with this module's own opener (a redirect to a private address is refused; other modules' urllib calls
    are not touched). Tests replace this. -> (status, content_type, bytes, final_url)."""
    # through a proxy the proxy resolves the name (and may be on the home network): only the host check above applies
    handlers = [] if urllib.request.getproxies() else [_PublicHTTPHandler, _PublicHTTPSHandler]
    opener = urllib.request.build_opener(_NoPrivateRedirect, *handlers)
    with opener.open(req, timeout=TIMEOUT) as r:  # noqa: S310 (scheme and host checked in get())
        return r.status, r.headers.get("Content-Type", ""), r.read(MAX_BYTES + 1), r.geturl()


def get(url, accept="text/html, application/pdf, text/calendar, application/json;q=0.9, */*;q=0.5", check_host=True):
    """GET a public address after the switch and the fence. -> (content_type, bytes, final_url). Raises Refused."""
    need_on()
    url = safe_url(url)
    check_out(url_text(url))
    host = urllib.parse.urlsplit(url).hostname
    if check_host and not _public_host(host):
        raise Refused("That address is not on the public internet.")
    req = urllib.request.Request(url, method="GET")
    req.add_header("User-Agent", f"{brand.PRODUCT} look-up")
    req.add_header("Accept", accept)
    try:
        status, ctype, body, final = _open(req)
    except urllib.error.HTTPError as e:
        raise Refused(f"{host} answered {e.code}.") from None
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise Refused(f"{host} could not be reached ({str(getattr(e, 'reason', e))[:80]}).") from None
    if status and status >= 400:
        raise Refused(f"{host} answered {status}.")
    if len(body) > MAX_BYTES:
        raise Refused("That file is too big to read here (over 8 MB).")
    return (ctype or "").split(";")[0].strip().lower(), body, final or url


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    c = sub.add_parser("check")
    c.add_argument("text")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print("Online look-ups: " + ("on" if enabled() else "off"))
        return 0
    why = problem(a.text)
    print("Would be sent." if not why else f"Would be refused: {why}.")
    return 0 if not why else 1


if __name__ == "__main__":
    sys.exit(main())
