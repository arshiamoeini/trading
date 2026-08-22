from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.analytics.portfolio import SimulatedPortfolio
from option_platform.domain.errors import InvalidTransition
from option_platform.domain.models import (
    Instrument,
    OrderLegIntent,
    OrderState,
    Quote,
    Side,
    TradeIntent,
)
from option_platform.execution.broker import PaperBroker, PaperScenario
from option_platform.execution.oms import InMemoryOrderStore, OrderManagementSystem
from option_platform.execution.state_machine import ALLOWED_TRANSITIONS, transition
from option_platform.risk.engine import RiskEngine, RiskLimits
from option_platform.runtime.clock import FrozenClock, SequentialIdGenerator

pytestmark = pytest.mark.unit


def intent(at, amount: str = "10") -> TradeIntent:
    return TradeIntent(
        UUID(int=10),
        UUID(int=11),
        (OrderLegIntent(UUID(int=1), Side.BUY, 1),),
        at,
        max_debit=Decimal(amount),
    )


def test_risk_boundary_and_multiple_reasons(at) -> None:
    quote = Quote(UUID(int=1), Decimal("1"), Decimal("2"), at, at, 1)
    limits = RiskLimits(max_contracts=1, max_debit=Decimal("10"))
    assert RiskEngine(limits).evaluate(intent(at), {UUID(int=1): quote}, at).approved
    decision = RiskEngine(limits).evaluate(intent(at, "11"), {}, at)
    assert set(decision.reasons) == {"max_debit_exceeded", "missing_quote"}


def test_risk_uses_executable_vertical_debit_after_slippage(at) -> None:
    spread = TradeIntent(
        UUID(int=12),
        UUID(int=11),
        (
            OrderLegIntent(UUID(int=1), Side.BUY, 1),
            OrderLegIntent(UUID(int=2), Side.SELL, 1),
        ),
        at,
        max_debit=Decimal("90"),
    )
    quotes = {
        UUID(int=1): Quote(UUID(int=1), Decimal("100"), Decimal("120"), at, at, 1),
        UUID(int=2): Quote(UUID(int=2), Decimal("40"), Decimal("50"), at, at, 1),
    }

    assert RiskEngine().evaluate(spread, quotes, at).approved

    decision = RiskEngine(RiskLimits(slippage=Decimal("10"))).evaluate(spread, quotes, at)

    assert not decision.approved
    assert decision.reasons == ("executable_debit_exceeds_intent_limit",)


def test_terminal_states_have_no_transitions() -> None:
    for state in (OrderState.FILLED, OrderState.CANCELLED, OrderState.REJECTED):
        assert ALLOWED_TRANSITIONS[state] == frozenset()
        with pytest.raises(InvalidTransition):
            transition(state, OrderState.SUBMITTED)


async def test_oms_idempotency_and_duplicate_fill(at) -> None:
    instrument = Instrument(UUID(int=1), "XYZ")
    quote = Quote(UUID(int=1), Decimal("1"), Decimal("2"), at, at, 1)
    clock = FrozenClock(at)
    ids = SequentialIdGenerator(100)
    broker = PaperBroker(clock, ids, PaperScenario.DUPLICATE_EVENT)
    portfolio = SimulatedPortfolio(Decimal("100"), {instrument.instrument_id: instrument})
    oms = OrderManagementSystem(RiskEngine(), broker, InMemoryOrderStore(), clock, ids, portfolio)
    order = await oms.submit(intent(at), {UUID(int=1): quote})
    assert (
        await oms.submit(intent(at), {UUID(int=1): quote})
    ).order_group_id == order.order_group_id
    assert len(broker.submissions) == 1
    await oms.consume_broker_events(order)
    assert order.legs[0].filled_quantity == 1
    assert len(oms.applied_fills) == 1


async def test_timeout_becomes_unknown_without_resubmit(at) -> None:
    quote = Quote(UUID(int=1), Decimal("1"), Decimal("2"), at, at, 1)
    clock = FrozenClock(at)
    ids = SequentialIdGenerator(100)
    broker = PaperBroker(clock, ids, PaperScenario.TIMEOUT)
    oms = OrderManagementSystem(RiskEngine(), broker, InMemoryOrderStore(), clock, ids)
    order = await oms.submit(intent(at), {UUID(int=1): quote})
    assert order.state is OrderState.UNKNOWN
    await oms.submit(intent(at), {UUID(int=1): quote})
    assert len(broker.submissions) == 0
