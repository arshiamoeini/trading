from __future__ import annotations

import asyncio
import json
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

import httpx
import websockets

from option_platform.domain.errors import DomainError
from option_platform.domain.models import (
    ExerciseStyle,
    Instrument,
    MarketSnapshot,
    OptionContract,
    OptionRight,
    Quote,
    SettlementType,
    UnderlyingInstrument,
)

from .base import OptionChain
from .cache import TtlCache


@dataclass(frozen=True, slots=True)
class ProviderProfile:
    name: str
    rest_base_url: str
    websocket_url: str
    instrument_path: str = "/instruments/{instrument_id}"
    quote_path: str = "/quotes/{instrument_id}"
    chain_path: str = "/chains/{underlying_id}"
    snapshot_path: str = "/snapshots/latest"
    requests_per_second: Decimal = Decimal("5")
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    max_retries: int = 3
    instrument_ttl_seconds: int = 3600
    chain_ttl_seconds: int = 60
    quote_ttl_seconds: int = 2
    headers: Mapping[str, str] = field(default_factory=dict)


class ProviderMapper(Protocol):
    def instrument(self, payload: Mapping[str, Any]) -> Instrument: ...

    def option_chain(self, payload: Mapping[str, Any]) -> OptionChain: ...

    def quote(self, payload: Mapping[str, Any], received_at: datetime) -> Quote: ...

    def snapshot(self, payload: Mapping[str, Any], received_at: datetime) -> MarketSnapshot: ...

    def subscription(self, instrument_ids: tuple[UUID, ...]) -> Mapping[str, Any]: ...


class JsonFieldMapper:
    """Reference flat-JSON mapper; complex vendors supply a dedicated mapper."""

    def __init__(self, source: str, dataset_id: UUID) -> None:
        self.source = source
        self.dataset_id = dataset_id

    def instrument(self, payload: Mapping[str, Any]) -> Instrument:
        common: dict[str, Any] = {
            "instrument_id": UUID(str(payload["instrument_id"])),
            "symbol": str(payload["symbol"]),
            "currency": str(payload.get("currency", "USD")),
            "multiplier": Decimal(str(payload.get("multiplier", "1"))),
            "tick_size": Decimal(str(payload.get("tick_size", "0.01"))),
        }
        if str(payload["kind"]).upper() == "UNDERLYING":
            return UnderlyingInstrument(
                **common, asset_class=str(payload.get("asset_class", "EQUITY"))
            )
        return OptionContract(
            **common,
            underlying_id=UUID(str(payload["underlying_id"])),
            expiry=date.fromisoformat(str(payload["expiry"])),
            strike=Decimal(str(payload["strike"])),
            right=OptionRight(str(payload["right"]).upper()),
            exercise_style=ExerciseStyle(str(payload.get("exercise_style", "AMERICAN")).upper()),
            settlement=SettlementType(str(payload.get("settlement", "PHYSICAL")).upper()),
        )

    def option_chain(self, payload: Mapping[str, Any]) -> OptionChain:
        raw_contracts = payload["contracts"]
        if not isinstance(raw_contracts, list):
            raise DomainError("option-chain contracts must be a list")
        instruments = tuple(self.instrument(item) for item in raw_contracts)
        if not all(isinstance(item, OptionContract) for item in instruments):
            raise DomainError("option chain can only contain option contracts")
        contracts = cast(tuple[OptionContract, ...], instruments)
        return OptionChain(
            underlying_id=UUID(str(payload["underlying_id"])),
            as_of=datetime.fromisoformat(str(payload["as_of"]).replace("Z", "+00:00")),
            contracts=contracts,
        )

    def quote(self, payload: Mapping[str, Any], received_at: datetime) -> Quote:
        timestamp = datetime.fromisoformat(str(payload["timestamp"]).replace("Z", "+00:00"))
        return Quote(
            instrument_id=UUID(str(payload["instrument_id"])),
            bid=Decimal(str(payload["bid"])),
            ask=Decimal(str(payload["ask"])),
            bid_size=(
                Decimal(str(payload["bid_size"])) if payload.get("bid_size") is not None else None
            ),
            ask_size=(
                Decimal(str(payload["ask_size"])) if payload.get("ask_size") is not None else None
            ),
            provider_timestamp=timestamp,
            received_at=received_at,
            sequence=int(payload["sequence"]),
            source=self.source,
        )

    def snapshot(self, payload: Mapping[str, Any], received_at: datetime) -> MarketSnapshot:
        quote_payloads = payload.get("quotes", [payload])
        if not isinstance(quote_payloads, list):
            raise DomainError("snapshot quotes must be a list")
        quotes = {
            quote.instrument_id: quote
            for quote in (self.quote(item, received_at) for item in quote_payloads)
        }
        return MarketSnapshot(
            snapshot_id=UUID(str(payload.get("snapshot_id", uuid4()))),
            dataset_id=self.dataset_id,
            provider_timestamp=max(quote.provider_timestamp for quote in quotes.values()),
            received_at=received_at,
            sequence=int(payload.get("sequence", max(quote.sequence for quote in quotes.values()))),
            source=self.source,
            quotes=quotes,
        )

    def subscription(self, instrument_ids: tuple[UUID, ...]) -> Mapping[str, Any]:
        return {
            "action": "subscribe",
            "instrument_ids": [str(value) for value in instrument_ids],
        }


