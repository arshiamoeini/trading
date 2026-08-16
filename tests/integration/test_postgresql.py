from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from option_platform.infrastructure.models import Base

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
            assert {"order_groups", "fills", "positions", "execution_events"} <= set(tables)
            await transaction.rollback()
    finally:
        await engine.dispose()
