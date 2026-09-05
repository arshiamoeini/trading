from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from option_platform.backtest.engine import BacktestEngine, RunManifest
from option_platform.domain.models import (
    Fill,
    Instrument,
    MarketSnapshot,
    OrderLegIntent,
    Quote,
    Side,
    TradeIntent,
)
from option_platform.market_data.base import OrderBookLevel, OrderBookSnapshot
from option_platform.market_data.recording import FileSnapshotStore
from option_platform.strategies.example_vertical import VerticalSignalStrategy

pytestmark = pytest.mark.replay


def write_recorded_market_data(path: Path, at) -> None:
    dataset_id = UUID(int=20)
    rows = [
        {
            "snapshot_id": str(UUID(int=21)),
            "dataset_id": str(dataset_id),
            "provider_timestamp": at.isoformat(),
            "received_at": (at + timedelta(seconds=1)).isoformat(),
            "sequence": 1,
            "source": "tsetmc:recorded",
            "content_hash": "recorded-market-snapshot-1",
            "chain_instrument_ids": [str(UUID(int=2)), str(UUID(int=3))],
            "quotes": [
                {
                    "instrument_id": str(UUID(int=2)),
                    "bid": "1.00",
                    "ask": "1.10",
                    "provider_timestamp": at.isoformat(),
                    "received_at": (at + timedelta(seconds=1)).isoformat(),
                    "sequence": 1,
                    "bid_size": "120",
                    "ask_size": "90",
                    "source": "tsetmc:recorded",
                },
                {
                    "instrument_id": str(UUID(int=3)),
                    "bid": "0.40",
                    "ask": "0.50",
                    "provider_timestamp": at.isoformat(),
                    "received_at": (at + timedelta(seconds=1)).isoformat(),
                    "sequence": 1,
                    "bid_size": "80",
                    "ask_size": "110",
                    "source": "tsetmc:recorded",
                },
            ],
        },
        {
            "snapshot_id": str(UUID(int=22)),
            "dataset_id": str(dataset_id),
            "provider_timestamp": (at + timedelta(minutes=1)).isoformat(),
            "received_at": (at + timedelta(minutes=1, seconds=1)).isoformat(),
            "sequence": 2,
            "source": "tsetmc:recorded",
            "content_hash": "recorded-market-snapshot-2",
            "chain_instrument_ids": [str(UUID(int=2)), str(UUID(int=3))],
            "quotes": [
                {
                    "instrument_id": str(UUID(int=2)),
                    "bid": "1.20",
                    "ask": "1.30",
                    "provider_timestamp": (at + timedelta(minutes=1)).isoformat(),
                    "received_at": (at + timedelta(minutes=1, seconds=1)).isoformat(),
                    "sequence": 2,
                    "bid_size": "140",
                    "ask_size": "70",
                    "source": "tsetmc:recorded",
                },
                {
                    "instrument_id": str(UUID(int=3)),
                    "bid": "0.50",
                    "ask": "0.60",
                    "provider_timestamp": (at + timedelta(minutes=1)).isoformat(),
                    "received_at": (at + timedelta(minutes=1, seconds=1)).isoformat(),
                    "sequence": 2,
                    "bid_size": "75",
                    "ask_size": "95",
                    "source": "tsetmc:recorded",
                },
            ],
        },
    ]
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows), encoding="utf-8")


async def test_backtest_uses_recorded_market_data_and_is_reproducible(at, tmp_path) -> None:
    instruments = {
        UUID(int=2): Instrument(UUID(int=2), "LONG", multiplier=Decimal("100")),
        UUID(int=3): Instrument(UUID(int=3), "SHORT", multiplier=Decimal("100")),
    }
    market_data_path = tmp_path / "recorded-market.jsonl"
    write_recorded_market_data(market_data_path, at)
    snapshots = await FileSnapshotStore(market_data_path).load(UUID(int=20))
    manifest = RunManifest(
        UUID(int=30),
        UUID(int=20),
        "v1",
        "abc",
        "VerticalSignalStrategy",
        "1",
        {"threshold": "-1"},
        100,
        at,
        at + timedelta(minutes=1),
        point_in_time_complete=True,
    )

    def run():
        return BacktestEngine(instruments).run(
            VerticalSignalStrategy(UUID(int=2), UUID(int=3)),
            UUID(int=40),
            snapshots,
            manifest,
            indicator=lambda _: Decimal("-2"),
        )

    assert run() == run()
    result = run()
    assert result.validated
    assert len(result.intents) == 1
    assert len(result.fills) == 2
    assert [fill.price for fill in result.fills] == [Decimal("1.10"), Decimal("0.40")]
    assert result.equity_curve[-1].equity == Decimal("99990.00")
    assert result.metrics.total_return == Decimal("-0.0001")
    assert result.metrics.unrealized_pnl == Decimal("-10.00")
    assert result.metrics.spread_attribution == Decimal("10.00")
    assert result.metrics.slippage_attribution == Decimal("0.00")


