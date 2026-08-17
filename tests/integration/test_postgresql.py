from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import func, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from option_platform.domain.models import MarketSnapshot, UnderlyingInstrument
from option_platform.infrastructure.models import (
    Base,
    InstrumentIdentifierRow,
    InstrumentRow,
    MarketBarRow,
    MarketSnapshotRow,
    OrderBookSnapshotRow,
)
from option_platform.market_data.base import (
    InstrumentIdentifier,
    MarketBar,
    OrderBookLevel,
    OrderBookSnapshot,
)
from option_platform.runtime.market_collector import TsetmcCollector

pytestmark = pytest.mark.integration


async def test_real_postgresql_connection_and_transaction() -> None:
    url = os.getenv("OPTION_PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set OPTION_PLATFORM_TEST_DATABASE_URL to a disposable PostgreSQL database")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("integration tests require PostgreSQL through asyncpg; SQLite is unsupported")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            assert await connection.scalar(text("SELECT 1")) == 1
            schema = f"option_platform_test_{uuid4().hex}"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
            tables = await connection.run_sync(lambda sync: inspect(sync).get_table_names())
            assert {
                "order_groups",
                "fills",
                "positions",
                "execution_events",
                "instrument_identifiers",
                "market_data_bars",
                "market_data_order_books",
            } <= set(tables)
            instrument_columns = await connection.run_sync(
                lambda sync: {item["name"] for item in inspect(sync).get_columns("instruments")}
            )
            assert {"provider", "provider_instrument_id", "venue"}.isdisjoint(
                instrument_columns
            )
            await transaction.rollback()
    finally:
        await engine.dispose()


@dataclass(frozen=True)
class _FakeConfig:
    timezone: str = "Asia/Tehran"
    depth_concurrency: int = 1
    depth_watchlist: tuple[str, ...] = ("101",)
    poll_seconds: float = 1.0


class _FakeCollectorProvider:
    source = "fake-market"

    def __init__(self) -> None:
        self.config = _FakeConfig()
        self.dataset_id = uuid4()
        self.instrument = UnderlyingInstrument(
            uuid4(), "FAKE", currency="IRR", tick_size=Decimal("1")
        )
        self.instruments = {self.instrument.instrument_id: self.instrument}
        self.instrument_metadata = {
            self.instrument.instrument_id: InstrumentIdentifier(
                "fake", "101", "TSE", raw_symbol="FAKE", isin="IRTEST000001"
            )
        }
        self.instrument_content_hash = "stable-instruments"
        self.observed_at = datetime(2026, 1, 2, 8, tzinfo=UTC)

    def set_dataset_id(self, dataset_id) -> None:
        self.dataset_id = dataset_id

    def instrument_id_for_code(self, provider_code: str):
        return self.instrument.instrument_id if provider_code == "101" else None

    async def refresh(self) -> MarketSnapshot:
        return MarketSnapshot(
            snapshot_id=uuid4(),
            dataset_id=self.dataset_id,
            provider_timestamp=self.observed_at,
            received_at=self.observed_at,
            sequence=1,
            source=self.source,
            quotes={},
            content_hash="stable-snapshot",
        )

    async def get_order_book(self, instrument_id, depth: int = 5) -> OrderBookSnapshot:
        return OrderBookSnapshot(
            instrument_id,
            self.observed_at,
            self.source,
            (OrderBookLevel(1, Decimal("99"), Decimal("10"), 2,
                            Decimal("101"), Decimal("12"), 3),),
        )

    async def get_daily_bars(self, instrument_id, start=None, end=None):
        return (
            MarketBar(
                instrument_id,
                date(2026, 1, 1),
                self.observed_at,
                Decimal("100"),
                Decimal("110"),
                Decimal("90"),
                Decimal("105"),
                Decimal("106"),
                Decimal("98"),
                Decimal("7"),
                Decimal("1000"),
                Decimal("103000"),
                self.source,
            ),
        )


async def test_collector_persists_generic_market_data_through_higher_layers() -> None:
    url = os.getenv("OPTION_PLATFORM_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set OPTION_PLATFORM_TEST_DATABASE_URL to a disposable PostgreSQL database")
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            schema = f"option_platform_collector_{uuid4().hex}"
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(connection, expire_on_commit=False)
            provider = _FakeCollectorProvider()
            collector = TsetmcCollector(factory, provider)  # type: ignore[arg-type]

            assert await collector.run_once() is True
            assert await collector.run_once() is False
            assert await collector.import_history("101") == 1

            async with factory() as session:
                assert await session.scalar(select(func.count()).select_from(InstrumentRow)) == 1
                identifier = await session.scalar(select(InstrumentIdentifierRow))
                assert identifier is not None
                assert identifier.provider_instrument_id == "101"
                assert identifier.isin == "IRTEST000001"
                snapshot_count = await session.scalar(
                    select(func.count()).select_from(MarketSnapshotRow)
                )
                assert snapshot_count == 1
                assert await session.scalar(
                    select(func.count()).select_from(OrderBookSnapshotRow)
                ) == 1
                bar = await session.scalar(select(MarketBarRow))
                assert bar is not None
                assert bar.timeframe == "1d"
                assert bar.close_price == Decimal("105")
            await transaction.rollback()
    finally:
        await engine.dispose()
