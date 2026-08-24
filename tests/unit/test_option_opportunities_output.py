from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from option_opportunities import (
    OUTPUT_HEADERS,
    _average_last_five_values,
    _business_days_to_expiry,
    _export_row,
    _to_jalali,
)
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
