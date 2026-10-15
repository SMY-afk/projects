"""create order domain tables

Revision ID: d7e9f1a2b405
Revises: c6d8e0f2a314
Create Date: 2026-08-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e9f1a2b405"
down_revision: str | Sequence[str] | None = "c6d8e0f2a314"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM shops GROUP BY platform, platform_shop_id HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'Duplicate platform shops must be resolved before order webhook rollout';
          END IF;
        END $$;
        """
    )
    op.create_unique_constraint(
        "uq_shops_platform_external_id", "shops", ["platform", "platform_shop_id"]
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shop_id", sa.Uuid(), nullable=False),
        sa.Column("platform_order_id", sa.String(128), nullable=False),
        sa.Column("order_number", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("external_status", sa.String(64), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("shipping_fee_minor", sa.BigInteger(), nullable=False),
        sa.Column("discount_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("tax_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("buyer_username_masked", sa.String(128)),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("platform_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "synced_at",
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
        sa.UniqueConstraint("id", "tenant_id", name="uq_orders_id_tenant"),
        sa.UniqueConstraint(
            "shop_id", "platform_order_id", name="uq_orders_shop_platform_order"
        ),
    )
    for column in (
        "shop_id",
        "order_number",
        "status",
        "placed_at",
        "platform_updated_at",
        "tenant_id",
    ):
        op.create_index(op.f(f"ix_orders_{column}"), "orders", [column])

    op.create_table(
        "order_lines",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid()),
        sa.Column("product_sku_id", sa.Uuid()),
        sa.Column("platform_line_id", sa.String(128), nullable=False),
        sa.Column("platform_product_id", sa.String(128)),
        sa.Column("platform_sku_id", sa.String(128)),
        sa.Column("seller_sku", sa.String(128)),
        sa.Column("product_name", sa.String(300), nullable=False),
        sa.Column("sku_name", sa.String(300)),
        sa.Column("image_url", sa.String(1000)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("original_unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("sale_unit_price_minor", sa.BigInteger(), nullable=False),
        sa.Column("discount_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("line_total_amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["product_sku_id"], ["product_skus.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id", "platform_line_id", name="uq_order_lines_order_platform_line"
        ),
    )
    for column in (
        "order_id",
        "product_id",
        "product_sku_id",
        "platform_sku_id",
        "tenant_id",
    ):
        op.create_index(op.f(f"ix_order_lines_{column}"), "order_lines", [column])

    op.create_table(
        "order_fulfillments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("platform_package_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(64), nullable=False),
        sa.Column("carrier", sa.String(128)),
        sa.Column("tracking_number_masked", sa.String(128)),
        sa.Column("tracking_number_ciphertext", sa.Text()),
        sa.Column("shipped_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id", "platform_package_id", name="uq_fulfillments_order_package"
        ),
    )
    op.create_index(
        op.f("ix_order_fulfillments_order_id"), "order_fulfillments", ["order_id"]
    )
    op.create_index(
        op.f("ix_order_fulfillments_tenant_id"), "order_fulfillments", ["tenant_id"]
    )

    op.create_table(
        "order_recipients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("name_masked", sa.String(128)),
        sa.Column("phone_masked", sa.String(64)),
        sa.Column("address_masked", sa.String(300)),
        sa.Column("name_ciphertext", sa.Text()),
        sa.Column("phone_ciphertext", sa.Text()),
        sa.Column("address_ciphertext", sa.Text()),
        sa.Column("country_code", sa.String(2)),
        sa.Column("purge_after", sa.DateTime(timezone=True)),
        sa.Column("purged_at", sa.DateTime(timezone=True)),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["order_id", "tenant_id"],
            ["orders.id", "orders.tenant_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_order_recipients_order"),
    )
    for column in ("order_id", "purge_after", "tenant_id"):
        op.create_index(
            op.f(f"ix_order_recipients_{column}"), "order_recipients", [column]
        )


def downgrade() -> None:
    op.drop_table("order_recipients")
    op.drop_table("order_fulfillments")
    op.drop_table("order_lines")
    op.drop_table("orders")
    op.drop_constraint("uq_shops_platform_external_id", "shops", type_="unique")
