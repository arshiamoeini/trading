# Simple Guide: Add And Test A Strategy

In this project, `strategy_sdk` is the rulebook and `strategies` contains real strategies.
A strategy reads market/context data and returns `TradeIntent`s. It does not talk to broker,
database, FastAPI, or Docker directly.

## 1. Add Strategy File

Create a file in:

```text
src/option_platform/strategies/my_strategy.py
```

Your class should have these four methods:

```python
def on_start(self, ctx): ...
def on_market(self, ctx) -> list[TradeIntent]: ...
def on_fill(self, ctx, fill): ...
def on_stop(self, ctx): ...
```

The main method is `on_market`. It gets current data from `ctx`:

```python
snapshot = ctx.snapshot()
quote = ctx.quote(instrument_id)
signal = ctx.indicator("zscore")
position = ctx.position(instrument_id)
```

If no trade is needed, return:

```python
return []
```

If trade is needed, return a `TradeIntent`:

```python
TradeIntent(
    intent_id=ctx.ids.new(),
    strategy_instance_id=ctx.strategy_instance_id,
    legs=(OrderLegIntent(long_id, Side.BUY, 1),),
    max_debit=Decimal("2"),
    created_at=ctx.clock.now(),
)
```

## 2. Test Strategy Logic

Use `FakeStrategyContext` and `ScenarioBuilder` to create fake market data. Then call:

```python
intents = strategy.on_market(ctx)
```

Check if it returns one intent when signal is valid, and `[]` when signal is invalid/stale/duplicate.

## 3. Test Full Simulation

Use `execute_vertical_slice(...)` to test the full path:

```text
Strategy -> RiskEngine -> OMS -> PaperBroker -> Portfolio -> Metrics
```

This proves your strategy works with the platform, not only by itself.

## 4. Backtest

Use `BacktestEngine.run(...)` with old `MarketSnapshot`s. It replays snapshots one by one,
calls `on_market`, simulates fills, and calculates metrics such as return, drawdown, Sharpe,
and win rate.

Important: `win_rate` only counts closed trades, so add exit logic if you want useful win-rate
results.
