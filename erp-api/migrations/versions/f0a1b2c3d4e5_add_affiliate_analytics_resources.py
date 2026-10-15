"""add affiliate analytics sync resource types

Revision ID: f0a1b2c3d4e5
Revises: e5f6a7b8c9d0
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | Sequence[str] | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "analytics_sync_runs",
    "analytics_sync_cursors",
    "analytics_quality_alerts",
)
_RESOURCE_CHECK = (
    "resource_type IN ('video', 'live', 'affiliate_creator', 'affiliate_video')"
)


def upgrade() -> None:
    for table_name in _TABLES:
        op.alter_column(
            table_name,
            "resource_type",
            existing_type=sa.String(16),
            type_=sa.String(32),
            existing_nullable=False,
        )
        op.create_check_constraint(
            f"ck_{table_name}_resource_type",
            table_name,
            _RESOURCE_CHECK,
        )


def downgrade() -> None:
    connection = op.get_bind()
    for table_name in _TABLES:
        affiliate_count = connection.scalar(
            sa.text(
                f"SELECT count(*) FROM {table_name} "
                "WHERE resource_type IN ('affiliate_creator', 'affiliate_video')"
            )
        )
        if affiliate_count:
            raise RuntimeError(
                "Cannot remove affiliate analytics resource types while data exists."
            )

    for table_name in reversed(_TABLES):
        op.drop_constraint(
            f"ck_{table_name}_resource_type",
            table_name,
            type_="check",
        )
        op.alter_column(
            table_name,
            "resource_type",
            existing_type=sa.String(32),
            type_=sa.String(16),
            existing_nullable=False,
        )
