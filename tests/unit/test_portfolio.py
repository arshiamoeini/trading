from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.analytics.portfolio import SimulatedPortfolio
from option_platform.domain.models import Fill, Instrument, Quote, Side

pytestmark = pytest.mark.unit


def make_fill(at, *, side: Side, price: str, midpoint: str, reference: str, execution: str) -> Fill:
    return Fill(
        UUID(int=100 + len(execution)),
        execution,
        UUID(int=50),
        UUID(int=51),
        UUID(int=1),
        UUID(int=2),
        side,
        1,
        Decimal(price),
        Decimal("1"),
        at,
        Decimal(midpoint),
        Decimal(reference),
    )


def test_spread_and_slippage_are_attribution_not_double_charged(at) -> None:
    instrument = Instrument(UUID(int=1), "XYZ")
    portfolio = SimulatedPortfolio(Decimal("100"), {instrument.instrument_id: instrument})
    portfolio.apply_fill(
        make_fill(at, side=Side.BUY, price="11.2", midpoint="10", reference="11", execution="buy")
    )
    # Cash reflects fill and commission exactly once: 100 - 11.2 - 1.
    assert portfolio.cash == Decimal("87.8")
    assert portfolio.spread_attribution == Decimal("1.2")
    assert portfolio.slippage_attribution == Decimal("0.2")
    quote = Quote(UUID(int=1), Decimal("11"), Decimal("12"), at, at, 1)
    point = portfolio.mark(at, {UUID(int=1): quote})
    assert point.equity == Decimal("98.8")


def test_average_cost_and_realized_pnl(at) -> None:
    instrument = Instrument(UUID(int=1), "XYZ")
    portfolio = SimulatedPortfolio(Decimal("100"), {instrument.instrument_id: instrument})
    portfolio.apply_fill(
        make_fill(at, side=Side.BUY, price="10", midpoint="10", reference="10", execution="a")
    )
    portfolio.apply_fill(
        make_fill(at, side=Side.SELL, price="12", midpoint="12", reference="12", execution="b")
    )
    position = portfolio.positions[(UUID(int=2), UUID(int=1))]
    assert position.quantity == 0
    assert position.realized_pnl == Decimal("2")
    assert portfolio.cash == Decimal("100")  # two commissions offset the two-point gain
