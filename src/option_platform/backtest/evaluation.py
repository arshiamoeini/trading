from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import product
from uuid import UUID

from option_platform.domain.models import MarketSnapshot, Quote


@dataclass(frozen=True, slots=True)
class DatasetSplit:
    train: slice
    validation: slice
    out_of_sample: slice


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    train: slice
    validation: slice


@dataclass(frozen=True, slots=True)
class EvaluationProtocol:
    train_fraction: Decimal = Decimal("0.60")
    validation_fraction: Decimal = Decimal("0.20")
    out_of_sample_fraction: Decimal = Decimal("0.20")
    minimum_walk_forward_folds: int = 4

    def split(self, length: int) -> DatasetSplit:
        if length < 10:
            raise ValueError("statistical evaluation needs at least ten observations")
        train_end = int(length * self.train_fraction)
        validation_end = train_end + int(length * self.validation_fraction)
        return DatasetSplit(
            slice(0, train_end), slice(train_end, validation_end), slice(validation_end, length)
        )

    def walk_forward(self, development_length: int) -> tuple[WalkForwardFold, ...]:
        folds = self.minimum_walk_forward_folds
        test_size = max(1, development_length // (folds + 4))
        train_size = development_length - folds * test_size
        if train_size <= 0:
            raise ValueError("dataset is too short for requested walk-forward folds")
        return tuple(
            WalkForwardFold(
                slice(index * test_size, index * test_size + train_size),
                slice(index * test_size + train_size, index * test_size + train_size + test_size),
            )
            for index in range(folds)
        )


class OutOfSampleGuard:
    """Prevents accidental repeated inspection of the final holdout in one evaluation."""

    def __init__(self) -> None:
        self.consumed = False

    def evaluate_once[R](self, runner: Callable[[], R]) -> R:
        if self.consumed:
            raise RuntimeError("final out-of-sample data has already been evaluated")
        self.consumed = True
        return runner()


def parameter_grid(values: dict[str, Sequence[object]]) -> tuple[dict[str, object], ...]:
    names = tuple(sorted(values))
    return tuple(
        dict(zip(names, combination, strict=True))
        for combination in product(*(values[n] for n in names))
    )


def evaluate_grid[R](
    values: dict[str, Sequence[object]], runner: Callable[[dict[str, object]], R]
) -> dict[tuple[tuple[str, object], ...], R]:
    return {tuple(sorted(item.items())): runner(item) for item in parameter_grid(values)}


def cash_baseline(initial_cash: Decimal, observations: int) -> tuple[Decimal, ...]:
    return (initial_cash,) * observations


def buy_and_hold_baseline(
    initial_cash: Decimal,
    first_ask: Decimal,
    bids: Sequence[Decimal],
    multiplier: Decimal = Decimal("1"),
) -> tuple[Decimal, ...]:
    quantity = int(initial_cash // (first_ask * multiplier))
    remaining = initial_cash - first_ask * quantity * multiplier
    return tuple(remaining + bid * quantity * multiplier for bid in bids)


@dataclass(frozen=True, slots=True)
class StressScenario:
    name: str
    spread_multiplier: Decimal = Decimal("1")
    slippage_multiplier: Decimal = Decimal("1")
    fee_multiplier: Decimal = Decimal("1")
    liquidity_multiplier: Decimal = Decimal("1")
    volatility_shift: Decimal = Decimal("0")
    drop_every_nth_quote: int | None = None


DEFAULT_STRESS_SCENARIOS = (
    StressScenario("wide_spread", spread_multiplier=Decimal("2")),
    StressScenario("high_slippage", slippage_multiplier=Decimal("2")),
    StressScenario("high_fee", fee_multiplier=Decimal("2")),
    StressScenario("low_liquidity", liquidity_multiplier=Decimal("0.5")),
    StressScenario("missing_data", drop_every_nth_quote=10),
    StressScenario("volatility_shock", volatility_shift=Decimal("0.20")),
)


@dataclass(frozen=True, slots=True)
class DatasetQualityReport:
    observations: int
    sequence_gaps: int
    missing_quote_observations: int
    stale_quote_observations: int
    point_in_time_complete: bool

    @property
    def survivorship_bias_risk(self) -> bool:
        return not self.point_in_time_complete

    @property
    def validated(self) -> bool:
        return not self.survivorship_bias_risk and self.sequence_gaps == 0


def assess_dataset(
    snapshots: Sequence[MarketSnapshot],
    *,
    required_instruments: set[UUID],
    stale_after: timedelta,
    point_in_time_complete: bool,
) -> DatasetQualityReport:
    sequence_gaps = sum(
        current.sequence != previous.sequence + 1
        for previous, current in zip(snapshots, snapshots[1:], strict=False)
    )
    missing = 0
    stale = 0
    for snapshot in snapshots:
        if not required_instruments.issubset(snapshot.quotes):
            missing += 1
        if any(
            snapshot.provider_timestamp - quote.provider_timestamp > stale_after
            for quote in snapshot.quotes.values()
        ):
            stale += 1
    return DatasetQualityReport(
        len(snapshots), sequence_gaps, missing, stale, point_in_time_complete
    )


def apply_stress(
    snapshots: Sequence[MarketSnapshot], scenario: StressScenario
) -> tuple[MarketSnapshot, ...]:
    stressed: list[MarketSnapshot] = []
    for index, snapshot in enumerate(snapshots, start=1):
        quotes: dict[UUID, Quote] = {}
        for instrument_id, quote in snapshot.quotes.items():
            if scenario.drop_every_nth_quote and index % scenario.drop_every_nth_quote == 0:
                continue
            midpoint = quote.midpoint * (Decimal("1") + scenario.volatility_shift)
            half_spread = (quote.ask - quote.bid) / 2 * scenario.spread_multiplier
            quotes[instrument_id] = Quote(
                instrument_id=instrument_id,
                bid=max(Decimal("0"), midpoint - half_spread),
                ask=max(Decimal("0"), midpoint + half_spread),
                provider_timestamp=quote.provider_timestamp,
                received_at=quote.received_at,
                sequence=quote.sequence,
                bid_size=(
                    quote.bid_size * scenario.liquidity_multiplier
                    if quote.bid_size is not None
                    else None
                ),
                ask_size=(
                    quote.ask_size * scenario.liquidity_multiplier
                    if quote.ask_size is not None
                    else None
                ),
                source=f"{quote.source}:stress:{scenario.name}",
            )
        stressed.append(
            MarketSnapshot(
                snapshot.snapshot_id,
                snapshot.dataset_id,
                snapshot.provider_timestamp,
                snapshot.received_at,
                snapshot.sequence,
                f"{snapshot.source}:stress:{scenario.name}",
                quotes,
                snapshot.chain_instrument_ids,
                snapshot.content_hash,
            )
        )
    return tuple(stressed)


def stress_execution_costs(
    slippage: Decimal,
    commission: Decimal,
    scenario: StressScenario,
) -> tuple[Decimal, Decimal]:
    return (
        slippage * scenario.slippage_multiplier,
        commission * scenario.fee_multiplier,
    )
