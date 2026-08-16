from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import UUID

from option_platform.domain.models import MarketSnapshot, Quote


class ScenarioBuilder:
    def __init__(self, dataset_id: UUID, source: str = "fixture") -> None:
        self.dataset_id = dataset_id
        self.source = source
        self._snapshots: list[MarketSnapshot] = []

    def snapshot(
        self,
        snapshot_id: UUID,
        at: datetime,
        sequence: int,
        prices: dict[UUID, tuple[Decimal, Decimal]],
        *,
        received_delay: timedelta = timedelta(0),
        quote_age: timedelta = timedelta(0),
    ) -> ScenarioBuilder:
        quotes = {
            instrument_id: Quote(
                instrument_id=instrument_id,
                bid=bid,
                ask=ask,
                provider_timestamp=at - quote_age,
                received_at=at + received_delay,
                sequence=sequence,
                source=self.source,
            )
            for instrument_id, (bid, ask) in prices.items()
        }
        self._snapshots.append(
            MarketSnapshot(
                snapshot_id=snapshot_id,
                dataset_id=self.dataset_id,
                provider_timestamp=at,
                received_at=at + received_delay,
                sequence=sequence,
                source=self.source,
                quotes=quotes,
            )
        )
        return self

    def widen_spreads(self, amount: Decimal) -> ScenarioBuilder:
        widened: list[MarketSnapshot] = []
        for snapshot in self._snapshots:
            quotes = {
                key: Quote(
                    instrument_id=value.instrument_id,
                    bid=max(Decimal("0"), value.bid - amount / 2),
                    ask=value.ask + amount / 2,
                    provider_timestamp=value.provider_timestamp,
                    received_at=value.received_at,
                    sequence=value.sequence,
                    source=value.source,
                )
                for key, value in snapshot.quotes.items()
            }
            widened.append(
                MarketSnapshot(
                    snapshot.snapshot_id,
                    snapshot.dataset_id,
                    snapshot.provider_timestamp,
                    snapshot.received_at,
                    snapshot.sequence,
                    snapshot.source,
                    quotes,
                )
            )
        self._snapshots = widened
        return self

    def build(self) -> tuple[MarketSnapshot, ...]:
        return tuple(
            sorted(self._snapshots, key=lambda item: (item.provider_timestamp, item.sequence))
        )
