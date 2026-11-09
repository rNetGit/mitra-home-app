# Contributing

Thanks for helping. Mitra Home is a local-first tool families run on their own PC, so the bar is: nothing you
add may leak, delete or quietly change their data, and a family must still be able to install and update with
`python onboard.py` alone.

## Set up a development copy
```bash
git clone https://github.com/rNetGit/mitra-home-app.git
cd mitra-home-app
python -m pip install -r requirements.txt -r requirements-dev.txt
pre-commit install            # optional: ruff, verify_clean and the agent lint on every commit
```
Python 3.12 or newer. Nothing needs to be installed as a package; scripts run from the checkout.

**Work from the parent directory when you use Claude Code.** The template ships an agent fence
(`.claude/settings.json` plus the `scripts/guard_tool.py` hook) that blocks edits to `data/`, `tasks/`, `scripts/`,
agents and `CLAUDE.md`. It applies whenever Claude Code's working directory is this folder. Open Claude Code one
level up (or in any other folder) and point it at the files, or edit with your own editor.

## Run the checks
```bash
python -m pytest                      # everything (a few minutes; builds throwaway families in a temp folder)
python scripts/smoke_test.py         # the release gate: the whole suite, in parallel with pytest-xdist
python -m pytest -k llm               # one area
python -m ruff check .
python scripts/verify_clean.py        # no leftover personal strings
python scripts/lint_agents.py         # agent definitions are well formed
```
Tests never touch your own `config/`, database or documents: every module gets its own copy of the template under
pytest's temp directory (`--basetemp DIR` keeps it somewhere you choose). CI runs all of this on Ubuntu with Python
3.13 for every pull request; maintainers run the Windows / macOS / Python 3.12 matrix by hand when a change needs it
(RELEASING.md, "Keeping CI cheap").

## Rules that keep families safe
1. **Additive migrations only.** New tables and columns go in a new `data/migrate_NNN_name.py` that is idempotent
   (`CREATE TABLE IF NOT EXISTS`, guarded `ALTER TABLE ... ADD COLUMN`). Never rename or drop. Databases from older
   releases must upgrade in one step (`tests/test_migrations.py` checks this).
2. **Standard library only** in `onboard.py`, `data/updater.py`, `data/migrate.py` and `data/llm.py`: they run
   before `pip install`. Optional packages are imported lazily with a clear message when missing.
3. **Documents are data.** Anything that reads a file, email or model output validates it before writing. New
   agent prompts say so (the lint checks) and must stay inside the fence: writes only under `archive/`, `reports/`,
   `brief/`, `inbox/` and `config/category_rules.json`; commands only `python data/<script>.py` and moves from
   `inbox/`. If you need a new capability, extend `scripts/guard_tool.py` and its tests, not the prose.
4. **Never read or forward credentials.** Check environment variables and settings by name only. Keys live in
   `config/secrets.env`; the code never prints them. No provider subscription tokens, ever (see `COMPLIANCE.md`).
5. **Never delete originals.** Files move from `inbox/` to `archive/`; rows change status instead of being deleted.
6. **Last4 only.** Account, policy, VIN, plate and ID numbers are stored and printed as the last four digits.
7. **Anything a family may edit lives outside the code:** `config/`, `CLAUDE.local.md`,
   `.claude/settings.local.json`, `.claude/agents/local-*.md`. Code, agents and `CLAUDE.md` are replaced on update.
8. **No personal data in the repository.** Use the test family (Alex, Sam, Biscuit, Acme Power). Run
   `python scripts/verify_clean.py` before you push; it also flags the shape of leaks (dated anecdotes, "the user
   asked", last4 maps). Keep your own private terms in `scripts/private_terms.txt` (git-ignored).
9. **One way in to the database.** `import db` and `db.connect()` / `db.connect(readonly=True)` / `with db.open()`,
   never a bare `sqlite3.connect` (foreign keys must be on). Dates through `dates.parse` / `dates.add_months`,
   amounts through `money.fmt`. Catch `sqlite3.OperationalError` only as `if not db.missing(e): raise`: an old
   database is fine to skip, a locked or broken one is not. Log with `log.get("<area>")`, never document text,
   prompts, keys or full numbers.
10. **Forward slashes in paths** inside agents and docs; the tool runs on Mac and Linux too.

## Pull requests
- One topic per PR. Add or extend a test in `tests/` for behaviour you change; every test is part of the release gate.
  Tests in one module share one copy of the template (`root`), so keep them independent of other modules.
- Add a line to the top `CHANGELOG.md` section written for families: what changed and what they must do.
- Bump `VERSION` only in a release PR (maintainers; see `RELEASING.md`).
- Do not add telemetry, network calls or new third-party dependencies without discussing it in an issue first.

## Style
`ruff` with the rules in `pyproject.toml` (long lines and one-liners are tolerated in the `data/` scripts; new
code should still be readable without them). Plain functions, `argparse` or a tiny hand-rolled argv, parameterised
SQL only. Docstrings at the top of each script say how to run it.

## Testing gotchas
- A fixture named `app` is hijacked by the `pytest-flask` plugin if it is installed; the web tests call theirs `web`.
- A form field named like a test helper's argument (`token`, `c`) collides with it: helpers name theirs `csrf_`, `client_`.
- `AIFA_DRY_RUN=1` makes `onboard.py` skip Task Scheduler / cron and the Claude ping. The tests set it.
- The update tests use a fake release `99.0.0` so they never collide with a real one.
- `onboard.py doctor` shows one `[!]` for `ANTHROPIC_BASE_URL` or `ANTHROPIC_API_KEY` if your own shell has them;
  that is the check working, not a failure.

## Releases
Maintainers: `RELEASING.md`. Families get code only from GitHub Releases, never from `main`.

## Licence and sign-off
Mitra Home is released under the **AGPL-3.0-or-later**. By contributing you agree that your contribution is licensed
under the same terms and that you wrote it or have the right to submit it (the
[Developer Certificate of Origin](https://developercertificate.org/)). Sign off each commit:

```bash
git commit -s -m "Fix the bills due date rollover"    # adds: Signed-off-by: Your Name <you@example.com>
```

You keep the copyright in your own contribution. The name "Mitra Home" and its logo are covered by `TRADEMARK.md`.
