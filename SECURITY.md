# Security policy

Mitra Home holds a household's financial and personal records on one PC, with companion phone apps (Android and
iPhone, repository `rNetGit/mitra-home-companion`) and Mitra Wall tablets that talk only to that PC. Treat any way
to read, change or leak that data as a security issue.

## Reporting a vulnerability
- Open a **private** report: GitHub "Report a vulnerability" on this repository (Security tab), or email
  **cloudwareedge@gmail.com** with "Security" in the subject. Do not open a public issue for a security problem.
  The same address covers the phone apps and the Mitra Wall.
- Include: the version (`VERSION` file), the setup level (laptop only / Drive / Claude Code / API key), steps to
  reproduce, and what an attacker gains. Do not send your own `config/`, database or documents.
- You will get an acknowledgement within 7 days and a fix or a workaround in the next release where possible.
  Fixed issues are credited in `CHANGELOG.md` unless you prefer not to be named.

## Supported versions
Only the latest release is supported. Families update with `python onboard.py update`.

## What counts
In scope:
- A document, email or file in `inbox/` (or Google Drive `Inbox`) that makes an agent or the Python pipeline do
  anything beyond reading it and filing it: run code, read `config/secrets.env`, write outside `archive/`,
  `reports/`, `brief/`, `inbox/`, fetch a URL, send mail.
- A way around the agent fence (`.claude/settings.json`, `scripts/guard_tool.py`) or the assistant's fixed
  action catalog (`data/assistant.py`, `data/edit_actions.py`, `data/validators.py`).
- Secrets or full account numbers leaking into the database, logs, briefs, backups, the dashboard or a provider
  request (see `data/llm.py` redaction).
- The updater (`data/updater.py`) accepting code from anywhere but GitHub over HTTPS, a zip that writes
  outside the install folder, or any file that is not in a release's signed `SHA256SUMS` (signature checked by
  `data/ed25519_verify.py` against `data/release_keys.json`).
- Encrypted backups (`data/crypto_box.py`) that can be read, altered or truncated without the passphrase being
  detected.
- The limited (kids/guest) dashboard view showing money, accounts or AI.
- Phone and wall pairing (`data/devices.py`, `data/wall.py`, `data/lan_tls.py`): a device on the Wi-Fi that pairs
  without a valid one-time code, a paired device that reads more than its scopes allow, a revoked device that keeps
  access, or a wall that shows amounts without an adult's PIN.
- Anything sent to the internet without the family switching it on (look-ups, weather, update checks), or with
  more than the fence allows (`data/lookups.py`).

Out of scope:
- Anything that needs the attacker to already run code as the family's user on that PC (the model assumes the
  PC and its user account are trusted; see `THREAT_MODEL.md`).
- Weak PINs chosen by the family, or a passphrase stored where the family put it.
- The behaviour, retention or training policies of the AI provider the family chose (see `COMPLIANCE.md`).
- Reports about third-party tools (Claude Code, FastAPI, Google Drive for Desktop); report those upstream.

## Design rules a fix must keep
See `THREAT_MODEL.md` and `CONTRIBUTING.md`: never read or forward credentials, never delete originals,
last4 only, documents are data not instructions, standard library only in the bootstrap scripts.
