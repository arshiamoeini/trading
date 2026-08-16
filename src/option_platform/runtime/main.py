from __future__ import annotations

import asyncio

from option_platform.config import settings
from option_platform.infrastructure.database import create_engine, session_factory
from option_platform.infrastructure.repositories import StrategyRepository


async def main() -> None:
    from option_platform.runtime.pipeline import RecordedPaperPipeline
    from option_platform.runtime.runner import StrategyRunner
    from option_platform.runtime.supervisor import Supervisor

    engine = create_engine(settings)
    factory = session_factory(engine)
    sessions = []

    def repository_factory() -> StrategyRepository:
        session = factory()
        sessions.append(session)
        return StrategyRepository(session)

    async def async_repository_factory() -> StrategyRepository:
        return repository_factory()

    supervisor = Supervisor(
        repository_factory,
        lambda instance_id: StrategyRunner(
            instance_id,
            async_repository_factory,
            workload=RecordedPaperPipeline(factory, instance_id).run,
        ),
        settings.runtime_poll_seconds,
    )
    try:
        await supervisor.run()
    finally:
        await supervisor.stop()
        for session in sessions:
            await session.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
