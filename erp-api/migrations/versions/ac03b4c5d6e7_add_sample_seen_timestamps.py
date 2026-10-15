"""add sample application seen timestamps

Revision ID: ac03b4c5d6e7
Revises: 9bf2a3b4c5d6
Create Date: 2026-09-10 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ac03b4c5d6e7"
down_revision: str | None = "9bf2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sample_applications",
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "sample_applications",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE sample_applications
        SET first_seen_at = COALESCE(created_at, source_observed_at, now()),
            last_seen_at = COALESCE(source_observed_at, updated_at, created_at, now())
        """
    )
    op.alter_column(
        "sample_applications",
        "first_seen_at",
        nullable=False,
        server_default=sa.func.now(),
    )
    op.alter_column(
        "sample_applications",
        "last_seen_at",
        nullable=False,
        server_default=sa.func.now(),
    )


def downgrade() -> None:
    op.drop_column("sample_applications", "last_seen_at")
    op.drop_column("sample_applications", "first_seen_at")
