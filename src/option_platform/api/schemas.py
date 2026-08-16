from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StrategyView(ApiModel):
    id: UUID
    definition_id: UUID
    desired_state: str
    actual_state: str
    config: dict[str, object]
    heartbeat_at: datetime | None
    last_error: str | None


class OrderLegView(ApiModel):
    id: UUID
    instrument_id: UUID
    side: str
    quantity: int
    filled_quantity: int


class OrderView(ApiModel):
    id: UUID
    intent_id: UUID
    strategy_instance_id: UUID
    state: str
    broker_order_id: str | None
    created_at: datetime
    updated_at: datetime
    legs: list[OrderLegView]


class PositionView(ApiModel):
    strategy_instance_id: UUID
    instrument_id: UUID
    quantity: int
    average_open_price: Decimal
    realized_pnl: Decimal
    updated_at: datetime

    @field_serializer("average_open_price", "realized_pnl")
    def serialize_decimal(self, value: Decimal) -> str:
        return str(value)


class BacktestCreate(ApiModel):
    dataset_id: UUID
    strategy_instance_id: UUID | None = None
    seed: int = 1
    strategy_version: str = "1"
    configuration: dict[str, object] = {}


class RunView(ApiModel):
    id: UUID
    dataset_id: UUID
    strategy_instance_id: UUID | None
    run_type: str
    status: str
    seed: int
    strategy_version: str
    engine_version: str
    configuration: dict[str, object]
    metrics: dict[str, object] | None
    survivorship_bias_risk: bool
    created_at: datetime
    completed_at: datetime | None
