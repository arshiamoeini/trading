from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from option_platform.domain.errors import DomainError
from option_platform.domain.models import (
    Instrument,
    MarketSnapshot,
    OptionContract,
    OptionRight,
    Side,
)

ZERO = Decimal("0")
HUNDRED = Decimal("100")


class RecommendationKind(StrEnum):
    LONG_CALL = "LONG_CALL"
    LONG_PUT = "LONG_PUT"
    SHORT_CALL = "SHORT_CALL"
    SHORT_PUT = "SHORT_PUT"


@dataclass(frozen=True, slots=True)
class ExpiryOpportunity:
    rank: int
    symbol: str
    underlying_symbol: str
    expiry: date
    days_to_expiry: int
    right: OptionRight
    side: Side
    kind: RecommendationKind
    strike: Decimal
    underlying_price: Decimal
    option_price: Decimal
    break_even_price: Decimal
    break_even_move_percent: Decimal
    safety_margin_percent: Decimal
    max_profit_percent: Decimal | None
    score: Decimal


@dataclass(slots=True)
class ExpiryOpportunityStrategy:
    """Ranks single-leg option opportunities using their expiration payoff.

    Long positions use the ask and short positions use the bid.  The score for
    short positions is ``max_profit_percent * safety_margin_percent``.  Long
    positions are ranked by the inverse distance to break-even because their
    upside cannot be inferred from a single market snapshot.
    """

    include_long: bool = True
    include_short: bool = True
    fee_per_option: Decimal = ZERO

    def __post_init__(self) -> None:
        if not self.include_long and not self.include_short:
            raise DomainError("at least one side must be included")
        if self.fee_per_option < ZERO:
            raise DomainError("fee_per_option cannot be negative")

    def analyze(
        self,
        snapshot: MarketSnapshot,
        instruments: Mapping[UUID, Instrument],
        underlying_last_prices: Mapping[UUID, Decimal],
        *,
        as_of: date | None = None,
    ) -> list[ExpiryOpportunity]:
        valuation_date = as_of or snapshot.provider_timestamp.date()
        candidates: list[ExpiryOpportunity] = []
        for instrument_id in snapshot.chain_instrument_ids:
            instrument = instruments.get(instrument_id)
            quote = snapshot.quotes.get(instrument_id)
            if not isinstance(instrument, OptionContract) or quote is None:
                continue
            spot = underlying_last_prices.get(instrument.underlying_id)
            underlying = instruments.get(instrument.underlying_id)
            if spot is None or spot <= ZERO or underlying is None:
                continue
            days = (instrument.expiry - valuation_date).days
            if days < 0:
                continue
            if self.include_long and quote.ask + self.fee_per_option > ZERO:
                candidates.append(self._long(instrument, underlying.symbol, spot, quote.ask, days))
            net_credit = quote.bid - self.fee_per_option
            if self.include_short and net_credit > ZERO:
                candidates.append(self._short(instrument, underlying.symbol, spot, quote.bid, days))

        # Expiry first makes comparisons within identical maturities explicit.
        candidates.sort(key=lambda item: (item.expiry, -item.score, item.symbol, item.side.value))
        ranked: list[ExpiryOpportunity] = []
        previous_expiry: date | None = None
        expiry_rank = 0
        for item in candidates:
            expiry_rank = expiry_rank + 1 if item.expiry == previous_expiry else 1
            previous_expiry = item.expiry
            ranked.append(
                ExpiryOpportunity(
                    rank=expiry_rank,
                    symbol=item.symbol,
                    underlying_symbol=item.underlying_symbol,
                    expiry=item.expiry,
                    days_to_expiry=item.days_to_expiry,
                    right=item.right,
                    side=item.side,
                    kind=item.kind,
                    strike=item.strike,
                    underlying_price=item.underlying_price,
                    option_price=item.option_price,
                    break_even_price=item.break_even_price,
                    break_even_move_percent=item.break_even_move_percent,
                    safety_margin_percent=item.safety_margin_percent,
                    max_profit_percent=item.max_profit_percent,
                    score=item.score,
                )
            )
        return ranked

    def _long(
        self,
        option: OptionContract,
        underlying_symbol: str,
        spot: Decimal,
        market_price: Decimal,
        days: int,
    ) -> ExpiryOpportunity:
        premium = market_price + self.fee_per_option
        direction = Decimal("1") if option.right is OptionRight.CALL else Decimal("-1")
        break_even = option.strike + direction * premium
        move = (break_even / spot - Decimal("1")) * HUNDRED
        required_move = max(ZERO, direction * move)
        # Smaller required move is preferable. +1 keeps an at-the-money result finite.
        score = HUNDRED / (Decimal("1") + required_move)
        kind = (
            RecommendationKind.LONG_CALL
            if option.right is OptionRight.CALL
            else RecommendationKind.LONG_PUT
        )
        return ExpiryOpportunity(
            0,
            option.symbol,
            underlying_symbol,
            option.expiry,
            days,
            option.right,
            Side.BUY,
            kind,
            option.strike,
            spot,
            market_price,
            break_even,
            move,
            required_move,
            None,
            score,
        )

    def _short(
        self,
        option: OptionContract,
        underlying_symbol: str,
        spot: Decimal,
        market_price: Decimal,
        days: int,
    ) -> ExpiryOpportunity:
        credit = market_price - self.fee_per_option
        direction = Decimal("1") if option.right is OptionRight.CALL else Decimal("-1")
        break_even = option.strike + direction * credit
        move = (break_even / spot - Decimal("1")) * HUNDRED
        safety = max(ZERO, direction * move)
        collateral = spot if option.right is OptionRight.CALL else option.strike
        max_profit_percent = credit / collateral * HUNDRED
        score = safety * max_profit_percent
        kind = (
            RecommendationKind.SHORT_CALL
            if option.right is OptionRight.CALL
            else RecommendationKind.SHORT_PUT
        )
        return ExpiryOpportunity(
            0,
            option.symbol,
            underlying_symbol,
            option.expiry,
            days,
            option.right,
            Side.SELL,
            kind,
            option.strike,
            spot,
            market_price,
            break_even,
            move,
            safety,
            max_profit_percent,
            score,
        )
