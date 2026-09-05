from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from option_platform.analytics.portfolio import PortfolioMetrics, SimulatedPortfolio
from option_platform.domain.models import Fill, Instrument, MarketSnapshot, Quote, Side, TradeIntent
from option_platform.market_data.base import OrderBookSnapshot
from option_platform.runtime.clock import FrozenClock, SequentialIdGenerator
from option_platform.strategy_sdk.base import Strategy
from option_platform.strategy_sdk.context import FakeStrategyContext


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: UUID
    dataset_id: UUID
    dataset_version: str
    dataset_hash: str
    strategy_name: str
    strategy_version: str
    strategy_parameters: dict[str, str]
    seed: int
    started_at: datetime
    ended_at: datetime
    engine_version: str = "1"
    point_in_time_complete: bool = False

    @property
    def survivorship_bias_risk(self) -> bool:
        return not self.point_in_time_complete


@dataclass(frozen=True, slots=True)
class FillModel:
    slippage: Decimal = Decimal("0")
    commission_per_contract: Decimal = Decimal("0")

    def price(self, side: Side, bid: Decimal, ask: Decimal) -> tuple[Decimal, Decimal]:
        reference = ask if side is Side.BUY else bid
        actual = reference + self.slippage if side is Side.BUY else reference - self.slippage
        return max(Decimal("0"), actual), reference

    def execute(
        self,
        side: Side,
        quantity: int,
        quote: Quote,
        order_book: OrderBookSnapshot | None = None,
    ) -> tuple[int, Decimal, Decimal]:
        if order_book is None:
            size = quote.ask_size if side is Side.BUY else quote.bid_size
            price, reference = self.price(side, quote.bid, quote.ask)
            return quantity if size is None else min(quantity, int(size)), price, reference

        remaining = quantity
        filled = 0
        notional = Decimal("0")
        top_reference = quote.ask if side is Side.BUY else quote.bid
        levels = tuple(sorted(order_book.levels, key=lambda item: item.level))
        for level in levels:
            if remaining <= 0:
                break
            level_size = level.ask_size if side is Side.BUY else level.bid_size
            level_quantity = min(remaining, int(level_size))
            if level_quantity <= 0:
                continue
            level_price = level.ask if side is Side.BUY else level.bid
            price = level_price + self.slippage if side is Side.BUY else level_price - self.slippage
            price = max(Decimal("0"), price)
            notional += price * level_quantity
            filled += level_quantity
            remaining -= level_quantity
        if filled == 0:
            return 0, Decimal("0"), top_reference
        return filled, notional / Decimal(filled), top_reference


@dataclass(frozen=True, slots=True)
class BacktestResult:
    manifest: RunManifest
    intents: tuple[TradeIntent, ...]
    fills: tuple[Fill, ...]
    metrics: PortfolioMetrics
    equity_curve: tuple[object, ...]
    validated: bool


class BacktestEngine:
    def __init__(
        self,
        instruments: dict[UUID, Instrument],
        fill_model: FillModel | None = None,
    ) -> None:
        self.instruments = instruments
        self.fill_model = fill_model or FillModel()

    def run(
        self,
        strategy: Strategy,
        strategy_instance_id: UUID,
        snapshots: tuple[MarketSnapshot, ...],
        manifest: RunManifest,
        *,
        initial_cash: Decimal = Decimal("100000"),
        indicator: Callable[[MarketSnapshot], Decimal | None] | None = None,
        order_books: Mapping[tuple[datetime, UUID], OrderBookSnapshot] | None = None,
    ) -> BacktestResult:
        if not snapshots:
            raise ValueError("backtest requires snapshots")
        ordered = tuple(
            sorted(snapshots, key=lambda item: (item.provider_timestamp, item.sequence))
        )
        clock = FrozenClock(ordered[0].provider_timestamp)
        ids = SequentialIdGenerator(manifest.seed)
        ctx = FakeStrategyContext(strategy_instance_id, clock, ids, ordered[0])
        portfolio = SimulatedPortfolio(initial_cash, self.instruments)
        intents: list[TradeIntent] = []
        fills: list[Fill] = []
        strategy.on_start(ctx)
        for snapshot in ordered:
            clock.advance_to(snapshot.provider_timestamp)
            ctx.set_snapshot(snapshot)
            value = indicator(snapshot) if indicator is not None else None
            if value is not None:
                ctx.indicators["zscore"] = value
            for intent in strategy.on_market(ctx):
                intents.append(intent)
                group_id = ids.new()
                for leg in intent.legs:
                    quote = snapshot.quotes[leg.instrument_id]
                    order_book = (
                        None
                        if order_books is None
                        else order_books.get((snapshot.provider_timestamp, leg.instrument_id))
                    )
                    quantity, price, reference = self.fill_model.execute(
                        leg.side, leg.quantity, quote, order_book
                    )
                    if quantity == 0:
                        continue
                    fill = Fill(
                        fill_id=ids.new(),
                        execution_id=f"backtest-{ids.new()}",
                        order_group_id=group_id,
                        leg_id=ids.new(),
                        instrument_id=leg.instrument_id,
                        strategy_instance_id=intent.strategy_instance_id,
                        side=leg.side,
                        quantity=quantity,
                        price=price,
                        commission=self.fill_model.commission_per_contract * quantity,
                        occurred_at=clock.now(),
                        quote_midpoint=quote.midpoint,
                        reference_price=reference,
                    )
                    fills.append(fill)
                    portfolio.apply_fill(fill)
                    ctx.positions[fill.instrument_id] = portfolio.positions[
                        (fill.strategy_instance_id, fill.instrument_id)
                    ]
                    strategy.on_fill(ctx, fill)
            portfolio.mark(clock.now(), dict(snapshot.quotes))
        strategy.on_stop(ctx)
        metrics = portfolio.metrics(dict(ordered[-1].quotes))
        return BacktestResult(
            manifest=manifest,
            intents=tuple(intents),
            fills=tuple(fills),
            metrics=metrics,
            equity_curve=tuple(portfolio.equity_curve),
            validated=not manifest.survivorship_bias_risk,
        )
