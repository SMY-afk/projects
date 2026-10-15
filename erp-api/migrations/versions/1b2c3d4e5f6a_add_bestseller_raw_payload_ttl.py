"""add bestseller raw payload retention columns

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "1b2c3d4e5f6a"
down_revision: str | Sequence[str] | None = "0a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "bestseller_entries",
        sa.Column("raw_payload", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "bestseller_entries",
        sa.Column("raw_payload_expires_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_bestseller_entries_raw_payload_expires_at",
        "bestseller_entries",
        ["raw_payload_expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_bestseller_entries_raw_payload_expires_at",
        table_name="bestseller_entries",
    )
    op.drop_column("bestseller_entries", "raw_payload_expires_at")
    op.drop_column("bestseller_entries", "raw_payload")
