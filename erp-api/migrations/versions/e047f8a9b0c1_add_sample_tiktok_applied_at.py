"""add sample TikTok application timestamp

Revision ID: e047f8a9b0c1
Revises: df36e7f8a9b0
Create Date: 2026-09-14 16:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e047f8a9b0c1"
down_revision: str | None = "df36e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sample_applications",
        sa.Column("tiktok_applied_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("sample_applications", "tiktok_applied_at")
