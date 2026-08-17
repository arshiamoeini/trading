from __future__ import annotations

import asyncio
import hashlib
import json
import random
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID, uuid4, uuid5
from zoneinfo import ZoneInfo

import httpx

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

from .base import (
    InstrumentIdentifier,
    MarketBar,
    OptionChain,
    OrderBookLevel,
    OrderBookSnapshot,
)

TSETMC_NAMESPACE = UUID("d742b61a-ec4e-4bb0-9f0f-f740f07c8a76")
MARKET_IDS = {"TSE": 1, "IFB": 2}


@dataclass(frozen=True, slots=True)
class TsetmcConfig:
    base_url: str = "https://cdn.tsetmc.com"
    markets: tuple[str, ...] = ("TSE", "IFB")
    poll_seconds: float = 5.0
    timeout_seconds: float = 10.0
    max_retries: int = 3
    depth_watchlist: tuple[str, ...] = ()
    depth_concurrency: int = 4
    timezone: str = "Asia/Tehran"

    def __post_init__(self) -> None:
        if self.poll_seconds <= 0 or self.timeout_seconds <= 0:
            raise ValueError("poll and timeout values must be positive")
        if self.max_retries < 0 or self.depth_concurrency <= 0:
            raise ValueError("retry and concurrency values are invalid")
        unknown = set(self.markets) - MARKET_IDS.keys()
        if unknown:
            raise ValueError(f"unsupported TSETMC markets: {sorted(unknown)}")


RequestJson = Callable[[str], Awaitable[Mapping[str, Any]]]


