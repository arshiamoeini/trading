from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from option_platform.application.services import (
    BacktestQueueService,
    BacktestRequest,
    ConflictError,
    NotFoundError,
    StrategyControlService,
)
from option_platform.config import settings
from option_platform.infrastructure.database import create_engine, session_factory
from option_platform.infrastructure.repositories import QueryRepository, StrategyRepository

from .schemas import BacktestCreate, OrderView, PositionView, RunView, StrategyView


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.sessions = session_factory(engine)
    yield
    await engine.dispose()


app = FastAPI(title="Option Platform", version="0.1.0", lifespan=lifespan)


async def get_session() -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = app.state.sessions
    async with factory() as session:
        yield session


def translate_service_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(404, str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(409, str(exc))
    return HTTPException(500, "application service failure")


@app.get("/health")
async def health(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok", "database": "ok", "live_trading": False}


@app.get("/strategies", response_model=list[StrategyView])
async def strategies(session: AsyncSession = Depends(get_session)) -> Sequence[object]:
    return await StrategyRepository(session).list()


@app.get("/strategies/{instance_id}", response_model=StrategyView)
async def strategy(instance_id: UUID, session: AsyncSession = Depends(get_session)) -> object:
    row = await StrategyRepository(session).get(instance_id)
    if row is None:
        raise HTTPException(404, "strategy instance not found")
    return row


@app.post("/strategies/{instance_id}/start", status_code=202)
async def start_strategy(
    instance_id: UUID, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    try:
        await StrategyControlService(StrategyRepository(session)).start(instance_id)
    except (NotFoundError, ConflictError) as exc:
        raise translate_service_error(exc) from exc
    return {"status": "start_requested"}


@app.post("/strategies/{instance_id}/stop", status_code=202)
async def stop_strategy(
    instance_id: UUID, session: AsyncSession = Depends(get_session)
) -> dict[str, str]:
    try:
        await StrategyControlService(StrategyRepository(session)).stop(instance_id)
    except (NotFoundError, ConflictError) as exc:
        raise translate_service_error(exc) from exc
    return {"status": "stop_requested"}


@app.get("/orders", response_model=list[OrderView])
async def orders(session: AsyncSession = Depends(get_session)) -> Sequence[object]:
    return await QueryRepository(session).orders()


@app.get("/orders/{order_id}", response_model=OrderView)
async def order(order_id: UUID, session: AsyncSession = Depends(get_session)) -> object:
    row = await QueryRepository(session).order(order_id)
    if row is None:
        raise HTTPException(404, "order not found")
    return row


@app.get("/positions", response_model=list[PositionView])
async def positions(session: AsyncSession = Depends(get_session)) -> Sequence[object]:
    return await QueryRepository(session).positions()


@app.get("/monitoring/status")
async def monitoring(session: AsyncSession = Depends(get_session)) -> dict[str, object]:
    strategies = await StrategyRepository(session).list()
    orders = await QueryRepository(session).orders()
    return {
        "strategies": {
            row.actual_state: sum(item.actual_state == row.actual_state for item in strategies)
            for row in strategies
        },
        "open_orders": sum(row.state not in {"FILLED", "CANCELLED", "REJECTED"} for row in orders),
        "live_trading": False,
    }


@app.post("/backtests", response_model=RunView, status_code=202)
async def create_backtest(
    payload: BacktestCreate, session: AsyncSession = Depends(get_session)
) -> object:
    request = BacktestRequest(
        payload.dataset_id,
        payload.strategy_instance_id,
        payload.seed,
        payload.strategy_version,
        payload.configuration,
    )
    return await BacktestQueueService(QueryRepository(session)).enqueue(request)


@app.get("/runs", response_model=list[RunView])
async def runs(session: AsyncSession = Depends(get_session)) -> Sequence[object]:
    return await QueryRepository(session).runs()


@app.websocket("/events")
async def events(websocket: WebSocket) -> None:
    await websocket.accept()
    cursor = datetime.now(UTC)
    factory: async_sessionmaker[AsyncSession] = app.state.sessions
    try:
        while True:
            async with factory() as session:
                rows = await QueryRepository(session).events_after(cursor)
            for row in rows:
                cursor = max(cursor, row.occurred_at)
                await websocket.send_json(
                    {
                        "event_id": str(row.id),
                        "type": row.event_type,
                        "aggregate_id": str(row.aggregate_id),
                        "occurred_at": row.occurred_at.isoformat(),
                        "payload": row.payload,
                    }
                )
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    path = Path(__file__).with_name("dashboard.html")
    return path.read_text(encoding="utf-8")
