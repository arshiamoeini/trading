from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from option_platform.domain.errors import DomainError
from option_platform.domain.models import (
    Fill,
    MarketSnapshot,
    OrderGroup,
    OrderLeg,
    OrderState,
    Side,
    StrategyRunState,
)
from option_platform.market_data.recording import SnapshotStore, decode_snapshot, snapshot_payload

from .models import (
    ExecutionEventRow,
    FillRow,
    InstrumentRow,
    MarketSnapshotRow,
    OrderGroupRow,
    OrderLegRow,
    PositionRow,
    StrategyInstanceRow,
    StrategyRunRow,
)


class StrategyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self) -> list[StrategyInstanceRow]:
        return list((await self.session.scalars(select(StrategyInstanceRow))).all())

    async def get(self, instance_id: UUID) -> StrategyInstanceRow | None:
        return await self.session.get(StrategyInstanceRow, instance_id)

    async def set_desired_state(self, instance_id: UUID, state: StrategyRunState) -> bool:
        row = await self.get(instance_id)
        if row is None:
            return False
        row.desired_state = state.value
        await self.session.commit()
        return True

    async def heartbeat(
        self,
        instance_id: UUID,
        state: StrategyRunState,
        at: datetime,
        error: str | None = None,
    ) -> None:
        row = await self.get(instance_id)
        if row is None:
            return
        row.actual_state = state.value
        row.heartbeat_at = at
        row.last_error = error
        await self.session.commit()


class QueryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def orders(self) -> list[OrderGroupRow]:
        return list(
            (
                await self.session.scalars(
                    select(OrderGroupRow).order_by(OrderGroupRow.created_at.desc())
                )
            )
            .unique()
            .all()
        )

    async def order(self, order_id: UUID) -> OrderGroupRow | None:
        return await self.session.get(OrderGroupRow, order_id)

    async def positions(self) -> list[PositionRow]:
        return list((await self.session.scalars(select(PositionRow))).all())

    async def runs(self) -> list[StrategyRunRow]:
        return list(
            (
                await self.session.scalars(
                    select(StrategyRunRow).order_by(StrategyRunRow.created_at.desc())
                )
            ).all()
        )

    async def events_after(self, at: datetime) -> list[ExecutionEventRow]:
        statement = (
            select(ExecutionEventRow)
            .where(ExecutionEventRow.occurred_at > at)
            .order_by(ExecutionEventRow.occurred_at)
        )
        return list((await self.session.scalars(statement)).all())


class PostgresSnapshotStore(SnapshotStore):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def append(self, snapshot: MarketSnapshot) -> None:
        self.session.add(
            MarketSnapshotRow(
                id=snapshot.snapshot_id,
                dataset_id=snapshot.dataset_id,
                provider_timestamp=snapshot.provider_timestamp,
                received_at=snapshot.received_at,
                sequence=snapshot.sequence,
                source=snapshot.source,
                content_hash=snapshot.content_hash,
                payload=snapshot_payload(snapshot),
            )
        )
        await self.session.commit()

    async def load(self, dataset_id: UUID) -> tuple[MarketSnapshot, ...]:
        rows = (
            await self.session.scalars(
                select(MarketSnapshotRow)
                .where(MarketSnapshotRow.dataset_id == dataset_id)
                .order_by(MarketSnapshotRow.provider_timestamp, MarketSnapshotRow.sequence)
            )
        ).all()
        return tuple(decode_snapshot(row.payload) for row in rows)


