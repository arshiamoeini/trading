from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import date, datetime
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


class MarketDataProvider(Protocol):
    async def get_instrument(self, instrument_id: UUID) -> Instrument: ...

    async def get_option_chain(self, underlying_id: UUID) -> OptionChain: ...

    async def get_quote(self, instrument_id: UUID) -> Quote: ...

    async def snapshot(self) -> MarketSnapshot: ...

    def stream(self) -> AsyncIterator[MarketSnapshot]: ...

    async def health(self) -> dict[str, object]: ...
