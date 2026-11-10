"""Start the web app (FastAPI).

    python data/web_app.py                 this PC only, http://127.0.0.1:8601
    python data/web_app.py --port 8602
    python data/web_app.py --lan           also phones on the same home Wi-Fi (refused until someone has a PIN)

With --lan the PC keeps http://127.0.0.1:<port> and phones get HTTPS on <port> + 100 (8701), encrypted with this PC's
own certificate (data/lan_tls.py, made the first time). Nothing on the home network is served without encryption.
It reads the same household folder, people and PINs as the rest of the app.
"""
import argparse
import pathlib
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def phone_server(uvicorn, port, cert, key):
    """The HTTPS listener for phones, on every address of this PC."""
    cfg = uvicorn.Config("webapp.app:app", host="0.0.0.0", port=int(port), log_level="warning",  # noqa: S104 (--lan only)
                         server_header=False, ssl_certfile=str(cert), ssl_keyfile=str(key))
    return uvicorn.Server(cfg)


def start_phone_server(server, wait=10.0):
    """Run it in a background thread (no signal handlers there; it ends with the app). -> True once it listens."""
    t = threading.Thread(target=server.run, name="phones-https", daemon=True)
    t.start()
    end = time.time() + wait
    while time.time() < end and t.is_alive() and not server.started:
        time.sleep(0.05)
    return bool(server.started)


def waiting_updates():
    """Database updates (migrations) not applied yet -> their file names; [] for a brand-new install with no database
    yet (the first-run setup makes it) or a database that cannot be read (the app says so on its pages)."""
    import sqlite3
    import db
    import paths
    if not paths.DB.exists():
        return []
    try:
        import migrate
        with db.open(paths.DB, readonly=True) as con:
            return [p.name for p in migrate.pending(con)]
    except sqlite3.Error:
        return []


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--port", type=int, default=8601)
    ap.add_argument("--lan", action="store_true", help="also phones on the home network, over HTTPS (needs a PIN)")
    ap.add_argument("--lan-port", type=int, default=0, help="HTTPS port for phones (default: --port + 100)")
    args = ap.parse_args(argv)
    import log
    log.use("web")  # runs for hours: a log file of its own (log.py)
    import auth
    import brand
    waiting = waiting_updates()
    if waiting:  # audit A10: new code on an old database would show empty pages and fail on writes
        print(f"{len(waiting)} database update(s) are waiting, so the app does not start on the old database. Start it "
              f"with \"Start {brand.PRODUCT}\" (it backs up the database and applies them first), or run: "
              "python onboard.py upgrade")
        return 3
    if args.lan and not auth.users():
        print("Phones on the network need a PIN first. Set one in Settings > Home Profile first (this PC), then start again.")
        return 2
    try:
        import uvicorn
    except ImportError:
        print("The web app needs: python -m pip install fastapi uvicorn jinja2   (they are in requirements.txt)")
        return 2
    import os
    os.environ["MITRAHOME_WEB_LAN"] = "1" if args.lan else ""  # a restore starts the web app again the same way
    os.environ["MITRAHOME_WEB_PORT"] = str(args.port)  # ... on this PC's port (a phone's request arrives on port + 100)
    os.environ["MITRAHOME_WEB_LAN_PORT"] = ""
    print(f"{brand.PRODUCT} web app: http://127.0.0.1:{args.port}")
    try:  # jobs that exist but whose flag was never written (R: had them for days): say so in family.json
        import task_register
        task_register.adopt_flags()
    except Exception:  # noqa: BLE001
        pass
    if args.lan:
        import lan_tls
        try:
            fp, change = lan_tls.ensure(lan_tls.lan_ip())
        except ImportError:
            print("Phones need encryption, which needs: python -m pip install cryptography   (it is in requirements.txt)")
            return 2
        port = args.lan_port or lan_tls.lan_port(args.port)
        os.environ["MITRAHOME_WEB_LAN_PORT"] = str(port)
        if not start_phone_server(phone_server(uvicorn, port, lan_tls.cert_path(), lan_tls.key_path())):
            print(f"Phones: could not listen on port {port} (another program uses it?). Close it and start again.")
            return 2
        in_box = os.environ.get("MITRAHOME_CONTAINER") == "1"
        ip = "<server-address>" if in_box else (lan_tls.lan_ip() or "<this PC's address>")
        print(f"Phones on this Wi-Fi: https://{ip}:{port}  (certificate {'just made' if change == 'made' else 'renewed, same key' if change else 'kept'}, "
              f"fingerprint starts {lan_tls.pretty(fp)[:23]})")
        remote = lan_tls.remote_ip()
        if remote:
            print(f"Phones on your private network (away from home): https://{remote}:{port}")
    try:  # this process is the app folder's web app, also when a restart from Settings started it (not launch.py), so
        import dashboard_record  # the 5-minute start task and the next double-click reopen it instead of a second copy
        dashboard_record.write(args.port, pid=os.getpid(), lan=args.lan)
    except Exception:  # noqa: BLE001
        pass
    uvicorn.run("webapp.app:app", host="127.0.0.1", port=args.port, log_level="warning", server_header=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
