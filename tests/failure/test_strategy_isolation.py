from __future__ import annotations

import asyncio

import pytest

pytestmark = pytest.mark.failure


async def test_one_task_failure_does_not_cancel_another() -> None:
    completed = asyncio.Event()

    async def broken() -> None:
        raise RuntimeError("strategy failed")

    async def healthy() -> None:
        await asyncio.sleep(0)
        completed.set()

    results = await asyncio.gather(broken(), healthy(), return_exceptions=True)
    assert isinstance(results[0], RuntimeError)
    assert completed.is_set()
