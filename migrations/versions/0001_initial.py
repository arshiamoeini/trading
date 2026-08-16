"""Initial option platform schema and disabled example strategy."""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from alembic import op
from sqlalchemy.dialects.postgresql import insert

from option_platform.infrastructure.models import (
    Base,
    InstrumentRow,
    MarketDatasetRow,
    MarketSnapshotRow,
    StrategyDefinitionRow,
    StrategyInstanceRow,
)

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

EXAMPLE_DEFINITION_ID = UUID("00000000-0000-0000-0000-000000000101")
EXAMPLE_INSTANCE_ID = UUID("00000000-0000-0000-0000-000000000102")
UNDERLYING_ID = UUID("00000000-0000-0000-0000-000000000201")
LONG_OPTION_ID = UUID("00000000-0000-0000-0000-000000000202")
SHORT_OPTION_ID = UUID("00000000-0000-0000-0000-000000000203")
DATASET_ID = UUID("00000000-0000-0000-0000-000000000301")
SNAPSHOT_ID = UUID("00000000-0000-0000-0000-000000000302")
SNAPSHOT_AT = datetime(2026, 1, 2, 15, 0, tzinfo=UTC)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    for values in (
        {
            "id": UNDERLYING_ID,
            "kind": "UNDERLYING",
            "symbol": "EXAMPLE",
            "currency": "USD",
            "multiplier": "1",
            "tick_size": "0.01",
        },
        {
            "id": LONG_OPTION_ID,
            "kind": "OPTION",
            "symbol": "EXAMPLE-202603-C90",
            "currency": "USD",
            "multiplier": "100",
            "tick_size": "0.01",
            "underlying_id": UNDERLYING_ID,
            "expiry": date(2026, 3, 20),
            "strike": "90",
            "option_right": "CALL",
            "exercise_style": "AMERICAN",
            "settlement": "PHYSICAL",
        },
        {
            "id": SHORT_OPTION_ID,
            "kind": "OPTION",
            "symbol": "EXAMPLE-202603-C100",
            "currency": "USD",
            "multiplier": "100",
            "tick_size": "0.01",
            "underlying_id": UNDERLYING_ID,
            "expiry": date(2026, 3, 20),
            "strike": "100",
            "option_right": "CALL",
            "exercise_style": "AMERICAN",
            "settlement": "PHYSICAL",
        },
    ):
        statement = insert(InstrumentRow.__table__).values(**values)
        bind.execute(statement.on_conflict_do_nothing(index_elements=["id"]))
    dataset = insert(MarketDatasetRow.__table__).values(
        id=DATASET_ID,
        version="seed-v1",
        content_hash="seed-v1-recorded-dataset",
        source="seed-fixture",
        point_in_time_complete=False,
        created_at=SNAPSHOT_AT,
    )
    bind.execute(dataset.on_conflict_do_nothing(index_elements=["id"]))
    quote_payloads = [
        {
            "instrument_id": str(LONG_OPTION_ID),
            "bid": "1.00",
            "ask": "1.10",
            "provider_timestamp": SNAPSHOT_AT.isoformat(),
            "received_at": SNAPSHOT_AT.isoformat(),
            "sequence": 1,
            "bid_size": "10",
            "ask_size": "10",
            "source": "seed-fixture",
        },
        {
            "instrument_id": str(SHORT_OPTION_ID),
            "bid": "0.40",
            "ask": "0.50",
            "provider_timestamp": SNAPSHOT_AT.isoformat(),
            "received_at": SNAPSHOT_AT.isoformat(),
            "sequence": 1,
            "bid_size": "10",
            "ask_size": "10",
            "source": "seed-fixture",
        },
    ]
    snapshot = insert(MarketSnapshotRow.__table__).values(
        id=SNAPSHOT_ID,
        dataset_id=DATASET_ID,
        provider_timestamp=SNAPSHOT_AT,
        received_at=SNAPSHOT_AT,
        sequence=1,
        source="seed-fixture",
        content_hash="seed-v1-snapshot",
        payload={
            "snapshot_id": str(SNAPSHOT_ID),
            "dataset_id": str(DATASET_ID),
            "provider_timestamp": SNAPSHOT_AT.isoformat(),
            "received_at": SNAPSHOT_AT.isoformat(),
            "sequence": 1,
            "source": "seed-fixture",
            "chain_instrument_ids": [str(LONG_OPTION_ID), str(SHORT_OPTION_ID)],
            "quotes": quote_payloads,
            "content_hash": "seed-v1-snapshot",
        },
    )
    bind.execute(snapshot.on_conflict_do_nothing(index_elements=["id"]))
    definition = insert(StrategyDefinitionRow.__table__).values(
        id=EXAMPLE_DEFINITION_ID,
        name="Example Vertical Spread",
        import_path="option_platform.strategies.example_vertical:VerticalSignalStrategy",
        version="1",
        default_config={
            "dataset_id": str(DATASET_ID),
            "long_instrument_id": str(LONG_OPTION_ID),
            "short_instrument_id": str(SHORT_OPTION_ID),
        },
    )
    bind.execute(definition.on_conflict_do_nothing(index_elements=["id"]))
    instance = insert(StrategyInstanceRow.__table__).values(
        id=EXAMPLE_INSTANCE_ID,
        definition_id=EXAMPLE_DEFINITION_ID,
        desired_state="STOPPED",
        actual_state="STOPPED",
        config={
            "dataset_id": str(DATASET_ID),
            "long_instrument_id": str(LONG_OPTION_ID),
            "short_instrument_id": str(SHORT_OPTION_ID),
            "zscore": "-2",
            "seed": 100,
            "initial_cash": "100000",
        },
        heartbeat_at=None,
        last_error=None,
        claimed_by=None,
    )
    bind.execute(instance.on_conflict_do_nothing(index_elements=["id"]))


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
