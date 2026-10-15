"""add analytics job state and quality alerts

Revision ID: d0e3f4a5b6c7
Revises: c9d2e3f4a5b6
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d0e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c9d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analytics_sync_runs",
        sa.Column("job_id", sa.String(160), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "analytics_sync_runs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("analytics_sync_runs", "job_id", server_default=None)
    op.alter_column("analytics_sync_runs", "attempt_count", server_default=None)
    op.create_index("ix_analytics_sync_runs_job_id", "analytics_sync_runs", ["job_id"])
    op.create_check_constraint(
        "ck_analytics_sync_runs_status",
        "analytics_sync_runs",
        "status IN ('queued', 'running', 'retry_wait', 'succeeded', 'failed', 'dead_letter', 'cancelled')",
    )
    op.create_table(
        "analytics_quality_alerts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("resource_type", sa.String(16), nullable=False),
        sa.Column("category", sa.String(48), nullable=False),
        sa.Column("platform_external_id", sa.String(128)),
        sa.Column("details", postgresql.JSONB(), nullable=False),
        sa.Column(
            "detected_at",
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
        sa.ForeignKeyConstraint(
            ["sync_run_id", "tenant_id"],
            ["analytics_sync_runs.id", "analytics_sync_runs.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analytics_quality_alerts_shop_id", "analytics_quality_alerts", ["shop_id"]
    )
    op.create_index(
        "ix_analytics_quality_alerts_sync_run_id",
        "analytics_quality_alerts",
        ["sync_run_id"],
    )
    op.create_index(
        "ix_analytics_quality_alerts_tenant_id",
        "analytics_quality_alerts",
        ["tenant_id"],
    )
    op.create_index(
        "ix_analytics_quality_alerts_shop_category_detected",
        "analytics_quality_alerts",
        ["shop_id", "category", "detected_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analytics_quality_alerts_shop_category_detected",
        table_name="analytics_quality_alerts",
    )
    op.drop_index(
        "ix_analytics_quality_alerts_tenant_id", table_name="analytics_quality_alerts"
    )
    op.drop_index(
        "ix_analytics_quality_alerts_sync_run_id", table_name="analytics_quality_alerts"
    )
    op.drop_index(
        "ix_analytics_quality_alerts_shop_id", table_name="analytics_quality_alerts"
    )
    op.drop_table("analytics_quality_alerts")
    op.drop_constraint(
        "ck_analytics_sync_runs_status", "analytics_sync_runs", type_="check"
    )
    op.drop_index("ix_analytics_sync_runs_job_id", table_name="analytics_sync_runs")
    op.drop_column("analytics_sync_runs", "attempt_count")
    op.drop_column("analytics_sync_runs", "job_id")
