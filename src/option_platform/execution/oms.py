from __future__ import annotations

from typing import Protocol
from uuid import UUID

from option_platform.analytics.portfolio import SimulatedPortfolio
from option_platform.domain.errors import DomainError
from option_platform.domain.models import Fill, OrderGroup, OrderLeg, OrderState, Quote, TradeIntent
from option_platform.ports import Clock, IdGenerator
from option_platform.risk.engine import RiskEngine

from .broker import Broker, BrokerEvent, BrokerTimeout
from .state_machine import transition


class OrderStore(Protocol):
    async def by_intent(self, intent_id: UUID) -> OrderGroup | None: ...

    async def save(self, order: OrderGroup) -> None: ...


class FillStore(Protocol):
    async def apply_fill(self, fill: Fill) -> bool: ...


class InMemoryOrderStore:
    def __init__(self) -> None:
        self.orders: dict[UUID, OrderGroup] = {}

    async def by_intent(self, intent_id: UUID) -> OrderGroup | None:
        return self.orders.get(intent_id)

    async def save(self, order: OrderGroup) -> None:
        existing = self.orders.get(order.intent_id)
        if existing is not None and existing.order_group_id != order.order_group_id:
            raise DomainError("duplicate intent_id")
        self.orders[order.intent_id] = order


class OrderManagementSystem:
    def __init__(
        self,
        risk: RiskEngine,
        broker: Broker,
        store: OrderStore,
        clock: Clock,
        ids: IdGenerator,
        portfolio: SimulatedPortfolio | None = None,
        fill_store: FillStore | None = None,
    ) -> None:
        self.risk = risk
        self.broker = broker
        self.store = store
        self.clock = clock
        self.ids = ids
        self.portfolio = portfolio
        self.fill_store = fill_store
        self.applied_fills: list[Fill] = []

    async def submit(self, intent: TradeIntent, quotes: dict[UUID, Quote]) -> OrderGroup:
        existing = await self.store.by_intent(intent.intent_id)
        if existing is not None:
            return existing
        order = OrderGroup(
            order_group_id=self.ids.new(),
            intent_id=intent.intent_id,
            strategy_instance_id=intent.strategy_instance_id,
            legs=[
                OrderLeg(self.ids.new(), leg.instrument_id, leg.side, leg.quantity)
                for leg in intent.legs
            ],
            state=OrderState.CREATED,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
        )
        await self.store.save(order)
        decision = self.risk.evaluate(intent, quotes, self.clock.now())
        if not decision.approved:
            order.state = transition(order.state, OrderState.REJECTED)
            await self.store.save(order)
            return order
        order.state = transition(order.state, OrderState.RISK_APPROVED)
        order.state = transition(order.state, OrderState.SUBMITTING)
        await self.store.save(order)
        try:
            submission = await self.broker.submit_order_group(order, quotes)
        except BrokerTimeout:
            order.state = transition(order.state, OrderState.UNKNOWN)
            order.updated_at = self.clock.now()
            await self.store.save(order)
            return order
        order.broker_order_id = submission.broker_order_id
        order.state = transition(order.state, submission.state)
        order.updated_at = self.clock.now()
        await self.store.save(order)
        return order

    async def consume_broker_events(self, order: OrderGroup) -> None:
        async for event in self.broker.stream_execution_events():
            if event.order_group_id != order.order_group_id:
                continue
            await self.apply_event(order, event)

    async def apply_event(self, order: OrderGroup, event: BrokerEvent) -> None:
        if event.execution_id in order.seen_execution_ids:
            return
        order.seen_execution_ids.add(event.execution_id)
        if event.fill is not None:
            if self.fill_store is not None and not await self.fill_store.apply_fill(event.fill):
                return
            leg = next(item for item in order.legs if item.leg_id == event.fill.leg_id)
            if leg.filled_quantity + event.fill.quantity > leg.quantity:
                raise DomainError("fill quantity exceeds ordered quantity")
            leg.filled_quantity += event.fill.quantity
            self.applied_fills.append(event.fill)
            if self.portfolio is not None:
                self.portfolio.apply_fill(event.fill)
            target = (
                OrderState.FILLED
                if all(item.filled_quantity == item.quantity for item in order.legs)
                else OrderState.PARTIALLY_FILLED
            )
        else:
            target = event.state
        if target != order.state:
            order.state = transition(order.state, target)
        order.updated_at = self.clock.now()
        await self.store.save(order)

    async def reconcile_unknown(self, order: OrderGroup) -> OrderState:
        if order.state is not OrderState.UNKNOWN or order.broker_order_id is None:
            return order.state
        status = await self.broker.get_order_status(order.broker_order_id)
        if status is not OrderState.UNKNOWN:
            order.state = transition(order.state, status)
            order.updated_at = self.clock.now()
            await self.store.save(order)
        return order.state
