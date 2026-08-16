from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.analytics.portfolio import SimulatedPortfolio
from option_platform.application.vertical_slice import execute_vertical_slice
from option_platform.domain.models import Instrument, OrderState
from option_platform.execution.broker import PaperBroker
from option_platform.execution.oms import InMemoryOrderStore, OrderManagementSystem
from option_platform.risk.engine import RiskEngine
from option_platform.runtime.clock import FrozenClock, SequentialIdGenerator
from option_platform.strategies.example_vertical import VerticalSignalStrategy
from option_platform.strategy_sdk.context import FakeStrategyContext
from option_platform.testing.scenario import ScenarioBuilder

pytestmark = pytest.mark.e2e


async def run_once(at):
    long_option = Instrument(UUID(int=2), "LONG", multiplier=Decimal("100"))
    short_option = Instrument(UUID(int=3), "SHORT", multiplier=Decimal("100"))
    snapshot = (
        ScenarioBuilder(UUID(int=20))
        .snapshot(
            UUID(int=21),
            at,
            1,
            {
                UUID(int=2): (Decimal("1.0"), Decimal("1.1")),
                UUID(int=3): (Decimal("0.4"), Decimal("0.5")),
            },
        )
        .build()[0]
    )
    clock = FrozenClock(at)
    ids = SequentialIdGenerator(100)
    context = FakeStrategyContext(UUID(int=30), clock, ids, snapshot, {"zscore": Decimal("-2")})
    portfolio = SimulatedPortfolio(
        Decimal("10000"), {UUID(int=2): long_option, UUID(int=3): short_option}
    )
    broker = PaperBroker(clock, ids)
    oms = OrderManagementSystem(RiskEngine(), broker, InMemoryOrderStore(), clock, ids, portfolio)
    strategy = VerticalSignalStrategy(UUID(int=2), UUID(int=3), max_debit=Decimal("2"))
    return await execute_vertical_slice(strategy, context, (snapshot,), oms, portfolio)


async def test_complete_vertical_slice_is_deterministic(at) -> None:
    first = await run_once(at)
    second = await run_once(at)
    assert len(first.intents) == 1
    assert len(first.orders) == 1
    assert len(first.orders[0].legs) == 2
    assert first.orders[0].state is OrderState.FILLED
    assert len(first.fills) == 2
    assert first == second
    assert first.metrics.spread_attribution == Decimal("10.0")
