from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from option_platform.domain.models import StrategyRunState
from option_platform.infrastructure.models import StrategyRunRow
from option_platform.infrastructure.repositories import QueryRepository, StrategyRepository


class NotFoundError(LookupError):
    pass


class ConflictError(RuntimeError):
    pass


class StrategyControlService:
    def __init__(self, repository: StrategyRepository) -> None:
        self.repository = repository

    async def start(self, instance_id: UUID) -> None:
        row = await self.repository.get(instance_id)
        if row is None:
            raise NotFoundError("strategy instance not found")
        if row.desired_state == StrategyRunState.RUNNING.value:
            raise ConflictError("strategy is already requested to run")
        await self.repository.set_desired_state(instance_id, StrategyRunState.RUNNING)

    async def stop(self, instance_id: UUID) -> None:
        row = await self.repository.get(instance_id)
        if row is None:
            raise NotFoundError("strategy instance not found")
        if row.desired_state == StrategyRunState.STOPPED.value:
            raise ConflictError("strategy is already requested to stop")
        await self.repository.set_desired_state(instance_id, StrategyRunState.STOPPED)


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    dataset_id: UUID
    strategy_instance_id: UUID | None
    seed: int
    strategy_version: str
    configuration: dict[str, object]


class BacktestQueueService:
    def __init__(self, query: QueryRepository) -> None:
        self.query = query

    async def enqueue(self, request: BacktestRequest) -> StrategyRunRow:
        row = StrategyRunRow(
            id=uuid4(),
            strategy_instance_id=request.strategy_instance_id,
            dataset_id=request.dataset_id,
            run_type="BACKTEST",
            status="PENDING",
            seed=request.seed,
            strategy_version=request.strategy_version,
            engine_version="1",
            configuration=request.configuration,
            metrics=None,
            survivorship_bias_risk=True,
            created_at=datetime.now(UTC),
            completed_at=None,
        )
        self.query.session.add(row)
        await self.query.session.commit()
        return row
