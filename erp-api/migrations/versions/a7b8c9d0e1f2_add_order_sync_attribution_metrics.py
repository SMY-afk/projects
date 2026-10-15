"""add order sync attribution metrics

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for column in (
        "confirmed_count",
        "derived_count",
        "unknown_count",
        "unsupported_field_count",
    ):
        op.add_column(
            "order_sync_runs",
            sa.Column(column, sa.Integer(), nullable=False, server_default="0"),
        )
    for column in (
        "confirmed_count",
        "derived_count",
        "unknown_count",
        "unsupported_field_count",
    ):
        op.alter_column("order_sync_runs", column, server_default=None)


def downgrade() -> None:
    for column in (
        "unsupported_field_count",
        "unknown_count",
        "derived_count",
        "confirmed_count",
    ):
        op.drop_column("order_sync_runs", column)
