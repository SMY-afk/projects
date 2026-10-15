"""create analytics sync audit tables

Revision ID: c9d2e3f4a5b6
Revises: b8c1d2e3f4a5
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c9d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b8c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("start_cursor", sa.Text()),
        sa.Column("recovery_cursor", sa.Text()),
        sa.Column("fetched_count", sa.Integer(), nullable=False),
        sa.Column("persisted_count", sa.Integer(), nullable=False),
        sa.Column("platform_request_id", sa.String(128)),
        sa.Column("last_source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("error_category", sa.String(32)),
        sa.Column("error_summary", sa.Text()),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_analytics_sync_runs_id_tenant"),
    )
    op.create_index(
        "ix_analytics_sync_runs_shop_id", "analytics_sync_runs", ["shop_id"]
    )
    op.create_index(
        "ix_analytics_sync_runs_resource_type", "analytics_sync_runs", ["resource_type"]
    )
    op.create_index("ix_analytics_sync_runs_status", "analytics_sync_runs", ["status"])
    op.create_index(
        "ix_analytics_sync_runs_tenant_id", "analytics_sync_runs", ["tenant_id"]
    )
    op.create_table(
        "analytics_sync_cursors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("committed_cursor", sa.Text()),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("fresh_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "shop_id", "resource_type", name="uq_analytics_sync_cursors_shop_resource"
        ),
    )
    op.create_index(
        "ix_analytics_sync_cursors_shop_id", "analytics_sync_cursors", ["shop_id"]
    )
    op.create_index(
        "ix_analytics_sync_cursors_tenant_id", "analytics_sync_cursors", ["tenant_id"]
    )
    op.create_table(
        "analytics_raw_payloads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("payload_kind", sa.String(32), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("platform_request_id", sa.String(128)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id", "tenant_id"],
            ["analytics_sync_runs.id", "analytics_sync_runs.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_raw_payloads_shop_id", "analytics_raw_payloads", ["shop_id"]
    )
    op.create_index(
        "ix_analytics_raw_payloads_sync_run_id",
        "analytics_raw_payloads",
        ["sync_run_id"],
    )
    op.create_index(
        "ix_analytics_raw_payloads_tenant_id", "analytics_raw_payloads", ["tenant_id"]
    )
    op.create_index(
        "ix_analytics_raw_payloads_expires_at", "analytics_raw_payloads", ["expires_at"]
    )


def downgrade() -> None:
    for index in (
        "ix_analytics_raw_payloads_expires_at",
        "ix_analytics_raw_payloads_tenant_id",
        "ix_analytics_raw_payloads_sync_run_id",
        "ix_analytics_raw_payloads_shop_id",
    ):
        op.drop_index(index, table_name="analytics_raw_payloads")
    op.drop_table("analytics_raw_payloads")
    for index in (
        "ix_analytics_sync_cursors_tenant_id",
        "ix_analytics_sync_cursors_shop_id",
    ):
        op.drop_index(index, table_name="analytics_sync_cursors")
    op.drop_table("analytics_sync_cursors")
    for index in (
        "ix_analytics_sync_runs_tenant_id",
        "ix_analytics_sync_runs_status",
        "ix_analytics_sync_runs_resource_type",
        "ix_analytics_sync_runs_shop_id",
    ):
        op.drop_index(index, table_name="analytics_sync_runs")
    op.drop_table("analytics_sync_runs")
