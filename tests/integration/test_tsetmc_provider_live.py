from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.domain.models import OptionContract
from option_platform.market_data.tsetmc import TsetmcConfig, TsetmcMarketDataProvider

pytestmark = pytest.mark.integration

LIVE_ENV = "OPTION_PLATFORM_RUN_LIVE_TESTS"
DATASET_ID = UUID(int=20)
FIXED_UNDERLYING_PROVIDER_CODE = "17914401175772326"
FIXED_START = date(2026, 8, 1)
FIXED_END = date(2026, 8, 16)
EXPECTED_DAILY_BARS = (
    (date(2026, 8, 1), "40449.0", "40999.0", "39326.0", "40016.0", "39326.0"),
    (date(2026, 8, 2), "41616.0", "41616.0", "41510.0", "41615.0", "41616.0"),
    (date(2026, 8, 3), "43279.0", "43279.0", "43279.0", "43279.0", "43279.0"),
    (date(2026, 8, 5), "45010.0", "45010.0", "45010.0", "45010.0", "45010.0"),
    (date(2026, 8, 8), "46810.0", "46810.0", "46810.0", "46810.0", "46810.0"),
    (date(2026, 8, 9), "48682.0", "48682.0", "47470.0", "48527.0", "48682.0"),
    (date(2026, 8, 10), "48527.0", "50468.0", "48012.0", "50094.0", "50468.0"),
    (date(2026, 8, 11), "51780.0", "52097.0", "50468.0", "51647.0", "52097.0"),
    (date(2026, 8, 15), "52712.0", "52712.0", "49582.0", "49832.0", "49582.0"),
    (date(2026, 8, 16), "48828.0", "51825.0", "48300.0", "50491.0", "51825.0"),
)


def _skip_unless_enabled() -> None:
    if os.getenv(LIVE_ENV) != "1":
        pytest.skip(f"set {LIVE_ENV}=1 to run live TSETMC provider tests")


async def test_tsetmc_live_public_api_and_fixed_daily_bars() -> None:
    _skip_unless_enabled()

    provider = TsetmcMarketDataProvider(
        DATASET_ID,
        TsetmcConfig(markets=("TSE",), timeout_seconds=20.0, max_retries=1),
    )
    try:
        snapshot = await provider.snapshot()

        assert snapshot.source == "tsetmc"
        assert snapshot.dataset_id == DATASET_ID
        assert snapshot.quotes
        assert provider.instrument_content_hash

        underlying_id = provider.instrument_id_for_code(FIXED_UNDERLYING_PROVIDER_CODE)
        assert underlying_id is not None
        chain = await provider.get_option_chain(underlying_id)
        assert chain.contracts

        contract = chain.contracts[0]
        assert isinstance(contract, OptionContract)
        contract_id = contract.instrument_id
        quote = await provider.get_quote(contract_id)
        health = await provider.health()

        assert contract.instrument_id == contract_id
        assert quote.instrument_id == contract_id
        assert quote.bid >= 0
        assert quote.ask > 0
        assert quote.bid <= quote.ask
        assert contract_id in {item.instrument_id for item in chain.contracts}
        assert health["provider"] == "tsetmc"
        assert health["ok"] is True
        assert health["quotes"] > 0

        book = await provider.get_order_book(contract_id, depth=3)
        assert book.instrument_id == contract_id
        assert book.levels
        assert len(book.levels) <= 3
        levels = [level.level for level in book.levels]
        assert levels == sorted(levels)
        for level in book.levels:
            assert level.bid >= 0
            assert level.ask >= 0
            assert level.bid_size >= 0
            assert level.ask_size >= 0

        bars = await provider.get_daily_bars(underlying_id, start=FIXED_START, end=FIXED_END)
        assert bars
        assert all(FIXED_START <= bar.trading_date <= FIXED_END for bar in bars)
        assert tuple(bar.trading_date for bar in bars) == tuple(
            sorted(bar.trading_date for bar in bars)
        )
        assert len(bars) == len(EXPECTED_DAILY_BARS)
        for bar in bars:
            assert bar.instrument_id == underlying_id
            assert bar.open >= 0
            assert bar.high >= 0
            assert bar.low >= 0
            assert bar.close >= 0
            assert bar.last >= 0

        assert tuple(
            (
                bar.trading_date,
                bar.open,
                bar.high,
                bar.low,
                bar.close,
                bar.last,
            )
            for bar in bars
        ) == tuple(
            (
                trading_date,
                Decimal(open_),
                Decimal(high),
                Decimal(low),
                Decimal(close),
                Decimal(last),
            )
            for trading_date, open_, high, low, close, last in EXPECTED_DAILY_BARS
        )
    finally:
        await provider.aclose()
