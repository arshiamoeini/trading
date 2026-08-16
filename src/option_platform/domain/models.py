from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from .errors import DomainError

ZERO = Decimal("0")


def require_aware(value: datetime, name: str = "timestamp") -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DomainError(f"{name} must be timezone-aware")


def utc_now() -> datetime:
    return datetime.now(UTC)


class OptionRight(StrEnum):
    CALL = "CALL"
    PUT = "PUT"


class ExerciseStyle(StrEnum):
    AMERICAN = "AMERICAN"
    EUROPEAN = "EUROPEAN"


class SettlementType(StrEnum):
    CASH = "CASH"
    PHYSICAL = "PHYSICAL"


class Side(StrEnum):
    BUY = "BUY"
    SELL = "SELL"

    @property
    def sign(self) -> int:
        return 1 if self is Side.BUY else -1


class OrderState(StrEnum):
    CREATED = "CREATED"
    RISK_APPROVED = "RISK_APPROVED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class StrategyRunState(StrEnum):
    STOPPED = "STOPPED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class Instrument:
    instrument_id: UUID
    symbol: str
    currency: str = "USD"
    multiplier: Decimal = Decimal("1")
    tick_size: Decimal = Decimal("0.01")

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise DomainError("instrument symbol is required")
        if self.multiplier <= ZERO or self.tick_size <= ZERO:
            raise DomainError("multiplier and tick_size must be positive")


@dataclass(frozen=True, slots=True)
class UnderlyingInstrument(Instrument):
    asset_class: str = "EQUITY"


@dataclass(frozen=True, slots=True)
class OptionContract(Instrument):
    underlying_id: UUID = field(default_factory=lambda: UUID(int=0))
    expiry: date = field(default_factory=date.today)
    strike: Decimal = ZERO
    right: OptionRight = OptionRight.CALL
    exercise_style: ExerciseStyle = ExerciseStyle.AMERICAN
    settlement: SettlementType = SettlementType.PHYSICAL

    def __post_init__(self) -> None:
        Instrument.__post_init__(self)
        if self.underlying_id.int == 0:
            raise DomainError("underlying_id is required")
        if self.strike <= ZERO:
            raise DomainError("strike must be positive")

    def intrinsic_value(self, underlying_price: Decimal) -> Decimal:
        if underlying_price < ZERO:
            raise DomainError("underlying price cannot be negative")
        if self.right is OptionRight.CALL:
            return max(ZERO, underlying_price - self.strike)
        return max(ZERO, self.strike - underlying_price)


@dataclass(frozen=True, slots=True)
class Quote:
    instrument_id: UUID
    bid: Decimal
    ask: Decimal
    provider_timestamp: datetime
    received_at: datetime
    sequence: int
    bid_size: Decimal | None = None
    ask_size: Decimal | None = None
    source: str = "unknown"

    def __post_init__(self) -> None:
        require_aware(self.provider_timestamp, "provider_timestamp")
        require_aware(self.received_at, "received_at")
        if self.bid < ZERO or self.ask < ZERO or self.bid > self.ask:
            raise DomainError("quote requires 0 <= bid <= ask")
        if self.sequence < 0:
            raise DomainError("sequence cannot be negative")
        if self.bid_size is not None and self.bid_size < ZERO:
            raise DomainError("bid_size cannot be negative")
        if self.ask_size is not None and self.ask_size < ZERO:
            raise DomainError("ask_size cannot be negative")

    @property
    def midpoint(self) -> Decimal:
        return (self.bid + self.ask) / Decimal("2")

    def is_stale(self, at: datetime, max_age_seconds: int) -> bool:
        require_aware(at, "at")
        return (at - self.provider_timestamp).total_seconds() > max_age_seconds


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    snapshot_id: UUID
    dataset_id: UUID
    provider_timestamp: datetime
    received_at: datetime
    sequence: int
    source: str
    quotes: Mapping[UUID, Quote]
    chain_instrument_ids: tuple[UUID, ...] = ()
    content_hash: str = ""

    def __post_init__(self) -> None:
        require_aware(self.provider_timestamp, "provider_timestamp")
        require_aware(self.received_at, "received_at")
        if self.sequence < 0:
            raise DomainError("sequence cannot be negative")
        if any(q.provider_timestamp > self.provider_timestamp for q in self.quotes.values()):
            raise DomainError("snapshot cannot contain a quote from the future")


@dataclass(frozen=True, slots=True)
class OrderLegIntent:
    instrument_id: UUID
    side: Side
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise DomainError("quantity must be positive")


@dataclass(frozen=True, slots=True)
class TradeIntent:
    intent_id: UUID
    strategy_instance_id: UUID
    legs: tuple[OrderLegIntent, ...]
    created_at: datetime
    max_debit: Decimal | None = None
    min_credit: Decimal | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
        if not 1 <= len(self.legs) <= 4:
            raise DomainError("intent must contain between one and four legs")
        if (self.max_debit is None) == (self.min_credit is None):
            raise DomainError("exactly one of max_debit and min_credit is required")
        limit = self.max_debit if self.max_debit is not None else self.min_credit
        if limit is not None and limit < ZERO:
            raise DomainError("debit/credit limit cannot be negative")


@dataclass(slots=True)
class OrderLeg:
    leg_id: UUID
    instrument_id: UUID
    side: Side
    quantity: int
    filled_quantity: int = 0
    broker_order_id: str | None = None

    def __post_init__(self) -> None:
        if self.quantity <= 0 or not 0 <= self.filled_quantity <= self.quantity:
            raise DomainError("invalid order-leg quantity")


@dataclass(slots=True)
class OrderGroup:
    order_group_id: UUID
    intent_id: UUID
    strategy_instance_id: UUID
    legs: list[OrderLeg]
    state: OrderState
    created_at: datetime
    updated_at: datetime
    broker_order_id: str | None = None
    seen_execution_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        require_aware(self.created_at, "created_at")
        require_aware(self.updated_at, "updated_at")
        if not self.legs:
            raise DomainError("order group needs at least one leg")


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: UUID
    execution_id: str
    order_group_id: UUID
    leg_id: UUID
    instrument_id: UUID
    strategy_instance_id: UUID
    side: Side
    quantity: int
    price: Decimal
    commission: Decimal
    occurred_at: datetime
    quote_midpoint: Decimal | None = None
    reference_price: Decimal | None = None

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, "occurred_at")
        if self.quantity <= 0 or self.price < ZERO or self.commission < ZERO:
            raise DomainError("invalid fill values")


@dataclass(slots=True)
class Position:
    strategy_instance_id: UUID
    instrument_id: UUID
    quantity: int = 0
    average_open_price: Decimal = ZERO
    realized_pnl: Decimal = ZERO
    updated_at: datetime = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        require_aware(self.updated_at, "updated_at")


@dataclass(frozen=True, slots=True)
class RiskDecision:
    approved: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DomainEvent:
    event_id: UUID
    event_type: str
    aggregate_id: UUID
    occurred_at: datetime
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        require_aware(self.occurred_at, "occurred_at")
