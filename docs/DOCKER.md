# Mitra Home in Docker (Linux server or NAS)

For phones and wall tablets only. The container serves HTTPS on port 8701 and **requires a PIN**; the PC browser
screen (plain http, trusted on loopback) is deliberately not offered. Setup is done in a terminal.

## First time

```bash
docker compose build
docker compose run --rm mitra setup          # quick-start questions: family name, people, country
docker compose run --rm mitra pin Anna adult # one PIN per adult (asked twice is not needed; type it when prompted)
docker compose up -d
```

`serve` refuses to start until `setup` has made a household, and phone access starts only once an adult has a PIN.

Then open Settings > Phones from a phone on the same Wi-Fi at `https://<server-ip>:8701` (the first visit shows a
certificate warning: check that the fingerprint printed by `docker compose logs mitra` matches), or pair the phone app.
Settings pages that change the PC itself stay PC-only and are not reachable here; use the terminal
(`docker compose run --rm mitra shell`).

## What runs inside

- The web app (`launch.py --no-browser --lan`) on 8601 inside the container, HTTPS for phones on 8701.
- A small scheduler (`docker/scheduler.py`) running the household's jobs (daily brief, weekly digest, weekly backup,
  inbox check). `crontab` inside the image is a shim that keeps the lines in `/data/config/crontab.txt`, so
  `onboard.py` and Settings work unchanged. The AI steps need an API-key provider; the Claude CLI is not in the image.

## Your data

Everything (database, papers, settings, certificate) is in the `mitra-data` volume mounted at `/data`. Back that
volume up. Never publish port 8701 to the internet; use Tailscale (docs/REMOTE_ACCESS.md) for away-from-home access.

## Update

```bash
git pull && docker compose build && docker compose up -d
```

The start step brings the database up to date (a backup is taken first).
