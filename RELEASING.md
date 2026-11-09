# Releasing a new version (maintainers)

Families update with `python onboard.py update`, which follows **GitHub Releases** of this repo, not `main`.
So `main` can be work in progress; only a published release reaches families.

**Visibility:** families can only clone and update if the repo is public, or if you invite each family and they set a read-only token in `MITRAHOME_TOKEN`. Check anonymously with `curl -s -o /dev/null -w "%{http_code}" https://github.com/rNetGit/mitra-home-app` (200 = public, 404 = private).

## Rules that keep upgrades safe
1. **Additive migrations only.** Add `data/migrate_NNN_name.py` (idempotent, `CREATE TABLE IF NOT EXISTS`, `ALTER TABLE ... ADD COLUMN` guarded). Never rename or drop a table or column; add a new one and copy the data.
2. Anything a family may edit lives in `config/`, `CLAUDE.local.md`, `.claude/settings.local.json` or `.claude/agents/local-*.md`. Code, agents and `CLAUDE.md` are replaced on update.
3. Never commit family data. `.gitignore` covers it; `python scripts/verify_clean.py` must print `0 hit(s)`. Keep your private terms in `scripts/private_terms.txt` (git-ignored).
4. `requirements.txt` keeps upper bounds (audit A4). To take a newer fastapi, cryptography and so on, raise the bound, reinstall and run the whole suite before the release.
5. Python standard library only for `onboard.py`, `data/updater.py`, `data/migrate.py` and `data/llm.py` (they must run before `pip install`).
6. **Agent fence.** `.claude/settings.json` plus the `scripts/guard_tool.py` hook block writes to code, agents, `CLAUDE.md`, `tasks/`, `scripts/` and any `python -c`. They apply whenever Claude Code's working directory is this folder, so develop the template from the parent directory (or any other folder) with Claude Code, not from inside the template. Families extend permissions in `.claude/settings.local.json`; deny rules and the hook still win.

## Steps
1. Change code; add migrations; update `CHANGELOG.md` (new `## X.Y.Z` section at the top).
2. Bump `VERSION` (semver: patch = fixes, minor = features/migrations, major = breaking).
3. `python -m pytest` (or `python scripts/smoke_test.py`, the whole suite; `--quick` is only for work in progress) -> everything passes (`python scripts/smoke_test.py` runs the same suite in parallel when pytest-xdist is installed; it includes old-database upgrade, zip and git update keep family files). Also `python -m ruff check .`, `python scripts/verify_clean.py`, `python scripts/lint_agents.py`. CI (`.github/workflows/ci.yml`) runs the same on Ubuntu for every pull request and push to `main`; wait for it to be green on `main` before tagging (the tag itself runs no CI, see "Keeping CI cheap"). When
CI cannot run (for example GitHub Actions billing is off), the local `python scripts/smoke_test.py` run is the gate:
say so in the release notes.
4. Commit, then tag, sign and publish the release (the signature files go up WITH the release):
   ```bash
   git tag vX.Y.Z
   python scripts/sign_release.py sign vX.Y.Z      # -> dist/vX.Y.Z/SHA256SUMS + SHA256SUMS.sig (dist/ is git-ignored)
   git push origin main --tags
   # first copy just this version's CHANGELOG section into dist/vX.Y.Z/NOTES.md (the whole file is over GitHub's 125000-character limit)
   gh release create vX.Y.Z dist/vX.Y.Z/SHA256SUMS dist/vX.Y.Z/SHA256SUMS.sig --title "Mitra Home X.Y.Z" --notes-file dist/vX.Y.Z/NOTES.md
   ```
   Forgot the files? `gh release upload vX.Y.Z dist/vX.Y.Z/SHA256SUMS dist/vX.Y.Z/SHA256SUMS.sig`. Until they are
   there, families on 0.31.0 or later are told the release is not signed and their update stops.
5. Check: on another folder, `python onboard.py check` shows the new version; an update prints "Signature OK".

## Keeping CI cheap
While the repository is private, GitHub bills every Actions minute after the free 2,000 a month: Linux 1x, **Windows 2x,
macOS 10x** (on a public repository standard runners are free, but keep the rules below: the Mac runner is still the slow, scarce one). October 2026 cost about $51, mostly the full Windows + macOS test matrix on each of ~90 release tags and
a Mac installer build on every release. The workflows now follow these rules; keep them when you change them:
1. **Pull requests and pushes to `main`: Ubuntu + Python 3.13 only**, tests in 4 parallel workers. A newer push to the
   same pull request cancels the older run. Changes to Markdown, `docs/`, `LICENSE` or `NOTICE` alone run no CI.
2. **A release tag runs no CI.** It points at the merge commit that `main` already tested, and the full suite runs
   locally (`python scripts/smoke_test.py`) before every release.
3. **The full matrix (Windows, macOS, Linux x Python 3.12, 3.13) is a manual run**: Actions > CI > Run workflow. Run it
   before a release that changes the installers, `launch.py`, `onboard.py`, paths, file locking, or anything else that
   behaves differently on Windows or a Mac; not for every release.
