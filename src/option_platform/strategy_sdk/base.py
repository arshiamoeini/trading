from __future__ import annotations

from typing import Protocol

from option_platform.domain.models import Fill, TradeIntent

from .context import StrategyContext


class Strategy(Protocol):
    def on_start(self, ctx: StrategyContext) -> None: ...

    def on_market(self, ctx: StrategyContext) -> list[TradeIntent]: ...

    def on_fill(self, ctx: StrategyContext, fill: Fill) -> None: ...

    def on_stop(self, ctx: StrategyContext) -> None: ...
