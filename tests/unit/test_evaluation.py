from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.backtest.evaluation import (
    EvaluationProtocol,
    OutOfSampleGuard,
    StressScenario,
    apply_stress,
    assess_dataset,
    buy_and_hold_baseline,
    cash_baseline,
    parameter_grid,
)
from option_platform.testing.scenario import ScenarioBuilder

pytestmark = pytest.mark.unit


def test_chronological_split_and_walk_forward() -> None:
    protocol = EvaluationProtocol()
    split = protocol.split(100)
    assert split.train == slice(0, 60)
    assert split.validation == slice(60, 80)
    assert split.out_of_sample == slice(80, 100)
    folds = protocol.walk_forward(80)
    assert len(folds) == 4
    assert all(fold.train.stop <= fold.validation.start for fold in folds)


def test_parameter_grid_and_baselines() -> None:
    assert len(parameter_grid({"window": [10, 20], "threshold": [-1, -2]})) == 4
    assert cash_baseline(Decimal("100"), 3) == (Decimal("100"),) * 3
    curve = buy_and_hold_baseline(Decimal("100"), Decimal("10"), [Decimal("9"), Decimal("11")])
    assert curve == (Decimal("90"), Decimal("110"))


def test_oos_guard_dataset_quality_and_stress(at) -> None:
    guard = OutOfSampleGuard()
    assert guard.evaluate_once(lambda: "final") == "final"
    with pytest.raises(RuntimeError):
        guard.evaluate_once(lambda: "leaked")
    snapshots = (
        ScenarioBuilder(UUID(int=20))
        .snapshot(UUID(int=21), at, 1, {UUID(int=1): (Decimal("9"), Decimal("11"))})
        .build()
    )
    quality = assess_dataset(
        snapshots,
        required_instruments={UUID(int=1)},
        stale_after=timedelta(seconds=30),
        point_in_time_complete=False,
    )
    assert quality.survivorship_bias_risk
    wide = apply_stress(snapshots, StressScenario("wide", spread_multiplier=Decimal("2")))
    assert wide[0].quotes[UUID(int=1)].ask - wide[0].quotes[UUID(int=1)].bid == Decimal("4")
