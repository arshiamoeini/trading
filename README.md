# Option Platform

A provider-neutral Python platform for deterministic option-strategy research and paper
execution. The v1 reference path is:

`Recorded data -> Vertical strategy -> Risk -> OMS -> Paper broker -> Portfolio -> Metrics`

## Safety boundary

The project does **not** contain a real broker adapter and cannot submit live orders.
`LIVE_TRADING_ENABLED` is rejected if set. The HTTP/WebSocket adapter is market-data-only.
Authentication and authorization are not implemented; expose the API only on a trusted internal
network. A future live broker requires a named provider, sandbox credentials, authentication,
authorization, audit controls, reconciliation, and separate approval.

## Development

```bash
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
pytest -m "unit or contract"
pytest -m replay
pytest -m failure
pytest -m e2e
pytest -m integration
ruff check .
ruff format --check .
mypy src
docker compose up --build
```

On Windows use `.venv\Scripts\python` and `.venv\Scripts\pip`. The dashboard is served at
`http://localhost:8000/`.

## Managed PostgreSQL

Docker Compose is development-only. In production, provide a managed PostgreSQL async DSN in
`OPTION_PLATFORM_DATABASE_URL`, configure TLS with `OPTION_PLATFORM_DATABASE_SSL=true`, run
`alembic upgrade head` as a separate deployment step, and start API and runtime independently.

## Market provider profiles

The generic adapter needs a provider profile and mapper. Tests use sanitized JSON/JSONL fixtures
and fake transports; they never call a live API. Vendor compatibility is only claimed after that
vendor's payloads pass the shared adapter contract suite.

## Tehran options market data

The TSETMC collector reads TSE and IFB option chains and top-of-book quotes every five seconds.
It records only valid two-sided quotes, while retaining every discovered contract in its option
chain. Five-level order books are collected only for comma-separated `insCode` values configured
in `OPTION_PLATFORM_TSETMC_DEPTH_WATCHLIST`.

```bash
alembic upgrade head
option-platform-tsetmc --once
option-platform-tsetmc
option-platform-tsetmc --history-code 10417081465897562 --start 2026-01-01
```

On Windows the equivalent module command is
`.venv\Scripts\python -m option_platform.runtime.market_collector`. Daily history is stored as
OHLC bars and is never converted into synthetic bid/ask quotes. Full bid/ask replay starts with
snapshots captured by the running collector.

The initial migration installs a disabled recorded-data VerticalSpread example. Starting its
instance through the API makes the separate runtime execute Risk -> OMS -> PaperBroker, atomically
persist fills/positions/events, and store portfolio metrics. It never submits a live order.

## Statistical validity

Every run records dataset hash/version, strategy version/configuration, engine version and seed.
The default protocol is chronological 60/20/20 train/validation/OOS. Final OOS is evaluated once.
Datasets without point-in-time chains including expired/delisted contracts are marked
`survivorship_bias_risk` and cannot be labelled validated.
