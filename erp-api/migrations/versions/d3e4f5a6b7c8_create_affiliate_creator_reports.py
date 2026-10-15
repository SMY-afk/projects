"""create affiliate creator reports

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-25
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _tenant_column() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "affiliate_creators",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant_column(),
        sa.Column("username", sa.String(255), nullable=False),
        sa.Column("username_normalized", sa.String(255), nullable=False),
        sa.Column("creator_open_id", sa.String(128)),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("id", "tenant_id", name="uq_affiliate_creators_id_tenant"),
        sa.UniqueConstraint(
            "tenant_id",
            "username_normalized",
            name="uq_affiliate_creators_tenant_username",
        ),
        sa.UniqueConstraint(
            "tenant_id", "creator_open_id", name="uq_affiliate_creators_tenant_open_id"
        ),
    )
    op.create_index(
        "ix_affiliate_creators_tenant_id", "affiliate_creators", ["tenant_id"]
    )
    op.create_index(
        "ix_affiliate_creators_tenant_username",
        "affiliate_creators",
        ["tenant_id", "username_normalized"],
    )

    op.create_table(
        "affiliate_creator_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant_column(),
        sa.Column("scope_label", sa.String(255), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_filename", sa.Text(), nullable=False),
        sa.Column("source_file_sha256", sa.String(64), nullable=False),
        sa.Column("query_fingerprint", sa.String(64), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column(
            "imported_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_affiliate_creator_reports_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "query_fingerprint",
            "revision_no",
            name="uq_affiliate_creator_reports_query_revision",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "source_file_sha256",
            "query_fingerprint",
            name="uq_affiliate_creator_reports_file_query",
        ),
    )
    op.create_index(
        "ix_affiliate_creator_reports_tenant_id",
        "affiliate_creator_reports",
        ["tenant_id"],
    )
    op.create_index(
        "ix_affiliate_creator_reports_tenant_period",
        "affiliate_creator_reports",
        ["tenant_id", "period_start", "period_end"],
    )

    op.create_table(
        "affiliate_creator_report_shops",
        sa.Column("report_id", sa.Uuid(), primary_key=True),
        sa.Column("shop_id", sa.Uuid(), primary_key=True),
        _tenant_column(),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id"],
            ["affiliate_creator_reports.id", "affiliate_creator_reports.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_affiliate_creator_report_shops_tenant_id",
        "affiliate_creator_report_shops",
        ["tenant_id"],
    )

    metric_columns = [
        "affiliate_gmv_minor",
        "affiliate_live_gmv_minor",
        "affiliate_video_gmv_minor",
        "affiliate_showcase_gmv_minor",
        "affiliate_product_items_sold",
        "items_sold",
        "estimated_commission_minor",
        "estimated_flat_fee_minor",
        "average_order_amount_minor",
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
        "affiliate_follower_count",
    ]
    nullable_metrics = {
        "affiliate_product_items_sold",
        "estimated_flat_fee_minor",
        "average_order_amount_minor",
        "affiliate_follower_count",
    }
    op.create_table(
        "affiliate_creator_metrics",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant_column(),
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("source_row_number", sa.Integer(), nullable=False),
        *(
            sa.Column(name, sa.BigInteger(), nullable=name in nullable_metrics)
            for name in metric_columns[:11]
        ),
        sa.Column("click_through_rate", sa.Numeric(12, 8)),
        *(
            sa.Column(name, sa.BigInteger(), nullable=name in nullable_metrics)
            for name in metric_columns[11:12]
        ),
        sa.Column("average_affiliate_customers", sa.Numeric(20, 4), nullable=False),
        *(
            sa.Column(name, sa.BigInteger(), nullable=name in nullable_metrics)
            for name in metric_columns[12:]
        ),
        sa.ForeignKeyConstraint(
            ["report_id", "tenant_id"],
            ["affiliate_creator_reports.id", "affiliate_creator_reports.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["creator_id", "tenant_id"],
            ["affiliate_creators.id", "affiliate_creators.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "report_id",
            "creator_id",
            name="uq_affiliate_creator_metrics_report_creator",
        ),
    )
    op.create_index(
        "ix_affiliate_creator_metrics_tenant_id",
        "affiliate_creator_metrics",
        ["tenant_id"],
    )
    op.create_index(
        "ix_affiliate_creator_metrics_report_gmv",
        "affiliate_creator_metrics",
        ["tenant_id", "report_id", "affiliate_gmv_minor"],
    )

    permission_id = uuid4()
    op.execute(
        sa.text(
            "INSERT INTO permissions (id, code, name) VALUES (:id, 'affiliate-center:view', 'affiliate center') ON CONFLICT (code) DO UPDATE SET name = EXCLUDED.name"
        ).bindparams(sa.bindparam("id", value=permission_id, type_=sa.Uuid()))
    )
    op.execute(
        sa.text(
            "INSERT INTO role_permissions (role_id, permission_id) SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions WHERE roles.code = 'admin' AND permissions.code = 'affiliate-center:view' ON CONFLICT DO NOTHING"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM permissions WHERE code = 'affiliate-center:view'"))
    op.drop_table("affiliate_creator_metrics")
    op.drop_table("affiliate_creator_report_shops")
    op.drop_table("affiliate_creator_reports")
    op.drop_table("affiliate_creators")
