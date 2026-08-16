from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class InstrumentRow(Base):
    __tablename__ = "instruments"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32))
    symbol: Mapped[str] = mapped_column(String(128), unique=True)
    currency: Mapped[str] = mapped_column(String(8))
    multiplier: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    tick_size: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    underlying_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("instruments.id")
    )
    expiry: Mapped[date | None] = mapped_column(Date)
    strike: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    option_right: Mapped[str | None] = mapped_column(String(8))
    exercise_style: Mapped[str | None] = mapped_column(String(16))
    settlement: Mapped[str | None] = mapped_column(String(16))


class StrategyDefinitionRow(Base):
    __tablename__ = "strategy_definitions"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    import_path: Mapped[str] = mapped_column(String(256))
    version: Mapped[str] = mapped_column(String(32))
    default_config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class StrategyInstanceRow(Base):
    __tablename__ = "strategy_instances"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    definition_id: Mapped[UUID] = mapped_column(ForeignKey("strategy_definitions.id"))
    desired_state: Mapped[str] = mapped_column(String(16), default="STOPPED")
    actual_state: Mapped[str] = mapped_column(String(16), default="STOPPED")
    config: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    claimed_by: Mapped[str | None] = mapped_column(String(128))


class MarketDatasetRow(Base):
    __tablename__ = "market_data_datasets"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    version: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(128))
    point_in_time_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MarketSnapshotRow(Base):
    __tablename__ = "market_data_snapshots"
    __table_args__ = (UniqueConstraint("dataset_id", "provider_timestamp", "sequence"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("market_data_datasets.id", ondelete="CASCADE")
    )
    provider_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sequence: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, object]] = mapped_column(JSONB)


class OrderGroupRow(Base):
    __tablename__ = "order_groups"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    intent_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), unique=True, index=True)
    strategy_instance_id: Mapped[UUID] = mapped_column(ForeignKey("strategy_instances.id"))
    state: Mapped[str] = mapped_column(String(32))
    broker_order_id: Mapped[str | None] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    legs: Mapped[list[OrderLegRow]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class OrderLegRow(Base):
    __tablename__ = "order_legs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    order_group_id: Mapped[UUID] = mapped_column(ForeignKey("order_groups.id", ondelete="CASCADE"))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id"))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    filled_quantity: Mapped[int] = mapped_column(Integer, default=0)
    broker_order_id: Mapped[str | None] = mapped_column(String(128), unique=True)


class FillRow(Base):
    __tablename__ = "fills"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    execution_id: Mapped[str] = mapped_column(String(128), unique=True)
    order_group_id: Mapped[UUID] = mapped_column(ForeignKey("order_groups.id"))
    leg_id: Mapped[UUID] = mapped_column(ForeignKey("order_legs.id"))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id"))
    strategy_instance_id: Mapped[UUID] = mapped_column(ForeignKey("strategy_instances.id"))
    side: Mapped[str] = mapped_column(String(8))
    quantity: Mapped[int] = mapped_column(Integer)
    price: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    commission: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PositionRow(Base):
    __tablename__ = "positions"
    __table_args__ = (UniqueConstraint("strategy_instance_id", "instrument_id"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    strategy_instance_id: Mapped[UUID] = mapped_column(ForeignKey("strategy_instances.id"))
    instrument_id: Mapped[UUID] = mapped_column(ForeignKey("instruments.id"))
    quantity: Mapped[int] = mapped_column(Integer)
    average_open_price: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    realized_pnl: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutionEventRow(Base):
    __tablename__ = "execution_events"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    aggregate_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)


class StrategyRunRow(Base):
    __tablename__ = "strategy_runs"
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    strategy_instance_id: Mapped[UUID | None] = mapped_column(ForeignKey("strategy_instances.id"))
    dataset_id: Mapped[UUID] = mapped_column(ForeignKey("market_data_datasets.id"))
    run_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    seed: Mapped[int] = mapped_column(Integer)
    strategy_version: Mapped[str] = mapped_column(String(32))
    engine_version: Mapped[str] = mapped_column(String(32))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB, default=dict)
    metrics: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    survivorship_bias_risk: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EquityPointRow(Base):
    __tablename__ = "equity_points"
    __table_args__ = (UniqueConstraint("run_id", "occurred_at"),)
    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    run_id: Mapped[UUID] = mapped_column(ForeignKey("strategy_runs.id", ondelete="CASCADE"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    equity: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    drawdown: Mapped[Decimal] = mapped_column(Numeric(30, 10))
