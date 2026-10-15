"""create product skus table

Revision ID: 8c2d6e1f4b90
Revises: 7a1f4e9c2b30
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c2d6e1f4b90"
down_revision: str | Sequence[str] | None = "7a1f4e9c2b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_skus",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("platform_sku_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("price_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("stock", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "platform_sku_id",
            name="uq_product_skus_product_platform_sku",
        ),
    )
    op.create_index(
        op.f("ix_product_skus_product_id"), "product_skus", ["product_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_product_skus_product_id"), table_name="product_skus")
    op.drop_table("product_skus")
