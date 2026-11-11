# Mitra Home in Docker (Linux server or NAS)

For phones and wall tablets only. The container serves HTTPS on port 8701 and **requires a PIN**; the PC browser
screen (plain http, trusted on loopback) is deliberately not offered. Setup is done in a terminal.

## First time

Get the code of the latest release (0.148.0 is the first with Docker; there is no published image yet, you build it):

```bash
git clone --branch v0.148.0 https://github.com/rNetGit/mitra-home-app.git mitra-home && cd mitra-home
docker compose build
docker compose run --rm mitra setup          # quick-start questions: family name, people, country
docker compose run --rm mitra pin Anna adult # one PIN per adult (asked twice is not needed; type it when prompted)
docker compose up -d
```

`serve` refuses to start until `setup` has made a household, and phone access starts only once an adult has a PIN.

Then open Settings > Phones from a phone on the same Wi-Fi at `https://<server-ip>:8701` (the first visit shows a
certificate warning: check that the fingerprint printed by `docker compose logs mitra` matches).
Settings pages that change the PC itself stay PC-only and are not reachable here; use the terminal
(`docker compose run --rm mitra shell`).

## Pairing the phone app or a wall

Settings > Phones shows its pairing code only on the PC itself, and a container has no PC screen. Make the code in the
terminal instead. Start the container once first (the certificate is made then), and give the address your phone uses
for the server (not the container's 172.x address):

```bash
docker compose run --rm mitra pair phone Anna "Anna's phone" --host 192.168.1.20
docker compose run --rm mitra pair wall "Kitchen wall" --host 192.168.1.20
```

A QR code is drawn in the terminal (`--invert` on a light terminal, `--no-qr` for text only); scan it with the app, or
paste the text line under it. Use `--port` if you publish a different port, or set `MITRAHOME_PUBLIC_HOST` and
`MITRAHOME_PUBLIC_PORT` in a `.env` file next to `docker-compose.yml` to leave `--host` out. The code works once and
for a few minutes. Show it only to the phone that scans it: it is a key to the household. A person needs a PIN first.

## What runs inside

- The web app (`launch.py --no-browser --lan`) on 8601 inside the container, HTTPS for phones on 8701.
- A small scheduler (`docker/scheduler.py`) running the household's jobs (daily brief, weekly digest, weekly backup,
  inbox check). `crontab` inside the image is a shim that keeps the lines in `/data/config/crontab.txt`, so
  `onboard.py` and Settings work unchanged. The AI steps need an API-key provider; the Claude CLI is not in the image.

## Timezone

The container clock is UTC unless you set `TZ`, so the 7:00 daily brief would run at 7:00 UTC. Set your zone before
`up`: `TZ=America/New_York docker compose up -d` (or put `TZ=...` in a `.env` file next to `docker-compose.yml`).

## Notes on what you see in the logs

The image sets `MITRAHOME_CONTAINER=1`, so the start-up text talks about the server: it prints `https://<server-address>:8701`
(use your server's own address, not the container address 172.x.x.x) and leaves out the Windows Firewall lines. The setup
wizard (`docker compose run --rm mitra setup`) says "this server" too and notes that the signed-in AI options (Claude Code and the other CLIs) are not in the image, so pick an API key option or none. Pairing steps that say "Settings > Phones" are done from a phone's browser or the app on the home Wi-Fi.

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

To a new release (replace the tag with the newest one on the Releases page):

```bash
git fetch --tags && git checkout v0.148.0 && docker compose build && docker compose up -d
```

If you follow `main` instead of releases: `git pull && docker compose build && docker compose up -d`.

The start step brings the database up to date (a backup is taken first).

The in-app update (Settings > Data > Updates, the Inbox "update" item, `onboard.py update`) does not install inside a container: files changed there are lost when the container is recreated. It says so and shows this command. Checking for a new version still works.
