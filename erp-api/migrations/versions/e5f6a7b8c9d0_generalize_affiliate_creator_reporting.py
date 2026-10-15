"""generalize affiliate creator reporting

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FACT_BIGINT_COLUMNS = (
    "affiliate_gmv_minor",
    "affiliate_live_gmv_minor",
    "affiliate_video_gmv_minor",
    "affiliate_showcase_gmv_minor",
    "items_sold",
    "estimated_commission_minor",
    "showcase_product_count",
    "affiliate_order_count",
    "product_impressions",
    "affiliate_live_count",
    "affiliate_video_count",
    "target_collaboration_gmv_minor",
    "target_collaboration_estimated_commission_minor",
    "open_collaboration_gmv_minor",
    "open_collaboration_estimated_commission_minor",
    "refunded_affiliate_gmv_minor",
    "refunded_affiliate_product_count",
)


def upgrade() -> None:
    _upgrade_creator_master()
    _upgrade_report_batches()
    _upgrade_report_facts()


def _upgrade_creator_master() -> None:
    op.add_column("affiliate_creators", sa.Column("avatar_url", sa.Text()))
    for name in ("source_identifiers", "extensions"):
        op.add_column(
            "affiliate_creators",
            sa.Column(
                name,
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )
    op.execute("UPDATE affiliate_creators SET extensions = attributes")
    op.drop_column("affiliate_creators", "attributes")
    for name in ("source_identifiers", "extensions"):
        op.alter_column("affiliate_creators", name, server_default=None)


def _upgrade_report_batches() -> None:
    op.add_column("affiliate_creator_reports", sa.Column("shop_id", sa.Uuid()))
    op.add_column(
        "affiliate_creator_reports",
        sa.Column("window_start_utc", sa.DateTime(timezone=True)),
    )
    op.add_column(
        "affiliate_creator_reports",
        sa.Column("window_end_utc", sa.DateTime(timezone=True)),
    )
    op.alter_column(
        "affiliate_creator_reports", "timezone", new_column_name="shop_timezone"
    )
    op.add_column(
        "affiliate_creator_reports", sa.Column("source_fingerprint", sa.String(128))
    )
    op.add_column(
        "affiliate_creator_reports",
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "affiliate_creator_reports", sa.Column("expected_total", sa.Integer())
    )
    for name in (
        "pages_fetched",
        "records_received",
        "records_unique",
        "duplicate_count",
    ):
        op.add_column(
            "affiliate_creator_reports",
            sa.Column(name, sa.Integer(), nullable=False, server_default="0"),
        )
    op.add_column(
        "affiliate_creator_reports", sa.Column("completeness_reason", sa.String(64))
    )
    op.alter_column(
        "affiliate_creator_reports", "imported_at", new_column_name="captured_at"
    )
    op.execute(
        """
        UPDATE affiliate_creator_reports AS report
        SET shop_id = scope.shop_id,
            window_start_utc = report.period_start::timestamp
                AT TIME ZONE report.shop_timezone,
            window_end_utc = (report.period_end + 1)::timestamp
                AT TIME ZONE report.shop_timezone,
            source_fingerprint = report.source_file_sha256,
            source_metadata = jsonb_build_object('filename', report.source_filename),
            expected_total = report.row_count,
            pages_fetched = 1,
            records_received = report.row_count,
            records_unique = report.row_count,
            completeness_reason = 'complete'
        FROM affiliate_creator_report_shops AS scope
        WHERE scope.report_id = report.id
          AND scope.tenant_id = report.tenant_id
        """
    )
    for name in ("shop_id", "window_start_utc", "window_end_utc"):
        op.alter_column("affiliate_creator_reports", name, nullable=False)
    op.create_foreign_key(
        "fk_affiliate_creator_reports_shop_tenant",
        "affiliate_creator_reports",
        "shops",
        ["shop_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_affiliate_creator_reports_utc_window",
        "affiliate_creator_reports",
        "window_end_utc > window_start_utc",
    )
    op.create_index(
        "ix_affiliate_creator_reports_shop_window",
        "affiliate_creator_reports",
        ["tenant_id", "shop_id", "window_start_utc", "window_end_utc"],
    )
    op.drop_constraint(
        "uq_affiliate_creator_reports_file_query",
        "affiliate_creator_reports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_affiliate_creator_reports_source_query",
        "affiliate_creator_reports",
        ["tenant_id", "source_fingerprint", "query_fingerprint"],
    )
    for name in ("source_filename", "source_file_sha256", "row_count"):
        op.drop_column("affiliate_creator_reports", name)
    op.drop_table("affiliate_creator_report_shops")
    for name in (
        "source_metadata",
        "pages_fetched",
        "records_received",
        "records_unique",
        "duplicate_count",
    ):
        op.alter_column("affiliate_creator_reports", name, server_default=None)


def _upgrade_report_facts() -> None:
    op.add_column(
        "affiliate_creator_metrics",
        sa.Column(
            "extensions",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        """
        UPDATE affiliate_creator_metrics
        SET extensions = jsonb_build_object(
            'excel', jsonb_build_object('sourceRowNumber', source_row_number)
        )
        """
    )
    op.drop_column("affiliate_creator_metrics", "source_row_number")
    op.alter_column("affiliate_creator_metrics", "extensions", server_default=None)
    for name in _FACT_BIGINT_COLUMNS:
        op.alter_column(
            "affiliate_creator_metrics",
            name,
            existing_type=sa.BigInteger(),
            nullable=True,
        )
    op.alter_column(
        "affiliate_creator_metrics",
        "average_affiliate_customers",
        existing_type=sa.Numeric(20, 4),
        nullable=True,
    )
    op.alter_column(
        "affiliate_creator_metrics",
        "click_through_rate",
        existing_type=sa.Numeric(12, 8),
        type_=sa.String(32),
        postgresql_using="click_through_rate::text",
    )


def downgrade() -> None:
    raise RuntimeError(
        "This migration cannot be safely downgraded after non-Excel sources are stored."
    )
