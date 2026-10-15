"""align shops display and identity fields

Revision ID: b5c7d9e1f203
Revises: a4f8c1e2d7b6
Create Date: 2026-08-12

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b5c7d9e1f203"
down_revision: str | Sequence[str] | None = "a4f8c1e2d7b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "shops",
        "name",
        new_column_name="shop_name",
        existing_type=sa.String(length=200),
        type_=sa.String(length=255),
    )
    op.alter_column(
        "shops",
        "platform",
        existing_type=sa.String(length=50),
        type_=sa.String(length=30),
    )
    op.alter_column(
        "shops",
        "platform_shop_id",
        existing_type=sa.String(length=128),
        type_=sa.String(length=100),
    )
    op.alter_column(
        "shops",
        "region",
        existing_type=sa.String(length=32),
        type_=sa.String(length=30),
    )
    op.alter_column(
        "shops",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
    )
    op.add_column("shops", sa.Column("shop_code", sa.String(length=50), nullable=True))
    op.add_column("shops", sa.Column("currency", sa.String(length=10), nullable=True))
    op.add_column(
        "shops",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("shops", "updated_at")
    op.drop_column("shops", "currency")
    op.drop_column("shops", "shop_code")
    op.alter_column(
        "shops",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
    )
    op.alter_column(
        "shops",
        "region",
        existing_type=sa.String(length=30),
        type_=sa.String(length=32),
    )
    op.alter_column(
        "shops",
        "platform_shop_id",
        existing_type=sa.String(length=100),
        type_=sa.String(length=128),
    )
    op.alter_column(
        "shops",
        "platform",
        existing_type=sa.String(length=30),
        type_=sa.String(length=50),
    )
    op.alter_column(
        "shops",
        "shop_name",
        new_column_name="name",
        existing_type=sa.String(length=255),
        type_=sa.String(length=200),
    )