class TokenBucket:
    def __init__(self, rate: Decimal) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = float(rate)
        self.tokens = float(rate)
        self.updated: float | None = None
        self.lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self.lock:
            if self.updated is None:
                self.updated = asyncio.get_running_loop().time()
            while True:
                now = asyncio.get_running_loop().time()
                self.tokens = min(self.rate, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1:
                    self.tokens -= 1
                    return
                await asyncio.sleep((1 - self.tokens) / self.rate)


class ExternalApiAdapter:
    """Complete MarketDataProvider adapter with no order-submission surface."""

    def __init__(
        self,
        profile: ProviderProfile,
        mapper: ProviderMapper,
        *,
        request_once: Callable[[str], Awaitable[Mapping[str, Any]]] | None = None,
        subscribed_instruments: tuple[UUID, ...] = (),
    ) -> None:
        self.profile = profile
        self.mapper = mapper
        self.request_once = request_once
        self.subscribed_instruments = subscribed_instruments
        self.limiter: TokenBucket | None = None
        self.instrument_cache = TtlCache[Instrument](
            timedelta(seconds=profile.instrument_ttl_seconds)
        )
        self.chain_cache = TtlCache[OptionChain](timedelta(seconds=profile.chain_ttl_seconds))
        self.quote_cache = TtlCache[Quote](timedelta(seconds=profile.quote_ttl_seconds))
        self.last_error: str | None = None

    def _limiter(self) -> TokenBucket:
        if self.limiter is None:
            self.limiter = TokenBucket(self.profile.requests_per_second)
        return self.limiter

    async def _http_get_once(self, path: str) -> Mapping[str, Any]:
        if self.request_once is not None:
            return await self.request_once(path)
        timeout = httpx.Timeout(
            connect=self.profile.connect_timeout_seconds,
            read=self.profile.read_timeout_seconds,
            write=self.profile.read_timeout_seconds,
            pool=self.profile.connect_timeout_seconds,
        )
        async with httpx.AsyncClient(
            base_url=self.profile.rest_base_url,
            headers=self.profile.headers,
            timeout=timeout,
        ) as client:
            response = await client.get(path)
            if response.status_code == 429:
                raise httpx.HTTPStatusError(
                    "rate limited", request=response.request, response=response
                )
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise DomainError("provider response must be a JSON object")
            return value

    async def _get(self, path: str) -> Mapping[str, Any]:
        for attempt in range(self.profile.max_retries + 1):
            await self._limiter().acquire()
            try:
                value = await asyncio.wait_for(
                    self._http_get_once(path), timeout=self.profile.read_timeout_seconds
                )
                self.last_error = None
                return value
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 429 or attempt >= self.profile.max_retries:
                    self.last_error = str(exc)
                    raise
                await asyncio.sleep(float(exc.response.headers.get("Retry-After", "1")))
            except (TimeoutError, httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.profile.max_retries:
                    self.last_error = str(exc)
                    raise
                await asyncio.sleep((2**attempt) * 0.1 + random.random() * 0.05)
        raise DomainError("market request exhausted retries")

    async def get_instrument(self, instrument_id: UUID) -> Instrument:
        now = datetime.now(UTC)
        cached = self.instrument_cache.get(instrument_id, now)
        if cached is not None:
            return cached
        payload = await self._get(self.profile.instrument_path.format(instrument_id=instrument_id))
        instrument = self.mapper.instrument(payload)
        self.instrument_cache.put(instrument_id, instrument, now)
        return instrument

    async def get_option_chain(self, underlying_id: UUID) -> OptionChain:
        now = datetime.now(UTC)
        cached = self.chain_cache.get(underlying_id, now)
        if cached is not None:
            return cached
        payload = await self._get(self.profile.chain_path.format(underlying_id=underlying_id))
        chain = self.mapper.option_chain(payload)
        self.chain_cache.put(underlying_id, chain, now)
        return chain

    async def get_quote(self, instrument_id: UUID) -> Quote:
        now = datetime.now(UTC)
        cached = self.quote_cache.get(instrument_id, now)
        if cached is not None:
            return cached
        payload = await self._get(self.profile.quote_path.format(instrument_id=instrument_id))
        quote = self.mapper.quote(payload, now)
        self.quote_cache.put(instrument_id, quote, now)
        return quote

    async def snapshot(self) -> MarketSnapshot:
        payload = await self._get(self.profile.snapshot_path)
        return self.mapper.snapshot(payload, datetime.now(UTC))

    def stream(self) -> AsyncIterator[MarketSnapshot]:
        return self.stream_quotes(self.subscribed_instruments)

    async def health(self) -> dict[str, object]:
        return {
            "connected": self.last_error is None,
            "source": self.profile.name,
            "last_error": self.last_error,
        }

    async def stream_quotes(
        self, instrument_ids: tuple[UUID, ...]
    ) -> AsyncIterator[MarketSnapshot]:
        delay = 0.25
        expected_sequence: int | None = None
        while True:
            try:
                async with websockets.connect(
                    self.profile.websocket_url,
                    additional_headers=self.profile.headers,
                    open_timeout=self.profile.connect_timeout_seconds,
                    ping_interval=20,
                    ping_timeout=20,
                ) as socket:
                    await socket.send(json.dumps(self.mapper.subscription(instrument_ids)))
                    async for raw in socket:
                        payload = json.loads(raw)
                        snapshot = self.mapper.snapshot(payload, datetime.now(UTC))
                        if expected_sequence is not None and snapshot.sequence != expected_sequence:
                            recovered = await self.snapshot()
                            expected_sequence = recovered.sequence + 1
                            yield recovered
                            if snapshot.sequence <= recovered.sequence:
                                continue
                            if snapshot.sequence != expected_sequence:
                                raise DomainError(
                                    "provider sequence gap remained after REST resync"
                                )
                        expected_sequence = snapshot.sequence + 1
                        delay = 0.25
                        self.last_error = None
                        yield snapshot
            except (OSError, websockets.ConnectionClosed, DomainError) as exc:
                self.last_error = str(exc)
                await asyncio.sleep(delay + random.random() * delay / 4)
                delay = min(delay * 2, 30)
                expected_sequence = None
