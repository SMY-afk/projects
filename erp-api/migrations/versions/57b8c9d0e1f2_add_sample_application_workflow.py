"""add sample application workflow

Revision ID: 57b8c9d0e1f2
Revises: 46a7b8c9d0e1
Create Date: 2026-09-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "57b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "46a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sample_applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform_application_id", sa.String(128), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("platform_status", sa.String(64), nullable=False),
        sa.Column("creator_open_id", sa.String(255)),
        sa.Column("creator_username", sa.String(255)),
        sa.Column("creator_nickname", sa.String(255)),
        sa.Column("follower_count", sa.BigInteger()),
        sa.Column("product_id", sa.String(128)),
        sa.Column("product_title", sa.Text()),
        sa.Column("sku_id", sa.String(128)),
        sa.Column("sku_name", sa.Text()),
        sa.Column("sku_image_url", sa.Text()),
        sa.Column("order_id", sa.String(128)),
        sa.Column("tracking_number", sa.String(128)),
        sa.Column("commission_rate", sa.Numeric(12, 6)),
        sa.Column("available_quantity", sa.Integer()),
        sa.Column("is_approvable", sa.Boolean()),
        sa.Column("approve_expiration_at", sa.DateTime(timezone=True)),
        sa.Column("shipment_expiration_at", sa.DateTime(timezone=True)),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('official_api', 'hubstudio_cdp')",
            name="ck_sample_applications_source_type",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_sample_applications_id_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "shop_id",
            "platform_application_id",
            name="uq_sample_applications_tenant_shop_platform_id",
        ),
    )
    op.create_index(
        "ix_sample_applications_tenant_id", "sample_applications", ["tenant_id"]
    )
    op.create_index(
        "ix_sample_applications_tenant_shop_status",
        "sample_applications",
        ["tenant_id", "shop_id", "platform_status"],
    )

    op.create_table(
        "sample_application_workflows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sample_application_id", sa.Uuid(), nullable=False),
        sa.Column("feishu_record_id", sa.String(128)),
        sa.Column("assigned_bd_name", sa.String(255)),
        sa.Column("processing_status", sa.String(64)),
        sa.Column("processing_result", sa.Text()),
        sa.Column("business_note", sa.Text()),
        sa.Column("assignment_version", sa.Integer(), server_default="0", nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("feishu_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "assignment_version >= 0",
            name="ck_sample_application_workflows_assignment_version",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["shop_id", "tenant_id"],
            ["shops.id", "shops.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sample_application_id", "tenant_id"],
            ["sample_applications.id", "sample_applications.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "sample_application_id",
            name="uq_sample_application_workflows_application",
        ),
        sa.UniqueConstraint(
            "feishu_record_id", name="uq_sample_application_workflows_feishu_record"
        ),
    )
    op.create_index(
        "ix_sample_application_workflows_tenant_id",
        "sample_application_workflows",
        ["tenant_id"],
    )

    op.create_table(
        "sample_application_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("sample_application_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("event_source", sa.String(64), nullable=False),
        sa.Column("external_event_id", sa.String(255)),
        sa.Column("actor_name", sa.String(255)),
        sa.Column("before_data", sa.JSON()),
        sa.Column("after_data", sa.JSON()),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
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
            ["sample_application_id", "tenant_id"],
            ["sample_applications.id", "sample_applications.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "event_source",
            "external_event_id",
            name="uq_sample_application_events_source_external",
        ),
    )
    op.create_index(
        "ix_sample_application_events_tenant_id",
        "sample_application_events",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_table("sample_application_events")
    op.drop_table("sample_application_workflows")
    op.drop_table("sample_applications")
