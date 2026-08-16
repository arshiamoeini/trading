from __future__ import annotations

from dataclasses import dataclass

from option_platform.analytics.portfolio import PortfolioMetrics, SimulatedPortfolio
from option_platform.domain.models import Fill, MarketSnapshot, OrderGroup, TradeIntent
from option_platform.execution.oms import OrderManagementSystem
from option_platform.strategy_sdk.base import Strategy
from option_platform.strategy_sdk.context import FakeStrategyContext


@dataclass(frozen=True, slots=True)
class VerticalSliceResult:
    intents: tuple[TradeIntent, ...]
    orders: tuple[OrderGroup, ...]
    fills: tuple[Fill, ...]
    metrics: PortfolioMetrics


async def execute_vertical_slice(
    strategy: Strategy,
    context: FakeStrategyContext,
    snapshots: tuple[MarketSnapshot, ...],
    oms: OrderManagementSystem,
    portfolio: SimulatedPortfolio,
) -> VerticalSliceResult:
    intents: list[TradeIntent] = []
    orders: list[OrderGroup] = []
    fill_offset = len(oms.applied_fills)
    strategy.on_start(context)
    for snapshot in snapshots:
        advance_to = getattr(context.clock, "advance_to", None)
        if callable(advance_to):
            advance_to(snapshot.provider_timestamp)
        context.set_snapshot(snapshot)
        for intent in strategy.on_market(context):
            intents.append(intent)
            order = await oms.submit(intent, dict(snapshot.quotes))
            orders.append(order)
            await oms.consume_broker_events(order)
        portfolio.mark(snapshot.provider_timestamp, dict(snapshot.quotes))
    strategy.on_stop(context)
    return VerticalSliceResult(
        tuple(intents),
        tuple(orders),
        tuple(oms.applied_fills[fill_offset:]),
        portfolio.metrics(dict(snapshots[-1].quotes)),
    )
