"""add visible creator metrics to sample applications

Revision ID: ce25d6e7f8a9
Revises: bd14c5d6e7f8
Create Date: 2026-09-10 11:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ce25d6e7f8a9"
down_revision: str | None = "bd14c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sample_applications", sa.Column("creator_content_count", sa.BigInteger())
    )
    op.add_column(
        "sample_applications", sa.Column("creator_ec_video_view", sa.BigInteger())
    )
    op.add_column(
        "sample_applications",
        sa.Column("creator_fulfillment_percentage", sa.Numeric(7, 2)),
    )
    op.add_column(
        "sample_applications", sa.Column("creator_units_sold", sa.BigInteger())
    )
    op.add_column(
        "sample_applications", sa.Column("creator_pps", sa.Numeric(3, 1))
    )
    op.add_column(
        "sample_applications", sa.Column("creator_rating", sa.Numeric(3, 1))
    )


def downgrade() -> None:
    op.drop_column("sample_applications", "creator_rating")
    op.drop_column("sample_applications", "creator_pps")
    op.drop_column("sample_applications", "creator_units_sold")
    op.drop_column("sample_applications", "creator_fulfillment_percentage")
    op.drop_column("sample_applications", "creator_ec_video_view")
    op.drop_column("sample_applications", "creator_content_count")