4. **Installers:** the Windows setup is built for every release. The Mac app only for a minor release (`vX.Y.0`), or
   when the release notes contain `[mac]`; an installed Mac updates itself with `onboard.py update`, so a patch release
   needs no new dmg. Otherwise Actions > Installers > Run workflow with the tag (and only Mac ticked) attaches it later.
5. **Release in batches.** Several fixes in one patch release, not one release per fix: each release still builds the
   Windows installer and runs the update test. Aim for at most one release a day unless a fix cannot wait.
6. Workflow artifacts are kept 7 days (the release assets are the ones families download).
7. Once the repository is public, Actions minutes are free and rules 2-4 can relax.
8. **The maintainer's own Mac does the macOS jobs** (Mac installer, the macOS part of the manual full run) as a
   self-hosted runner, which GitHub does not bill. Set the repository variable `MAC_RUNNER` to `self` once it is set
   up; anything else (or no variable) falls back to GitHub's macOS runner. Setup on the Mac, once:
   - GitHub > the repository > Settings > Actions > Runners > New self-hosted runner > macOS, follow its commands in
     `~/actions-runner`, label `macOS` (added by default), then `./svc.sh install && ./svc.sh start` so it runs in the
     background after sign-in.
   - Notarization without a password in GitHub: `xcrun notarytool store-credentials mitra-notary --apple-id <id>
     --team-id <team>` (asks for the app-specific password once, keeps it in the login keychain), then set the
     repository variable `MAC_NOTARY_PROFILE` to `mitra-notary`. The Developer ID certificate already in the login
     keychain signs the app.
   - The Mac must be on and awake when a release is published (or the job waits in the queue until it is).
   - Self-hosted jobs run only on releases and manual runs. Before the repository goes public, keep it that way: no
     workflow with a `pull_request` trigger may run on `self-hosted`, or a stranger's pull request runs on this Mac.

## Signing key
- `python scripts/sign_release.py init` made it once (Ed25519). The private key is at `~/.mitrahome/release_signing_ed25519.pem` (or `~/.familyagent/`, where it was made before the rename)
  (or `MITRAHOME_SIGNING_KEY`); it is never committed or printed. **Back it up offline.** The public key is in
  `data/release_keys.json` (committed; every install checks against the copy it already has).
- Rotation: add the new public key to `data/release_keys.json`, ship that in a release signed with the OLD key, then
  sign later releases with the new one and drop the old key from the file.
- Lost key: families cannot verify new releases. Ship one release with the new key and tell families to run
  `python onboard.py update --allow-unsigned` once (git installs: check `git log` first).
- Offline zips: send `SHA256SUMS` and `SHA256SUMS.sig` next to the zip; `update --from FILE.zip` finds them.

## How families get it
- New family: `git clone https://github.com/rNetGit/mitra-home-app.git D:\MitraHome` (or download the zip from Releases), then `python onboard.py`.
- Existing family: `python onboard.py update` (git clones fast-forward to the release tag; zip installs overlay code files and keep a copy of every file replaced in `data/backups_pre_upgrade/`). The database is backed up and migrated automatically.
- Offline: send the release zip with `SHA256SUMS` and `SHA256SUMS.sig` in the same folder; they run `python onboard.py update --from MitraHome.zip`.
- Rollback: restore `data/backups_pre_upgrade/family_*.db` and either `git checkout <old tag>` or copy files back from `data/backups_pre_upgrade/code_*/`.

## Sharing with a family while the repository is private
Pick one per family. None needs the family to have a GitHub account except the first.
| Way | Family gets | Updates | Revoke |
|---|---|---|---|
| Release zip (simplest) | the zip + `SHA256SUMS` + `SHA256SUMS.sig` by private message or a shared drive link | you send each new zip; they run `python onboard.py update --from MitraHome.zip` (signature checked) | stop sending |
| Fine-grained token | the zip once, then a token you made: GitHub > Settings > Developer settings > Fine-grained tokens, only this repository, Contents: Read-only, with an expiry date | they set it as `MITRAHOME_TOKEN`; `python onboard.py check` / `update` work as usual | delete the token |
| Collaborator invite (Read) | a GitHub account invited to the repo; they can `git clone` and use their own token | same as the token row (a clone also needs the token to fast-forward) | remove the collaborator |

Notes:
- Send the token and the zip through a private channel, never a group chat or email thread others can read.
- Anonymous check that the repo is still private: `curl -s -o /dev/null -w "%{http_code}" https://github.com/rNetGit/mitra-home-app` (404 = private).
- Before the first family: run `python scripts/verify_clean.py` (must print `0 hit(s)`) and read `COMPLIANCE.md` with them; each family signs in to its own AI account.
- You never get their data. Ask for sanitized error text only; `python onboard.py doctor` output is safe to share (names of settings, never values).
