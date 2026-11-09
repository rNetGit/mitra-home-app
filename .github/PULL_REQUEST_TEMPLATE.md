## What this changes

## Checklist
- [ ] `python -m pytest` passes locally (or I explain which tests I could not run)
- [ ] `python -m ruff check .` and `python scripts/verify_clean.py` and `python scripts/lint_agents.py` pass
- [ ] Database changes are a new additive `data/migrate_NNN_*.py` (never rename or drop)
- [ ] `onboard.py`, `data/updater.py`, `data/migrate.py`, `data/llm.py` stay standard library only
- [ ] Agents and the guard hook (`scripts/guard_tool.py`) still confine agents to `archive/`, `reports/`, `brief/`, `inbox/`
- [ ] `CHANGELOG.md` has a line for families (what changed, what they must do)
- [ ] No family data, names, account digits or personal paths in the diff
