from __future__ import annotations

from collections import deque
from decimal import Decimal


class MovingAverage:
    def __init__(self, window: int) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        self.values: deque[Decimal] = deque(maxlen=window)

    def update(self, value: Decimal) -> Decimal:
        self.values.append(value)
        return sum(self.values, Decimal("0")) / len(self.values)


class ZScore:
    def __init__(self, window: int) -> None:
        self.values: deque[Decimal] = deque(maxlen=window)

    def update(self, value: Decimal) -> Decimal | None:
        self.values.append(value)
        if len(self.values) < 2:
            return None
        mean = sum(self.values, Decimal("0")) / len(self.values)
        variance = sum(((item - mean) ** 2 for item in self.values), Decimal("0")) / len(
            self.values
        )
        if variance == 0:
            return Decimal("0")
        return (value - mean) / variance.sqrt()
