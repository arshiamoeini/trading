from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
from hypothesis import given
from hypothesis import strategies as st

from option_platform.domain.models import OptionContract, OptionRight, UnderlyingInstrument
from option_platform.domain.structures import (
    box_spread,
    butterfly,
    calendar_spread,
    conversion_reversal,
    jelly_roll,
    vertical_spread,
)

pytestmark = pytest.mark.unit


def test_all_canonical_structure_builders(instruments: dict[UUID, object]) -> None:
    underlying = instruments[UUID(int=1)]
    calls = [instruments[UUID(int=value)] for value in (2, 3, 4)]
    puts = [instruments[UUID(int=value)] for value in (5, 6, 7)]
    far_call = instruments[UUID(int=8)]
    far_put = instruments[UUID(int=9)]
    assert isinstance(underlying, UnderlyingInstrument)
    assert all(isinstance(item, OptionContract) for item in [*calls, *puts, far_call, far_put])
    assert len(vertical_spread(calls[0], calls[1]).legs) == 2
    assert [leg.quantity for leg in butterfly(*calls).legs] == [1, 2, 1]
    assert calendar_spread(calls[1], far_call).name == "CALENDAR"
    assert box_spread(calls[0], calls[2], puts[0], puts[2], long=True).name == "LONG_BOX"
    conversion = conversion_reversal(underlying, calls[1], puts[1], conversion=True)
    assert conversion.name == "CONVERSION"
    assert conversion.legs[0].quantity == 100
    assert conversion_reversal(underlying, calls[1], puts[1], conversion=False).name == "REVERSAL"
    assert jelly_roll(calls[1], puts[1], far_call, far_put).name == "JELLY_ROLL"


def test_canonical_payoffs(instruments: dict[UUID, object]) -> None:
    underlying = instruments[UUID(int=1)]
    calls = [instruments[UUID(int=value)] for value in (2, 3, 4)]
    puts = [instruments[UUID(int=value)] for value in (5, 6, 7)]
    far_call = instruments[UUID(int=8)]
    far_put = instruments[UUID(int=9)]
    assert isinstance(underlying, UnderlyingInstrument)
    assert all(isinstance(item, OptionContract) for item in [*calls, *puts, far_call, far_put])
    near_date = date(2026, 3, 20)
    far_date = date(2026, 6, 20)
    assert butterfly(*calls).expiration_payoff({near_date: Decimal("100")}) == Decimal("1000")
    long_box = box_spread(calls[0], calls[2], puts[0], puts[2], long=True)
    assert long_box.expiration_payoff({near_date: Decimal("75")}) == Decimal("2000")
    conversion = conversion_reversal(underlying, calls[1], puts[1], conversion=True)
    assert conversion.expiration_payoff({near_date: Decimal("130")}) == Decimal("10000")
    calendar = calendar_spread(calls[1], far_call)
    assert calendar.expiration_payoff(
        {near_date: Decimal("100"), far_date: Decimal("110")}
    ) == Decimal("1000")
    jelly = jelly_roll(calls[1], puts[1], far_call, far_put)
    assert isinstance(
        jelly.expiration_payoff({near_date: Decimal("95"), far_date: Decimal("105")}),
        Decimal,
    )


@given(
    price=st.decimals(min_value=0, max_value=200, places=2, allow_nan=False, allow_infinity=False)
)
def test_structure_payoff_equals_sum_of_legs(price: Decimal) -> None:
    underlying_id = UUID(int=1)
    low = OptionContract(
        UUID(int=2),
        "LOW",
        multiplier=Decimal("100"),
        underlying_id=underlying_id,
        expiry=date(2026, 3, 20),
        strike=Decimal("90"),
        right=OptionRight.CALL,
    )
    high = OptionContract(
        UUID(int=3),
        "HIGH",
        multiplier=Decimal("100"),
        underlying_id=underlying_id,
        expiry=date(2026, 3, 20),
        strike=Decimal("100"),
        right=OptionRight.CALL,
    )
    structure = vertical_spread(low, high)
    payoff = structure.expiration_payoff({low.expiry: price})
    expected = (
        low.intrinsic_value(price) * low.multiplier - high.intrinsic_value(price) * high.multiplier
    )
    assert payoff == expected


@pytest.mark.parametrize(
    ("underlying_price", "expected"),
    [
        (Decimal("80"), Decimal("0")),
        (Decimal("95"), Decimal("500")),
        (Decimal("120"), Decimal("1000")),
    ],
)
def test_vertical_payoff(
    underlying_price: Decimal, expected: Decimal, instruments: dict[UUID, object]
) -> None:
    low = instruments[UUID(int=2)]
    high = instruments[UUID(int=3)]
    assert isinstance(low, OptionContract) and isinstance(high, OptionContract)
    assert (
        vertical_spread(low, high).expiration_payoff({date(2026, 3, 20): underlying_price})
        == expected
    )
