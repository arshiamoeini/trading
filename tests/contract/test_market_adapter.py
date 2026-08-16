from __future__ import annotations

from decimal import Decimal
from uuid import UUID

import pytest

from option_platform.domain.errors import DomainError
from option_platform.market_data.base import MarketDataProvider
from option_platform.market_data.external import (
    ExternalApiAdapter,
    JsonFieldMapper,
    ProviderProfile,
)

pytestmark = pytest.mark.contract


def profile() -> ProviderProfile:
    return ProviderProfile(
        "fixture-vendor",
        "https://market.invalid",
        "wss://market.invalid/stream",
        requests_per_second=Decimal("1000"),
        max_retries=1,
    )


async def test_external_adapter_maps_and_caches_without_live_network(at) -> None:
    calls: list[str] = []

    async def request(path: str):
        calls.append(path)
        if path.startswith("/instruments"):
            return {
                "kind": "UNDERLYING",
                "instrument_id": str(UUID(int=1)),
                "symbol": "XYZ",
            }
        if path.startswith("/chains"):
            return {
                "underlying_id": str(UUID(int=1)),
                "as_of": at.isoformat(),
                "contracts": [
                    {
                        "kind": "OPTION",
                        "instrument_id": str(UUID(int=2)),
                        "symbol": "XYZ-C100",
                        "underlying_id": str(UUID(int=1)),
                        "expiry": "2026-03-20",
                        "strike": "100",
                        "right": "CALL",
                    }
                ],
            }
        return {
            "instrument_id": str(UUID(int=1)),
            "bid": "99",
            "ask": "101",
            "timestamp": at.isoformat(),
            "sequence": 1,
        }

    adapter = ExternalApiAdapter(
        profile(), JsonFieldMapper("fixture-vendor", UUID(int=20)), request_once=request
    )
    provider: MarketDataProvider = adapter
    assert (await provider.get_instrument(UUID(int=1))).symbol == "XYZ"
    assert len((await provider.get_option_chain(UUID(int=1))).contracts) == 1
    assert (await provider.get_quote(UUID(int=1))).midpoint == Decimal("100")
    await provider.get_quote(UUID(int=1))
    assert calls.count(f"/quotes/{UUID(int=1)}") == 1


async def test_external_adapter_retries_timeout(at) -> None:
    attempts = 0

    async def request(path: str):
        nonlocal attempts
        del path
        attempts += 1
        if attempts == 1:
            raise TimeoutError
        return {
            "instrument_id": str(UUID(int=1)),
            "bid": "1",
            "ask": "2",
            "timestamp": at.isoformat(),
            "sequence": 1,
        }

    adapter = ExternalApiAdapter(
        profile(), JsonFieldMapper("fixture-vendor", UUID(int=20)), request_once=request
    )
    assert (await adapter.get_quote(UUID(int=1))).bid == Decimal("1")
    assert attempts == 2


def test_mapper_rejects_bad_vendor_quote(at) -> None:
    mapper = JsonFieldMapper("fixture-vendor", UUID(int=20))
    with pytest.raises(DomainError):
        mapper.quote(
            {
                "instrument_id": str(UUID(int=1)),
                "bid": "3",
                "ask": "2",
                "timestamp": at.isoformat(),
                "sequence": 1,
            },
            at,
        )
