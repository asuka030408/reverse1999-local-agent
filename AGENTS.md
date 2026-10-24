# Project notes for coding agents

- Read `README.md` and `docs/architecture.md` before changing workflows or documented behavior.
- Keep `.env`, screenshots, logs, and `work/agent_state.json` out of version control; never print API keys.
- Preserve dry-run defaults and the action, purchase, and stamina checks in `agent.py` and `policy.py`.
- Run `python -m pytest -q` from the project environment for logic changes. Device interaction needs separate verification with MuMu.
- Update README when CLI commands, settings, supported workflows, or safety behavior changes.
