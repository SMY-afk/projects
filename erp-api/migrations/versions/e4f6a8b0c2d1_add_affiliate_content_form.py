"""add affiliate content form

Revision ID: e4f6a8b0c2d1
Revises: cd23c299adc8
Create Date: 2026-08-18 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4f6a8b0c2d1"
down_revision: str | Sequence[str] | None = "cd23c299adc8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "affiliate_order_items",
        sa.Column("promotion_type", sa.Integer(), nullable=True),
    )
    op.add_column(
        "affiliate_order_items",
        sa.Column("content_form", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        WITH source AS (
            SELECT
                id,
                raw_data #>> ARRAY[
                    'sku_order_base_info_for_affiliate_seller',
                    'sku_order_info',
                    'promotion_position_info',
                    'promotion_type'
                ] AS promotion_type_text
            FROM affiliate_order_items
        )
        UPDATE affiliate_order_items AS item
        SET
            promotion_type = CASE
                WHEN source.promotion_type_text ~ '^[0-9]+$'
                THEN source.promotion_type_text::integer
                ELSE NULL
            END,
            content_form = CASE source.promotion_type_text
                WHEN '1' THEN 'product_showcase'
                WHEN '2' THEN 'video'
                WHEN '3' THEN 'live'
                WHEN '5' THEN 'affiliate_product_page'
                WHEN '6' THEN 'external_traffic_plan'
                ELSE NULL
            END
        FROM source
        WHERE item.id = source.id
        """
    )


def downgrade() -> None:
    op.drop_column("affiliate_order_items", "content_form")
    op.drop_column("affiliate_order_items", "promotion_type")
