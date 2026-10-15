"""add sample creator gmv level

Revision ID: 79d0e1f2a3b4
Revises: 68c9d0e1f2a3
Create Date: 2026-09-09 18:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "79d0e1f2a3b4"
down_revision: str | None = "68c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sample_applications", sa.Column("creator_gmv_minor", sa.BigInteger())
    )
    op.add_column(
        "sample_applications", sa.Column("creator_gmv_currency", sa.String(3))
    )
    op.add_column(
        "sample_applications", sa.Column("creator_level", sa.String(2))
    )
    op.create_check_constraint(
        "ck_sample_applications_creator_level",
        "sample_applications",
        "creator_level IS NULL OR creator_level IN "
        "('L0', 'L1', 'L2', 'L3', 'L4', 'L5', 'L6', 'L7')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_sample_applications_creator_level",
        "sample_applications",
        type_="check",
    )
    op.drop_column("sample_applications", "creator_level")
    op.drop_column("sample_applications", "creator_gmv_currency")
    op.drop_column("sample_applications", "creator_gmv_minor")