def normalize_symbol(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    return " ".join(text.replace("ي", "ی").replace("ك", "ک").replace("\u200c", " ").split())


def instrument_uuid(provider_code: object) -> UUID:
    return uuid5(TSETMC_NAMESPACE, f"tsetmc:{provider_code}")


def _decimal(value: object, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise DomainError(f"invalid TSETMC {field}") from exc


def _date(value: object, field: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y%m%d").date()
    except ValueError as exc:
        raise DomainError(f"invalid TSETMC {field}") from exc


class TsetmcMarketDataProvider:
    source = "tsetmc"

    def __init__(
        self,
        dataset_id: UUID,
        config: TsetmcConfig | None = None,
        *,
        request_json: RequestJson | None = None,
    ) -> None:
        self.dataset_id = dataset_id
        self.config = config or TsetmcConfig()
        self.request_json = request_json
        self._client: httpx.AsyncClient | None = None
        self._instruments: dict[UUID, Instrument] = {}
        self._metadata: dict[UUID, InstrumentIdentifier] = {}
        self._codes: dict[str, UUID] = {}
        self._chains: dict[UUID, OptionChain] = {}
        self._quotes: dict[UUID, Quote] = {}
        self._snapshot: MarketSnapshot | None = None
        self._sequence = 0
        self._last_success: datetime | None = None
        self._last_error: str | None = None
        self._venue_status: dict[str, str] = {}
        self._invalid_quote_count = 0
        self._instrument_content_hash = ""

    @property
    def instruments(self) -> Mapping[UUID, Instrument]:
        return self._instruments

    @property
    def instrument_metadata(self) -> Mapping[UUID, InstrumentIdentifier]:
        return self._metadata

    @property
    def instrument_content_hash(self) -> str:
        return self._instrument_content_hash

    def set_dataset_id(self, dataset_id: UUID) -> None:
        self.dataset_id = dataset_id

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _request_once(self, path: str) -> Mapping[str, Any]:
        if self.request_json is not None:
            return await self.request_json(path)
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
                headers={"User-Agent": "option-platform/0.1"},
            )
        response = await self._client.get(path)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise DomainError("TSETMC response must be a JSON object")
        return payload

    async def _get(self, path: str) -> Mapping[str, Any]:
        for attempt in range(self.config.max_retries + 1):
            try:
                return await asyncio.wait_for(
                    self._request_once(path), timeout=self.config.timeout_seconds
                )
            except (TimeoutError, httpx.TimeoutException, httpx.NetworkError):
                if attempt >= self.config.max_retries:
                    raise
                await asyncio.sleep((2**attempt) * 0.1 + random.random() * 0.05)
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                if not retryable or attempt >= self.config.max_retries:
                    raise
                retry_after = float(exc.response.headers.get("Retry-After", "0"))
                await asyncio.sleep(max(retry_after, (2**attempt) * 0.1))
        raise DomainError(f"TSETMC request exhausted retries: {path}")

    async def refresh(self) -> MarketSnapshot:
        received_at = datetime.now(UTC)

        async def fetch(venue: str) -> tuple[str, Mapping[str, Any]]:
            market_id = MARKET_IDS[venue]
            payload = await self._get(f"/api/Instrument/GetInstrumentOptionMarketWatch/{market_id}")
            return venue, payload

        try:
            responses = await asyncio.gather(*(fetch(venue) for venue in self.config.markets))
            snapshot = self._map_market(responses, received_at)
        except Exception as exc:
            self._last_error = str(exc)
            raise
        self._snapshot = snapshot
        self._last_success = received_at
        self._last_error = None
        self._venue_status = {venue: "ok" for venue in self.config.markets}
        return snapshot

    def _map_market(
        self,
        responses: list[tuple[str, Mapping[str, Any]]],
        received_at: datetime,
    ) -> MarketSnapshot:
        self._sequence += 1
        instruments: dict[UUID, Instrument] = {}
        metadata: dict[UUID, InstrumentIdentifier] = {}
        contracts_by_underlying: dict[UUID, dict[UUID, OptionContract]] = {}
        quotes: dict[UUID, Quote] = {}
        invalid_quotes = 0

        for venue, payload in responses:
            rows = payload.get("instrumentOptMarketWatch")
            if not isinstance(rows, list):
                raise DomainError(f"TSETMC {venue} option-watch rows must be a list")
            for raw_row in rows:
                if not isinstance(raw_row, dict):
                    raise DomainError(f"TSETMC {venue} option row must be an object")
                underlying_code = str(raw_row["uaInsCode"])
                underlying_id = instrument_uuid(underlying_code)
                underlying = UnderlyingInstrument(
                    instrument_id=underlying_id,
                    symbol=normalize_symbol(raw_row["lval30_UA"]),
                    currency="IRR",
                    multiplier=Decimal("1"),
                    tick_size=Decimal("1"),
                )
                instruments[underlying_id] = underlying
                metadata[underlying_id] = InstrumentIdentifier(
                    "tsetmc", underlying_code, venue, raw_symbol=underlying.symbol
                )
                contracts_by_underlying.setdefault(underlying_id, {})

                for suffix, right in (("C", OptionRight.CALL), ("P", OptionRight.PUT)):
                    code = str(raw_row.get(f"insCode_{suffix}", "")).strip()
                    symbol = normalize_symbol(raw_row.get(f"lVal18AFC_{suffix}", ""))
                    if not code or not symbol or code == "0":
                        continue
                    contract_id = instrument_uuid(code)
                    contract = OptionContract(
                        instrument_id=contract_id,
                        symbol=symbol,
                        currency="IRR",
                        multiplier=_decimal(raw_row["contractSize"], "contract size"),
                        tick_size=Decimal("1"),
                        underlying_id=underlying_id,
                        expiry=_date(raw_row["endDate"], "expiry"),
                        strike=_decimal(raw_row["strikePrice"], "strike"),
                        right=right,
                        exercise_style=ExerciseStyle.EUROPEAN,
                        settlement=SettlementType.PHYSICAL,
                    )
                    instruments[contract_id] = contract
                    metadata[contract_id] = InstrumentIdentifier(
                        "tsetmc", code, venue, raw_symbol=symbol
                    )
                    contracts_by_underlying[underlying_id][contract_id] = contract
                    quote = self._map_quote(raw_row, suffix, contract_id, received_at, venue)
                    if quote is None:
                        invalid_quotes += 1
                    else:
                        quotes[contract_id] = quote

        chains = {
            underlying_id: OptionChain(
                underlying_id=underlying_id,
                as_of=received_at,
                contracts=tuple(
                    sorted(
                        contracts.values(),
                        key=lambda item: (item.expiry, item.strike, item.right.value),
                    )
                ),
            )
            for underlying_id, contracts in contracts_by_underlying.items()
        }
        chain_ids = tuple(
            sorted(
                (
                    contract.instrument_id
                    for chain in chains.values()
                    for contract in chain.contracts
                ),
                key=str,
            )
        )
        instrument_payload = [
            (
                str(instrument.instrument_id),
                instrument.symbol,
                str(instrument.multiplier),
                metadata[instrument.instrument_id].provider_instrument_id,
                metadata[instrument.instrument_id].venue,
                str(instrument.underlying_id) if isinstance(instrument, OptionContract) else None,
                instrument.expiry.isoformat() if isinstance(instrument, OptionContract) else None,
                str(instrument.strike) if isinstance(instrument, OptionContract) else None,
                instrument.right.value if isinstance(instrument, OptionContract) else None,
            )
            for instrument in sorted(instruments.values(), key=lambda item: str(item.instrument_id))
        ]
        instrument_hash = hashlib.sha256(
            json.dumps(instrument_payload, separators=(",", ":")).encode()
        ).hexdigest()
        fingerprint_payload = {
            "instruments": instrument_hash,
            "chain_ids": [str(value) for value in chain_ids],
            "quotes": [
                (
                    str(item.instrument_id),
                    str(item.bid),
                    str(item.ask),
                    None if item.bid_size is None else str(item.bid_size),
                    None if item.ask_size is None else str(item.ask_size),
                )
                for item in sorted(quotes.values(), key=lambda quote: str(quote.instrument_id))
            ],
        }
        fingerprint = hashlib.sha256(
            json.dumps(fingerprint_payload, separators=(",", ":")).encode()
        ).hexdigest()
        self._instruments = instruments
        self._metadata = metadata
        self._codes = {item.provider_instrument_id: key for key, item in metadata.items()}
        self._chains = chains
        self._quotes = quotes
        self._invalid_quote_count = invalid_quotes
        self._instrument_content_hash = instrument_hash
        return MarketSnapshot(
            snapshot_id=uuid4(),
            dataset_id=self.dataset_id,
            provider_timestamp=received_at,
            received_at=received_at,
            sequence=self._sequence,
            source=self.source,
            quotes=quotes,
            chain_instrument_ids=chain_ids,
            content_hash=fingerprint,
        )

    def _map_quote(
        self,
        row: Mapping[str, Any],
        suffix: str,
        instrument_id: UUID,
        received_at: datetime,
        venue: str,
    ) -> Quote | None:
        bid = _decimal(row.get(f"pMeDem_{suffix}", 0), "bid")
        ask = _decimal(row.get(f"pMeOf_{suffix}", 0), "ask")
        if bid < 0 or ask <= 0 or bid > ask:
            return None
        return Quote(
            instrument_id=instrument_id,
            bid=bid,
            ask=ask,
            bid_size=_decimal(row.get(f"qTitMeDem_{suffix}", 0), "bid size"),
            ask_size=_decimal(row.get(f"qTitMeOf_{suffix}", 0), "ask size"),
            provider_timestamp=received_at,
            received_at=received_at,
            sequence=self._sequence,
            source=f"{self.source}:{venue.lower()}",
        )

    async def _ensure_loaded(self) -> None:
        if self._snapshot is None:
            await self.refresh()

    async def get_instrument(self, instrument_id: UUID) -> Instrument:
        await self._ensure_loaded()
        try:
            return self._instruments[instrument_id]
        except KeyError as exc:
            raise DomainError("unknown TSETMC instrument") from exc

    async def get_option_chain(self, underlying_id: UUID) -> OptionChain:
        await self._ensure_loaded()
        try:
            return self._chains[underlying_id]
        except KeyError as exc:
            raise DomainError("unknown TSETMC underlying") from exc

    async def get_quote(self, instrument_id: UUID) -> Quote:
        await self._ensure_loaded()
        try:
            return self._quotes[instrument_id]
        except KeyError as exc:
            raise DomainError("TSETMC instrument has no valid two-sided quote") from exc

    async def snapshot(self) -> MarketSnapshot:
        return await self.refresh()

    async def stream(self) -> AsyncIterator[MarketSnapshot]:
        while True:
            try:
                yield await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._last_error = str(exc)
            await asyncio.sleep(self.config.poll_seconds)

    async def health(self) -> dict[str, object]:
        stale_seconds = (
            None
            if self._last_success is None
            else (datetime.now(UTC) - self._last_success).total_seconds()
        )
        return {
            "provider": self.source,
            "ok": self._last_error is None and self._last_success is not None,
            "last_success": self._last_success,
            "last_error": self._last_error,
            "stale_seconds": stale_seconds,
            "venues": dict(self._venue_status),
            "instruments": len(self._instruments),
            "quotes": len(self._quotes),
            "invalid_quotes": self._invalid_quote_count,
        }

    async def get_order_book(self, instrument_id: UUID, depth: int = 5) -> OrderBookSnapshot:
        if depth < 1 or depth > 5:
            raise ValueError("TSETMC depth must be between 1 and 5")
        await self._ensure_loaded()
        metadata = self._metadata.get(instrument_id)
        if metadata is None:
            raise DomainError("unknown TSETMC instrument")
        payload = await self._get(f"/api/BestLimits/{metadata.provider_instrument_id}")
        rows = payload.get("bestLimits")
        if not isinstance(rows, list):
            raise DomainError("TSETMC best limits must be a list")
        levels = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            level = int(raw["number"])
            if level > depth:
                continue
            levels.append(
                OrderBookLevel(
                    level=level,
                    bid=_decimal(raw.get("pMeDem", 0), "depth bid"),
                    bid_size=_decimal(raw.get("qTitMeDem", 0), "depth bid size"),
                    bid_orders=int(raw.get("zOrdMeDem", 0)),
                    ask=_decimal(raw.get("pMeOf", 0), "depth ask"),
                    ask_size=_decimal(raw.get("qTitMeOf", 0), "depth ask size"),
                    ask_orders=int(raw.get("zOrdMeOf", 0)),
                )
            )
        return OrderBookSnapshot(
            instrument_id=instrument_id,
            observed_at=datetime.now(UTC),
            source=f"{self.source}:{(metadata.venue or 'unknown').lower()}",
            levels=tuple(sorted(levels, key=lambda item: item.level)),
        )

    async def get_daily_bars(
        self,
        instrument_id: UUID,
        start: date | None = None,
        end: date | None = None,
    ) -> tuple[MarketBar, ...]:
        await self._ensure_loaded()
        metadata = self._metadata.get(instrument_id)
        if metadata is None:
            raise DomainError("unknown TSETMC instrument")
        payload = await self._get(
            f"/api/ClosingPrice/GetClosingPriceDailyList/{metadata.provider_instrument_id}/0"
        )
        rows = payload.get("closingPriceDaily")
        if not isinstance(rows, list):
            raise DomainError("TSETMC daily prices must be a list")
        timezone = ZoneInfo(self.config.timezone)
        bars: list[MarketBar] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            trading_date = _date(raw["dEven"], "trading date")
            if (start is not None and trading_date < start) or (
                end is not None and trading_date > end
            ):
                continue
            raw_time = str(raw.get("hEven", 0)).zfill(6)
            event_time = time(int(raw_time[:2]), int(raw_time[2:4]), int(raw_time[4:6]))
            event_at = datetime.combine(trading_date, event_time, timezone).astimezone(UTC)
            bars.append(
                MarketBar(
                    instrument_id=instrument_id,
                    trading_date=trading_date,
                    event_at=event_at,
                    open=_decimal(raw["priceFirst"], "daily open"),
                    high=_decimal(raw["priceMax"], "daily high"),
                    low=_decimal(raw["priceMin"], "daily low"),
                    close=_decimal(raw["pClosing"], "daily close"),
                    last=_decimal(raw["pDrCotVal"], "daily last"),
                    previous_close=_decimal(raw["priceYesterday"], "previous close"),
                    trades=_decimal(raw["zTotTran"], "daily trades"),
                    volume=_decimal(raw["qTotTran5J"], "daily volume"),
                    value=_decimal(raw["qTotCap"], "daily value"),
                    source=f"{self.source}:{(metadata.venue or 'unknown').lower()}",
                )
            )
        return tuple(sorted(bars, key=lambda item: item.trading_date))

    def instrument_id_for_code(self, provider_code: str) -> UUID | None:
        return self._codes.get(provider_code)
