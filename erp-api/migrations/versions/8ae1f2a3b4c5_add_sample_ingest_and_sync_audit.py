"""add sample ingest and sync audit

Revision ID: 8ae1f2a3b4c5
Revises: 79d0e1f2a3b4
Create Date: 2026-09-09 19:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "8ae1f2a3b4c5"
down_revision: str | None = "79d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sample_ingest_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_identity", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expected_total", sa.Integer()),
        sa.Column("captured_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("page_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_hash", sa.String(64)),
        sa.Column("completeness_evidence", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_summary", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('official_api', 'hubstudio_cdp')",
            name="ck_sample_ingest_batches_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'partial', 'failed')",
            name="ck_sample_ingest_batches_status",
        ),
        sa.CheckConstraint(
            "expected_total IS NULL OR expected_total >= 0",
            name="ck_sample_ingest_batches_expected_total",
        ),
        sa.CheckConstraint(
            "captured_total >= 0 AND page_count >= 0",
            name="ck_sample_ingest_batches_counts",
        ),
        sa.CheckConstraint(
            "status <> 'complete' OR finished_at IS NOT NULL",
            name="ck_sample_ingest_batches_complete_finished",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_sample_ingest_batches_id_tenant"),
    )
    op.create_index(
        "ix_sample_ingest_batches_tenant_id", "sample_ingest_batches", ["tenant_id"]
    )
    op.create_index(
        "ix_sample_ingest_batches_shop_source_started",
        "sample_ingest_batches",
        ["tenant_id", "shop_id", "source_type", "started_at"],
    )

    op.create_table(
        "sample_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sync_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("pages_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_read", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("feishu_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("feishu_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.Column("error_summary", sa.Text()),
        sa.Column("platform_request_ids", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("source_batch_ids", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "sync_type IN ('source_to_postgres', 'postgres_to_feishu', "
            "'feishu_to_postgres', 'reconciliation')",
            name="ck_sample_sync_runs_sync_type",
        ),
        sa.CheckConstraint(
            "source_type IN ('official_api', 'hubstudio_cdp', 'postgresql', 'feishu')",
            name="ck_sample_sync_runs_source_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed')",
            name="ck_sample_sync_runs_status",
        ),
        sa.CheckConstraint(
            "pages_read >= 0 AND records_read >= 0 AND records_created >= 0 "
            "AND records_updated >= 0 AND feishu_created >= 0 "
            "AND feishu_updated >= 0",
            name="ck_sample_sync_runs_counts",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "tenant_id", name="uq_sample_sync_runs_id_tenant"),
    )
    op.create_index("ix_sample_sync_runs_tenant_id", "sample_sync_runs", ["tenant_id"])
    op.create_index(
        "ix_sample_sync_runs_shop_status_started",
        "sample_sync_runs",
        ["tenant_id", "shop_id", "status", "started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sample_sync_runs_shop_status_started", table_name="sample_sync_runs"
    )
    op.drop_index("ix_sample_sync_runs_tenant_id", table_name="sample_sync_runs")
    op.drop_table("sample_sync_runs")
    op.drop_index(
        "ix_sample_ingest_batches_shop_source_started",
        table_name="sample_ingest_batches",
    )
    op.drop_index(
        "ix_sample_ingest_batches_tenant_id", table_name="sample_ingest_batches"
    )
    op.drop_table("sample_ingest_batches")
