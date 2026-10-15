"""use shop and platform product id as the product unique key

Revision ID: c6d8e0f2a314
Revises: b5c7d9e1f203
Create Date: 2026-08-12

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c6d8e0f2a314"
down_revision: str | Sequence[str] | None = "b5c7d9e1f203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_products_tenant_shop_platform_product",
        "products",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_products_shop_platform_product",
        "products",
        ["shop_id", "platform_product_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_products_shop_platform_product",
        "products",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_products_tenant_shop_platform_product",
        "products",
        ["tenant_id", "shop_id", "platform_product_id"],
    )
