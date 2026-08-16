from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from option_platform.domain.models import Fill, OrderLegIntent, Side, TradeIntent
from option_platform.strategy_sdk.context import StrategyContext


@dataclass(slots=True)
class VerticalSignalStrategy:
    long_instrument_id: UUID
    short_instrument_id: UUID
    entry_threshold: Decimal = Decimal("-1")
    max_debit: Decimal = Decimal("2")
    stale_after_seconds: int = 30
    seen_snapshot_ids: set[UUID] = field(default_factory=set)

    def on_start(self, ctx: StrategyContext) -> None:
        del ctx

    def on_market(self, ctx: StrategyContext) -> list[TradeIntent]:
        snapshot = ctx.snapshot()
        if snapshot.snapshot_id in self.seen_snapshot_ids:
            return []
        self.seen_snapshot_ids.add(snapshot.snapshot_id)
        if any(
            q.is_stale(ctx.clock.now(), self.stale_after_seconds) for q in snapshot.quotes.values()
        ):
            return []
        if ctx.has_open_orders() or ctx.position(self.long_instrument_id) is not None:
            return []
        signal = ctx.indicator("zscore")
        if signal is None or signal > self.entry_threshold:
            return []
        return [
            TradeIntent(
                intent_id=ctx.ids.new(),
                strategy_instance_id=ctx.strategy_instance_id,
                legs=(
                    OrderLegIntent(self.long_instrument_id, Side.BUY, 1),
                    OrderLegIntent(self.short_instrument_id, Side.SELL, 1),
                ),
                max_debit=self.max_debit,
                created_at=ctx.clock.now(),
                metadata={"structure": "VERTICAL", "snapshot_id": str(snapshot.snapshot_id)},
            )
        ]

    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None:
        del ctx, fill

    def on_stop(self, ctx: StrategyContext) -> None:
        del ctx
