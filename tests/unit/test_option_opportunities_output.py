from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from option_opportunities import (
    OUTPUT_HEADERS,
    _average_last_five_values,
    _business_days_to_expiry,
    _export_row,
    _to_jalali,
)
from option_opportunities_tools import black_scholes_call_price
from option_platform.market_data.base import MarketBar


def test_final_output_uses_requested_entry_formula_and_columns() -> None:
    row = {
        "rank": 1,
        "symbol": "ضراز6008",
        "underlying_symbol": "هم تراز",
        "expiry": date(2026, 8, 26),
        "days_to_expiry": 2,
        "kind": "LONG_CALL",
        "strike": Decimal("18000"),
        "underlying_price": Decimal("23055"),
        "option_price": Decimal("4880"),
        "break_even_price": Decimal("22880"),
    }

    result = _export_row(row)

    expected = (
        (Decimal("23055") - Decimal("4880") - Decimal("18000")) / Decimal("23055") * Decimal("100")
    )
    assert result["entry_profit_percent"] == expected
    assert result["expiry_jalali"] == "1405-06-04"
    assert result["business_days_to_expiry"] == 2
    assert "right" not in OUTPUT_HEADERS
    assert "side" not in OUTPUT_HEADERS
    assert "safety_margin_percent" not in OUTPUT_HEADERS
    assert "max_profit_percent" not in OUTPUT_HEADERS
    assert "score" not in OUTPUT_HEADERS


def test_known_gregorian_date_converts_to_jalali() -> None:
    assert _to_jalali(date(2026, 3, 21)) == "1405-01-01"


def test_black_scholes_matches_all_calculated_fields_in_official_panel() -> None:
    panel = {
        "valuation_timestamp": datetime(2026, 8, 26, 12, 29, tzinfo=ZoneInfo("Asia/Tehran")),
        "expiry": date(2026, 9, 2),
        "underlying_price": Decimal("2946"),
        "strike": Decimal("2600"),
        "last_price": Decimal("374"),
        "closing_price": Decimal("355"),
        "previous_closing_price": Decimal("303"),
        "last_price_change_percent": Decimal("23.43"),
        "historical_volatility": Decimal("0.31"),
        "historical_volatility_price": Decimal("359"),
        "weighted_iv_se": Decimal("0.82"),
        "weighted_iv_se_price": Decimal("374"),
        "weighted_iv": Decimal("0.82"),
        "weighted_iv_price": Decimal("374"),
        "implied_volatility": Decimal("0.82"),
    }
    calendar_days = (panel["expiry"] - panel["valuation_timestamp"].date()).days
    row = {
        "rank": 1,
        "symbol": "ضستا6051",
        "underlying_symbol": "شستا",
        "expiry": panel["expiry"],
        "days_to_expiry": calendar_days,
        "kind": "LONG_CALL",
        "strike": panel["strike"],
        "underlying_price": panel["underlying_price"],
        "option_price": panel["last_price"],
        "break_even_price": Decimal("2974"),
    }

    result = _export_row(row)
    pricing_years = Decimal(calendar_days - 1) / Decimal("365")
    model_prices = {
        "historical_volatility_price": black_scholes_call_price(
            panel["underlying_price"],
            panel["strike"],
            pricing_years,
            Decimal("0.30"),
            panel["historical_volatility"],
        ).quantize(Decimal("1")),
        "weighted_iv_se_price": black_scholes_call_price(
            panel["underlying_price"],
            panel["strike"],
            pricing_years,
            Decimal("0.30"),
            panel["weighted_iv_se"],
        ).quantize(Decimal("1")),
        "weighted_iv_price": black_scholes_call_price(
            panel["underlying_price"],
            panel["strike"],
            pricing_years,
            Decimal("0.30"),
            panel["weighted_iv"],
        ).quantize(Decimal("1")),
    }
    last_price_change = (
        (panel["last_price"] / panel["previous_closing_price"] - Decimal("1")) * Decimal("100")
    ).quantize(Decimal("0.01"))

    assert calendar_days == 7
    assert pricing_years == Decimal("6") / Decimal("365")
    assert result["option_price"] == panel["last_price"]
    assert panel["closing_price"] == Decimal("355")
    assert last_price_change == panel["last_price_change_percent"]
    assert model_prices["historical_volatility_price"] == panel["historical_volatility_price"]
    assert model_prices["weighted_iv_se_price"] == panel["weighted_iv_se_price"]
    assert model_prices["weighted_iv_price"] == panel["weighted_iv_price"]
    assert (result["implied_volatility_percent"] / Decimal("100")).quantize(
        Decimal("0.01")
    ) == panel["implied_volatility"]
    assert float(result["implied_volatility_percent"]) == pytest.approx(82.12654378, abs=1e-8)


def test_business_days_exclude_iran_market_weekend() -> None:
    # Wednesday through the following Saturday: Thu/Fri excluded, Saturday included.
    assert _business_days_to_expiry(date(2026, 8, 26), date(2026, 8, 29)) == 1


def test_average_uses_five_completed_trading_records(at) -> None:
    bars = tuple(
        MarketBar(
            instrument_id=UUID(int=1),
            trading_date=date(2026, 8, day),
            event_at=at,
            open=Decimal("1"),
            high=Decimal("1"),
            low=Decimal("1"),
            close=Decimal("1"),
            last=Decimal("1"),
            previous_close=Decimal("1"),
            trades=Decimal("1"),
            volume=Decimal("1"),
            value=Decimal(day),
            source="test",
        )
        for day in range(17, 24)
    )

    assert _average_last_five_values(bars, date(2026, 8, 24)) == Decimal("21")
