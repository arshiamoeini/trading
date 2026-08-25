# Agent instructions

## Project

This repository contains a Python 3.12 platform for deterministic option-strategy
research and paper trading.

Read `README.md`, `STRATEGY_GUIDE.md`, and `TESTING_MODULES.md` before making
architectural changes.

## Safety boundary

- Never enable live trading.
- Never add or connect a real broker unless explicitly requested.
- Keep `OPTION_PLATFORM_LIVE_TRADING_ENABLED=false`.
- Never use real trading, market-provider, or database credentials.
- Tests must not call live broker APIs.
- Do not perform destructive database operations.
- Do not modify an existing migration that may have been deployed. Create a new
  Alembic migration instead.

## Development rules

- Use Python 3.12.
- Preserve strict mypy compatibility.
- Keep lines within Ruff's 100-character limit.
- Keep provider-specific behavior behind adapters.
- Preserve deterministic replay behavior.
- Add or update tests for every behavioral change.
- Avoid unrelated refactoring.
- Never overwrite unrelated existing changes.

## Validation

Run the most relevant tests first.

For normal changes:

```bash
python -m pytest -m "unit or contract"
python -m ruff check .
python -m ruff format --check .
python -m mypy src
```

When relevant:

```bash
python -m pytest -m replay
python -m pytest -m failure
```

Integration and end-to-end tests require PostgreSQL. If PostgreSQL is unavailable,
report that clearly instead of claiming those tests passed.

## Git

- Work on a new branch.
- Never force-push.
- Do not commit secrets, `.env` files, caches, or generated files.
- Review `git diff` before committing.
- Keep commits and pull requests focused on the requested change.
