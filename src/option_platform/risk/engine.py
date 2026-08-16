from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from option_platform.domain.models import Quote, RiskDecision, TradeIntent


@dataclass(frozen=True, slots=True)
class RiskLimits:
    max_legs: int = 4
    max_contracts: int = 20
    max_debit: Decimal = Decimal("10000")
    stale_after_seconds: int = 30


class RiskEngine:
    def __init__(self, limits: RiskLimits | None = None) -> None:
        self.limits = limits or RiskLimits()
        self.processed_intents: set[UUID] = set()

    def evaluate(
        self,
        intent: TradeIntent,
        quotes: dict[UUID, Quote],
        now: datetime,
    ) -> RiskDecision:
        reasons: list[str] = []
        if not intent.legs:
            reasons.append("intent_has_no_legs")
        if len(intent.legs) > self.limits.max_legs:
            reasons.append("too_many_legs")
        if any(leg.quantity <= 0 for leg in intent.legs):
            reasons.append("non_positive_quantity")
        if sum(leg.quantity for leg in intent.legs) > self.limits.max_contracts:
            reasons.append("max_contracts_exceeded")
        if intent.max_debit is not None and intent.max_debit > self.limits.max_debit:
            reasons.append("max_debit_exceeded")
        if intent.intent_id in self.processed_intents:
            reasons.append("duplicate_intent")
        missing = [leg.instrument_id for leg in intent.legs if leg.instrument_id not in quotes]
        if missing:
            reasons.append("missing_quote")
        elif any(
            quotes[leg.instrument_id].is_stale(now, self.limits.stale_after_seconds)
            for leg in intent.legs
        ):
            reasons.append("stale_market_data")
        approved = not reasons
        if approved:
            self.processed_intents.add(intent.intent_id)
        return RiskDecision(approved, tuple(reasons))
