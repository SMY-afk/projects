"""add affiliate creator detail snapshots

Revision ID: 13d4e5f6a7b8
Revises: 12c3d4e5f6a7
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "13d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "12c3d4e5f6a7"
branch_labels = None
depends_on = None

_RESOURCE_CHECK = (
    "resource_type IN ('video', 'live', 'affiliate_creator', "
    "'affiliate_video', 'affiliate_creator_detail')"
)


def upgrade() -> None:
    for table in ("analytics_sync_runs", "analytics_sync_cursors"):
        op.drop_constraint(f"ck_{table}_resource_type", table, type_="check")
        op.create_check_constraint(f"ck_{table}_resource_type", table, _RESOURCE_CHECK)
    op.drop_constraint(
        "ck_analytics_quality_alerts_resource_type",
        "analytics_quality_alerts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_analytics_quality_alerts_resource_type",
        "analytics_quality_alerts",
        _RESOURCE_CHECK,
    )
    op.create_table(
        "affiliate_creator_detail_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("sync_run_id", sa.Uuid(), nullable=False),
        sa.Column("resource_kind", sa.String(24), nullable=False),
        sa.Column("query_fingerprint", sa.String(64), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("window_start_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end_utc", sa.DateTime(timezone=True), nullable=False),
        sa.Column("shop_timezone", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expected_total", sa.Integer()),
        sa.Column("pages_fetched", sa.Integer(), nullable=False),
        sa.Column("records_received", sa.Integer(), nullable=False),
        sa.Column("records_unique", sa.Integer(), nullable=False),
        sa.Column("completeness_reason", sa.String(64)),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id", "tenant_id", "shop_id"],
            [
                "affiliate_creators.id",
                "affiliate_creators.tenant_id",
                "affiliate_creators.shop_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sync_run_id", "tenant_id"],
            ["analytics_sync_runs.id", "analytics_sync_runs.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("id", "tenant_id", "shop_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "creator_id",
            "resource_kind",
            "query_fingerprint",
            "revision_no",
            name="uq_affiliate_creator_detail_revision",
        ),
        sa.CheckConstraint(
            "resource_kind IN ('video', 'live', 'product', 'product_card')",
            name="ck_affiliate_creator_detail_resource",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'complete', 'partial')",
            name="ck_affiliate_creator_detail_status",
        ),
        sa.CheckConstraint("window_end_utc > window_start_utc"),
    )
    op.create_index(
        "ix_affiliate_creator_detail_latest",
        "affiliate_creator_detail_reports",
        [
            "tenant_id",
            "shop_id",
            "creator_id",
            "resource_kind",
            "window_start_utc",
            "window_end_utc",
        ],
    )
    op.create_table(
        "affiliate_creator_detail_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("platform_content_id", sa.String(192), nullable=False),
        sa.Column("identity", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column("extensions", postgresql.JSONB(), nullable=False),
        sa.Column("source_request_id", sa.String(128)),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id", "shop_id"],
            [
                "affiliate_creator_detail_reports.id",
                "affiliate_creator_detail_reports.tenant_id",
                "affiliate_creator_detail_reports.shop_id",
            ],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "report_id",
            "platform_content_id",
            name="uq_affiliate_creator_detail_item",
        ),
    )
    op.create_index(
        "ix_affiliate_creator_detail_items_report",
        "affiliate_creator_detail_items",
        ["tenant_id", "shop_id", "report_id"],
    )


def downgrade() -> None:
    op.drop_table("affiliate_creator_detail_items")
    op.drop_table("affiliate_creator_detail_reports")
    previous = _RESOURCE_CHECK.replace(", 'affiliate_creator_detail'", "")
    for table in ("analytics_sync_runs", "analytics_sync_cursors"):
        op.drop_constraint(f"ck_{table}_resource_type", table, type_="check")
        op.create_check_constraint(f"ck_{table}_resource_type", table, previous)
    op.drop_constraint(
        "ck_analytics_quality_alerts_resource_type",
        "analytics_quality_alerts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_analytics_quality_alerts_resource_type",
        "analytics_quality_alerts",
        previous,
    )
