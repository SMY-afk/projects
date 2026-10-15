"""bind TikTok shop connections to App profiles

Revision ID: 35f6a7b8c9d0
Revises: 24e5f6a7b8c9
Create Date: 2026-08-31
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "35f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "24e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "shop_connections",
        sa.Column(
            "app_profile",
            sa.String(length=32),
            server_default="legacy",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("shop_connections", "app_profile")
