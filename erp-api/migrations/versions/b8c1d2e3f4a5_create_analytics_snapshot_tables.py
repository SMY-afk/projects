"""create analytics snapshot tables

Revision ID: b8c1d2e3f4a5
Revises: b2c4d6e8f102
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b8c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "b2c4d6e8f102"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analytics_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("metric_set", sa.String(64), nullable=False),
        sa.Column("granularity", sa.String(8), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("platform_request_id", sa.String(128)),
        sa.Column(
            "captured_at",
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
            "shop_id",
            "metric_set",
            "granularity",
            "window_start",
            "window_end",
            "currency",
            name="uq_analytics_snapshots_shop_metric_window_currency",
        ),
    )
    op.create_index(
        "ix_analytics_snapshots_shop_id", "analytics_snapshots", ["shop_id"]
    )
    op.create_index(
        "ix_analytics_snapshots_tenant_id", "analytics_snapshots", ["tenant_id"]
    )
    op.create_index(
        "ix_analytics_snapshots_shop_metric_granularity_start",
        "analytics_snapshots",
        ["shop_id", "metric_set", "granularity", "window_start"],
    )
    _create_content_table(
        "tiktok_video_contents",
        "platform_video_id",
        "uq_tiktok_video_contents_shop_platform_video",
    )
    _create_content_table(
        "tiktok_live_sessions",
        "platform_live_id",
        "uq_tiktok_live_sessions_shop_platform_live",
    )


def downgrade() -> None:
    for table_name in ("tiktok_live_sessions", "tiktok_video_contents"):
        op.drop_index(f"ix_{table_name}_tenant_id", table_name=table_name)
        op.drop_index(f"ix_{table_name}_shop_id", table_name=table_name)
        op.drop_table(table_name)
    op.drop_index(
        "ix_analytics_snapshots_shop_metric_granularity_start",
        table_name="analytics_snapshots",
    )
    op.drop_index("ix_analytics_snapshots_tenant_id", table_name="analytics_snapshots")
    op.drop_index("ix_analytics_snapshots_shop_id", table_name="analytics_snapshots")
    op.drop_table("analytics_snapshots")


def _create_content_table(
    table_name: str, external_id_column: str, unique_name: str
) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column(external_id_column, sa.String(128), nullable=False),
        sa.Column("fields", postgresql.JSONB(), nullable=False),
        sa.Column("source_status", sa.String(128)),
        sa.Column("status", sa.String(32)),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("platform_request_id", sa.String(128)),
        sa.Column(
            "observed_at",
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
        sa.UniqueConstraint("shop_id", external_id_column, name=unique_name),
    )
    op.create_index(f"ix_{table_name}_shop_id", table_name, ["shop_id"])
    op.create_index(f"ix_{table_name}_tenant_id", table_name, ["tenant_id"])
