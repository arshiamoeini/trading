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
    min_credit: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    commission_per_contract: Decimal = Decimal("0")
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
        if intent.min_credit is not None and intent.min_credit < self.limits.min_credit:
            reasons.append("min_credit_below_limit")
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
        elif intent.max_debit is not None:
            executable_debit = self._executable_net_debit(intent, quotes)
            if executable_debit > intent.max_debit:
                reasons.append("executable_debit_exceeds_intent_limit")
            if executable_debit > self.limits.max_debit:
                reasons.append("executable_debit_exceeds_risk_limit")
        elif intent.min_credit is not None:
            executable_credit = -self._executable_net_debit(intent, quotes)
            if executable_credit < intent.min_credit:
                reasons.append("executable_credit_below_intent_limit")
            if executable_credit < self.limits.min_credit:
                reasons.append("executable_credit_below_risk_limit")
        approved = not reasons
        if approved:
            self.processed_intents.add(intent.intent_id)
        return RiskDecision(approved, tuple(reasons))

    def _executable_net_debit(
        self,
        intent: TradeIntent,
        quotes: dict[UUID, Quote],
    ) -> Decimal:
        total = Decimal("0")
        for leg in intent.legs:
            quote = quotes[leg.instrument_id]
            reference = quote.ask if leg.side.sign > 0 else quote.bid
            price = (
                reference + self.limits.slippage
                if leg.side.sign > 0
                else reference - self.limits.slippage
            )
            total += max(Decimal("0"), price) * leg.quantity * leg.side.sign
            total += self.limits.commission_per_contract * leg.quantity
        return total
