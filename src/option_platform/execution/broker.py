from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from option_platform.domain.models import Fill, OrderGroup, OrderState, Quote
from option_platform.ports import Clock, IdGenerator


class BrokerTimeout(TimeoutError):
    pass


class PaperScenario(StrEnum):
    FULL_FILL = "FULL_FILL"
    PARTIAL_FILL = "PARTIAL_FILL"
    REJECT = "REJECT"
    TIMEOUT = "TIMEOUT"
    DELAYED = "DELAYED"
    OUT_OF_ORDER = "OUT_OF_ORDER"
    DUPLICATE_EVENT = "DUPLICATE_EVENT"


@dataclass(frozen=True, slots=True)
class BrokerSubmission:
    broker_order_id: str
    state: OrderState


@dataclass(frozen=True, slots=True)
class BrokerEvent:
    execution_id: str
    order_group_id: UUID
    state: OrderState
    fill: Fill | None = None
    reason: str | None = None


class Broker(Protocol):
    async def submit_order_group(
        self, order: OrderGroup, quotes: dict[UUID, Quote]
    ) -> BrokerSubmission: ...

    async def cancel_order(self, broker_order_id: str) -> None: ...

    async def get_order_status(self, broker_order_id: str) -> OrderState: ...

    def stream_execution_events(self) -> AsyncIterator[BrokerEvent]: ...


class PaperBroker:
    def __init__(
        self,
        clock: Clock,
        ids: IdGenerator,
        scenario: PaperScenario = PaperScenario.FULL_FILL,
        *,
        partial_ratio: Decimal = Decimal("0.5"),
        delay_seconds: float = 0,
        commission_per_contract: Decimal = Decimal("0"),
        slippage: Decimal = Decimal("0"),
    ) -> None:
        self.clock = clock
        self.ids = ids
        self.scenario = scenario
        self.partial_ratio = partial_ratio
        self.delay_seconds = delay_seconds
        self.commission_per_contract = commission_per_contract
        self.slippage = slippage
        self._events: asyncio.Queue[BrokerEvent] = asyncio.Queue()
        self._states: dict[str, OrderState] = {}
        self.submissions: dict[UUID, BrokerSubmission] = {}

    async def submit_order_group(
        self, order: OrderGroup, quotes: dict[UUID, Quote]
    ) -> BrokerSubmission:
        if order.intent_id in self.submissions:
            return self.submissions[order.intent_id]
        broker_id = f"paper-{order.intent_id}"
        if self.scenario is PaperScenario.TIMEOUT:
            self._states[broker_id] = OrderState.UNKNOWN
            raise BrokerTimeout("paper broker timeout")
        if self.scenario is PaperScenario.REJECT:
            submission = BrokerSubmission(broker_id, OrderState.REJECTED)
            self.submissions[order.intent_id] = submission
            self._states[broker_id] = OrderState.REJECTED
            await self._events.put(
                BrokerEvent(
                    f"reject-{order.intent_id}",
                    order.order_group_id,
                    OrderState.REJECTED,
                    reason="scenario",
                )
            )
            return submission
        submission = BrokerSubmission(broker_id, OrderState.SUBMITTED)
        self.submissions[order.intent_id] = submission
        self._states[broker_id] = OrderState.SUBMITTED
        events: list[BrokerEvent] = []
        for leg in order.legs:
            quote = quotes[leg.instrument_id]
            quantity = leg.quantity
            state = OrderState.FILLED
            if self.scenario is PaperScenario.PARTIAL_FILL:
                quantity = max(1, int(Decimal(leg.quantity) * self.partial_ratio))
                state = (
                    OrderState.PARTIALLY_FILLED if quantity < leg.quantity else OrderState.FILLED
                )
            reference = quote.ask if leg.side.sign > 0 else quote.bid
            price = reference + self.slippage if leg.side.sign > 0 else reference - self.slippage
            execution_id = f"paper-exec-{self.ids.new()}"
            fill = Fill(
                fill_id=self.ids.new(),
                execution_id=execution_id,
                order_group_id=order.order_group_id,
                leg_id=leg.leg_id,
                instrument_id=leg.instrument_id,
                strategy_instance_id=order.strategy_instance_id,
                side=leg.side,
                quantity=quantity,
                price=max(Decimal("0"), price),
                commission=self.commission_per_contract * quantity,
                occurred_at=self.clock.now(),
                quote_midpoint=quote.midpoint,
                reference_price=reference,
            )
            events.append(BrokerEvent(execution_id, order.order_group_id, state, fill))
        if self.scenario is PaperScenario.OUT_OF_ORDER:
            events.reverse()
        if self.scenario is PaperScenario.DUPLICATE_EVENT and events:
            events.append(events[0])
        if self.scenario is PaperScenario.DELAYED and self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        for event in events:
            await self._events.put(event)
        return submission

    async def cancel_order(self, broker_order_id: str) -> None:
        state = self._states[broker_order_id]
        if state in {OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED}:
            return
        self._states[broker_order_id] = OrderState.CANCELLED

    async def get_order_status(self, broker_order_id: str) -> OrderState:
        return self._states[broker_order_id]

    def stream_execution_events(self) -> AsyncIterator[BrokerEvent]:
        async def iterate() -> AsyncIterator[BrokerEvent]:
            while not self._events.empty():
                yield await self._events.get()

        return iterate()
