from decimal import Decimal

import pytest

from option_opportunities_tools import (
    black_scholes_call_price,
    call_metrics_from_market_price,
    implied_volatility_call,
)


def test_known_black_scholes_call_and_greeks() -> None:
    price = black_scholes_call_price(
        Decimal("100"), Decimal("100"), Decimal("1"), Decimal("0.05"), Decimal("0.20")
    )
    assert float(price) == pytest.approx(10.45058357, abs=1e-8)
    metrics = call_metrics_from_market_price(
        price, Decimal("100"), Decimal("100"), Decimal("1"), Decimal("0.05")
    )
    assert metrics is not None
    assert float(metrics.implied_volatility) == pytest.approx(0.20, abs=1e-7)
    assert float(metrics.delta) == pytest.approx(0.63683065, abs=1e-7)
    assert float(metrics.gamma) == pytest.approx(0.01876202, abs=1e-7)
    assert float(metrics.theta_per_day) == pytest.approx(-6.41402755 / 365, abs=1e-7)
    assert float(metrics.vega_per_percent) == pytest.approx(0.37524035, abs=1e-7)
    assert float(metrics.rho_per_percent) == pytest.approx(0.53232482, abs=1e-7)


def test_iv_rejects_price_outside_call_arbitrage_bounds() -> None:
    assert (
        implied_volatility_call(
            Decimal("101"), Decimal("100"), Decimal("100"), Decimal("1"), Decimal("0.05")
        )
        is None
    )
