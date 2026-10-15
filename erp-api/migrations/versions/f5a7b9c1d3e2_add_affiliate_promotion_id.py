"""add affiliate promotion id

Revision ID: f5a7b9c1d3e2
Revises: e4f6a8b0c2d1
Create Date: 2026-08-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f5a7b9c1d3e2"
down_revision: str | Sequence[str] | None = "e4f6a8b0c2d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "affiliate_order_items",
        sa.Column("promotion_id", sa.String(length=128), nullable=True),
    )
    op.execute(
        """
        UPDATE affiliate_order_items
        SET promotion_id = raw_data #>> ARRAY[
            'sku_order_base_info_for_affiliate_seller',
            'sku_order_info',
            'promotion_position_info',
            'promotion_id'
        ]
        """
    )


def downgrade() -> None:
    op.drop_column("affiliate_order_items", "promotion_id")
