from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol
from uuid import UUID

from option_platform.domain.models import StrategyRunState
from option_platform.infrastructure.repositories import StrategyRepository


class Runner(Protocol):
    async def run(self) -> None: ...


class Supervisor:
    def __init__(
        self,
        repository_factory: Callable[[], StrategyRepository],
        runner_factory: Callable[[UUID], Runner],
        poll_seconds: float = 1.0,
    ) -> None:
        self.repository_factory = repository_factory
        self.runner_factory = runner_factory
        self.poll_seconds = poll_seconds
        self.tasks: dict[UUID, asyncio.Task[None]] = {}
        self.stopping = False

    async def tick(self) -> None:
        repository = self.repository_factory()
        rows = await repository.list()
        for row in rows:
            task = self.tasks.get(row.id)
            running = task is not None and not task.done()
            if row.desired_state == StrategyRunState.RUNNING.value and not running:
                runner = self.runner_factory(row.id)
                self.tasks[row.id] = asyncio.create_task(runner.run(), name=f"strategy-{row.id}")
            elif (
                row.desired_state == StrategyRunState.STOPPED.value and task is not None and running
            ):
                task.cancel()
        finished = [key for key, task in self.tasks.items() if task.done()]
        for key in finished:
            task = self.tasks.pop(key)
            if not task.cancelled():
                task.exception()

    async def run(self) -> None:
        while not self.stopping:
            await self.tick()
            await asyncio.sleep(self.poll_seconds)

    async def stop(self) -> None:
        self.stopping = True
        for task in self.tasks.values():
            task.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
