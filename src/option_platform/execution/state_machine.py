from __future__ import annotations

from option_platform.domain.errors import InvalidTransition
from option_platform.domain.models import OrderState

ALLOWED_TRANSITIONS: dict[OrderState, frozenset[OrderState]] = {
    OrderState.CREATED: frozenset({OrderState.RISK_APPROVED, OrderState.REJECTED}),
    OrderState.RISK_APPROVED: frozenset({OrderState.SUBMITTING}),
    OrderState.SUBMITTING: frozenset(
        {OrderState.SUBMITTED, OrderState.REJECTED, OrderState.UNKNOWN}
    ),
    OrderState.SUBMITTED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.REJECTED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.PARTIALLY_FILLED: frozenset(
        {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCEL_PENDING,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.CANCEL_PENDING: frozenset(
        {OrderState.CANCELLED, OrderState.PARTIALLY_FILLED, OrderState.FILLED, OrderState.UNKNOWN}
    ),
    OrderState.UNKNOWN: frozenset(
        {
            OrderState.SUBMITTED,
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.REJECTED,
        }
    ),
    OrderState.FILLED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.REJECTED: frozenset(),
}


def transition(current: OrderState, target: OrderState) -> OrderState:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidTransition(f"cannot transition from {current} to {target}")
    return target
