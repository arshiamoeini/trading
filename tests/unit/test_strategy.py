from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.runtime.clock import FrozenClock, SequentialIdGenerator
from option_platform.strategies.example_vertical import VerticalSignalStrategy
from option_platform.strategy_sdk.context import FakeStrategyContext
from option_platform.testing.scenario import ScenarioBuilder

pytestmark = pytest.mark.unit


def test_vertical_strategy_signal_duplicate_and_position_guards(at) -> None:
    snapshot = (
        ScenarioBuilder(UUID(int=20))
        .snapshot(
            UUID(int=21),
            at,
            1,
            {
                UUID(int=2): (Decimal("1"), Decimal("1.1")),
                UUID(int=3): (Decimal(".4"), Decimal(".5")),
            },
        )
        .build()[0]
    )
    ctx = FakeStrategyContext(
        UUID(int=30), FrozenClock(at), SequentialIdGenerator(), snapshot, {"zscore": Decimal("-2")}
    )
    strategy = VerticalSignalStrategy(UUID(int=2), UUID(int=3))
    assert len(strategy.on_market(ctx)) == 1
    assert strategy.on_market(ctx) == []


def test_vertical_strategy_no_signal(at) -> None:
    snapshot = (
        ScenarioBuilder(UUID(int=20))
        .snapshot(
            UUID(int=21),
            at,
            1,
            {
                UUID(int=2): (Decimal("1"), Decimal("1.1")),
                UUID(int=3): (Decimal(".4"), Decimal(".5")),
            },
        )
        .build()[0]
    )
    ctx = FakeStrategyContext(
        UUID(int=30), FrozenClock(at), SequentialIdGenerator(), snapshot, {"zscore": Decimal("0")}
    )
    assert VerticalSignalStrategy(UUID(int=2), UUID(int=3)).on_market(ctx) == []
