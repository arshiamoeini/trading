from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from uuid import UUID

from option_platform.domain.models import MarketSnapshot, Quote


class SnapshotStore(Protocol):
    async def append(self, snapshot: MarketSnapshot) -> None: ...

    async def load(self, dataset_id: UUID) -> tuple[MarketSnapshot, ...]: ...


def snapshot_payload(snapshot: MarketSnapshot) -> dict[str, object]:
    return {
        "snapshot_id": str(snapshot.snapshot_id),
        "dataset_id": str(snapshot.dataset_id),
        "provider_timestamp": snapshot.provider_timestamp.isoformat(),
        "received_at": snapshot.received_at.isoformat(),
        "sequence": snapshot.sequence,
        "source": snapshot.source,
        "chain_instrument_ids": [str(value) for value in snapshot.chain_instrument_ids],
        "quotes": [
            {
                "instrument_id": str(quote.instrument_id),
                "bid": str(quote.bid),
                "ask": str(quote.ask),
                "provider_timestamp": quote.provider_timestamp.isoformat(),
                "received_at": quote.received_at.isoformat(),
                "sequence": quote.sequence,
                "bid_size": None if quote.bid_size is None else str(quote.bid_size),
                "ask_size": None if quote.ask_size is None else str(quote.ask_size),
                "source": quote.source,
            }
            for quote in sorted(snapshot.quotes.values(), key=lambda item: str(item.instrument_id))
        ],
    }


def content_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def decode_snapshot(payload: dict[str, object]) -> MarketSnapshot:
    raw_quotes = payload["quotes"]
    assert isinstance(raw_quotes, list)
    quotes: dict[UUID, Quote] = {}
    for item in raw_quotes:
        assert isinstance(item, dict)
        quote = Quote(
            instrument_id=UUID(str(item["instrument_id"])),
            bid=Decimal(str(item["bid"])),
            ask=Decimal(str(item["ask"])),
            provider_timestamp=datetime.fromisoformat(str(item["provider_timestamp"])),
            received_at=datetime.fromisoformat(str(item["received_at"])),
            sequence=int(str(item["sequence"])),
            bid_size=None if item.get("bid_size") is None else Decimal(str(item["bid_size"])),
            ask_size=None if item.get("ask_size") is None else Decimal(str(item["ask_size"])),
            source=str(item["source"]),
        )
        quotes[quote.instrument_id] = quote
    raw_chain_ids = payload["chain_instrument_ids"]
    assert isinstance(raw_chain_ids, list)
    return MarketSnapshot(
        snapshot_id=UUID(str(payload["snapshot_id"])),
        dataset_id=UUID(str(payload["dataset_id"])),
        provider_timestamp=datetime.fromisoformat(str(payload["provider_timestamp"])),
        received_at=datetime.fromisoformat(str(payload["received_at"])),
        sequence=int(str(payload["sequence"])),
        source=str(payload["source"]),
        quotes=quotes,
        chain_instrument_ids=tuple(UUID(str(value)) for value in raw_chain_ids),
        content_hash=str(payload.get("content_hash", "")),
    )


@dataclass(slots=True)
class FileSnapshotStore:
    path: Path

    async def append(self, snapshot: MarketSnapshot) -> None:
        payload = snapshot_payload(snapshot)
        payload["content_hash"] = content_hash(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")

    async def load(self, dataset_id: UUID) -> tuple[MarketSnapshot, ...]:
        if not self.path.exists():
            return ()
        result: list[MarketSnapshot] = []
        with self.path.open(encoding="utf-8") as stream:
            for line in stream:
                payload = json.loads(line)
                if UUID(payload["dataset_id"]) == dataset_id:
                    result.append(decode_snapshot(payload))
        return tuple(sorted(result, key=lambda item: (item.provider_timestamp, item.sequence)))


class DataRecorder:
    def __init__(self, store: SnapshotStore) -> None:
        self.store = store

    async def record(self, snapshots: Iterable[MarketSnapshot]) -> None:
        for snapshot in snapshots:
            await self.store.append(snapshot)
