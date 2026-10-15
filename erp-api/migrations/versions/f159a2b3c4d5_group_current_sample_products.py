"""Group current sample products under one creator application.

Revision ID: f159a2b3c4d5
Revises: e047f8a9b0c1
Create Date: 2026-09-15 10:15:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f159a2b3c4d5"
down_revision: str | None = "e047f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "sample_applications",
        "product_id",
        existing_type=sa.String(length=128),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.alter_column(
        "sample_applications",
        "sku_id",
        existing_type=sa.String(length=128),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.add_column(
        "sample_applications",
        sa.Column(
            "product_image_urls",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "sample_applications",
        sa.Column(
            "is_current_projection",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_sample_applications_current_projection",
        "sample_applications",
        ["tenant_id", "shop_id", "is_current_projection"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_sample_applications_current_projection",
        table_name="sample_applications",
    )
    op.drop_column("sample_applications", "is_current_projection")
    op.drop_column("sample_applications", "product_image_urls")
    op.alter_column(
        "sample_applications",
        "sku_id",
        existing_type=sa.Text(),
        type_=sa.String(length=128),
        postgresql_using="left(sku_id, 128)",
        existing_nullable=True,
    )
    op.alter_column(
        "sample_applications",
        "product_id",
        existing_type=sa.Text(),
        type_=sa.String(length=128),
        postgresql_using="left(product_id, 128)",
        existing_nullable=True,
    )
