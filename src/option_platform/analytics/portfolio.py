from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from option_platform.domain.errors import DomainError
from option_platform.domain.models import (
    Fill,
    Instrument,
    OptionContract,
    OptionRight,
    Position,
    Quote,
    SettlementType,
    Side,
)
from option_platform.ports import IdGenerator

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class EquityPoint:
    at: datetime
    equity: Decimal
    drawdown: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioMetrics:
    total_return: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    max_drawdown: Decimal
    volatility: Decimal
    sharpe: Decimal
    win_rate: Decimal
    profit_factor: Decimal | None
    turnover: Decimal
    commission: Decimal
    slippage_attribution: Decimal
    spread_attribution: Decimal


class SimulatedPortfolio:
    def __init__(self, initial_cash: Decimal, instruments: dict[UUID, Instrument]) -> None:
        if initial_cash <= ZERO:
            raise DomainError("initial cash must be positive")
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.instruments = instruments
        self.positions: dict[tuple[UUID, UUID], Position] = {}
        self.equity_curve: list[EquityPoint] = []
        self.commission = ZERO
        self.turnover = ZERO
        self.slippage_attribution = ZERO
        self.spread_attribution = ZERO
        self.closed_trade_pnl: list[Decimal] = []

    def apply_fill(self, fill: Fill) -> None:
        instrument = self.instruments[fill.instrument_id]
        signed = fill.quantity * fill.side.sign
        notional = fill.price * fill.quantity * instrument.multiplier
        self.cash -= Decimal(signed) * fill.price * instrument.multiplier + fill.commission
        self.commission += fill.commission
        self.turnover += notional
        if fill.quote_midpoint is not None:
            self.spread_attribution += (
                abs(fill.price - fill.quote_midpoint) * fill.quantity * instrument.multiplier
            )
        if fill.reference_price is not None:
            self.slippage_attribution += (
                abs(fill.price - fill.reference_price) * fill.quantity * instrument.multiplier
            )

        key = (fill.strategy_instance_id, fill.instrument_id)
        position = self.positions.get(key)
        if position is None:
            position = Position(
                fill.strategy_instance_id, fill.instrument_id, updated_at=fill.occurred_at
            )
            self.positions[key] = position
        old_quantity = position.quantity
        if old_quantity == 0 or old_quantity * signed > 0:
            new_abs = abs(old_quantity) + abs(signed)
            position.average_open_price = (
                position.average_open_price * abs(old_quantity) + fill.price * abs(signed)
            ) / new_abs
            position.quantity += signed
        else:
            closing = min(abs(old_quantity), abs(signed))
            realized = (
                (fill.price - position.average_open_price)
                * closing
                * (1 if old_quantity > 0 else -1)
                * instrument.multiplier
            )
            position.realized_pnl += realized
            self.closed_trade_pnl.append(realized)
            position.quantity += signed
            if position.quantity == 0:
                position.average_open_price = ZERO
            elif old_quantity * position.quantity < 0:
                position.average_open_price = fill.price
        position.updated_at = fill.occurred_at

    def settle_expiration(
        self,
        at: datetime,
        underlying_prices: dict[UUID, Decimal],
        ids: IdGenerator,
    ) -> tuple[Fill, ...]:
        """Settle expired options without introducing a second accounting ledger."""
        settlements: list[Fill] = []
        for (strategy_id, instrument_id), position in list(self.positions.items()):
            instrument = self.instruments[instrument_id]
            if not isinstance(instrument, OptionContract) or instrument.expiry > at.date():
                continue
            if position.quantity == 0:
                continue
            underlying_price = underlying_prices[instrument.underlying_id]
            intrinsic = instrument.intrinsic_value(underlying_price)
            closing_side = Side.SELL if position.quantity > 0 else Side.BUY
            option_settlement_price = (
                intrinsic if instrument.settlement is SettlementType.CASH else ZERO
            )
            option_fill = Fill(
                fill_id=ids.new(),
                execution_id=f"settlement-{ids.new()}",
                order_group_id=ids.new(),
                leg_id=ids.new(),
                instrument_id=instrument_id,
                strategy_instance_id=strategy_id,
                side=closing_side,
                quantity=abs(position.quantity),
                price=option_settlement_price,
                commission=ZERO,
                occurred_at=at,
                quote_midpoint=option_settlement_price,
                reference_price=option_settlement_price,
            )
            self.apply_fill(option_fill)
            settlements.append(option_fill)
            if instrument.settlement is SettlementType.PHYSICAL and intrinsic > ZERO:
                underlying = self.instruments[instrument.underlying_id]
                units = abs(position.quantity) * instrument.multiplier / underlying.multiplier
                if units != int(units):
                    raise DomainError("physical settlement does not produce whole underlying units")
                option_was_long = closing_side is Side.SELL
                buy_underlying = (
                    option_was_long if instrument.right is OptionRight.CALL else not option_was_long
                )
                underlying_fill = Fill(
                    fill_id=ids.new(),
                    execution_id=f"exercise-{ids.new()}",
                    order_group_id=option_fill.order_group_id,
                    leg_id=ids.new(),
                    instrument_id=underlying.instrument_id,
                    strategy_instance_id=strategy_id,
                    side=Side.BUY if buy_underlying else Side.SELL,
                    quantity=int(units),
                    price=instrument.strike,
                    commission=ZERO,
                    occurred_at=at,
                    quote_midpoint=instrument.strike,
                    reference_price=instrument.strike,
                )
                self.apply_fill(underlying_fill)
                settlements.append(underlying_fill)
        return tuple(settlements)

    def mark(self, at: datetime, quotes: dict[UUID, Quote]) -> EquityPoint:
        market_value = ZERO
        for (_, instrument_id), position in self.positions.items():
            if position.quantity == 0:
                continue
            quote = quotes[instrument_id]
            liquidation_price = quote.bid if position.quantity > 0 else quote.ask
            market_value += (
                Decimal(position.quantity)
                * liquidation_price
                * self.instruments[instrument_id].multiplier
            )
        equity = self.cash + market_value
        peak = max([self.initial_cash, *(point.equity for point in self.equity_curve)])
        drawdown = ZERO if peak == 0 else (equity - peak) / peak
        point = EquityPoint(at, equity, drawdown)
        self.equity_curve.append(point)
        return point

    def metrics(self, quotes: dict[UUID, Quote]) -> PortfolioMetrics:
        if not self.equity_curve:
            raise DomainError("portfolio must be marked before metrics are calculated")
        unrealized = ZERO
        realized = ZERO
        for (_, instrument_id), position in self.positions.items():
            realized += position.realized_pnl
            if position.quantity:
                mark = (
                    quotes[instrument_id].bid
                    if position.quantity > 0
                    else quotes[instrument_id].ask
                )
                unrealized += (
                    (mark - position.average_open_price)
                    * position.quantity
                    * self.instruments[instrument_id].multiplier
                )
        returns = [
            float((current.equity - previous.equity) / previous.equity)
            for previous, current in zip(self.equity_curve, self.equity_curve[1:], strict=False)
            if previous.equity != 0
        ]
        volatility = Decimal(str(statistics.pstdev(returns))) if len(returns) > 1 else ZERO
        mean = Decimal(str(statistics.fmean(returns))) if returns else ZERO
        sharpe = mean / volatility if volatility else ZERO
        wins = [value for value in self.closed_trade_pnl if value > 0]
        losses = [value for value in self.closed_trade_pnl if value < 0]
        win_rate = (
            Decimal(len(wins)) / len(self.closed_trade_pnl) if self.closed_trade_pnl else ZERO
        )
        profit_factor = sum(wins, ZERO) / abs(sum(losses, ZERO)) if losses else None
        return PortfolioMetrics(
            total_return=(self.equity_curve[-1].equity - self.initial_cash) / self.initial_cash,
            realized_pnl=realized,
            unrealized_pnl=unrealized,
            max_drawdown=abs(min((point.drawdown for point in self.equity_curve), default=ZERO)),
            volatility=volatility,
            sharpe=sharpe,
            win_rate=win_rate,
            profit_factor=profit_factor,
            turnover=self.turnover,
            commission=self.commission,
            slippage_attribution=self.slippage_attribution,
            spread_attribution=self.spread_attribution,
        )
