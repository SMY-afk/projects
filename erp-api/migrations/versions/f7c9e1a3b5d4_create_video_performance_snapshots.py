"""create video performance snapshots

Revision ID: f7c9e1a3b5d4
Revises: f5a7b9c1d3e2
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f7c9e1a3b5d4"
down_revision: str | Sequence[str] | None = "f5a7b9c1d3e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tiktok_video_performance_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("platform_video_id", sa.String(128), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("account_type", sa.String(32), nullable=False),
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
        sa.CheckConstraint(
            "window_end > window_start",
            name="ck_tiktok_video_performance_window",
        ),
        sa.CheckConstraint(
            "account_type IN ('ALL', 'OFFICIAL_ACCOUNTS', "
            "'MARKETING_ACCOUNTS', 'AFFILIATE_ACCOUNTS')",
            name="ck_tiktok_video_performance_account_type",
        ),
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
        sa.ForeignKeyConstraint(
            ["shop_id", "platform_video_id"],
            [
                "tiktok_video_contents.shop_id",
                "tiktok_video_contents.platform_video_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sync_run_id",
            "platform_video_id",
            name="uq_tiktok_video_performance_run_video",
        ),
    )
    op.create_index(
        "ix_tiktok_video_performance_snapshots_tenant_id",
        "tiktok_video_performance_snapshots",
        ["tenant_id"],
    )
    op.create_index(
        "ix_tiktok_video_performance_window_lookup",
        "tiktok_video_performance_snapshots",
        [
            "tenant_id",
            "shop_id",
            "window_start",
            "window_end",
            "currency",
            "account_type",
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tiktok_video_performance_window_lookup",
        table_name="tiktok_video_performance_snapshots",
    )
    op.drop_index(
        "ix_tiktok_video_performance_snapshots_tenant_id",
        table_name="tiktok_video_performance_snapshots",
    )
    op.drop_table("tiktok_video_performance_snapshots")
