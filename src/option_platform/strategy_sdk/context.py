from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from option_platform.domain.models import MarketSnapshot, Position, Quote
from option_platform.ports import Clock, IdGenerator


class StrategyContext(Protocol):
    strategy_instance_id: UUID
    clock: Clock
    ids: IdGenerator

    def snapshot(self) -> MarketSnapshot: ...

    def quote(self, instrument_id: UUID) -> Quote: ...

    def indicator(self, name: str) -> Decimal | None: ...

    def position(self, instrument_id: UUID) -> Position | None: ...

    def has_open_orders(self) -> bool: ...


@dataclass(slots=True)
class FakeStrategyContext:
    strategy_instance_id: UUID
    clock: Clock
    ids: IdGenerator
    current_snapshot: MarketSnapshot
    indicators: dict[str, Decimal] = field(default_factory=dict)
    positions: dict[UUID, Position] = field(default_factory=dict)
    open_orders: bool = False

    def snapshot(self) -> MarketSnapshot:
        return self.current_snapshot

    def quote(self, instrument_id: UUID) -> Quote:
        return self.current_snapshot.quotes[instrument_id]

    def indicator(self, name: str) -> Decimal | None:
        return self.indicators.get(name)

    def position(self, instrument_id: UUID) -> Position | None:
        return self.positions.get(instrument_id)

    def has_open_orders(self) -> bool:
        return self.open_orders

    def set_snapshot(self, snapshot: MarketSnapshot) -> None:
        self.current_snapshot = snapshot

    @property
    def now(self) -> datetime:
        return self.clock.now()
