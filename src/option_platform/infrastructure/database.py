from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from option_platform.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, object] = {}
    if settings.database_ssl:
        connect_args["ssl"] = "require"
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args=connect_args,
    )


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        async with session.begin():
            yield session
