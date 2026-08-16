from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .errors import DomainError
from .models import Instrument, OptionContract, OptionRight, Side, UnderlyingInstrument


@dataclass(frozen=True, slots=True)
class StructureLeg:
    instrument: Instrument
    side: Side
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity <= 0:
            raise DomainError("structure-leg quantity must be positive")


@dataclass(frozen=True, slots=True)
class OptionStructure:
    name: str
    legs: tuple[StructureLeg, ...]

    def expiration_payoff(self, prices_by_expiry: Mapping[date, Decimal]) -> Decimal:
        total = Decimal("0")
        latest_price = prices_by_expiry[max(prices_by_expiry)]
        for leg in self.legs:
            instrument = leg.instrument
            if isinstance(instrument, OptionContract):
                price = prices_by_expiry[instrument.expiry]
                value = instrument.intrinsic_value(price)
            elif isinstance(instrument, UnderlyingInstrument):
                value = latest_price
            else:
                raise DomainError("unsupported instrument type")
            total += value * instrument.multiplier * leg.quantity * leg.side.sign
        return total


def _options(legs: Sequence[StructureLeg]) -> list[OptionContract]:
    return [leg.instrument for leg in legs if isinstance(leg.instrument, OptionContract)]


def _same(values: Sequence[object], message: str) -> None:
    if not values or len(set(values)) != 1:
        raise DomainError(message)


def vertical_spread(
    long_option: OptionContract, short_option: OptionContract, quantity: int = 1
) -> OptionStructure:
    _same([long_option.underlying_id, short_option.underlying_id], "underlying must match")
    _same([long_option.expiry, short_option.expiry], "expiry must match")
    _same([long_option.right, short_option.right], "option right must match")
    if long_option.strike == short_option.strike:
        raise DomainError("vertical strikes must differ")
    return OptionStructure(
        "VERTICAL",
        (
            StructureLeg(long_option, Side.BUY, quantity),
            StructureLeg(short_option, Side.SELL, quantity),
        ),
    )


def butterfly(
    low: OptionContract, middle: OptionContract, high: OptionContract, quantity: int = 1
) -> OptionStructure:
    opts = [low, middle, high]
    _same([o.underlying_id for o in opts], "underlying must match")
    _same([o.expiry for o in opts], "expiry must match")
    _same([o.right for o in opts], "option right must match")
    if not low.strike < middle.strike < high.strike:
        raise DomainError("butterfly strikes must be ordered")
    if middle.strike - low.strike != high.strike - middle.strike:
        raise DomainError("v1 butterfly must have symmetric wings")
    return OptionStructure(
        "BUTTERFLY",
        (
            StructureLeg(low, Side.BUY, quantity),
            StructureLeg(middle, Side.SELL, quantity * 2),
            StructureLeg(high, Side.BUY, quantity),
        ),
    )


def calendar_spread(
    near: OptionContract, far: OptionContract, quantity: int = 1
) -> OptionStructure:
    _same([near.underlying_id, far.underlying_id], "underlying must match")
    _same([near.strike, far.strike], "strike must match")
    _same([near.right, far.right], "option right must match")
    if near.expiry >= far.expiry:
        raise DomainError("calendar expiries must be ordered")
    return OptionStructure(
        "CALENDAR",
        (StructureLeg(near, Side.SELL, quantity), StructureLeg(far, Side.BUY, quantity)),
    )


def box_spread(
    low_call: OptionContract,
    high_call: OptionContract,
    low_put: OptionContract,
    high_put: OptionContract,
    *,
    long: bool,
    quantity: int = 1,
) -> OptionStructure:
    opts = [low_call, high_call, low_put, high_put]
    _same([o.underlying_id for o in opts], "underlying must match")
    _same([o.expiry for o in opts], "expiry must match")
    if low_call.right is not OptionRight.CALL or high_call.right is not OptionRight.CALL:
        raise DomainError("call legs required")
    if low_put.right is not OptionRight.PUT or high_put.right is not OptionRight.PUT:
        raise DomainError("put legs required")
    if low_call.strike != low_put.strike or high_call.strike != high_put.strike:
        raise DomainError("box strikes must pair")
    if low_call.strike >= high_call.strike:
        raise DomainError("box strikes must be ordered")
    long_legs = (
        StructureLeg(low_call, Side.BUY, quantity),
        StructureLeg(high_call, Side.SELL, quantity),
        StructureLeg(low_put, Side.SELL, quantity),
        StructureLeg(high_put, Side.BUY, quantity),
    )
    if long:
        return OptionStructure("LONG_BOX", long_legs)
    return OptionStructure(
        "SHORT_BOX",
        tuple(
            StructureLeg(
                leg.instrument, Side.SELL if leg.side is Side.BUY else Side.BUY, leg.quantity
            )
            for leg in long_legs
        ),
    )


def conversion_reversal(
    underlying: UnderlyingInstrument,
    call: OptionContract,
    put: OptionContract,
    *,
    conversion: bool,
    quantity: int = 1,
) -> OptionStructure:
    _same(
        [call.underlying_id, put.underlying_id, underlying.instrument_id], "underlying must match"
    )
    _same([call.expiry, put.expiry], "expiry must match")
    _same([call.strike, put.strike], "strike must match")
    if call.right is not OptionRight.CALL or put.right is not OptionRight.PUT:
        raise DomainError("conversion/reversal requires call and put")
    underlying_units = quantity * call.multiplier / underlying.multiplier
    if underlying_units != int(underlying_units):
        raise DomainError("conversion/reversal needs whole underlying units")
    legs = (
        StructureLeg(underlying, Side.BUY, int(underlying_units)),
        StructureLeg(put, Side.BUY, quantity),
        StructureLeg(call, Side.SELL, quantity),
    )
    if conversion:
        return OptionStructure("CONVERSION", legs)
    return OptionStructure(
        "REVERSAL",
        tuple(
            StructureLeg(
                leg.instrument, Side.SELL if leg.side is Side.BUY else Side.BUY, leg.quantity
            )
            for leg in legs
        ),
    )


def jelly_roll(
    near_call: OptionContract,
    near_put: OptionContract,
    far_call: OptionContract,
    far_put: OptionContract,
    quantity: int = 1,
) -> OptionStructure:
    opts = [near_call, near_put, far_call, far_put]
    _same([o.underlying_id for o in opts], "underlying must match")
    _same([o.strike for o in opts], "strike must match")
    if near_call.expiry != near_put.expiry or far_call.expiry != far_put.expiry:
        raise DomainError("call/put expiry pairs must match")
    if near_call.expiry >= far_call.expiry:
        raise DomainError("jelly-roll expiries must be ordered")
    if near_call.right is not OptionRight.CALL or far_call.right is not OptionRight.CALL:
        raise DomainError("call legs required")
    if near_put.right is not OptionRight.PUT or far_put.right is not OptionRight.PUT:
        raise DomainError("put legs required")
    return OptionStructure(
        "JELLY_ROLL",
        (
            StructureLeg(near_call, Side.BUY, quantity),
            StructureLeg(near_put, Side.SELL, quantity),
            StructureLeg(far_call, Side.SELL, quantity),
            StructureLeg(far_put, Side.BUY, quantity),
        ),
    )
