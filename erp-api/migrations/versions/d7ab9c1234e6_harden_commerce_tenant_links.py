"""harden commerce tenant links

Revision ID: d7ab9c1234e6
Revises: c69a8b0123d5
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7ab9c1234e6"
down_revision: str | Sequence[str] | None = "c69a8b0123d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_skus", sa.Column("tenant_id", sa.Uuid(), nullable=True))
    op.execute(
        """
        UPDATE product_skus AS sku
        SET tenant_id = product.tenant_id
        FROM products AS product
        WHERE product.id = sku.product_id
          AND sku.tenant_id IS NULL
        """
    )
    _validate_backfill()
    op.alter_column("product_skus", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_product_skus_tenant",
        "product_skus",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_products_id_tenant", "products", ["id", "tenant_id"]
    )
    op.create_unique_constraint(
        "uq_product_skus_id_tenant", "product_skus", ["id", "tenant_id"]
    )
    op.create_foreign_key(
        "fk_product_skus_product_tenant",
        "product_skus",
        "products",
        ["product_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_order_lines_product_tenant",
        "order_lines",
        "products",
        ["product_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    op.create_foreign_key(
        "fk_order_lines_product_sku_tenant",
        "order_lines",
        "product_skus",
        ["product_sku_id", "tenant_id"],
        ["id", "tenant_id"],
    )
    _create_indexes()


def _validate_backfill() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM product_skus WHERE tenant_id IS NULL) THEN
            RAISE EXCEPTION 'Cannot resolve tenant_id for every product_sku';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM order_lines AS line
            JOIN products AS product ON product.id = line.product_id
            WHERE line.product_id IS NOT NULL
              AND line.tenant_id <> product.tenant_id
          ) THEN
            RAISE EXCEPTION 'Cross-tenant order line product link detected';
          END IF;
          IF EXISTS (
            SELECT 1
            FROM order_lines AS line
            JOIN product_skus AS sku ON sku.id = line.product_sku_id
            WHERE line.product_sku_id IS NOT NULL
              AND line.tenant_id <> sku.tenant_id
          ) THEN
            RAISE EXCEPTION 'Cross-tenant order line SKU link detected';
          END IF;
        END $$;
        """
    )


def _create_indexes() -> None:
    op.create_index("ix_shops_tenant_status", "shops", ["tenant_id", "status"])
    op.create_index("ix_products_tenant_shop", "products", ["tenant_id", "shop_id"])
    op.create_index(
        "ix_product_skus_tenant_product",
        "product_skus",
        ["tenant_id", "product_id"],
    )
    op.create_index(
        "ix_orders_tenant_shop_platform",
        "orders",
        ["tenant_id", "shop_id", "platform_order_id"],
    )
    op.create_index(
        "ix_order_lines_tenant_order", "order_lines", ["tenant_id", "order_id"]
    )
    op.create_index(
        "ix_order_lines_tenant_product",
        "order_lines",
        ["tenant_id", "product_id"],
    )
    op.create_index(
        "ix_order_lines_tenant_product_sku",
        "order_lines",
        ["tenant_id", "product_sku_id"],
    )


def downgrade() -> None:
    for name in (
        "ix_order_lines_tenant_product_sku",
        "ix_order_lines_tenant_product",
        "ix_order_lines_tenant_order",
    ):
        op.drop_index(name, table_name="order_lines")
    op.drop_index("ix_orders_tenant_shop_platform", table_name="orders")
    op.drop_index("ix_product_skus_tenant_product", table_name="product_skus")
    op.drop_index("ix_products_tenant_shop", table_name="products")
    op.drop_index("ix_shops_tenant_status", table_name="shops")
    op.drop_constraint(
        "fk_order_lines_product_sku_tenant", "order_lines", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_order_lines_product_tenant", "order_lines", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_product_skus_product_tenant", "product_skus", type_="foreignkey"
    )
    op.drop_constraint("uq_product_skus_id_tenant", "product_skus", type_="unique")
    op.drop_constraint("uq_products_id_tenant", "products", type_="unique")
    op.drop_constraint("fk_product_skus_tenant", "product_skus", type_="foreignkey")
    op.drop_column("product_skus", "tenant_id")
