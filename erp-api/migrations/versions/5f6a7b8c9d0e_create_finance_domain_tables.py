"""create finance domain tables

Revision ID: 5f6a7b8c9d0e
Revises: 4e5f6a7b8c9d
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5f6a7b8c9d0e"
down_revision: str | Sequence[str] | None = "4e5f6a7b8c9d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE")


def _shop_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["shop_id", "tenant_id"],
        ["shops.id", "shops.tenant_id"],
        ondelete="CASCADE",
    )


def _indexes(table: str, definitions: tuple[tuple[str, tuple[str, ...]], ...]) -> None:
    op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    for name, columns in definitions:
        op.create_index(name, table, list(columns))


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_order_lines_id_tenant", "order_lines", ["id", "tenant_id"]
    )
    _create_statements()
    _create_payments()
    _create_payment_statements()
    _create_transactions()
    _create_components()
    _create_sync_runs()
    _create_sync_cursors()


def _create_statements() -> None:
    op.create_table(
        "finance_statements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform_statement_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("payment_status", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("revenue_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("fee_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("settlement_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("statement_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("statement_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("platform_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("platform_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _shop_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_finance_statements_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "platform_statement_id",
            name="uq_finance_statements_tenant_shop_platform",
        ),
    )
    _indexes(
        "finance_statements",
        (
            (
                "ix_finance_statements_filter",
                (
                    "tenant_id",
                    "shop_id",
                    "statement_end_at",
                    "currency",
                    "payment_status",
                ),
            ),
        ),
    )


def _create_payments() -> None:
    op.create_table(
        "finance_payments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform_payment_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("payment_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("initiated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("bank_reference_masked", sa.String(128)),
        sa.Column("platform_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _shop_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_finance_payments_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "platform_payment_id",
            name="uq_finance_payments_tenant_shop_platform",
        ),
    )
    _indexes(
        "finance_payments",
        (
            (
                "ix_finance_payments_filter",
                ("tenant_id", "shop_id", "paid_at", "currency", "status"),
            ),
        ),
    )


def _create_payment_statements() -> None:
    op.create_table(
        "finance_payment_statements",
        sa.Column("payment_id", sa.Uuid(), nullable=False),
        sa.Column("statement_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["payment_id", "tenant_id"],
            ["finance_payments.id", "finance_payments.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["statement_id", "tenant_id"],
            ["finance_statements.id", "finance_statements.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "payment_id", "statement_id"),
    )
    _indexes(
        "finance_payment_statements",
        (("ix_finance_payment_statements_statement", ("tenant_id", "statement_id")),),
    )


def _create_transactions() -> None:
    op.create_table(
        "finance_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("source_record_key", sa.String(256), nullable=False),
        sa.Column("platform_transaction_id", sa.String(128)),
        sa.Column("statement_id", sa.Uuid()),
        sa.Column("order_id", sa.Uuid()),
        sa.Column("platform_order_id", sa.String(128)),
        sa.Column("transaction_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("is_estimated", sa.Boolean(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("revenue_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("refund_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("shipping_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("fee_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("adjustment_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("settlement_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("platform_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "synced_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("data_completeness", sa.String(32), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _shop_fk(),
        sa.ForeignKeyConstraint(
            ["statement_id", "tenant_id"],
            ["finance_statements.id", "finance_statements.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_finance_transactions_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "source_record_key",
            name="uq_finance_transactions_tenant_shop_source",
        ),
    )
    _indexes(
        "finance_transactions",
        (
            (
                "ix_finance_transactions_filter",
                ("tenant_id", "shop_id", "occurred_at", "currency", "status"),
            ),
            ("ix_finance_transactions_statement", ("tenant_id", "statement_id")),
            ("ix_finance_transactions_order", ("tenant_id", "order_id")),
            (
                "ix_finance_transactions_platform_order",
                ("tenant_id", "shop_id", "platform_order_id"),
            ),
        ),
    )


def _create_components() -> None:
    op.create_table(
        "finance_transaction_components",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("transaction_id", sa.Uuid(), nullable=False),
        sa.Column("component_code", sa.String(128), nullable=False),
        sa.Column("component_category", sa.String(32), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("platform_sku_id", sa.String(128)),
        sa.Column("order_line_id", sa.Uuid()),
        sa.Column("description", sa.Text()),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        sa.ForeignKeyConstraint(
            ["transaction_id", "tenant_id"],
            ["finance_transactions.id", "finance_transactions.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_line_id", "tenant_id"],
            ["order_lines.id", "order_lines.tenant_id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "finance_transaction_components",
        (
            (
                "ix_finance_components_transaction",
                ("tenant_id", "transaction_id", "component_category"),
            ),
            ("ix_finance_components_code", ("tenant_id", "component_code")),
            ("ix_finance_components_platform_sku", ("tenant_id", "platform_sku_id")),
        ),
    )


def _create_sync_runs() -> None:
    op.create_table(
        "finance_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("window_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("recovery_cursor", sa.Text()),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("written_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("discrepancy_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_summary", sa.Text()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _shop_fk(),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'dead_letter', 'cancelled')",
            name="ck_finance_sync_runs_status",
        ),
        sa.CheckConstraint(
            "window_to > window_from", name="ck_finance_sync_runs_window"
        ),
        sa.CheckConstraint(
            "fetched_count >= 0 AND written_count >= 0 AND skipped_count >= 0 AND failed_count >= 0 AND discrepancy_count >= 0",
            name="ck_finance_sync_runs_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    _indexes(
        "finance_sync_runs",
        (
            (
                "ix_finance_sync_runs_window",
                (
                    "tenant_id",
                    "shop_id",
                    "entity_type",
                    "window_from",
                    "window_to",
                    "status",
                ),
            ),
            (
                "ix_finance_sync_runs_status_started",
                ("tenant_id", "status", "started_at"),
            ),
        ),
    )


def _create_sync_cursors() -> None:
    op.create_table(
        "finance_sync_cursors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("recovery_cursor", sa.Text()),
        sa.Column("committed_cursor", sa.Text()),
        sa.Column("last_successful_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        _tenant_fk(),
        _shop_fk(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "entity_type",
            name="uq_finance_sync_cursors_tenant_shop_entity",
        ),
    )
    _indexes(
        "finance_sync_cursors",
        (
            (
                "ix_finance_sync_cursors_freshness",
                ("tenant_id", "shop_id", "last_successful_at"),
            ),
        ),
    )


def downgrade() -> None:
    for table in (
        "finance_sync_cursors",
        "finance_sync_runs",
        "finance_transaction_components",
        "finance_transactions",
        "finance_payment_statements",
        "finance_payments",
        "finance_statements",
    ):
        op.drop_table(table)
    op.drop_constraint("uq_order_lines_id_tenant", "order_lines", type_="unique")
