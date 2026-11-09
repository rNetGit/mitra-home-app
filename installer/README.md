# Windows installer (maintainer)

`python installer/build_installer.py [--ref vX.Y.Z]` -> `dist/installer/MitraHome-Setup-<version>.exe`.
Needs Inno Setup 6 (`winget install JRSoftware.InnoSetup`) and internet for the first build (downloads are cached in
`installer/build/cache/`). Builds from a committed ref: uncommitted changes are not packaged.

## What the family gets
- One `.exe`, no administrator rights, no Python needed beforehand.
- Code in `%LOCALAPPDATA%\Programs\MitraHome` (updates with `onboard.py update` as a zip install).
- Python 3.12 (python-build-standalone) in `%LOCALAPPDATA%\MitraHome\runtime`, with every package of
  `requirements.txt` as wheels; the installer makes the private environment (`...\MitraHome\venv`) from them while it installs (`launch.py --prepare`), offline, so the first start is quick.
- Household folder chosen on a wizard page, default `Documents\Mitra-Home-Data`, or `%USERPROFILE%\Mitra-Home-Data`
  when Documents is redirected to OneDrive (common on Windows 11). Picking a OneDrive / Dropbox / Google Drive path
  asks first. Silent install: `/VERYSILENT /HOME="D:\Family\Mitra-Home-Data"`. Made by `launch.py --home` on the first
  start.
- Start menu: Mitra Home (follows Settings > Phones > Connection: phones and walls on the home Wi-Fi by default, once an
  adult has a PIN), Mitra Home (this PC only), Mitra Home health check; optional desktop icon.
- Uninstall removes code, Python, the environment and this install's scheduled tasks; the household folder stays.
- An installer older than the installed `VERSION` refuses to run (an install updated in place stays ahead).

## Not done yet
- Code signing: wired (`--sign`, see below) but needs the Azure account first. Unsigned builds make SmartScreen warn
  ("More info > Run anyway"); a new signed publisher still warns until the installer has some download reputation.
- Start at sign-in: a wizard checkbox (ticked by default) registers the web app's keep-alive task (`data/autostart.py on web --no-start --home <folder>`, PC only: a task every 5 minutes, first tick in 10, restarts the app after it stopped; a sign-in trigger is refused without admin on some PCs). It follows the phones setting like the Start menu entry. Uninstall removes the task.
- Firewall rule for phones (port + 100): a per-user installer cannot add it; Settings > Phones > Connection > Allow
  phones through Windows Firewall asks Windows (UAC) for that one rule.
- The app runs with no window (shortcuts = `pythonw.exe launch.py --quiet`); Settings > Data > Stop ends it. The installer stops a running app before it replaces files; the uninstaller stops it too. The last page names the app, household and backup folders.
- Python itself is not updated by `onboard.py update`; a new installer brings a new runtime.

## Code signing (Azure Artifact Signing, formerly Trusted Signing)
One-time, in the owner's Azure account (nobody else can do these): subscription, resource provider
`Microsoft.CodeSigning`, a Code Signing Account, identity validation (days), a Public Trust certificate profile, and
the role "Artifact Signing Certificate Profile Signer" for the user who signs. Then on the build PC:
1. Windows SDK (signtool) and the Artifact Signing client package (NuGet, contains `Azure.CodeSigning.Dlib.dll`).
2. `az login` (no secret is stored anywhere).
3. A metadata file outside the repo, e.g. `%USERPROFILE%\.mitra\signing\metadata.json`:
   `{"Endpoint": "https://<region>.codesigning.azure.net", "CodeSigningAccountName": "...", "CertificateProfileName": "..."}`
4. Environment: `MITRA_SIGN_DLIB` (path to the dll), `MITRA_SIGN_METADATA` (path to the json), optional `MITRA_SIGNTOOL`.
5. `python installer/build_installer.py --sign` signs the installer and uninstaller (SHA256, Microsoft timestamp) and
   runs `signtool verify /pa`. Without `--sign` nothing changes.
The certificate lasts days and is renewed by the service, so there is no key file to guard or lose. The `SHA256SUMS.sig`
release signature (`scripts/sign_release.py`) is a separate thing and stays.

# Mac app (maintainer)

`python installer/build_mac.py [--ref vX.Y.Z] [--arch arm64|x86_64]` -> `dist/installer/MitraHome-<version>-mac-arm64.zip`
and `-mac-intel.zip`. Runs on any computer (built on Windows): the zip is written straight from `git archive`, the
python-build-standalone macOS archive (SHA256-checked) and macOS wheels fetched with `pip download --platform ...`,
so file modes and symlinks are kept. Needs Pillow for the icon (else the default icon).

`--dmg` (on a Mac only; refused elsewhere before anything is downloaded) also writes `MitraHome-<version>-mac-arm64.dmg`
/ `-mac-intel.dmg` next to each zip: the zip unpacked with `ditto` plus an Applications shortcut, packed by `hdiutil`
(compressed, HFS+, volume "Mitra Home").

## What the family gets
- `Mitra Home.app` in a zip (unzip, drag to Applications) or a `.dmg` (open, drag the app onto Applications), then
  double-click. No Python, no admin rights.
- First start: the code is copied to `~/Library/Application Support/MitraHome/app` (writable, so `onboard.py update`
  works as for a zip install; a newer app copies newer code over it), the private environment is made from the
  bundled Python and wheels (offline), the household folder is `~/Documents/Mitra-Home-Data`, the browser opens.
- Runs in the background (no Dock icon, `LSUIElement`); double-clicking again reopens the browser. Log:
  `~/Library/Logs/MitraHome/start.log`. Scheduled jobs: LaunchAgents (Settings > Data > Runs on its own).

## Not done yet
- Tried on an Apple silicon Mac (the arm64 .dmg: first start offline and the setup page work). Not tried: the Intel
  build and the "Open Anyway" step below.
- Unsigned: macOS says it "cannot be opened". The family opens System Settings > Privacy & Security > Open Anyway once.
  Signing + notarizing: Apple Developer Program, then `rcodesign sign` + `rcodesign notary-submit --staple` (works from
  Windows or Linux).
- No way to stop it except logging out or Activity Monitor; no phones (LAN) start yet; no iCloud Documents warning.
- The `.dmg` needs a Mac to build (`--dmg`); a build on Windows or Linux gives the zip only.
- The `.dmg` has no background picture or icon layout yet, and is unsigned like the app inside it.
