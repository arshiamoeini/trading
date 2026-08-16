from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from option_platform.domain.errors import DomainError
from option_platform.market_data.providers import RecordedMarketDataProvider
from option_platform.market_data.recording import FileSnapshotStore
from option_platform.runtime.clock import FrozenClock
from option_platform.testing.scenario import ScenarioBuilder

pytestmark = [pytest.mark.unit, pytest.mark.replay]


async def test_recorded_provider_prevents_lookahead(at, tmp_path: Path) -> None:
    snapshots = (
        ScenarioBuilder(UUID(int=20))
        .snapshot(UUID(int=21), at, 1, {UUID(int=2): (Decimal("1"), Decimal("2"))})
        .snapshot(
            UUID(int=22), at + timedelta(minutes=1), 2, {UUID(int=2): (Decimal("2"), Decimal("3"))}
        )
        .build()
    )
    clock = FrozenClock(at)
    provider = RecordedMarketDataProvider(clock, snapshots)
    assert (await provider.snapshot()).snapshot_id == UUID(int=21)
    assert len(provider.visible_at(at)) == 1
    clock.advance_to(at + timedelta(minutes=1))
    assert (await provider.snapshot()).snapshot_id == UUID(int=22)

    store = FileSnapshotStore(tmp_path / "dataset.jsonl")
    await store.append(snapshots[0])
    loaded = await store.load(UUID(int=20))
    assert loaded[0].quotes[UUID(int=2)].bid == Decimal("1")


async def test_no_visible_snapshot_is_an_error(at) -> None:
    future = (
        ScenarioBuilder(UUID(int=20))
        .snapshot(
            UUID(int=21), at + timedelta(minutes=1), 1, {UUID(int=2): (Decimal("1"), Decimal("2"))}
        )
        .build()
    )
    with pytest.raises(DomainError):
        await RecordedMarketDataProvider(FrozenClock(at), future).snapshot()
