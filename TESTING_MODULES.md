## Module Testing Guide

This project keeps production code and tests separate:

- Production code lives under `src/option_platform/...`
- Tests live under `tests/...`

That means module tests should not be written inside the production module itself. For example:

- Module: `src/option_platform/market_data/tsetmc.py`
- Unit tests: `tests/unit/test_tsetmc.py`
- Contract tests: `tests/contract/test_tsetmc_adapter.py`

## Why Tests Stay Outside The Module

Keeping tests outside the module helps us:

- keep runtime code clean and focused on production behavior
- group tests by test type such as `unit`, `contract`, `integration`, and `e2e`
- avoid mixing test-only dependencies with application code
- make `pytest` collection and CI behavior more predictable

## Test Types In This Repository

Use the following rule of thumb when adding tests.

### Unit tests

Place fast, isolated tests in `tests/unit`.

Use unit tests for:

- pure helper functions
- validation logic
- mapping and parsing logic
- small methods whose behavior can be checked without real I/O

Examples for `tsetmc.py`:

- `normalize_symbol`
- `instrument_uuid`
- `_decimal`
- `_date`
- `_map_quote`
- `_map_market`
- `TsetmcConfig` validation

Unit tests should usually:

- avoid network calls
- avoid real databases
- use deterministic input fixtures
- assert exact outputs and raised errors

### Contract tests

Place provider-facing behavior tests in `tests/contract`.

Use contract tests for:

- checking that a provider implements the expected application-facing interface
- verifying behavior through public methods such as `snapshot`, `get_quote`, or `get_option_chain`
- testing with fake responses that represent provider payloads

Examples for `tsetmc.py`:

- `refresh()` loads option market data correctly
- `get_quote()` rejects invalid two-sided quotes
- `get_order_book()` maps best-limit payloads
- `get_daily_bars()` maps historical rows into domain bars

These tests still avoid real external calls, but they exercise the module through its public API rather than its small internal helpers.

### Integration and E2E tests

Use `tests/integration` and `tests/e2e` only when the behavior depends on real infrastructure or larger workflow composition.

## Recommended Implementation Pattern

When writing tests for a module, work from small to large:

1. Test pure functions first.
2. Test validation and error paths.
3. Test internal mapping logic with fixed payloads.
4. Test the public adapter behavior with fake request functions.
5. Move to integration tests only if real infrastructure matters.

For a provider module like `tsetmc.py`, the most useful split is:

- `tests/unit/test_tsetmc.py` for internal logic
- `tests/contract/test_tsetmc_adapter.py` for provider behavior

## Example Layout For `tsetmc.py`

Suggested coverage split:

- `tests/unit/test_tsetmc.py`
  - symbol normalization
  - UUID generation stability
  - decimal/date parsing errors
  - config validation
  - quote mapping edge cases
  - market mapping and sorting
- `tests/contract/test_tsetmc_adapter.py`
  - snapshot loading through the provider API
  - valid vs invalid quotes
  - order book mapping
  - historical bar mapping
  - retry behavior

## Practical Rules For Writing Module Tests

- Prefer deterministic fixtures over broad mocking.
- Mock only at the module boundary, such as `request_json`.
- Test one behavior per test when possible.
- Name tests by behavior, not implementation detail.
- Keep unit tests fast enough to run frequently.
- Assert domain-level behavior, not just incidental fields.

## Running Tests

Typical commands:

```bash
pytest tests/unit/test_tsetmc.py
pytest tests/contract/test_tsetmc_adapter.py
pytest -m unit
pytest -m contract
```

## Python Version Note

This repository declares `requires-python = ">=3.12"` in `pyproject.toml`.
Run tests with Python 3.12 or newer so the test environment matches the project configuration.
