"""Pair a phone app or a wall tablet from a terminal: for the Docker image, which has no PC screen (Settings > Phones shows
the pairing code only to a browser on the PC itself).

  python data/pair_cli.py phone PERSON PHONE NAME... [--host ADDRESS] [--port PORT] [--invert] [--no-qr]
  python data/pair_cli.py wall [WALL NAME...]        [--host ADDRESS] [--port PORT] [--invert] [--no-qr]

In Docker:  docker compose run --rm mitra pair phone Anna Anna's phone --host 192.168.1.20
ADDRESS = the address of the machine that runs Docker, as the phone reaches it (also MITRAHOME_PUBLIC_HOST); PORT = the
published HTTPS port (also MITRAHOME_PUBLIC_PORT, default 8701). The container must have been started once, so the
certificate exists. The code is one-time and valid for a few minutes; it is a key to the household, so show it only to the
phone that scans it. The QR is drawn in the terminal; the same code is printed as text for a tablet without a camera."""
import argparse
import json
import os
import re
import sqlite3
import sys

import admin_actions as aa
import auth
import brand
import devices
import lan_tls
import qr
import wall

HOST_OK = re.compile(r"^(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|[0-9A-Fa-f:]{2,45})$")
ACTOR = {"name": "terminal", "role": "adult"}


def render(rows, invert=False, border=2):
    """A QR matrix (rows of bools, True = dark) as text, two rows per line with half blocks. Scanners need dark modules on a
    light ground: the default draws light modules as blocks, which is right on a dark terminal; `invert` for a light one."""
    n = len(rows) + 2 * border
    grid = [[False] * n for _ in range(border)]
    grid += [[False] * border + list(r) + [False] * border for r in rows]
    grid += [[False] * n for _ in range(border)]
    if len(grid) % 2:
        grid.append([False] * n)
    glyph = {(True, True): " ", (True, False): "▄", (False, True): "▀", (False, False): "█"}  # (top dark, bottom dark)
    if invert:
        glyph = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}
    return "\n".join("".join(glyph[(grid[y][x], grid[y + 1][x])] for x in range(n)) for y in range(0, len(grid), 2))


def target(host, port):
    """-> (host, port) checked, or raises ValueError with a sentence."""
    host = (host or os.environ.get("MITRAHOME_PUBLIC_HOST") or "").strip()
    if not host:
        raise ValueError("Say which address the phone reaches this server on: --host 192.168.1.20 (or set MITRAHOME_PUBLIC_HOST).")
    if not HOST_OK.match(host):
        raise ValueError("That address does not look right: use an IP address or a name, no http:// and no port.")
    p = str(port or os.environ.get("MITRAHOME_PUBLIC_PORT") or lan_tls.lan_port(8601))
    if not (p.isdigit() and 1 <= int(p) <= 65535):
        raise ValueError("The port must be a number, for example 8701.")
    return host, int(p)


def certificate():
    fp, key = lan_tls.fingerprint(), lan_tls.key_fingerprint()
    if not fp:
        raise ValueError("There is no certificate yet: start the container once (docker compose up -d), then try again.")
    return fp, key


def show(payload, lines, no_qr=False, invert=False):
    if not no_qr:
        print()
        print(render(qr.encode(payload), invert))
    print()
    for ln in lines:
        print("  " + ln)
    print()
    print("  Same code as text (for an app or tablet without a camera):")
    print("  " + payload)
    print()


def phone(person, name, host, port, no_qr=False, invert=False):
    if not auth.users():
        raise ValueError("Set a PIN for an adult first: docker compose run --rm mitra pin NAME adult. Phones sign in with a PIN.")
    host, port = target(host, port)
    fp, key = certificate()
    con = devices._con()
    try:
        secret, info = devices.pair_start(con, person, name, by="terminal")
    except sqlite3.OperationalError as e:
        raise ValueError("The database is not up to date yet: start the container once, then try again.") from e
    finally:
        con.close()
    code = {"v": 1, "h": host, "p": port, "fp": fp, "s": secret}
    if key:
        code["k"] = key
    aa._audit(ACTOR, "phone_pair_code", f"{info['member']}: {info['name']}")
    show(json.dumps(code, separators=(",", ":")),
         [f"Pairing {info['name']} for {info['member']}. Open the {brand.PRODUCT} app > Add this phone and scan, or paste the text.",
          f"Valid until {info['expires_at'][11:16]} (once). Address {host}:{port}",
          f"Certificate fingerprint starts {lan_tls.pretty(fp)[:23]}"], no_qr, invert)


def wall_code(name, host, port, no_qr=False, invert=False):
    if not auth.users():
        raise ValueError("Set a PIN for an adult first: docker compose run --rm mitra pin NAME adult.")
    host, port = target(host, port)
    fp, key = certificate()
    con = wall._con()
    try:
        code, info = wall.pair_start(con, name, by="terminal")
    except wall.WallError as e:
        raise ValueError(str(e)) from e
    except sqlite3.OperationalError as e:
        raise ValueError("The database is not up to date yet: start the container once, then try again.") from e
    finally:
        con.close()
    pretty = wall.pretty_code(code)
    app = {"v": 1, "h": host, "p": port, "fp": fp, "w": pretty}
    if key:
        app["k"] = key
    aa._audit(ACTOR, "wall_pair_code", info["name"])
    show(json.dumps(app, separators=(",", ":")),
         [f"Pairing the wall {info['name']}. In the {brand.PRODUCT} app (wall mode) scan this, or type {pretty}.",
          f"A browser wall opens https://{host}:{port}/wall?code={pretty}",
          f"Valid until {info['expires_at'][11:16]} (once). Certificate fingerprint starts {lan_tls.pretty(fp)[:23]}"], no_qr, invert)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pair_cli.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("what", choices=["phone", "wall"])
    ap.add_argument("words", nargs="*", help="phone: PERSON then the phone's name; wall: the wall's name")
    ap.add_argument("--host")
    ap.add_argument("--port")
    ap.add_argument("--invert", action="store_true", help="for a light terminal")
    ap.add_argument("--no-qr", action="store_true")
    a = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # the QR blocks: a Windows pipe defaults to cp1252
        except (AttributeError, ValueError):
            pass
    try:
        if a.what == "phone":
            if len(a.words) < 2:
                raise ValueError("Say who and what to call the phone: pair phone Anna Anna's phone --host 192.168.1.20")
            phone(a.words[0], " ".join(a.words[1:]), a.host, a.port, a.no_qr, a.invert)
        else:
            wall_code(" ".join(a.words) or "Wall", a.host, a.port, a.no_qr, a.invert)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
