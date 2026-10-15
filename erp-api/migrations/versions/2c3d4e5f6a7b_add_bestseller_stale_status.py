"""add bestseller stale status

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c3d4e5f6a7b"
down_revision: str | Sequence[str] | None = "1b2c3d4e5f6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bestseller_snapshots",
        sa.Column(
            "is_stale",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "bestseller_snapshots",
        sa.Column("last_error_category", sa.String(length=32)),
    )
    op.add_column(
        "bestseller_snapshots",
        sa.Column("last_error_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_column("bestseller_snapshots", "last_error_at")
    op.drop_column("bestseller_snapshots", "last_error_category")
    op.drop_column("bestseller_snapshots", "is_stale")
