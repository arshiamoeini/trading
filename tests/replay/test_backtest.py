from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.backtest.engine import BacktestEngine, RunManifest
from option_platform.domain.models import Instrument
from option_platform.strategies.example_vertical import VerticalSignalStrategy
from option_platform.testing.scenario import ScenarioBuilder

pytestmark = pytest.mark.replay


def test_backtest_manifest_and_result_are_reproducible(at) -> None:
    instruments = {
        UUID(int=2): Instrument(UUID(int=2), "LONG", multiplier=Decimal("100")),
        UUID(int=3): Instrument(UUID(int=3), "SHORT", multiplier=Decimal("100")),
    }
    snapshots = (
        ScenarioBuilder(UUID(int=20))
        .snapshot(
            UUID(int=21),
            at,
            1,
            {
                UUID(int=2): (Decimal("1"), Decimal("1.1")),
                UUID(int=3): (Decimal(".4"), Decimal(".5")),
            },
        )
        .snapshot(
            UUID(int=22),
            at + timedelta(minutes=1),
            2,
            {
                UUID(int=2): (Decimal("1.2"), Decimal("1.3")),
                UUID(int=3): (Decimal(".5"), Decimal(".6")),
            },
        )
        .build()
    )
    manifest = RunManifest(
        UUID(int=30),
        UUID(int=20),
        "v1",
        "abc",
        "VerticalSignalStrategy",
        "1",
        {"threshold": "-1"},
        100,
        at,
        at + timedelta(minutes=1),
        point_in_time_complete=True,
    )

    def run():
        return BacktestEngine(instruments).run(
            VerticalSignalStrategy(UUID(int=2), UUID(int=3)),
            UUID(int=40),
            snapshots,
            manifest,
            indicator=lambda _: Decimal("-2"),
        )

    assert run() == run()
    assert run().validated
    assert len(run().intents) == 1


def test_incomplete_point_in_time_dataset_is_not_validated(at) -> None:
    manifest = RunManifest(UUID(int=30), UUID(int=20), "v1", "abc", "S", "1", {}, 1, at, at)
    assert manifest.survivorship_bias_risk
