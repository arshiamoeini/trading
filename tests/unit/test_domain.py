from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.domain.errors import DomainError
from option_platform.domain.models import OrderLegIntent, Quote, Side, TradeIntent

pytestmark = pytest.mark.unit


def test_quote_preserves_decimal_and_requires_aware_time(at: datetime) -> None:
    quote = Quote(UUID(int=1), Decimal("1.10"), Decimal("1.20"), at, at, 1)
    assert isinstance(quote.midpoint, Decimal)
    with pytest.raises(DomainError):
        Quote(UUID(int=1), Decimal("2"), Decimal("1"), at, at, 1)
    with pytest.raises(DomainError):
        Quote(UUID(int=1), Decimal("1"), Decimal("2"), at.replace(tzinfo=None), at, 1)


def test_trade_intent_validation(at: datetime) -> None:
    leg = OrderLegIntent(UUID(int=2), Side.BUY, 1)
    intent = TradeIntent(UUID(int=10), UUID(int=11), (leg,), at, max_debit=Decimal("1.00"))
    assert intent.max_debit == Decimal("1.00")
    with pytest.raises(DomainError):
        TradeIntent(UUID(int=10), UUID(int=11), (), at, max_debit=Decimal("1"))
    with pytest.raises(DomainError):
        TradeIntent(
            UUID(int=10),
            UUID(int=11),
            (leg,),
            at,
            max_debit=Decimal("1"),
            min_credit=Decimal("1"),
        )


def test_quantity_must_be_positive() -> None:
    with pytest.raises(DomainError):
        OrderLegIntent(UUID(int=2), Side.BUY, 0)
