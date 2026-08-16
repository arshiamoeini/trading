from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(slots=True)
class CacheEntry[T]:
    value: T
    expires_at: datetime


class TtlCache[T]:
    def __init__(self, ttl: timedelta) -> None:
        self.ttl = ttl
        self._items: dict[object, CacheEntry[T]] = {}

    def put(self, key: object, value: T, now: datetime) -> None:
        self._items[key] = CacheEntry(value, now + self.ttl)

    def get(self, key: object, now: datetime, *, allow_stale: bool = False) -> T | None:
        entry = self._items.get(key)
        if entry is None or (not allow_stale and entry.expires_at < now):
            return None
        return entry.value