def test_incomplete_point_in_time_dataset_is_not_validated(at) -> None:
    manifest = RunManifest(UUID(int=30), UUID(int=20), "v1", "abc", "S", "1", {}, 1, at, at)
    assert manifest.survivorship_bias_risk


class SingleOrderStrategy:
    def __init__(self, instrument_id: UUID, side: Side, quantity: int) -> None:
        self.instrument_id = instrument_id
        self.side = side
        self.quantity = quantity
        self.sent = False

    def on_start(self, ctx) -> None:
        del ctx

    def on_market(self, ctx) -> list[TradeIntent]:
        if self.sent:
            return []
        self.sent = True
        return [
            TradeIntent(
                intent_id=ctx.ids.new(),
                strategy_instance_id=ctx.strategy_instance_id,
                legs=(OrderLegIntent(self.instrument_id, self.side, self.quantity),),
                created_at=ctx.clock.now(),
                max_debit=Decimal("100"),
            )
        ]

    def on_fill(self, ctx, fill: Fill) -> None:
        del ctx, fill

    def on_stop(self, ctx) -> None:
        del ctx


def manifest(at) -> RunManifest:
    return RunManifest(
        UUID(int=30),
        UUID(int=20),
        "v1",
        "abc",
        "SingleOrderStrategy",
        "1",
        {},
        100,
        at,
        at,
        point_in_time_complete=True,
    )


def snapshot(at, quote: Quote) -> tuple[MarketSnapshot, ...]:
    return (
        MarketSnapshot(
            UUID(int=21),
            UUID(int=20),
            at,
            at,
            1,
            "test",
            {quote.instrument_id: quote},
        ),
    )


def order_books(at, book: OrderBookSnapshot) -> dict[tuple[object, UUID], OrderBookSnapshot]:
    return {(at, book.instrument_id): book}


def test_backtest_walks_multiple_ask_levels_for_complete_buy(at) -> None:
    instrument_id = UUID(int=2)
    result = BacktestEngine(
        {instrument_id: Instrument(instrument_id, "DEPTH", multiplier=Decimal("1"))}
    ).run(
        SingleOrderStrategy(instrument_id, Side.BUY, 10),
        UUID(int=40),
        snapshot(
            at,
            Quote(
                instrument_id,
                Decimal("99"),
                Decimal("100"),
                at,
                at,
                1,
                bid_size=Decimal("5"),
                ask_size=Decimal("4"),
            ),
        ),
        manifest(at),
        order_books=order_books(
            at,
            OrderBookSnapshot(
                instrument_id,
                at,
                "test",
                (
                    OrderBookLevel(
                        1, Decimal("99"), Decimal("5"), 1, Decimal("100"), Decimal("4"), 1
                    ),
                    OrderBookLevel(
                        2, Decimal("98"), Decimal("5"), 1, Decimal("101"), Decimal("6"), 1
                    ),
                    OrderBookLevel(
                        3, Decimal("97"), Decimal("5"), 1, Decimal("102"), Decimal("10"), 1
                    ),
                ),
            ),
        ),
    )

    assert len(result.fills) == 1
    assert result.fills[0].quantity == 10
    assert result.fills[0].price == Decimal("100.6")
    assert result.metrics.slippage_attribution == Decimal("6.0")


def test_backtest_partially_fills_when_bid_depth_is_exhausted(at) -> None:
    instrument_id = UUID(int=2)
    result = BacktestEngine(
        {instrument_id: Instrument(instrument_id, "DEPTH", multiplier=Decimal("1"))}
    ).run(
        SingleOrderStrategy(instrument_id, Side.SELL, 10),
        UUID(int=40),
        snapshot(
            at,
            Quote(
                instrument_id,
                Decimal("99"),
                Decimal("100"),
                at,
                at,
                1,
                bid_size=Decimal("3"),
                ask_size=Decimal("4"),
            ),
        ),
        manifest(at),
        order_books=order_books(
            at,
            OrderBookSnapshot(
                instrument_id,
                at,
                "test",
                (
                    OrderBookLevel(
                        1, Decimal("99"), Decimal("3"), 1, Decimal("100"), Decimal("4"), 1
                    ),
                    OrderBookLevel(
                        2, Decimal("98"), Decimal("2"), 1, Decimal("101"), Decimal("4"), 1
                    ),
                ),
            ),
        ),
    )

    assert len(result.fills) == 1
    assert result.fills[0].quantity == 5
    assert result.fills[0].price == Decimal("98.6")
    assert result.metrics.slippage_attribution == Decimal("2.0")
