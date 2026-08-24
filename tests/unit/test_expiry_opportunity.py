from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from option_platform.domain.models import (
    ExerciseStyle,
    MarketSnapshot,
    OptionContract,
    OptionRight,
    Quote,
    SettlementType,
    UnderlyingInstrument,
)
from option_platform.strategies import ExpiryOpportunityStrategy, RecommendationKind


def test_call_break_even_and_executable_prices() -> None:
    underlying_id = UUID(int=1)
    option_id = UUID(int=2)
    observed = datetime(2026, 8, 23, 9, tzinfo=UTC)
    underlying = UnderlyingInstrument(underlying_id, "شنا", currency="IRR")
    call = OptionContract(
        option_id,
        "ضشنا6050",
        currency="IRR",
        tick_size=Decimal("1"),
        underlying_id=underlying_id,
        expiry=date(2026, 9, 23),
        strike=Decimal("14260"),
        right=OptionRight.CALL,
        exercise_style=ExerciseStyle.EUROPEAN,
        settlement=SettlementType.PHYSICAL,
    )
    quote = Quote(option_id, Decimal("39"), Decimal("41"), observed, observed, 1)
    snapshot = MarketSnapshot(
        UUID(int=3), UUID(int=4), observed, observed, 1, "test", {option_id: quote}, (option_id,)
    )

    results = ExpiryOpportunityStrategy().analyze(
        snapshot,
        {underlying_id: underlying, option_id: call},
        {underlying_id: Decimal("11140")},
        as_of=date(2026, 8, 23),
    )

    long_call = next(item for item in results if item.kind is RecommendationKind.LONG_CALL)
    short_call = next(item for item in results if item.kind is RecommendationKind.SHORT_CALL)
    assert long_call.option_price == Decimal("41")
    assert long_call.break_even_price == Decimal("14301")
    assert long_call.break_even_move_percent.quantize(Decimal("0.1")) == Decimal("28.4")
    assert short_call.option_price == Decimal("39")
    assert short_call.break_even_price == Decimal("14299")
    assert short_call.safety_margin_percent.quantize(Decimal("0.1")) == Decimal("28.4")
    assert short_call.max_profit_percent.quantize(Decimal("0.01")) == Decimal("0.35")


def test_short_ranking_rewards_both_safety_and_yield() -> None:
    underlying_id = UUID(int=10)
    observed = datetime(2026, 8, 23, 9, tzinfo=UTC)
    expiry = date(2026, 9, 23)
    underlying = UnderlyingInstrument(underlying_id, "XYZ")
    safer = OptionContract(
        UUID(int=11),
        "XYZ-C150",
        underlying_id=underlying_id,
        expiry=expiry,
        strike=Decimal("150"),
        right=OptionRight.CALL,
    )
    riskier = OptionContract(
        UUID(int=12),
        "XYZ-C110",
        underlying_id=underlying_id,
        expiry=expiry,
        strike=Decimal("110"),
        right=OptionRight.CALL,
    )
    quotes = {
        safer.instrument_id: Quote(
            safer.instrument_id, Decimal("1"), Decimal("2"), observed, observed, 1
        ),
        riskier.instrument_id: Quote(
            riskier.instrument_id, Decimal("1"), Decimal("2"), observed, observed, 1
        ),
    }
    snapshot = MarketSnapshot(
        UUID(int=13), UUID(int=14), observed, observed, 1, "test", quotes, tuple(quotes)
    )
    results = ExpiryOpportunityStrategy(include_long=False).analyze(
        snapshot,
        {underlying_id: underlying, safer.instrument_id: safer, riskier.instrument_id: riskier},
        {underlying_id: Decimal("100")},
    )

    assert [item.symbol for item in results] == ["XYZ-C150", "XYZ-C110"]
    assert [item.rank for item in results] == [1, 2]
