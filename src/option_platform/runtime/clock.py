from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    def __init__(self, value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("frozen clock needs an aware datetime")
        self.value = value

    def now(self) -> datetime:
        return self.value

    def advance_to(self, value: datetime) -> None:
        if value < self.value:
            raise ValueError("clock cannot move backwards")
        self.value = value


class SequentialIdGenerator:
    def __init__(self, seed: int = 1) -> None:
        self.next_value = seed

    def new(self) -> UUID:
        value = UUID(int=self.next_value)
        self.next_value += 1
        return value
