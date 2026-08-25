"""Pure Black--Scholes calculations for the opportunity report.

Rates and volatility use decimal units (30% == 0.30). Reported vega/rho are
per one percentage-point move and theta is per calendar day.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import erf, exp, log, pi, sqrt


@dataclass(frozen=True, slots=True)
class BlackScholesMetrics:
    implied_volatility: Decimal
    delta: Decimal
    gamma: Decimal
    theta_per_day: Decimal
    vega_per_percent: Decimal
    rho_per_percent: Decimal


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return exp(-0.5 * value * value) / sqrt(2.0 * pi)


def _d1_d2(
    spot: float, strike: float, years: float, rate: float, volatility: float
) -> tuple[float, float]:
    root_time = sqrt(years)
    d1 = (log(spot / strike) + (rate + 0.5 * volatility**2) * years) / (volatility * root_time)
    return d1, d1 - volatility * root_time


def black_scholes_call_price(
    spot: Decimal, strike: Decimal, years: Decimal, rate: Decimal, volatility: Decimal
) -> Decimal:
    """Return the no-dividend European call value."""
    s, k, t, r, sigma = map(float, (spot, strike, years, rate, volatility))
    if s <= 0 or k <= 0 or t <= 0 or sigma <= 0:
        raise ValueError("spot, strike, years, and volatility must be positive")
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    return Decimal(str(s * _normal_cdf(d1) - k * exp(-r * t) * _normal_cdf(d2)))


def implied_volatility_call(
    market_price: Decimal,
    spot: Decimal,
    strike: Decimal,
    years: Decimal,
    rate: Decimal,
    *,
    tolerance: Decimal = Decimal("0.0000000001"),
    max_iterations: int = 200,
) -> Decimal | None:
    """Solve call IV by bisection; return None when no BS solution exists."""
    s, k, t, r, price = map(float, (spot, strike, years, rate, market_price))
    if s <= 0 or k <= 0 or t <= 0 or price <= 0:
        return None
    lower_price = max(0.0, s - k * exp(-r * t))
    if price < lower_price - float(tolerance) or price >= s:
        return None
    low, high = 1e-8, 10.0
    if float(black_scholes_call_price(spot, strike, years, rate, Decimal(str(high)))) < price:
        return None
    for _ in range(max_iterations):
        middle = (low + high) / 2.0
        model_price = float(
            black_scholes_call_price(spot, strike, years, rate, Decimal(str(middle)))
        )
        if abs(model_price - price) <= float(tolerance):
            return Decimal(str(middle))
        if model_price < price:
            low = middle
        else:
            high = middle
    return Decimal(str((low + high) / 2.0))


def call_metrics_from_market_price(
    market_price: Decimal,
    spot: Decimal,
    strike: Decimal,
    years: Decimal,
    rate: Decimal,
) -> BlackScholesMetrics | None:
    """Infer call IV, then calculate all requested Greeks at that IV."""
    volatility = implied_volatility_call(market_price, spot, strike, years, rate)
    if volatility is None:
        return None
    s, k, t, r, sigma = map(float, (spot, strike, years, rate, volatility))
    d1, d2 = _d1_d2(s, k, t, r, sigma)
    pdf = _normal_pdf(d1)
    theta_annual = -(s * pdf * sigma) / (2.0 * sqrt(t)) - r * k * exp(-r * t) * _normal_cdf(d2)
    return BlackScholesMetrics(
        implied_volatility=volatility,
        delta=Decimal(str(_normal_cdf(d1))),
        gamma=Decimal(str(pdf / (s * sigma * sqrt(t)))),
        theta_per_day=Decimal(str(theta_annual / 365.0)),
        vega_per_percent=Decimal(str(s * pdf * sqrt(t) / 100.0)),
        rho_per_percent=Decimal(str(k * t * exp(-r * t) * _normal_cdf(d2) / 100.0)),
    )
