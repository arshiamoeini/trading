from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from option_platform.domain.models import (
    Instrument,
    MarketSnapshot,
    OptionContract,
    OptionRight,
    Quote,
)


@dataclass(frozen=True, slots=True)
class OptionChain:
    underlying_id: UUID
    as_of: datetime
    contracts: tuple[OptionContract, ...]

    def filter(
        self,
        *,
        expiry: date | None = None,
        right: OptionRight | None = None,
    ) -> tuple[OptionContract, ...]:
        return tuple(
            contract
            for contract in self.contracts
            if (expiry is None or contract.expiry == expiry)
            and (right is None or contract.right is right)
        )


@dataclass(frozen=True, slots=True)
class MarketBar:
    instrument_id: UUID
    trading_date: date
    event_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    last: Decimal
    previous_close: Decimal
    trades: Decimal
    volume: Decimal
    value: Decimal
    source: str
    timeframe: str = "1d"


@dataclass(frozen=True, slots=True)
class InstrumentIdentifier:
    provider: str
    provider_instrument_id: str
    venue: str | None = None
    raw_symbol: str | None = None
    isin: str | None = None


@dataclass(frozen=True, slots=True)
class OrderBookLevel:
    level: int
    bid: Decimal
    bid_size: Decimal
    bid_orders: int
    ask: Decimal
    ask_size: Decimal
    ask_orders: int


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    instrument_id: UUID
    observed_at: datetime
    source: str
    levels: tuple[OrderBookLevel, ...]


class MarketDataProvider(Protocol):
    async def get_instrument(self, instrument_id: UUID) -> Instrument: ...

    async def get_option_chain(self, underlying_id: UUID) -> OptionChain: ...

    async def get_quote(self, instrument_id: UUID) -> Quote: ...

    async def snapshot(self) -> MarketSnapshot: ...

    def stream(self) -> AsyncIterator[MarketSnapshot]: ...

    async def health(self) -> dict[str, object]: ...


class HistoricalMarketDataReader(Protocol):
    async def get_daily_bars(
        self,
        instrument_id: UUID,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[MarketBar, ...]: ...


class OrderBookReader(Protocol):
    async def get_order_book(self, instrument_id: UUID, depth: int = 5) -> OrderBookSnapshot: ...
