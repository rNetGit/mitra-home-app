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

## Timezone

The container clock is UTC unless you set `TZ`, so the 7:00 daily brief would run at 7:00 UTC. Set your zone before
`up`: `TZ=America/New_York docker compose up -d` (or put `TZ=...` in a `.env` file next to `docker-compose.yml`).

## Notes on what you see in the logs

The start-up text was written for a PC. Inside the container, ignore "on this PC", the Windows Firewall lines and the
container address it prints (172.x.x.x). Use your server's own address: `https://<server-ip>:8701`. Setup and pairing
steps that say "Settings > Phones on this PC" are done from a phone's browser or the app on the home Wi-Fi.

## Changing a job time

The jobs are lines in `/data/config/crontab.txt` (the standard five time fields, then the command). Settings and
`onboard.py` write it for you. To see or edit by hand:
`docker compose exec mitra crontab -l`, for example the daily brief at 7:00:
`0 7 * * * cd '/app' && '/opt/venv/bin/python' tasks/run_task.py daily_digest`

## Your data

Everything (database, papers, settings, certificate) is in the `mitra-data` volume mounted at `/data`; weekly backups go to the
`mitra-backup` volume (`/Mitra-Home-Backup`). Back both up, and copy the backups off the server too.
Never publish port 8701 to the internet; use Tailscale (docs/REMOTE_ACCESS.md) for away-from-home access.

## Update

```bash
git pull && docker compose build && docker compose up -d
```

The start step brings the database up to date (a backup is taken first).