class ExecutionRepository:
    """Atomically journals a Fill and updates its leg, position, and group state."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def apply_fill(self, fill: Fill) -> bool:
        async with self.session.begin():
            duplicate = await self.session.scalar(
                select(FillRow.id).where(FillRow.execution_id == fill.execution_id)
            )
            if duplicate is not None:
                return False
            leg = await self.session.scalar(
                select(OrderLegRow).where(OrderLegRow.id == fill.leg_id).with_for_update()
            )
            if leg is None:
                raise DomainError("fill references an unknown order leg")
            if leg.filled_quantity + fill.quantity > leg.quantity:
                raise DomainError("fill quantity exceeds ordered quantity")
            instrument = await self.session.get(InstrumentRow, fill.instrument_id)
            if instrument is None:
                raise DomainError("fill references an unknown instrument")
            position = await self.session.scalar(
                select(PositionRow)
                .where(
                    PositionRow.strategy_instance_id == fill.strategy_instance_id,
                    PositionRow.instrument_id == fill.instrument_id,
                )
                .with_for_update()
            )
            if position is None:
                position = PositionRow(
                    id=uuid4(),
                    strategy_instance_id=fill.strategy_instance_id,
                    instrument_id=fill.instrument_id,
                    quantity=0,
                    average_open_price=Decimal("0"),
                    realized_pnl=Decimal("0"),
                    updated_at=fill.occurred_at,
                )
                self.session.add(position)
            signed = fill.quantity * fill.side.sign
            old_quantity = position.quantity
            if old_quantity == 0 or old_quantity * signed > 0:
                new_absolute = abs(old_quantity) + abs(signed)
                position.average_open_price = (
                    position.average_open_price * abs(old_quantity) + fill.price * abs(signed)
                ) / new_absolute
                position.quantity += signed
            else:
                closing = min(abs(old_quantity), abs(signed))
                position.realized_pnl += (
                    (fill.price - position.average_open_price)
                    * closing
                    * (1 if old_quantity > 0 else -1)
                    * instrument.multiplier
                )
                position.quantity += signed
                if position.quantity == 0:
                    position.average_open_price = Decimal("0")
                elif old_quantity * position.quantity < 0:
                    position.average_open_price = fill.price
            position.updated_at = fill.occurred_at
            leg.filled_quantity += fill.quantity
            self.session.add(
                FillRow(
                    id=fill.fill_id,
                    execution_id=fill.execution_id,
                    order_group_id=fill.order_group_id,
                    leg_id=fill.leg_id,
                    instrument_id=fill.instrument_id,
                    strategy_instance_id=fill.strategy_instance_id,
                    side=fill.side.value,
                    quantity=fill.quantity,
                    price=fill.price,
                    commission=fill.commission,
                    occurred_at=fill.occurred_at,
                )
            )
            await self.session.flush()
            group = await self.session.get(OrderGroupRow, fill.order_group_id)
            if group is None:
                raise DomainError("fill references an unknown order group")
            quantities = (
                await self.session.execute(
                    select(OrderLegRow.quantity, OrderLegRow.filled_quantity).where(
                        OrderLegRow.order_group_id == fill.order_group_id
                    )
                )
            ).all()
            group.state = (
                "FILLED"
                if quantities and all(filled == quantity for quantity, filled in quantities)
                else "PARTIALLY_FILLED"
            )
            group.updated_at = fill.occurred_at
            self.session.add(
                ExecutionEventRow(
                    id=uuid4(),
                    event_type="FILL_APPLIED",
                    aggregate_id=fill.order_group_id,
                    occurred_at=fill.occurred_at,
                    payload={
                        "execution_id": fill.execution_id,
                        "instrument_id": str(fill.instrument_id),
                        "side": fill.side.value,
                        "quantity": fill.quantity,
                        "price": str(fill.price),
                    },
                )
            )
        return True


class SqlAlchemyOrderStore:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def by_intent(self, intent_id: UUID) -> OrderGroup | None:
        row = await self.session.scalar(
            select(OrderGroupRow).where(OrderGroupRow.intent_id == intent_id)
        )
        if row is None:
            return None
        execution_ids = set(
            (
                await self.session.scalars(
                    select(FillRow.execution_id).where(FillRow.order_group_id == row.id)
                )
            ).all()
        )
        return OrderGroup(
            row.id,
            row.intent_id,
            row.strategy_instance_id,
            [
                OrderLeg(
                    leg.id,
                    leg.instrument_id,
                    Side(leg.side),
                    leg.quantity,
                    leg.filled_quantity,
                    leg.broker_order_id,
                )
                for leg in row.legs
            ],
            OrderState(row.state),
            row.created_at,
            row.updated_at,
            row.broker_order_id,
            execution_ids,
        )

    async def save(self, order: OrderGroup) -> None:
        row = await self.session.get(OrderGroupRow, order.order_group_id)
        if row is None:
            row = OrderGroupRow(
                id=order.order_group_id,
                intent_id=order.intent_id,
                strategy_instance_id=order.strategy_instance_id,
                state=order.state.value,
                broker_order_id=order.broker_order_id,
                created_at=order.created_at,
                updated_at=order.updated_at,
            )
            self.session.add(row)
            for leg in order.legs:
                self.session.add(
                    OrderLegRow(
                        id=leg.leg_id,
                        order_group_id=order.order_group_id,
                        instrument_id=leg.instrument_id,
                        side=leg.side.value,
                        quantity=leg.quantity,
                        filled_quantity=leg.filled_quantity,
                        broker_order_id=leg.broker_order_id,
                    )
                )
        else:
            row.state = order.state.value
            row.broker_order_id = order.broker_order_id
            row.updated_at = order.updated_at
            rows_by_id = {leg.id: leg for leg in row.legs}
            for leg in order.legs:
                rows_by_id[leg.leg_id].filled_quantity = leg.filled_quantity
                rows_by_id[leg.leg_id].broker_order_id = leg.broker_order_id
        await self.session.commit()
