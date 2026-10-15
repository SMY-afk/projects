"""create affiliate order items table

Revision ID: f2b3c4d5e6a7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2b3c4d5e6a7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "affiliate_order_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("main_order_id", sa.String(128), nullable=False),
        sa.Column("creator_id", sa.String(128)),
        sa.Column("creator_nickname", sa.String(255)),
        sa.Column("campaign_id", sa.String(128)),
        sa.Column("product_id", sa.String(128), nullable=False),
        sa.Column("product_name", sa.String(500)),
        sa.Column("image_uri", sa.String(2000)),
        sa.Column("sku_id", sa.String(128), nullable=False),
        sa.Column("sku_name", sa.String(500)),
        sa.Column("order_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_cod", sa.Boolean()),
        sa.Column("is_non_same_shop_order", sa.Boolean()),
        sa.Column("cos_type", sa.String(64)),
        sa.Column("commission_base", sa.Numeric(20, 4)),
        sa.Column("commission_currency", sa.String(10)),
        sa.Column("commission_rate", sa.Numeric(10, 6)),
        sa.Column("estimated_standard_commission", sa.Numeric(20, 4)),
        sa.Column("raw_data", postgresql.JSONB(), nullable=False),
        sa.Column("source_record_key", sa.String(256), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
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
            "shop_id",
            "source_record_key",
            name="uq_affiliate_order_items_shop_source_record",
        ),
    )
    op.create_index(
        "ix_affiliate_order_items_shop_id",
        "affiliate_order_items",
        ["shop_id"],
    )
    op.create_index(
        "ix_affiliate_order_items_tenant_id",
        "affiliate_order_items",
        ["tenant_id"],
    )
    op.create_index(
        "ix_affiliate_order_items_shop_main_order",
        "affiliate_order_items",
        ["shop_id", "main_order_id"],
    )
    op.create_index(
        "ix_affiliate_order_items_shop_order_created_at",
        "affiliate_order_items",
        ["shop_id", "order_created_at"],
    )
    op.create_index(
        "ix_affiliate_order_items_shop_creator",
        "affiliate_order_items",
        ["shop_id", "creator_id"],
    )
    op.create_index(
        "ix_affiliate_order_items_shop_campaign",
        "affiliate_order_items",
        ["shop_id", "campaign_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_affiliate_order_items_shop_campaign",
        table_name="affiliate_order_items",
    )
    op.drop_index(
        "ix_affiliate_order_items_shop_creator",
        table_name="affiliate_order_items",
    )
    op.drop_index(
        "ix_affiliate_order_items_shop_order_created_at",
        table_name="affiliate_order_items",
    )
    op.drop_index(
        "ix_affiliate_order_items_shop_main_order",
        table_name="affiliate_order_items",
    )
    op.drop_index(
        "ix_affiliate_order_items_tenant_id",
        table_name="affiliate_order_items",
    )
    op.drop_index(
        "ix_affiliate_order_items_shop_id",
        table_name="affiliate_order_items",
    )
    op.drop_table("affiliate_order_items")
