from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import UTC, date, datetime
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from option_platform.config import Settings, settings
from option_platform.infrastructure.database import create_engine, session_factory
from option_platform.infrastructure.repositories import (
    MarketDataRepository,
    PostgresSnapshotStore,
)
from option_platform.market_data.base import OrderBookSnapshot
from option_platform.market_data.tsetmc import TsetmcConfig, TsetmcMarketDataProvider

logger = logging.getLogger(__name__)


def config_from_settings(value: Settings) -> TsetmcConfig:
    return TsetmcConfig(
        base_url=value.tsetmc_base_url,
        markets=tuple(
            item.strip().upper() for item in value.tsetmc_markets.split(",") if item.strip()
        ),
        poll_seconds=value.tsetmc_poll_seconds,
        timeout_seconds=value.tsetmc_timeout_seconds,
        max_retries=value.tsetmc_max_retries,
        depth_watchlist=tuple(
            item.strip() for item in value.tsetmc_depth_watchlist.split(",") if item.strip()
        ),
        depth_concurrency=value.tsetmc_depth_concurrency,
        timezone=value.tsetmc_timezone,
    )


class TsetmcCollector:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        provider: TsetmcMarketDataProvider,
    ) -> None:
        self.factory = factory
        self.provider = provider
        self.timezone = ZoneInfo(provider.config.timezone)
        self._dataset_id: UUID | None = None
        self._capture_date: date | None = None
        self._instrument_content_hash = ""

    async def _prepare_dataset(self, now: datetime) -> UUID:
        capture_date = now.astimezone(self.timezone).date()
        async with self.factory() as session:
            repository = MarketDataRepository(session)
            if (
                self._dataset_id is not None
                and self._capture_date is not None
                and self._capture_date != capture_date
            ):
                await repository.finalize_dataset(self._dataset_id, now)
            dataset = await repository.get_or_create_dataset(
                capture_date,
                now,
                source=self.provider.source,
                version=f"{self.provider.source}-v1",
                source_params={"capture_session": capture_date.isoformat()},
            )
        self._dataset_id = dataset.id
        self._capture_date = capture_date
        self.provider.set_dataset_id(dataset.id)
        return dataset.id

    async def _collect_depth(self) -> None:
        semaphore = asyncio.Semaphore(self.provider.config.depth_concurrency)

        async def fetch(provider_code: str) -> OrderBookSnapshot | None:
            instrument_id = self.provider.instrument_id_for_code(provider_code)
            if instrument_id is None:
                return None
            async with semaphore:
                try:
                    return await self.provider.get_order_book(instrument_id)
                except Exception:
                    return None

        books = await asyncio.gather(
            *(fetch(code) for code in self.provider.config.depth_watchlist)
        )
        async with self.factory() as session:
            repository = MarketDataRepository(session)
            for book in books:
                if book is not None:
                    await repository.append_order_book(book)

    async def run_once(self) -> bool:
        now = datetime.now(UTC)
        dataset_id = await self._prepare_dataset(now)
        snapshot = await self.provider.refresh()
        async with self.factory() as session:
            repository = MarketDataRepository(session)
            if self._instrument_content_hash != self.provider.instrument_content_hash:
                await repository.upsert_instruments(
                    self.provider.instruments.values(), self.provider.instrument_metadata
                )
                self._instrument_content_hash = self.provider.instrument_content_hash
            duplicate = await repository.snapshot_hash_exists(dataset_id, snapshot.content_hash)
            if not duplicate:
                await PostgresSnapshotStore(session).append(snapshot)
        await self._collect_depth()
        return not duplicate

    async def import_history(
        self, provider_code: str, start: date | None = None, end: date | None = None
    ) -> int:
        await self._prepare_dataset(datetime.now(UTC))
        await self.provider.refresh()
        instrument_id = self.provider.instrument_id_for_code(provider_code)
        if instrument_id is None:
            raise ValueError(
                f"TSETMC instrument code is not in the current option market: {provider_code}"
            )
        bars = await self.provider.get_daily_bars(instrument_id, start, end)
        async with self.factory() as session:
            repository = MarketDataRepository(session)
            await repository.upsert_instruments(
                self.provider.instruments.values(), self.provider.instrument_metadata
            )
            await repository.upsert_bars(bars)
        return len(bars)

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("TSETMC collection cycle failed")
            await asyncio.sleep(self.provider.config.poll_seconds)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect Tehran option-market data")
    parser.add_argument("--once", action="store_true", help="collect one market snapshot")
    parser.add_argument("--history-code", help="import daily history for a TSETMC insCode")
    parser.add_argument("--start", type=date.fromisoformat, help="history start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=date.fromisoformat, help="history end date (YYYY-MM-DD)")
    return parser


async def _main(args: argparse.Namespace) -> None:
    engine = create_engine(settings)
    factory = session_factory(engine)
    provider = TsetmcMarketDataProvider(uuid4(), config_from_settings(settings))
    collector = TsetmcCollector(factory, provider)
    try:
        if args.history_code:
            count = await collector.import_history(args.history_code, args.start, args.end)
            print(f"Imported {count} daily bars for {args.history_code}")
        elif args.once:
            stored = await collector.run_once()
            print("Stored market snapshot" if stored else "Market snapshot unchanged")
        else:
            await collector.run()
    finally:
        await provider.aclose()
        await engine.dispose()


def run_cli() -> None:
    asyncio.run(_main(_parser().parse_args()))


if __name__ == "__main__":
    run_cli()
