from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID

from option_platform.domain.models import StrategyRunState
from option_platform.infrastructure.repositories import StrategyRepository


class StrategyRunner:
    def __init__(
        self,
        instance_id: UUID,
        repository_factory: Callable[[], Awaitable[StrategyRepository]],
        heartbeat_seconds: float = 2.0,
        workload: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.instance_id = instance_id
        self.repository_factory = repository_factory
        self.heartbeat_seconds = heartbeat_seconds
        self.workload = workload

    async def run(self) -> None:
        repository = await self.repository_factory()
        try:
            await repository.heartbeat(
                self.instance_id, StrategyRunState.RUNNING, datetime.now(UTC)
            )
            if self.workload is not None:
                await self.workload()
            while True:
                row = await repository.get(self.instance_id)
                if row is None or row.desired_state != StrategyRunState.RUNNING.value:
                    break
                await repository.heartbeat(
                    self.instance_id, StrategyRunState.RUNNING, datetime.now(UTC)
                )
                await asyncio.sleep(self.heartbeat_seconds)
            await repository.heartbeat(
                self.instance_id, StrategyRunState.STOPPED, datetime.now(UTC)
            )
        except asyncio.CancelledError:
            await repository.heartbeat(
                self.instance_id, StrategyRunState.STOPPED, datetime.now(UTC)
            )
            raise
        except Exception as exc:
            await repository.heartbeat(
                self.instance_id,
                StrategyRunState.FAILED,
                datetime.now(UTC),
                str(exc),
            )
