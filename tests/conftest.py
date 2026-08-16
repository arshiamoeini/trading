from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.domain.models import (
    ExerciseStyle,
    OptionContract,
    OptionRight,
    SettlementType,
    UnderlyingInstrument,
)


@pytest.fixture
def at() -> datetime:
    return datetime(2026, 1, 2, 15, 0, tzinfo=UTC)


@pytest.fixture
def instruments() -> dict[UUID, object]:
    underlying = UnderlyingInstrument(UUID(int=1), "XYZ", multiplier=Decimal("1"))

    def option(number: int, strike: str, right: OptionRight, month: int = 3) -> OptionContract:
        return OptionContract(
            instrument_id=UUID(int=number),
            symbol=f"XYZ-2026{month:02d}-{right.value}-{strike}",
            multiplier=Decimal("100"),
            underlying_id=underlying.instrument_id,
            expiry=date(2026, month, 20),
            strike=Decimal(strike),
            right=right,
            exercise_style=ExerciseStyle.AMERICAN,
            settlement=SettlementType.PHYSICAL,
        )

    items = [
        underlying,
        option(2, "90", OptionRight.CALL),
        option(3, "100", OptionRight.CALL),
        option(4, "110", OptionRight.CALL),
        option(5, "90", OptionRight.PUT),
        option(6, "100", OptionRight.PUT),
        option(7, "110", OptionRight.PUT),
        option(8, "100", OptionRight.CALL, 6),
        option(9, "100", OptionRight.PUT, 6),
    ]
    return {item.instrument_id: item for item in items}
