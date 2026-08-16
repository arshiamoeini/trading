from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import datetime
from uuid import UUID

from option_platform.domain.errors import DomainError
from option_platform.domain.models import Instrument, MarketSnapshot, Quote
from option_platform.ports import Clock

from .base import OptionChain


class FakeMarketDataProvider:
    def __init__(
        self,
        instruments: Iterable[Instrument] = (),
        chains: Iterable[OptionChain] = (),
        snapshots: Iterable[MarketSnapshot] = (),
    ) -> None:
        self.instruments = {item.instrument_id: item for item in instruments}
        self.chains = {item.underlying_id: item for item in chains}
        self.snapshots = list(snapshots)
        self.index = 0

    async def get_instrument(self, instrument_id: UUID) -> Instrument:
        return self.instruments[instrument_id]

    async def get_option_chain(self, underlying_id: UUID) -> OptionChain:
        return self.chains[underlying_id]

    async def get_quote(self, instrument_id: UUID) -> Quote:
        return (await self.snapshot()).quotes[instrument_id]

    async def snapshot(self) -> MarketSnapshot:
        if not self.snapshots:
            raise DomainError("no market snapshot available")
        idx = min(self.index, len(self.snapshots) - 1)
        return self.snapshots[idx]

    def stream(self) -> AsyncIterator[MarketSnapshot]:
        async def iterate() -> AsyncIterator[MarketSnapshot]:
            for index, snapshot in enumerate(self.snapshots):
                self.index = index
                yield snapshot
                await asyncio.sleep(0)

        return iterate()

    async def health(self) -> dict[str, object]:
        return {"connected": True, "source": "fake", "snapshots": len(self.snapshots)}


class RecordedMarketDataProvider(FakeMarketDataProvider):
    """Publishes immutable snapshots only when the injected clock reaches them."""

    def __init__(
        self,
        clock: Clock,
        snapshots: Sequence[MarketSnapshot],
        instruments: Iterable[Instrument] = (),
        chains: Iterable[OptionChain] = (),
    ) -> None:
        ordered = sorted(snapshots, key=lambda item: (item.provider_timestamp, item.sequence))
        if len({(s.provider_timestamp, s.sequence) for s in ordered}) != len(ordered):
            raise DomainError("recorded snapshots need unique timestamp/sequence pairs")
        super().__init__(instruments, chains, ordered)
        self.clock = clock

    async def snapshot(self) -> MarketSnapshot:
        visible = [s for s in self.snapshots if s.provider_timestamp <= self.clock.now()]
        if not visible:
            raise DomainError("no snapshot is visible at the current replay time")
        return visible[-1]

    def stream(self) -> AsyncIterator[MarketSnapshot]:
        async def iterate() -> AsyncIterator[MarketSnapshot]:
            for index, snapshot in enumerate(self.snapshots):
                if snapshot.provider_timestamp > self.clock.now():
                    break
                self.index = index
                yield snapshot
                await asyncio.sleep(0)

        return iterate()

    def visible_at(self, at: datetime) -> tuple[MarketSnapshot, ...]:
        return tuple(s for s in self.snapshots if s.provider_timestamp <= at)
