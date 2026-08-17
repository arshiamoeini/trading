"""Add generic market-data identifiers, bars, and order-book snapshots."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_tsetmc_market_data"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _columns(bind: sa.Connection, table: str) -> set[str]:
    return {item["name"] for item in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    dataset_columns = _columns(bind, "market_data_datasets")
    if "capture_date" not in dataset_columns:
        op.alter_column("market_data_datasets", "content_hash", nullable=True)
        op.add_column("market_data_datasets", sa.Column("capture_date", sa.Date(), nullable=True))
        op.add_column(
            "market_data_datasets",
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            "market_data_datasets",
            sa.Column("source_params", postgresql.JSONB(), nullable=False,
                      server_default=sa.text("'{}'::jsonb")),
        )
        op.create_index(
            "ix_market_data_datasets_capture_date", "market_data_datasets", ["capture_date"]
        )
        op.create_unique_constraint(
            "uq_dataset_capture", "market_data_datasets", ["source", "version", "capture_date"]
        )

    tables = set(sa.inspect(bind).get_table_names())
    if "instrument_identifiers" not in tables:
        op.create_table(
            "instrument_identifiers",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("instrument_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("provider", sa.String(32), nullable=False),
            sa.Column("provider_instrument_id", sa.String(64), nullable=False),
            sa.Column("venue", sa.String(32), nullable=True),
            sa.Column("raw_symbol", sa.String(128), nullable=True),
            sa.Column("isin", sa.String(32), nullable=True),
            sa.UniqueConstraint("provider", "provider_instrument_id",
                                name="uq_instrument_identifier_provider_id"),
        )
        for name, column in (
            ("instrument_id", "instrument_id"),
            ("provider", "provider"),
            ("venue", "venue"),
            ("isin", "isin"),
        ):
            op.create_index(f"ix_instrument_identifiers_{name}", "instrument_identifiers", [column])

    if "market_data_bars" not in tables:
        op.create_table(
            "market_data_bars",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("instrument_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("trading_date", sa.Date(), nullable=False),
            sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(128), nullable=False),
            sa.Column("timeframe", sa.String(16), nullable=False),
            sa.Column("open_price", sa.Numeric(30, 10), nullable=False),
            sa.Column("high_price", sa.Numeric(30, 10), nullable=False),
            sa.Column("low_price", sa.Numeric(30, 10), nullable=False),
            sa.Column("close_price", sa.Numeric(30, 10), nullable=False),
            sa.Column("last_price", sa.Numeric(30, 10), nullable=False),
            sa.Column("previous_close", sa.Numeric(30, 10), nullable=False),
            sa.Column("trades", sa.Numeric(30, 10), nullable=False),
            sa.Column("volume", sa.Numeric(30, 10), nullable=False),
            sa.Column("value", sa.Numeric(30, 10), nullable=False),
            sa.UniqueConstraint("source", "instrument_id", "timeframe", "trading_date",
                                name="uq_bar_source_instrument_timeframe_date"),
        )
        op.create_index("ix_market_data_bars_trading_date", "market_data_bars", ["trading_date"])

    if "market_data_order_books" not in tables:
        op.create_table(
            "market_data_order_books",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("instrument_id", postgresql.UUID(as_uuid=True),
                      sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("source", sa.String(128), nullable=False),
            sa.Column("payload", postgresql.JSONB(), nullable=False),
            sa.UniqueConstraint("instrument_id", "observed_at",
                                name="uq_order_book_instrument_observed"),
        )
        op.create_index("ix_market_data_order_books_observed_at", "market_data_order_books",
                        ["observed_at"])


def downgrade() -> None:
    op.drop_table("market_data_order_books")
    op.drop_table("market_data_bars")
    op.drop_table("instrument_identifiers")
    op.drop_constraint("uq_dataset_capture", "market_data_datasets", type_="unique")
    op.drop_index("ix_market_data_datasets_capture_date", table_name="market_data_datasets")
    op.drop_column("market_data_datasets", "source_params")
    op.drop_column("market_data_datasets", "completed_at")
    op.drop_column("market_data_datasets", "capture_date")
    op.alter_column("market_data_datasets", "content_hash", nullable=False)
