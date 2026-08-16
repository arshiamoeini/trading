from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from option_platform.analytics.portfolio import SimulatedPortfolio
from option_platform.application.vertical_slice import execute_vertical_slice
from option_platform.domain.errors import DomainError
from option_platform.domain.models import (
    ExerciseStyle,
    Instrument,
    OptionContract,
    OptionRight,
    SettlementType,
    UnderlyingInstrument,
)
from option_platform.execution.broker import PaperBroker
from option_platform.execution.oms import OrderManagementSystem
from option_platform.infrastructure.models import (
    EquityPointRow,
    InstrumentRow,
    StrategyInstanceRow,
    StrategyRunRow,
)
from option_platform.infrastructure.repositories import (
    ExecutionRepository,
    PostgresSnapshotStore,
    SqlAlchemyOrderStore,
)
from option_platform.risk.engine import RiskEngine
from option_platform.strategies.example_vertical import VerticalSignalStrategy
from option_platform.strategy_sdk.context import FakeStrategyContext

from .clock import FrozenClock, SequentialIdGenerator


def to_domain_instrument(row: InstrumentRow) -> Instrument:
    if row.kind == "UNDERLYING":
        return UnderlyingInstrument(row.id, row.symbol, row.currency, row.multiplier, row.tick_size)
    if None in {
        row.underlying_id,
        row.expiry,
        row.strike,
        row.option_right,
        row.exercise_style,
        row.settlement,
    }:
        raise DomainError("persisted option instrument is incomplete")
    assert row.underlying_id is not None
    assert row.expiry is not None
    assert row.strike is not None
    assert row.option_right is not None
    assert row.exercise_style is not None
    assert row.settlement is not None
    return OptionContract(
        instrument_id=row.id,
        symbol=row.symbol,
        currency=row.currency,
        multiplier=row.multiplier,
        tick_size=row.tick_size,
        underlying_id=row.underlying_id,
        expiry=row.expiry,
        strike=row.strike,
        right=OptionRight(row.option_right),
        exercise_style=ExerciseStyle(row.exercise_style),
        settlement=SettlementType(row.settlement),
    )


class RecordedPaperPipeline:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        instance_id: UUID,
    ) -> None:
        self.sessions = sessions
        self.instance_id = instance_id

    async def run(self) -> None:
        async with self.sessions() as session:
            instance = await session.get(StrategyInstanceRow, self.instance_id)
            if instance is None:
                raise DomainError("strategy instance disappeared")
            config = instance.config
            required = {"dataset_id", "long_instrument_id", "short_instrument_id"}
            if not required.issubset(config):
                raise DomainError("strategy instance lacks recorded-paper configuration")
            dataset_id = UUID(str(config["dataset_id"]))
            long_id = UUID(str(config["long_instrument_id"]))
            short_id = UUID(str(config["short_instrument_id"]))
            snapshots = await PostgresSnapshotStore(session).load(dataset_id)
            if not snapshots:
                raise DomainError("configured replay dataset is empty")
            rows = (
                await session.scalars(
                    select(InstrumentRow).where(InstrumentRow.id.in_({long_id, short_id}))
                )
            ).all()
            instruments = {row.id: to_domain_instrument(row) for row in rows}
            if set(instruments) != {long_id, short_id}:
                raise DomainError("configured strategy instruments are missing")
            clock = FrozenClock(snapshots[0].provider_timestamp)
            seed = int(str(config.get("seed", 1)))
            ids = SequentialIdGenerator(seed)
            context = FakeStrategyContext(
                self.instance_id,
                clock,
                ids,
                snapshots[0],
                {"zscore": Decimal(str(config.get("zscore", "-2")))},
            )
            portfolio = SimulatedPortfolio(
                Decimal(str(config.get("initial_cash", "100000"))), instruments
            )
            oms = OrderManagementSystem(
                RiskEngine(),
                PaperBroker(clock, ids),
                SqlAlchemyOrderStore(session),
                clock,
                ids,
                portfolio,
                ExecutionRepository(session),
            )
            strategy = VerticalSignalStrategy(
                long_id,
                short_id,
                Decimal(str(config.get("entry_threshold", "-1"))),
                Decimal(str(config.get("max_debit", "2"))),
            )
            result = await execute_vertical_slice(strategy, context, snapshots, oms, portfolio)
            run_id = uuid4()
            session.add(
                StrategyRunRow(
                    id=run_id,
                    strategy_instance_id=self.instance_id,
                    dataset_id=dataset_id,
                    run_type="PAPER",
                    status="COMPLETED",
                    seed=seed,
                    strategy_version="1",
                    engine_version="1",
                    configuration=config,
                    metrics={key: str(value) for key, value in asdict(result.metrics).items()},
                    survivorship_bias_risk=True,
                    created_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                )
            )
            for point in portfolio.equity_curve:
                session.add(
                    EquityPointRow(
                        id=uuid4(),
                        run_id=run_id,
                        occurred_at=point.at,
                        equity=point.equity,
                        drawdown=point.drawdown,
                    )
                )
            await session.commit()
